"""Hardware-free checks of the PWM startup lease and failure policy."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rae_hw.pwm import PwmStartup  # noqa: E402


class PwmStartupTest(unittest.TestCase):
    """Exercise real sysfs file handling with a fake devmem executable."""

    def setUp(self):
        """Create an isolated, recognizable RAE sysfs tree."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.chip = self.root / 'class/pwm/pwmchip0'
        self.chip.mkdir(parents=True)
        self.device = self.root / 'bus/platform/devices/203200a0.pwm'
        self.device.mkdir(parents=True)
        self.driver = self.root / 'bus/platform/drivers/pwm-keembay'
        self.driver.mkdir(parents=True)
        (self.device / 'driver').symlink_to(self.driver)
        (self.chip / 'device').symlink_to(self.device)
        for pin in (1, 2):
            channel = self.chip / f'pwm{pin}'
            channel.mkdir()
            (channel / 'enable').write_text('0')
            (channel / 'duty_cycle').write_text('100')
        self.value = 0x1FFFFFFF
        self.write_error = None
        self.readback = 0
        self.applet_list = 'devmem\ntrue'
        patcher = patch('rae_hw.pwm.subprocess.run', side_effect=self.run_busybox)
        self.runner = patcher.start()
        self.addCleanup(patcher.stop)

    def run_busybox(self, command, **kwargs):
        """Simulate devmem while checking argument and subprocess safety."""
        self.assertEqual(command[0], 'busybox')
        self.assertTrue(kwargs['check'])
        self.assertFalse(kwargs['shell'])
        self.assertEqual(kwargs['timeout'], 5)
        if command[1:] == ['--list']:
            output = self.applet_list
        elif len(command) == 4:
            self.assertEqual(command[1:], ['devmem', '0x20320180', '32'])
            output = f'{self.value:#010x}'
        else:
            self.assertEqual(command[1:], ['devmem', '0x20320180', '32', '0x00000000'])
            for pin in (1, 2):
                self.assertEqual((self.chip / f'pwm{pin}/enable').read_text(), '0')
                self.assertEqual((self.chip / f'pwm{pin}/duty_cycle').read_text(), '0')
            if self.write_error:
                raise self.write_error
            self.value = self.readback
            output = ''
        return subprocess.CompletedProcess(command, 0, stdout=output)

    def session(self):
        """Acquire a lease confined to the temporary directory."""
        session = PwmStartup(self.root, self.root / 'pwm.lock')
        self.addCleanup(session.close)
        return session

    def writes(self):
        """Return only register writes, excluding probes and reads."""
        return [call.args[0] for call in self.runner.call_args_list if len(call.args[0]) == 5]

    def test_motor_only_order(self):
        session = self.session()
        session.start_motors()
        self.assertTrue(session.motors_started)
        self.assertEqual([call.args[0] for call in self.runner.call_args_list], [
            ['busybox', '--list'],
            ['busybox', 'devmem', '0x20320180', '32'],
            ['busybox', 'devmem', '0x20320180', '32', '0x00000000'],
            ['busybox', 'devmem', '0x20320180', '32'],
        ])

    def test_camera_must_finish_before_reset_and_motors(self):
        session = self.session()
        session.begin_camera()
        with self.assertRaisesRegex(RuntimeError, 'Camera'):
            session.start_motors()
        self.assertEqual(self.writes(), [])
        session.finish_camera()
        session.start_motors()
        self.assertEqual(len(self.writes()), 1)

    def test_write_failure_blocks_motors(self):
        session = self.session()
        self.write_error = subprocess.CalledProcessError(1, 'busybox')
        with self.assertRaises(subprocess.CalledProcessError):
            session.start_motors()
        self.assertFalse(session.initialized)
        self.assertFalse(session.motors_started)

    def test_readback_mismatch_blocks_motors(self):
        session = self.session()
        self.readback = 0x1FFFFFFF
        with self.assertRaisesRegex(RuntimeError, 'readback'):
            session.start_motors()
        self.assertFalse(session.motors_started)

    def test_bad_read_or_missing_binary_blocks_motors(self):
        for error in (ValueError('bad readback'), FileNotFoundError('busybox'),
                      subprocess.TimeoutExpired('busybox', 5)):
            with self.subTest(error=error):
                session = self.session()
                with patch.object(session, 'read_register', side_effect=error):
                    with self.assertRaises(type(error)):
                        session.start_motors()
                self.assertFalse(session.motors_started)
                session.close()
        self.assertEqual(self.writes(), [])

    def test_missing_applet_prevents_startup(self):
        self.applet_list = 'true'
        with self.assertRaisesRegex(RuntimeError, 'applet'):
            self.session()
        self.assertEqual(self.writes(), [])

    def test_enabled_legacy_driver_is_not_reset(self):
        (self.chip / 'pwm2/enable').write_text('1')
        with self.assertRaisesRegex(RuntimeError, 'stop the motor driver'):
            self.session()
        self.runner.assert_not_called()

    def test_wrong_device_or_unexported_channel_is_not_reset(self):
        (self.chip / 'pwm1/enable').unlink()
        with self.assertRaises(FileNotFoundError):
            self.session()
        self.runner.assert_not_called()
        (self.chip / 'device').unlink()
        (self.chip / 'device').symlink_to(self.driver)
        with self.assertRaisesRegex(RuntimeError, 'device'):
            self.session()
        self.runner.assert_not_called()

    def test_untested_register_is_not_written(self):
        session = self.session()
        self.value = 123
        with self.assertRaisesRegex(RuntimeError, 'Untested'):
            session.start_motors()
        self.assertEqual(self.writes(), [])

    def test_second_launcher_is_blocked_until_first_exits(self):
        first = self.session()
        with self.assertRaises(BlockingIOError):
            self.session()
        first.start_motors()
        first.close()
        second = self.session()
        second.start_motors()
        self.assertEqual(len(self.writes()), 2)

    def test_no_second_motor_manager_or_hot_camera_start(self):
        session = self.session()
        session.start_motors()
        with self.assertRaisesRegex(RuntimeError, 'already claimed'):
            session.start_motors()
        with self.assertRaisesRegex(RuntimeError, 'whole launch'):
            session.begin_camera()
        self.assertEqual(len(self.writes()), 1)

    def test_changed_register_after_camera_blocks_motors(self):
        session = self.session()
        session.begin_camera()
        session.finish_camera()
        self.value = 0x1FFFFFFF
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            session.start_motors()
        self.assertFalse(session.motors_started)
        self.assertEqual(len(self.writes()), 1)


if __name__ == '__main__':
    unittest.main()
