"""话题查看工具：列表、详情、限时采样、限时频率统计。"""

from __future__ import annotations

import re

from .. import runner
from ._parse import parse_typed_list

_AVERAGE_RATE_RE = re.compile(r"average rate:\s*([0-9.]+)")


def register(mcp) -> None:
    @mcp.tool()
    @runner.guard
    def list_topics() -> dict:
        """列出当前系统中的全部话题及其消息类型。

        何时用：想看系统里在传什么数据、某个话题的类型是什么。
        返回：topic_count 与 topics 列表（name + type 字段）。
        失败时返回 error 字段。
        """
        res = runner.run_ros2(["topic", "list", "-t"])
        if not res.ok:
            return {"error": runner.describe_failure(res)}
        topics = parse_typed_list(res.stdout)
        return {
            "topic_count": len(topics),
            "topics": topics,
            "note": None if topics else "未发现任何话题——系统可能未启动",
        }

    @mcp.tool()
    @runner.guard
    def get_topic_info(topic: str, verbose: bool = True) -> dict:
        """获取指定话题的详情：消息类型、发布者数、订阅者数，以及 QoS 配置。

        何时用：确认话题类型；排查"发了没人收/收不到"类问题时看双方数量与 QoS。
        参数 topic：话题全名，以 / 开头（如 /chatter），大小写敏感；
        verbose=True 时附带每个端点的 QoS 详情（推荐）。
        返回：CLI 原始输出。失败时返回 error（常见：话题不存在）。
        """
        args = ["topic", "info"] + (["-v"] if verbose else []) + [topic]
        res = runner.run_ros2(args)
        if not res.ok:
            return {"error": runner.describe_failure(res)}
        return {"topic": topic, "report": res.stdout.strip()}

    @mcp.tool()
    @runner.guard
    def sample_topic(topic: str, max_messages: int = 5, timeout_s: float = 5.0) -> dict:
        """限时采样话题内容：抓取最多 max_messages 条消息，或 timeout_s 秒到期即停。

        何时用：想看某话题里数据实际长什么样、字段值是否合理。
        参数 topic：话题全名（/ 开头）；max_messages：1~50 条，默认 5；
        timeout_s：1~15 秒，默认 5。命令一定会在限时内返回，不会挂起。
        返回：messages_received（实际条数）、stopped_because
        （message_limit / timeout / publisher_stopped）、raw（消息原文，未解析）。
        采样窗口内无消息时 note 字段会说明（话题可能没有发布者）。
        """
        max_messages = max(1, min(int(max_messages), 50))
        timeout_s = min(max(float(timeout_s), 1.0), 15.0)
        res = runner.stream_ros2(
            ["topic", "echo", topic], duration_s=timeout_s, max_messages=max_messages
        )
        raw = res.text.strip()
        if res.returncode not in (0, None) and not raw:
            return {
                "topic": topic,
                "error": (
                    f"echo 退出码 {res.returncode}。常见原因：话题不存在，"
                    "或没有发布者导致无法确定消息类型"
                ),
            }
        if res.hit_message_limit:
            stopped = "message_limit"
        elif res.timed_out:
            stopped = "timeout"
        else:
            stopped = "publisher_stopped"
        return {
            "topic": topic,
            "messages_received": res.message_count,
            "stopped_because": stopped,
            "raw": raw or None,
            "note": None if raw else "采样窗口内未收到任何消息——话题可能没有发布者或频率极低",
        }

    @mcp.tool()
    @runner.guard
    def get_topic_rate(topic: str, duration_s: float = 5.0) -> dict:
        """限时统计话题发布频率：观察 duration_s 秒后返回平均频率。

        何时用：排查"数据不更新/更新太慢"类问题——先看频率是否正常。
        参数 topic：话题全名（/ 开头）；duration_s：1~15 秒，默认 5。
        返回：average_rate_hz（平均频率，未统计到时为 None）、raw_tail（原始输出尾部）。
        note 字段会说明未统计到频率的原因。
        """
        duration_s = min(max(float(duration_s), 1.0), 15.0)
        res = runner.stream_ros2(["topic", "hz", topic], duration_s=duration_s)
        rates = _AVERAGE_RATE_RE.findall(res.text)
        out: dict = {
            "topic": topic,
            "duration_s": duration_s,
            "average_rate_hz": float(rates[-1]) if rates else None,
            "raw_tail": "\n".join(res.text.strip().splitlines()[-8:]),
        }
        if not rates:
            out["note"] = "采样时长内未统计到频率——话题可能没有发布者"
        return out
