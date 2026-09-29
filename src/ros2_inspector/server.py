"""ros2-inspector MCP Server 入口：FastMCP 实例 + 工具注册。"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools import (
    actions,
    health,
    interfaces,
    nodes,
    overview,
    params,
    rosenv,
    topics,
)

mcp = FastMCP(
    "ros2-inspector",
    instructions=(
        "只读 ROS2 系统巡检工具集。使用建议："
        "1) 不确定本机有没有 ROS 时，先用 ros_install_info / machine_readiness；"
        "2) 不了解系统运行状态时，先用 system_overview 拿全局快照，再按需下钻；"
        "3) 看数据内容用 sample_topic，看频率用 get_topic_rate；"
        "4) 怀疑环境本身有问题用 health_check。"
        "所有工具均为只读查询，不提供任何发布/调用/设置类能力。"
    ),
)

for _module in (rosenv, overview, nodes, topics, params, actions, interfaces, health):
    _module.register(mcp)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
