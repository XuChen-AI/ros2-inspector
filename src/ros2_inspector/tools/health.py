"""ROS 环境健康检查工具。"""

from __future__ import annotations

from .. import runner


def register(mcp) -> None:
    @mcp.tool()
    @runner.guard
    def health_check() -> dict:
        """对 ROS2 环境本身做健康检查：daemon 状态 + doctor 体检结论。

        何时用：怀疑问题不在业务节点，而在 ROS 环境/网络/daemon 本身时；
        或 list_nodes 为空想进一步定位原因。
        返回：daemon_running（是否在运行）、doctor_returncode
        （0 全部通过 / 1 有警告 / 2 有错误）、verdict（doctor 结论行）、
        warnings_found（警告摘要）、raw_tail（doctor 原始输出尾部）。
        注意：doctor 含网络检查，最长约 30 秒。失败时返回 error 字段。
        """
        daemon = runner.run_ros2(["daemon", "status"])
        doc = runner.run_ros2(["doctor"], timeout=30.0)
        lines = [line for line in doc.stdout.splitlines() if line.strip()]
        verdict = lines[-1].strip() if lines else None
        warnings = [
            line.strip()
            for line in doc.stdout.splitlines() + doc.stderr.splitlines()
            if ("warning" in line.lower() or "error" in line.lower())
            and "has been updated" not in line  # 排除"有新版本可用"类噪音
        ]
        out: dict = {
            "daemon_running": daemon.returncode == 0,
            "daemon_status_raw": (daemon.stdout or daemon.stderr).strip()[:200],
            "doctor_returncode": doc.returncode,
            "verdict": verdict,
            "warnings_found": warnings[:20],
            "raw_tail": "\n".join(lines[-20:])[:4000],
        }
        if doc.timed_out:
            out["note"] = "doctor 在 30 秒内未完成（网络检查慢），结论不完整；daemon 状态仍然有效"
        return out
