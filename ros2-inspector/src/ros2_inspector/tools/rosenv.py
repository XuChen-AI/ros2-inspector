"""零 ROS 依赖的环境检测工具：纯 Python 标准库，零子进程。"""

from __future__ import annotations

import os
import platform
import shutil
import socket
from pathlib import Path

from .. import runner

# 官方发行版 ↔ Ubuntu 版本对照（截至 2025，供参考性结论）
_SUPPORT_MATRIX = {
    "20.04": ("Foxy", "Galactic"),
    "22.04": ("Humble", "Iron"),
    "24.04": ("Jazzy", "Kilted", "Lyrical"),
}


def register(mcp) -> None:
    @mcp.tool()
    @runner.guard
    def ros_install_info() -> dict:
        """检测本机是否安装了 ROS2、装了哪些发行版。无需安装 ROS 即可运行。

        何时用：不确定这台机器有没有 ROS、装的什么版本、工具能否查看时，
        先调这个再决定用哪些查看类工具。
        返回：installed（布尔）、distros 列表（发行版名+路径）、PATH 上是否
        直接可用 ros2、当前 MCP 工具将使用的发行版、ROS 相关环境变量。
        """
        distros: list[dict] = []
        if Path("/opt/ros").is_dir():
            for path in sorted(Path("/opt/ros").iterdir()):
                if (path / "setup.bash").exists():
                    distros.append({"distro": path.name, "path": str(path)})
        ctx = runner.discover_ros()
        env_vars = {
            key: os.environ[key]
            for key in ("ROS_DOMAIN_ID", "RMW_IMPLEMENTATION")
            if key in os.environ
        }
        return {
            "installed": bool(distros),
            "distros": distros,
            "ros2_on_path": shutil.which("ros2"),
            "active_distro_for_tools": ctx["distro"] if ctx else None,
            "ros_env_vars": env_vars,
            "note": None if distros else "在 /opt/ros 下未发现任何 ROS2 发行版",
        }

    @mcp.tool()
    @runner.guard
    def machine_readiness() -> dict:
        """评估本机是否适合安装/运行 ROS2。无需安装 ROS 即可运行（纯 Python，零子进程）。

        何时用：准备在这台机器上安装 ROS / 部署机器人软件之前的体检。
        返回：操作系统与版本、内核、架构、CPU/内存/磁盘概况、网络接口、
        主机名解析、locale、ROS_DOMAIN_ID，并对照官方支持矩阵给出参考结论
        （verdict 字段）与改进建议（hints 列表）。
        """
        release = platform.freedesktop_os_release()
        version_id = release.get("VERSION_ID", "unknown")
        pretty = release.get("PRETTY_NAME", "unknown")
        mem_total_gb, mem_available_gb = _memory_gb()
        disk = shutil.disk_usage("/")
        ifaces = (
            sorted(os.listdir("/sys/class/net"))
            if Path("/sys/class/net").is_dir()
            else []
        )
        try:
            socket.gethostbyname(socket.gethostname())
            hostname_ok = True
        except OSError:
            hostname_ok = False

        matched = _SUPPORT_MATRIX.get(version_id)
        if matched:
            verdict = f"{pretty} 在官方支持矩阵内，适合安装: {', '.join(matched)}"
        else:
            verdict = f"{pretty} 未在已知支持矩阵中，安装前请另行确认兼容性"

        hints: list[str] = []
        if mem_total_gb is not None and mem_total_gb < 4:
            hints.append("内存不足 4GB，运行 RViz 等可视化工具会吃力")
        if disk.free < 10 * 1024**3:
            hints.append("根分区剩余不足 10GB；ROS2 桌面完整安装通常需要约 15GB")
        if not hostname_ok:
            hints.append("主机名无法解析到本机地址，ROS2 节点间通信可能异常（检查 /etc/hosts）")

        return {
            "os": pretty,
            "version_id": version_id,
            "kernel": platform.release(),
            "arch": platform.machine(),
            "cpu_cores": os.cpu_count(),
            "memory_total_gb": mem_total_gb,
            "memory_available_gb": mem_available_gb,
            "disk_root_total_gb": round(disk.total / 1024**3, 1),
            "disk_root_free_gb": round(disk.free / 1024**3, 1),
            "network_interfaces": ifaces,
            "hostname_resolves": hostname_ok,
            "locale_env": os.environ.get("LANG") or os.environ.get("LC_ALL"),
            "ros_domain_id": os.environ.get("ROS_DOMAIN_ID"),
            "verdict": verdict,
            "hints": hints,
        }


def _memory_gb() -> tuple[float | None, float | None]:
    try:
        total = available = None
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                total = float(line.split()[1]) / 1024**2
            elif line.startswith("MemAvailable:"):
                available = float(line.split()[1]) / 1024**2
        return (
            round(total, 1) if total else None,
            round(available, 1) if available else None,
        )
    except OSError:
        return (None, None)
