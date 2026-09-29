"""测试辅助：最小发布者（不属于 Server 代码，仅供端到端验证使用）。

需要 ROS 环境，用系统 python3 运行：
    source /opt/ros/<发行版>/setup.bash && python3 tests/demo_talker.py
以 2Hz 向 /inspector_demo/chatter 发布字符串消息。
"""

import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


def main() -> None:
    rclpy.init()
    node = Node("inspector_demo_talker")
    pub = node.create_publisher(String, "/inspector_demo/chatter", 10)
    print("demo talker 已启动: /inspector_demo/chatter @2Hz", flush=True)
    count = 0
    try:
        while rclpy.ok():
            msg = String()
            msg.data = f"hello {count}"
            pub.publish(msg)
            count += 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
