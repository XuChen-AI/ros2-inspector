"""ros2-inspector：只读 ROS2 系统巡检 MCP Server。

Server 本体零 ROS 依赖：不 import 任何 ROS 库；ROS 环境由 runner 在
运行时自动探测并注入子进程，未安装 ROS 时相关工具返回友好结论。
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("ros2-inspector")
except PackageNotFoundError:  # 源码目录直接运行、未安装的场景
    __version__ = "0.0.0.dev0"
