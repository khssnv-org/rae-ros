# Physical RAE PWM startup

The motor driver enables PWM in `on_configure`. Initialization therefore gates
the entire controller manager, before its process starts.
The joint state broadcaster is spawned first; its successful exit admits the
diff controller spawner after another register readback. Either spawner failing
shuts down the launch.

- Control only: `ros2 launch rae_hw control.launch.py` checks that PWM1/2 are
  disabled, clears their duty cycles, writes `0x00000000` to `0x20320180`, and
  reads it back. It rechecks immediately before starting the controller manager.
- Cameras and control: `ros2 launch rae_bringup robot.launch.py` (also used by
  `bringup.launch.py`) starts the camera first. The camera's `start_camera` service
  signals completion of pipeline setup. The existing 15-second minimum camera
  settling interval is also preserved. The checked reset then runs, followed by
  control startup. Camera service discovery has a 60-second timeout; the settling
  interval alone never admits motors.
- `ros2 launch rae_camera rae_camera.launch.py enable_control:=true` uses the
  same sequence. Without that argument it starts only the camera and resets PWM
  after pipeline setup. `perception_ipc.launch.py` uses the same gate for IPC/control.

The independent camera reset timers are replaced by the common gate.
A nonzero exit, timeout, missing
`busybox devmem`, device mismatch, enabled PWM, unexpected register value, or
failed readback prevents motor startup. Only the diagnosed register values
`0x1FFFFFFF` and `0x00000000` are accepted before a reset. The physical entrypoints
require the RAE `pwm-keembay` device and exported PWM1/2, as prepared by the image
entrypoint. `busybox-static` and a build-time applet check are in `Dockerfile`.

One exclusive `/run/lock/rae-pwm.lock` lease is held until the launcher exits,
including child shutdown. A second hardware launch is refused. Stop the whole
launch before restarting it or changing the camera configuration; use a combined
launch instead of separately starting camera and control. Containers sharing the
robot must bind-mount the same host `/run/lock` directory. Enabled PWM also blocks
reset when a previous driver does not participate in the lease. External drivers
must be stopped; they cannot be serialized by this advisory lock.

No persistent "PWM ready" file is used: each new launch resets and verifies the
hardware again. Camera diagnostic auto-restart is disabled where supported.
Do not use the camera stop/start services while control is running: reinitializing
the camera requires restarting the combined launch through the gate.

`control_mock.launch.py` and `gazebo.launch.py` do not use the hardware gate.
The physical launch files refuse `mock`, `sim`, `sim_mode`, or `use_sim_time`
when true, before opening hardware or the lease. PID, geometry, odometry and the
motor driver's repeated `join()` shutdown issue are outside this change.

Run the hardware-free checks with:

```sh
python3 -m unittest discover -s rae_hw/test -p 'test_pwm*.py' -v
```

The event/readiness tests require ROS Humble Python packages and skip without
them. Both test files are also registered with `ament_cmake_test`. They cover
reset/readback order, process success/failure, late readiness after shutdown,
active drivers, concurrent/repeated launches and simulation exclusion.

On the robot, use suspended wheels and no competing drivers or command sources.
Verify control-only and combined startup, bounded constant-speed commands,
restart, and failure paths. Confirm `0x00000000` before motor activation and
PWM1/2 disabled with zero duty cycle after stopping. This verifies startup;
floor motion and encoder/odometry calibration are separate checks.
