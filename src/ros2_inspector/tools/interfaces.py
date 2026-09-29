"""消息接口定义查看工具。"""

from __future__ import annotations

from .. import runner


def register(mcp) -> None:
    @mcp.tool()
    @runner.guard
    def show_interface(interface_type: str) -> dict:
        """查看 ROS2 消息/服务/动作类型的字段定义。

        何时用：拿到一个类型名（如 sample_topic 返回里的 type）想看它有哪些字段、
        各字段是什么意思。
        参数 interface_type：格式为 包/类型/名称，例如 std_msgs/msg/String、
        example_interfaces/srv/AddTwoInts、turtlesim/action/RotateAbsolute。
        返回：definition 字段为字段定义原文。失败时返回 error（常见：类型名拼错、
        相应功能包未安装）。
        """
        res = runner.run_ros2(["interface", "show", interface_type])
        if not res.ok:
            return {"error": runner.describe_failure(res)}
        return {"interface_type": interface_type, "definition": res.stdout.strip()}
