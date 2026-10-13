"""Checked PWM initialization for the physical RAE, before motor startup."""

import fcntl
from pathlib import Path
import subprocess


class PwmStartup:
    """Own hardware startup for one launch lifetime; never stop another driver."""

    register = '0x20320180'

    def __init__(self, sysfs='/sys', lock_path='/run/lock/rae-pwm.lock'):
        """Acquire an exclusive lease and check the device before any write."""
        self.sysfs = Path(sysfs)
        self.chip = self.sysfs / 'class/pwm/pwmchip0'
        self.initialized = False
        self.camera_started = False
        self.camera_pending = False
        self.camera_failed = False
        self.motors_started = False
        self._lock = open(lock_path, 'a')
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.check_idle()
            if 'devmem' not in self._busybox('--list').splitlines():
                raise RuntimeError('BusyBox devmem applet is missing')
        except BaseException:
            self.close()
            raise

    def close(self):
        """Release the lease after all processes in the launch have stopped."""
        self._lock.close()

    @staticmethod
    def _busybox(*args):
        return subprocess.run(
            ['busybox', *args], check=True, capture_output=True,
            text=True, timeout=5, shell=False).stdout.strip()

    def check_idle(self):
        """Reject foreign devices, missing channels and already enabled motors."""
        device = self.sysfs / 'bus/platform/devices/203200a0.pwm'
        driver = self.sysfs / 'bus/platform/drivers/pwm-keembay'
        if (self.chip.joinpath('device').resolve(strict=True) != device.resolve(strict=True)
                or self.chip.joinpath('device/driver').resolve(strict=True)
                != driver.resolve(strict=True)):
            raise RuntimeError('Expected RAE pwm-keembay device is absent')
        for pin in (1, 2):
            if (self.chip / f'pwm{pin}/enable').read_text().strip() != '0':
                raise RuntimeError(f'PWM{pin} is enabled; stop the motor driver first')

    def read_register(self):
        """Read the register and reject malformed devmem output."""
        return int(self._busybox('devmem', self.register, '32'), 0)

    def initialize(self):
        """Reset once per startup, and confirm the result before admitting motors."""
        if self.camera_pending or self.camera_failed:
            raise RuntimeError('Camera initialization has not succeeded')
        self._initialize()

    def _initialize(self):
        self.check_idle()
        before = self.read_register()
        if self.initialized:
            if before != 0:
                raise RuntimeError('PWM changed after initialization; refusing motor startup')
            return
        if before not in (0, 0x1FFFFFFF):
            raise RuntimeError(f'Untested PWM register value: {before:#010x}')
        for pin in (1, 2):
            duty = self.chip / f'pwm{pin}/duty_cycle'
            duty.write_text('0')
            if duty.read_text().strip() != '0':
                raise RuntimeError(f'Failed to clear PWM{pin} duty cycle')
        self.check_idle()
        self._busybox('devmem', self.register, '32', '0x00000000')
        if self.read_register() != 0:
            raise RuntimeError('PWM reset readback is not 0x00000000')
        self.check_idle()
        self.initialized = True

    def begin_camera(self):
        """Reserve camera initialization before starting its process."""
        if self.motors_started or self.camera_started:
            raise RuntimeError('Restart the whole launch to initialize the camera again')
        self.check_idle()
        self.camera_started = True
        self.camera_pending = True
        self.initialized = False

    def finish_camera(self):
        """Reset and verify PWM after camera pipeline configuration."""
        if not self.camera_pending or self.camera_failed:
            raise RuntimeError('Unexpected camera readiness result')
        self.camera_pending = False
        self.initialize()

    def start_motors(self):
        """Admit one controller manager, after checked initialization."""
        if self.motors_started:
            raise RuntimeError('Motor startup is already claimed by this launch')
        self.initialize()
        self.motors_started = True
