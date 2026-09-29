"""节点与系统总览类工具。"""

from __future__ import annotations

from .. import runner
from ._parse import parse_node_connections, parse_typed_list

_MAX_NODE_DETAIL = 12
_NODE_INFO_TIMEOUT_S = 5.0


def register(mcp) -> None:
    @mcp.tool()
    @runner.guard
    def system_overview() -> dict:
        """获取当前 ROS2 系统的一页式快照：节点、话题、连接关系与数量统计。

        何时用：回答"系统现在什么状态"类问题的第一入口——先看总览，
        发现异常节点/话题后再用 get_node_info / get_topic_info / sample_topic 下钻。
        返回：node_count / topic_count 统计、nodes 列表、topics 列表（含类型）、
        connections（每个节点的发布/订阅概况）。节点数超过 12 个时只展开前 12 个
        （notes 字段会注明）。失败时返回 error 或 notes 说明原因，不会中断会话。
        """
        notes: list[str] = []
        nodes_res = runner.run_ros2(["node", "list"])
        if not nodes_res.ok:
            return {"error": runner.describe_failure(nodes_res)}
        nodes = [line.strip() for line in nodes_res.stdout.splitlines() if line.strip()]

        topics: list[dict] = []
        topics_res = runner.run_ros2(["topic", "list", "-t"])
        if topics_res.ok:
            topics = parse_typed_list(topics_res.stdout)
        else:
            notes.append("话题列表获取失败: " + runner.describe_failure(topics_res))

        connections: dict[str, dict] = {}
        for node in nodes[:_MAX_NODE_DETAIL]:
            info = runner.run_ros2(["node", "info", node], timeout=_NODE_INFO_TIMEOUT_S)
            if info.ok:
                pubs, subs = parse_node_connections(info.stdout)
                connections[node] = {"publishes": pubs, "subscribes": subs}
            else:
                connections[node] = {"detail": "获取失败（节点可能刚好退出）"}
        if len(nodes) > _MAX_NODE_DETAIL:
            notes.append(
                f"节点数 {len(nodes)} 超过详情上限 {_MAX_NODE_DETAIL}，仅展开前 {_MAX_NODE_DETAIL} 个"
            )

        return {
            "node_count": len(nodes),
            "topic_count": len(topics),
            "nodes": nodes,
            "topics": topics,
            "connections": connections,
            "notes": notes,
        }
