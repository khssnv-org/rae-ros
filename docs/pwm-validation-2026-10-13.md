# PWM validation, 2026-10-13

Robot: `rae-alpha`, `192.168.1.221`, suspended wheels.
Base image: `ghcr.io/khssnv-org/rae-ros:v0.5.0-humble-khssnv-org.1`.

Completed checks:

- Built a separate ARM64 validation image from the existing image, installed
  `busybox-static`, and passed `busybox --list | grep -qx devmem`.
- Built `rae_hw` with colcon, including installation of the new Python modules
  and executable. Both CTest/ament targets passed: 30 unittest checks, no skips
  in ROS Humble. New Python modules passed `ament_pep257`.
- Local Python/XML parsing and `git diff --check` passed. Without ROS, the local
  run passes 12 hardware-free checks and skips 18 ROS-dependent checks.
- Repeated hardware control-only startup passed on the final code. The register
  was `0x00000000` at activation and after stopping. A competing launch was
  refused. A separate lease with enabled motor PWM was also refused before reset,
  exercising the protection for drivers without the new shared lease.
- Combined startup through `robot.launch.py` passed on the final code, including
  both camera readiness phases, checked reset before control, and bounded
  `0.06`, `0.10`, `0.15 m/s` commands. Activation took 46.855 seconds. Both conflict
  checks also passed. Register readback remained zero at sampled checks and after
  stopping. IPC launch uses the same gate but was not exercised on hardware.

Control-only measurement, final two seconds of a four-second command at
`0.10 m/s`, stock PID and geometry:

| Quantity | Left | Right |
| --- | ---: | ---: |
| Mean encoder velocity, rad/s | 8.163 | 8.319 |
| Sample SD, rad/s | 1.139 | 0.799 |

With cameras running, the same `0.10 m/s` measurement gave means `7.957/7.824`
and SD `2.444/1.922 rad/s` (134 samples). Variation was higher with cameras;
this test does not establish its cause or validate loaded motion on the floor.

There were 158 recorded samples; repeated encoder values are not independent
physical measurements. The command corresponds to `8.403 rad/s` with the stock
`0.0119 m` wheel radius. An earlier control-only run also exercised `0.06` and
`0.15 m/s`. The original diagnostic script passed on the original image as a
control experiment, with the PWM register already zero.

The initial measuring script polled controller services during spawner startup;
those runs encountered service timeouts. Final measurements wait for the spawner
activation confirmation before observing motion. During camera checks, startup
changed the register from zero to `0x1FFFFFFF`; the writer was not identified.
Failed camera readiness blocked motor startup. Firmware crash-dump messages were
also observed; their relationship to missing frames was not established.

The full production Dockerfile was not rebuilt from its base, and AMD64 was not
built. No image publication or deployment was performed. The validation
image is local to the robot (`rae-pwm-check:local`). Logs, CSV files and the
bounded measuring script are in `/tmp/rae-pwm-check` on the robot.
Copies of the final evidence are also in the workstation's
`/tmp/rae-pwm-check/results`.

The known motor shutdown `join()` error remains outside this change. Test cleanup
removed the disposable container and explicitly disabled PWM1/2 and cleared both
duty cycles. Floor motion, odometry calibration and extended operation remain
untested.
