"""节点查看工具。"""

from __future__ import annotations

from .. import runner


def register(mcp) -> None:
    @mcp.tool()
    @runner.guard
    def list_nodes(target: str = "local") -> dict:
        """列出当前 ROS2 系统中所有正在运行的节点名。

        何时用：确认某个节点是否活着；排查前先看看系统里有什么。
        参数 target：巡检目标名（不填=本机；远端板子/容器先 list_targets 查看）。
        返回：node_count 与 nodes 列表（全名以 / 开头）。
        nodes 为空说明未发现任何节点——系统未启动、与目标机器 ROS_DOMAIN_ID
        不同或 daemon 异常，可用 health_check 进一步检查。
        失败时返回 error 字段。
        """
        res, via_fallback, tried_fallback = runner.run_ros2_daemon_fallback(
            ["node", "list"], target=target, fallback_on_empty=True
        )
        if not res.ok:
            return {"error": runner.describe_failure(res)}
        nodes = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        if via_fallback and nodes:
            note = "daemon 未能发现节点，已用 --no-daemon 直连 DDS 发现（daemon 缓存可能陈旧，建议目标终端执行 ros2 daemon stop && ros2 daemon start）"
        elif tried_fallback and not nodes:
            note = "daemon 与 --no-daemon 直连发现均为空——目标机器上大概率确实没有运行中的 ROS 节点，或发现被网络/域配置阻断"
        else:
            note = None if nodes else "未发现任何节点——ROS2 系统可能未启动，或 ROS_DOMAIN_ID 与目标机器不同"
        return {
            "target": target,
            "node_count": len(nodes),
            "nodes": nodes,
            "note": note,
        }

    @mcp.tool()
    @runner.guard
    def get_node_info(node: str, target: str = "local") -> dict:
        """获取指定节点的连接详情：发布/订阅哪些话题、提供/调用哪些服务与动作。

        何时用：已知节点名，想看它与系统其他部分的连接关系；
        或配合 system_overview 下钻某个可疑节点。
        参数 node：节点全名，以 / 开头（如 /talker），大小写敏感；
        target：巡检目标名（不填=本机）。
        返回：CLI 原始分节报告（Publishers/Subscribers/Service Servers/Action
        Servers 等）。失败时返回 error（常见原因：名称拼错、节点刚好退出）。
        """
        res = runner.run_ros2(["node", "info", node], target=target)
        if not res.ok:
            return {"error": runner.describe_failure(res)}
        return {"target": target, "node": node, "report": res.stdout.strip()}
