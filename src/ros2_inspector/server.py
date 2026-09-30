"""ros2-inspector MCP Server 入口：FastMCP 实例 + 工具注册。"""

from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP

from . import __version__, targets
from .tools import (
    actions,
    health,
    interfaces,
    manage,
    nodes,
    overview,
    params,
    rosenv,
    topics,
)

mcp = FastMCP(
    "ros2-inspector",
    instructions=(
        "只读 ROS2 系统巡检工具集，可巡检本机，也可通过 ssh 巡检远端板子/容器。"
        "使用建议：\n"
        "1) 用户提到远端/板子/容器时，先 list_targets 看已登记目标；没有合适的就"
        "向用户要地址和认证方式，用 add_target 登记（先出预览，用户确认后 confirm=true 落盘）；\n"
        "2) 每次会话第一次使用某个远端目标前，必须先 check_target 并把身份卡"
        "（主机名/系统/ROS 发行版/描述）亮给用户确认，再开始查询；\n"
        "3) 不了解系统运行状态时，先用 system_overview 拿全局快照，再按需下钻；\n"
        "4) 看数据内容用 sample_topic（content_changed 可判断节点是否空转），"
        "看频率用 get_topic_rate（verdict 是稳定性结论）；\n"
        "5) 不确定目标机器有没有 ROS 时用 ros_install_info，怀疑环境本身有问题用 health_check。\n"
        "所有工具均为只读查询，不提供任何发布/调用/设置类能力；"
        "target 参数不填即巡检本机。"
    ),
)

for _module in (manage, rosenv, overview, nodes, topics, params, actions, interfaces, health):
    _module.register(mcp)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ros2-inspector",
        description="只读 ROS2 系统巡检 MCP Server（stdio 传输，支持 ssh 远端目标）",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--targets",
        metavar="PATH",
        default=None,
        help="目标配置文件路径（默认 ~/.config/ros2-inspector/targets.json，热加载）",
    )
    args = parser.parse_args()
    if args.targets:
        targets.set_config_path(args.targets)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
