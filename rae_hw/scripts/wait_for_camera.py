#!/usr/bin/env python3
"""Wait for the physical RAE camera's pipeline configuration service."""

import argparse
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.utilities import remove_ros_args
from std_srvs.srv import Trigger


def wait_for_camera(node, camera, timeout, settle_time=15.0):
    """Require pipeline setup and preserve the existing firmware settling time."""
    client = node.create_client(Trigger, camera + '/start_camera')
    started = time.monotonic()
    try:
        if not client.wait_for_service(timeout_sec=timeout):
            raise RuntimeError('Timed out waiting for camera pipeline configuration')
        time.sleep(max(0.0, settle_time - (time.monotonic() - started)))
    finally:
        node.destroy_client(client)


def main():
    """Exit successfully only when launch may proceed with the checked reset."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', required=True)
    parser.add_argument('--timeout', type=float, default=60.0)
    args = parser.parse_args(remove_ros_args()[1:])
    rclpy.init()
    node = Node('rae_camera_startup_check')
    try:
        wait_for_camera(node, args.camera.rstrip('/'), args.timeout)
        node.get_logger().info('Camera pipeline configuration confirmed')
        return 0
    except (RuntimeError, KeyboardInterrupt) as exc:
        node.get_logger().error(str(exc))
        return 1
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    sys.exit(main())
