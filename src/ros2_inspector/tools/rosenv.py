"""环境检测工具：装没装 ROS、机器适不适合跑 ROS——体检"当前目标指向的机器"。

实现走 runner.run_probe（代码内固定 snippet，零用户输入拼接），
因此本机 / ssh 远端 / 容器目标语义完全一致。
"""

from __future__ import annotations

from .. import runner

# 官方发行版 ↔ Ubuntu 版本对照（截至 2025，供参考性结论）
_SUPPORT_MATRIX = {
    "20.04": ("Foxy", "Galactic"),
    "22.04": ("Humble", "Iron"),
    "24.04": ("Jazzy", "Kilted", "Lyrical"),
}

_INSTALL_INFO_SNIPPET = (
    'echo "DISTROS $(ls /opt/ros 2>/dev/null | tr \'\\n\' \' \')"; '
    'echo "ROS2 $(command -v ros2 2>/dev/null)"; '
    'echo "DOMAIN ${ROS_DOMAIN_ID:-}"; '
    'echo "RMW ${RMW_IMPLEMENTATION:-}"'
)

_READINESS_SNIPPET = (
    '(. /etc/os-release 2>/dev/null && echo "OS ${PRETTY_NAME:-unknown}" && echo "VERID ${VERSION_ID:-unknown}") '
    '|| { echo "OS unknown"; echo "VERID unknown"; }; '
    'echo "KERNEL $(uname -r 2>/dev/null)"; '
    'echo "ARCH $(uname -m 2>/dev/null)"; '
    'echo "CORES $(nproc 2>/dev/null)"; '
    'awk \'/MemTotal/{printf "MEMTOTAL %.1f\\n",$2/1048576}/MemAvailable/{printf "MEMAVAIL %.1f\\n",$2/1048576}\' /proc/meminfo 2>/dev/null; '
    'df -k / 2>/dev/null | awk \'NR==2{printf "DISK %.1f %.1f\\n",$2/1048576,$4/1048576}\'; '
    'echo "NET $(ls /sys/class/net 2>/dev/null | tr \'\\n\' \' \')"; '
    'getent hosts "$(hostname)" >/dev/null 2>&1 && echo "HOSTRESOLV ok" || echo "HOSTRESOLV fail"; '
    'echo "LOCALE ${LANG:-${LC_ALL:-}}"; '
    'echo "DOMAIN ${ROS_DOMAIN_ID:-}"'
)


def register(mcp) -> None:
    @mcp.tool()
    @runner.guard
    def ros_install_info(target: str = "local") -> dict:
        """检测目标机器是否安装了 ROS2、装了哪些发行版。无需安装 ROS 即可运行。

        何时用：不确定目标机器有没有 ROS、装的什么版本、工具能否查看时，
        先调这个再决定用哪些查看类工具。
        参数 target：巡检目标名（本机/远端板子/容器），指哪查哪。
        返回：installed（布尔）、distros 列表（发行版名+路径）、PATH 上是否
        直接可用 ros2、巡检工具将使用的发行版、ROS 相关环境变量。
        """
        cfg = runner.resolve_target(target)
        returncode, out, err = runner.run_probe(cfg, _INSTALL_INFO_SNIPPET)
        if returncode != 0:
            return {"error": f"目标 {target!r} 环境探测失败: {(err or out).strip()[:300]}"}
        distro_names: list[str] = []
        ros2_path: str | None = None
        domain = rmw = None
        for line in out.splitlines():
            label, _, value = line.partition(" ")
            value = value.strip()
            if label == "DISTROS":
                distro_names = value.split()
            elif label == "ROS2":
                ros2_path = value or None
            elif label == "DOMAIN":
                domain = value or None
            elif label == "RMW":
                rmw = value or None
        distros = [{"distro": name, "path": f"/opt/ros/{name}"} for name in sorted(distro_names)]
        env = runner.resolve_ros_env(cfg)
        return {
            "target": target,
            "installed": bool(distros),
            "distros": distros,
            "ros2_on_path": ros2_path,
            "active_distro_for_tools": env.distro if env else None,
            "ros_env_vars": {k: v for k, v in (("ROS_DOMAIN_ID", domain), ("RMW_IMPLEMENTATION", rmw)) if v},
            "note": None if distros else "在目标机器 /opt/ros 下未发现任何 ROS2 发行版",
        }

    @mcp.tool()
    @runner.guard
    def machine_readiness(target: str = "local") -> dict:
        """评估目标机器是否适合安装/运行 ROS2。无需安装 ROS 即可运行。

        何时用：准备在目标机器上安装 ROS / 部署机器人软件之前的体检。
        参数 target：巡检目标名（本机/远端板子/容器），指哪查哪。
        返回：操作系统与版本、内核、架构、CPU/内存/磁盘概况、网络接口、
        主机名解析、locale、ROS_DOMAIN_ID，并对照官方支持矩阵给出参考结论
        （verdict 字段）与改进建议（hints 列表）。
        """
        cfg = runner.resolve_target(target)
        returncode, out, err = runner.run_probe(cfg, _READINESS_SNIPPET)
        if returncode != 0:
            return {"error": f"目标 {target!r} 环境探测失败: {(err or out).strip()[:300]}"}
        info: dict[str, str] = {}
        for line in out.splitlines():
            label, _, value = line.partition(" ")
            info[label] = value.strip()

        version_id = info.get("VERID", "unknown")
        pretty = info.get("OS", "unknown")
        disk_total_gb = _float(info.get("DISK", "").split()[0]) if info.get("DISK") else None
        disk_free_gb = _float(info.get("DISK", "").split()[1]) if len(info.get("DISK", "").split()) > 1 else None
        matched = _SUPPORT_MATRIX.get(version_id)
        if matched:
            verdict = f"{pretty} 在官方支持矩阵内，适合安装: {', '.join(matched)}"
        else:
            verdict = f"{pretty} 未在已知支持矩阵中，安装前请另行确认兼容性"

        hints: list[str] = []
        mem_total = _float(info.get("MEMTOTAL"))
        if mem_total is not None and mem_total < 4:
            hints.append("内存不足 4GB，运行 RViz 等可视化工具会吃力")
        if disk_free_gb is not None and disk_free_gb < 10:
            hints.append("根分区剩余不足 10GB；ROS2 桌面完整安装通常需要约 15GB")
        if info.get("HOSTRESOLV") == "fail":
            hints.append("主机名无法解析到本机地址，ROS2 节点间通信可能异常（检查 /etc/hosts）")

        return {
            "target": target,
            "os": pretty,
            "version_id": version_id,
            "kernel": info.get("KERNEL") or None,
            "arch": info.get("ARCH") or None,
            "cpu_cores": int(_float(info.get("CORES")) or 0) or None,
            "memory_total_gb": mem_total,
            "memory_available_gb": _float(info.get("MEMAVAIL")),
            "disk_root_total_gb": disk_total_gb,
            "disk_root_free_gb": disk_free_gb,
            "network_interfaces": info.get("NET", "").split() or [],
            "hostname_resolves": info.get("HOSTRESOLV") == "ok",
            "locale_env": info.get("LOCALE") or None,
            "ros_domain_id": info.get("DOMAIN") or None,
            "verdict": verdict,
            "hints": hints,
        }


def _float(raw: str | None) -> float | None:
    try:
        return round(float(raw), 1) if raw else None
    except (TypeError, ValueError):
        return None
