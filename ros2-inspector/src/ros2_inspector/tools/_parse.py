"""CLI 输出解析辅助：只做轻量提取，解析不动时原样透传给大模型。"""

from __future__ import annotations


def parse_typed_list(text: str) -> list[dict]:
    """解析 `ros2 topic list -t` / `ros2 action list -t` 风格输出。

    每行形如 `/name [pkg/type/Name]`；没有类型标注时 type 为 None。
    """
    items: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.endswith("]") and " [" in line:
            name, _, typ = line.partition(" [")
            items.append({"name": name.strip(), "type": typ[:-1].strip()})
        else:
            items.append({"name": line, "type": None})
    return items


def parse_node_connections(text: str) -> tuple[list[str], list[str]]:
    """从 `ros2 node info` 输出中提取发布/订阅的话题名。"""
    publishers: list[str] = []
    subscribers: list[str] = []
    section: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower().rstrip(":")
        if line.endswith(":") and lowered in ("publishers", "subscribers"):
            section = lowered
            continue
        if line.startswith("/"):
            name = line.split(":")[0].split()[0]
            if section == "publishers":
                publishers.append(name)
            elif section == "subscribers":
                subscribers.append(name)
    return publishers, subscribers
