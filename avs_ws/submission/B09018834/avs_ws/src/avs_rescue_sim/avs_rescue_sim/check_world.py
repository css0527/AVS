"""Check the loaded course through ROS before spawning the rover.

Avoid short-lived `gz topic` connections here: Gazebo Classic 11's master can
reuse a live connection index after a diagnostic connection disconnects, losing
GUI subscriptions. The factory ROS service does not touch that transport.
"""
import sys
import xml.etree.ElementTree as ET

import rclpy
from gazebo_msgs.srv import GetModelList


def validate_models(response, expected):
    if response is None or not response.success:
        return False
    # This runs before spawning, so the world must contain exactly the models
    # from the requested SDF, with neither a stale rover nor another course.
    return set(response.model_names) == expected


def main(args=None):
    args = sys.argv[1:] if args is None else args
    world = ET.parse(args[0]).getroot().find('world')
    expected = {model.attrib['name'] for model in world.findall('model')}
    rclpy.init(args=[])
    node = rclpy.create_node('verify_rescue_course')
    try:
        client = node.create_client(GetModelList, '/get_model_list')
        if not client.wait_for_service(timeout_sec=25.0):
            print('[AVS WORLD ERROR] Gazebo model service unavailable after 25 s.', flush=True)
            return 1
        future = client.call_async(GetModelList.Request())
        rclpy.spin_until_future_complete(node, future, timeout_sec=5.0)
        response = future.result() if future.done() else None
        if validate_models(response, expected):
            print(f'[AVS WORLD VERIFIED] {world.attrib["name"]}: '
                  f'all {len(expected)} course models match {args[0]}', flush=True)
            return 0
        received = response.model_names if response else []
        print(f'[AVS WORLD ERROR] Course model mismatch: {received}; '
              'refusing to spawn or navigate.', flush=True)
        return 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
