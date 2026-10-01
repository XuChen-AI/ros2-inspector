"""话题查看工具：列表、详情、限时采样（含内容变化判定）、限时频率统计（含语义结论）。"""

from __future__ import annotations

import hashlib
import re

from .. import runner
from ._parse import parse_typed_list

_AVERAGE_RATE_RE = re.compile(r"average rate:\s*([0-9.]+)")
_GAP_NOTE_THRESHOLD = 2.0


def register(mcp) -> None:
    @mcp.tool()
    @runner.guard
    def list_topics(target: str = "local") -> dict:
        """列出当前系统中的全部话题及其消息类型。

        何时用：想看系统里在传什么数据、某个话题的类型是什么。
        返回：topic_count 与 topics 列表（name + type 字段）。
        失败时返回 error 字段。
        """
        res = runner.run_ros2(["topic", "list", "-t"], target=target)
        if not res.ok:
            return {"error": runner.describe_failure(res)}
        topics = parse_typed_list(res.stdout)
        return {
            "target": target,
            "topic_count": len(topics),
            "topics": topics,
            "note": None if topics else "未发现任何话题——系统可能未启动",
        }

    @mcp.tool()
    @runner.guard
    def get_topic_info(topic: str, verbose: bool = True, target: str = "local") -> dict:
        """获取指定话题的详情：消息类型、发布者数、订阅者数，以及 QoS 配置。

        何时用：确认话题类型；排查"发了没人收/收不到"类问题时看双方数量与 QoS。
        参数 topic：话题全名，以 / 开头（如 /chatter），大小写敏感；
        verbose=True 时附带每个端点的 QoS 详情（推荐）。
        返回：CLI 原始输出。失败时返回 error（常见：话题不存在）。
        """
        args = ["topic", "info"] + (["-v"] if verbose else []) + [topic]
        res, via_fallback, _tried = runner.run_ros2_daemon_fallback(args, target=target)
        if not res.ok:
            return {"error": runner.describe_failure(res)}
        return {
            "target": target,
            "topic": topic,
            "report": res.stdout.strip(),
            "note": "daemon 查询失败，已用 --no-daemon 直连重试" if via_fallback else None,
        }

    @mcp.tool()
    @runner.guard
    def sample_topic(
        topic: str, max_messages: int = 5, timeout_s: float = 5.0, target: str = "local"
    ) -> dict:
        """限时采样话题内容：抓取最多 max_messages 条消息，或 timeout_s 秒到期即停。

        何时用：想看某话题里数据实际长什么样、字段值是否合理；
        以及判断节点是"在干活"还是"空转发常量"（看 content_changed）。
        参数 topic：话题全名（/ 开头）；max_messages：1~50 条，默认 5；
        timeout_s：1~30 秒，默认 5。命令一定会在限时内返回，不会挂起。
        返回：messages_received（实际条数）、stopped_because、distinct_messages
        （去重后的内容种数）、content_changed（内容是否在变化）。
        采样窗口内无消息时 note 字段会说明（话题可能没有发布者）。
        """
        max_messages = max(1, min(int(max_messages), 50))
        timeout_s = min(max(float(timeout_s), 1.0), 30.0)
        res, via_fallback, _tried = runner.stream_ros2_daemon_fallback(
            ["topic", "echo", topic], duration_s=timeout_s,
            max_messages=max_messages, target=target,
        )
        raw = res.text.strip()
        if "Traceback (most recent call last)" in raw:
            if "unknown tag" in raw:
                error = (
                    "目标机器的 ros2 daemon 与其 Python 版本存在 XML-RPC 兼容性问题"
                    "（已知 Ubuntu 26.04/lyrical 的 Python 3.14 会触发），"
                    "自动 --no-daemon 绕过也未成功。可在目标终端手动执行 "
                    "`ros2 topic echo <话题> --no-daemon` 对照确认"
                )
            else:
                error = (
                    "echo 在目标机器上抛异常退出。常见原因：话题没有发布者，"
                    "CLI 无法推断消息类型；或类型定义缺失。"
                    "可先 get_topic_info 看发布者数量，或换 list_topics 里的活跃话题"
                )
            return {
                "target": target,
                "topic": topic,
                "error": error,
                "cli_tail": "\n".join(raw.splitlines()[-3:])[:500],
            }
        if res.returncode not in (0, None) and not raw:
            return {
                "target": target,
                "topic": topic,
                "error": (
                    f"echo 退出码 {res.returncode}。常见原因：话题不存在，"
                    "或没有发布者导致无法确定消息类型"
                ),
            }
        distinct, content_changed = _distinct_blocks(raw)
        if res.hit_message_limit:
            stopped = "message_limit"
        elif res.timed_out:
            stopped = "timeout"
        else:
            stopped = "publisher_stopped"
        note = None
        if via_fallback and raw:
            note = "daemon 路径失败，已自动改用 --no-daemon 直连采样（目标 daemon 存在兼容性问题）"
        elif not raw:
            note = "采样窗口内未收到任何消息——话题可能没有发布者或频率极低"
        elif not content_changed:
            note = "窗口内所有消息内容完全相同——节点可能在空转（发送常量/未更新数据）"
        return {
            "target": target,
            "topic": topic,
            "messages_received": res.message_count,
            "stopped_because": stopped,
            "distinct_messages": distinct,
            "content_changed": content_changed,
            "raw": raw or None,
            "note": note,
        }

    @mcp.tool()
    @runner.guard
    def get_topic_rate(topic: str, duration_s: float = 5.0, target: str = "local") -> dict:
        """限时统计话题发布频率：观察 duration_s 秒后返回平均频率与稳定性结论。

        何时用：排查"数据不更新/更新太慢/断断续续"类问题。
        参数 topic：话题全名（/ 开头）；duration_s：1~30 秒，默认 5。
        返回：samples（各秒窗频率）、average/min/max_rate_hz、verdict（一句话结论，
        如"稳定 ~10Hz"/"断续：2 次超 2s 间隙"/"窗口内无数据"）。
        """
        duration_s = min(max(float(duration_s), 1.0), 30.0)
        res, via_fallback, _tried = runner.stream_ros2_daemon_fallback(
            ["topic", "hz", topic], duration_s=duration_s, target=target
        )
        rates = [float(v) for v in _AVERAGE_RATE_RE.findall(res.text)]
        out: dict = {
            "target": target,
            "topic": topic,
            "duration_s": duration_s,
            "samples": rates,
            "average_rate_hz": round(sum(rates) / len(rates), 2) if rates else None,
            "min_rate_hz": min(rates) if rates else None,
            "max_rate_hz": max(rates) if rates else None,
            "gap_count": res.gap_count,
            "max_gap_s": res.max_gap_s,
        }
        out["verdict"] = _rate_verdict(rates, res.gap_count, res.max_gap_s)
        out["raw_tail"] = "\n".join(res.text.strip().splitlines()[-8:])
        if via_fallback and rates:
            out["note"] = "daemon 路径失败，已自动改用 --no-daemon 直连统计（目标 daemon 存在兼容性问题）"
        return out


def _distinct_blocks(raw: str) -> tuple[int, bool]:
    """按分隔符切块去重，返回 (去重种数, 内容是否变化)。"""
    blocks = [b.strip() for b in re.split(r"^---$", raw, flags=re.MULTILINE) if b.strip()]
    if not blocks:
        return 0, False
    fingerprints = {hashlib.sha256(b.encode("utf-8", "replace")).hexdigest() for b in blocks}
    return len(fingerprints), len(fingerprints) > 1


def _rate_verdict(rates: list[float], gap_count: int, max_gap_s: float) -> str:
    if not rates:
        return "窗口内未统计到频率——话题可能没有发布者，或 ROS_DOMAIN_ID 不匹配"
    avg = sum(rates) / len(rates)
    parts: list[str] = []
    if gap_count:
        avg_interval = 1.0 / avg if avg > 0 else float("inf")
        if avg_interval > _GAP_NOTE_THRESHOLD:
            # 低频话题静默是常态，不算断流
            parts.append(f"低频话题（平均 {avg:.2f} Hz），窗口内 {gap_count} 次静默间隔属正常")
        else:
            parts.append(
                f"断续：{gap_count} 次超过 {_GAP_NOTE_THRESHOLD:.0f}s 的间隙（最长 {max_gap_s:.1f}s）"
            )
    if (max(rates) - min(rates)) > max(0.5 * avg, 1.0):
        parts.append(f"频率波动大（{min(rates):.1f}~{max(rates):.1f} Hz）")
    if not parts:
        parts.append(f"稳定，平均 {avg:.1f} Hz")
    else:
        parts.append(f"平均 {avg:.1f} Hz")
    return "；".join(parts)
