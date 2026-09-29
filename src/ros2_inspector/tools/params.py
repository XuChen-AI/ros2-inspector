"""参数查看工具。"""

from __future__ import annotations

from .. import runner


def register(mcp) -> None:
    @mcp.tool()
    @runner.guard
    def params(node: str, name: str | None = None) -> dict:
        """读取指定节点的参数（只读，不支持设置）。

        何时用：想看某节点配置了什么、某个行为开关当前是什么值。
        参数 node：节点全名，以 / 开头（如 /talker）；
        name：参数名（不带前导斜杠，如 use_sim_time；复杂参数名可含 . 与 /）。
        name 不传=列出该节点全部参数名；传入=读取该参数当前值
        （raw 字段为含类型前缀的原文，如 "Integer value: 10"）。
        失败时返回 error（常见：节点名拼错、节点无此参数）。
        """
        if name is None:
            res = runner.run_ros2(["param", "list", node])
            if not res.ok:
                return {"error": runner.describe_failure(res)}
            names: list[str] = []
            cli_messages: list[str] = []
            for line in res.stdout.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                # CLI 的运行期警告（如 "Timed out waiting for ..."）不是参数名
                lowered = stripped.lower()
                if "timed out" in lowered or "warning" in lowered or "error" in lowered:
                    cli_messages.append(stripped)
                else:
                    names.append(stripped)
            return {
                "node": node,
                "param_count": len(names),
                "params": names,
                "cli_messages": cli_messages or None,
                "note": None if names else "该节点没有可列出的参数",
            }
        res = runner.run_ros2(["param", "get", node, name])
        if not res.ok:
            return {"error": runner.describe_failure(res)}
        return {"node": node, "param": name, "raw": res.stdout.strip()}
