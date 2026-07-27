#!/usr/bin/env python3
"""Send a Nav2 NavigateToPose goal and stream feedback to stdout.

Usage:
    python3 send_nav_goal.py <x> <y> [frame_id]
"""
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose


def main():
    x = float(sys.argv[1])
    y = float(sys.argv[2])
    frame = sys.argv[3] if len(sys.argv) > 3 else 'map'

    rclpy.init()
    node = Node('send_nav_goal_cli')

    client = ActionClient(
        node, NavigateToPose, '/navigate_to_pose')
    print(f'[{time.time():.1f}] Waiting for action server...')
    if not client.wait_for_server(timeout_sec=15.0):
        print('Action server did not appear in 15s')
        rclpy.shutdown()
        sys.exit(1)
    print(f'[{time.time():.1f}] Action server up')

    goal = NavigateToPose.Goal()
    goal.pose.header.frame_id = frame
    goal.pose.pose.position.x = x
    goal.pose.pose.position.y = y
    goal.pose.pose.position.z = 0.0
    goal.pose.pose.orientation.w = 1.0
    goal.behavior_tree = ''

    print(f'[{time.time():.1f}] Sending goal: ({x}, {y}) frame={frame}')

    def feedback_cb(fb):
        f = fb.feedback
        print(
            f'[{time.time():.1f}] FB: dist_remaining={f.distance_remaining:.2f} '
            f'nav_time={f.navigation_time.sec}.{f.navigation_time.nanosec:09d}s '
            f'pose=({f.current_pose.pose.position.x:.2f}, '
            f'{f.current_pose.pose.position.y:.2f}, '
            f'{f.current_pose.pose.orientation.w:.2f})'
        )

    fut = client.send_goal_async(goal, feedback_callback=feedback_cb)

    # Wait for accept
    rclpy.spin_until_future_complete(node, fut, timeout_sec=10)
    if not fut.done() or not fut.result().accepted:
        print('Goal not accepted')
        rclpy.shutdown()
        sys.exit(1)
    print(f'[{time.time():.1f}] Goal accepted: {fut.result().goal_id.uuid}')

    # Wait for result (timeout 120s) — spin on a callback group
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import SingleThreadedExecutor

    res_fut = fut.result().get_result_async()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin_until_future_complete(res_fut, timeout_sec=120)
        if res_fut.done():
            result = res_fut.result().result
            print(f'[{time.time():.1f}] RESULT: {result}')
        else:
            print(f'[{time.time():.1f}] Timed out after 120s — cancelling')
            client.cancel_goal_async(fut.result().goal_handle)
    except KeyboardInterrupt:
        print('KeyboardInterrupt — cancelling')
        client.cancel_goal_async(fut.result().goal_handle)
    finally:
        executor.shutdown()

    rclpy.shutdown()


if __name__ == '__main__':
    main()