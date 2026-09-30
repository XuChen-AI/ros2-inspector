"""动作（action）查看工具。"""

from __future__ import annotations

from .. import runner
from ._parse import parse_typed_list


def register(mcp) -> None:
    @mcp.tool()
    @runner.guard
    def actions(
        action_name: str | None = None, show_types: bool = False, target: str = "local"
    ) -> dict:
        """查询 ROS2 动作（action）。

        何时用：想看系统里有哪些动作、某个动作被谁提供服务。
        action_name 不传=列出全部动作（show_types=True 时附带类型）；
        传入=查看该动作详情：动作服务端/客户端数量（原文返回）。
        参数 action_name：动作全名，以 / 开头（如 /rotate_absolute）；
        target：巡检目标名（不填=本机）。
        失败时返回 error。
        """
        if action_name is None:
            args = ["action", "list"] + (["-t"] if show_types else [])
            res = runner.run_ros2(args, target=target)
            if not res.ok:
                return {"error": runner.describe_failure(res)}
            if show_types:
                items: list = parse_typed_list(res.stdout)
            else:
                items = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            return {
                "target": target,
                "action_count": len(items),
                "actions": items,
                "note": None if items else "当前系统中没有发现动作",
            }
        res = runner.run_ros2(["action", "info", action_name], target=target)
        if not res.ok:
            return {"error": runner.describe_failure(res)}
        return {"target": target, "action": action_name, "report": res.stdout.strip()}
