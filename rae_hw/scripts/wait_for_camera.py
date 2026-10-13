#!/usr/bin/env python3
"""Confirm live front/back camera streams and the configured camera service."""

import argparse
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.utilities import remove_ros_args
from sensor_msgs.msg import Image
from std_srvs.srv import Trigger


def wait_for_camera(node, camera, timeout, phase='streams', settle_time=15.0):
    """Require new frames from both stereo pipelines after service discovery."""
    client = node.create_client(Trigger, camera + '/start_camera')
    if phase == 'configured':
        started = time.monotonic()
        try:
            if client.wait_for_service(timeout_sec=timeout):
                # Preserve the existing RAE firmware settling interval. Service
                # discovery and post-reset frames are independent readiness checks.
                time.sleep(max(0.0, settle_time - (time.monotonic() - started)))
                return
            raise RuntimeError('Timed out waiting for camera pipeline configuration')
        finally:
            node.destroy_client(client)
    topics = [camera + '/' + stream + '/image_raw'
              for stream in ('stereo_front', 'stereo_back')]
    namespace, name = camera.rsplit('/', 1)
    namespace = namespace or '/'
    seen = set()

    def received(topic):
        def callback(msg):
            if client.service_is_ready():
                seen.add(topic)
        return callback

    subscriptions = [node.create_subscription(
        Image, topic, received(topic), qos_profile_sensor_data) for topic in topics]
    deadline = time.monotonic() + timeout
    publisher_error = ''
    try:
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if seen == set(topics) and client.service_is_ready():
                publisher_error = ''
                for topic in topics:
                    publishers = node.get_publishers_info_by_topic(topic)
                    if (len(publishers) != 1
                            or publishers[0].node_name != name
                            or (publishers[0].node_namespace or '/') != namespace):
                        # DDS graph metadata can lag behind the first frame.
                        # Keep motors blocked while discovery converges.
                        endpoints = [(p.node_name, p.node_namespace) for p in publishers]
                        publisher_error = f'; unexpected image publisher on {topic}: {endpoints}'
                        break
                if not publisher_error:
                    return
        raise RuntimeError('Timed out waiting for live front/back camera streams' + publisher_error)
    finally:
        for subscription in subscriptions:
            node.destroy_subscription(subscription)
        node.destroy_client(client)


def main():
    """Exit successfully only when the launch may proceed with the PWM reset."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', required=True)
    parser.add_argument('--timeout', type=float, default=60.0)
    parser.add_argument('--phase', choices=('configured', 'streams'), default='streams')
    args = parser.parse_args(remove_ros_args()[1:])
    rclpy.init()
    node = Node('rae_camera_startup_check')
    try:
        wait_for_camera(node, args.camera.rstrip('/'), args.timeout, args.phase)
        node.get_logger().info(f'Camera readiness phase confirmed: {args.phase}')
        return 0
    except (RuntimeError, KeyboardInterrupt) as exc:
        node.get_logger().error(str(exc))
        return 1
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    sys.exit(main())
