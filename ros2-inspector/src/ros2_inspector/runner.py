"""统一子进程执行器：所有 ros2 CLI 调用的唯一出口。

职责：
- ROS 环境自动探测：扫描 /opt/ros/*，一次性提取发行版环境变量供子进程使用；
  Server 本体不 import 任何 ROS 库，未安装 ROS 时相关工具返回友好结论而非崩溃。
- 四层安全围栏：动词白名单 / 黑名单令牌 / 参数正则校验 / 审计日志。
- 超时控制与进程组强杀：保证调用方窗口永远不会被流式命令挂住。
- 输出捕获与错误分类（友好提示）。

工具函数不允许自行 subprocess，必须经由本模块。
"""

from __future__ import annotations

import functools
import logging
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 10.0
MAX_TIMEOUT_S = 30.0

# ── 安全围栏第 2 层：子命令白名单（精确到"动词+子动词"前缀） ───────────
_ALLOWED_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("node", "list"), ("node", "info"),
    ("topic", "list"), ("topic", "info"), ("topic", "echo"), ("topic", "hz"),
    ("param", "list"), ("param", "get"),
    ("action", "list"), ("action", "info"),
    ("interface", "show"),
    ("doctor",), ("daemon", "status"),
)

# ── 安全围栏第 2 层：黑名单令牌（精确匹配整个参数，双保险） ─────────────
_BANNED_TOKENS: frozenset[str] = frozenset({
    "pub", "publish", "call", "set", "launch", "delete", "security",
    "run", "pkg", "service", "bag", "component", "lifecycle",
    "multicast", "wasm", "extension_points",
})

# ── 安全围栏第 3 层：参数格式白名单 ────────────────────────────────
_FLAG_RE = re.compile(r"^-{1,2}[A-Za-z0-9][A-Za-z0-9-]*$")
_ROS_NAME_RE = re.compile(r"^/[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*$")
_PARAM_NAME_RE = re.compile(r"^[A-Za-z0-9_./]+$")
_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_]+/(?:msg|srv|action)/[A-Za-z0-9_]+$")
_NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")

_MAX_TOKENS = 8
_MAX_TOKEN_LEN = 120


class SecurityError(RuntimeError):
    """参数未通过安全围栏校验（响亮报错，转为 isError 结果）。"""


class RunnerError(RuntimeError):
    """ros2 CLI 无法执行（如未检测到 ROS 环境）；工具层转为友好内容。"""


# ── 审计日志（安全围栏第 4 层） ───────────────────────────────────
_log = logging.getLogger("ros2_inspector.audit")


def _setup_audit_logger() -> None:
    if _log.handlers:
        return
    _log.setLevel(logging.INFO)
    _log.propagate = False
    fmt = logging.Formatter("%(asctime)s | %(message)s")
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    _log.addHandler(stream)
    try:
        path = Path(os.environ.get("ROS2_INSPECTOR_AUDIT_LOG", Path.cwd() / "audit.log"))
        file_handler = logging.FileHandler(path)
        file_handler.setFormatter(fmt)
        _log.addHandler(file_handler)
    except OSError:
        pass  # 文件不可写时仅保留 stderr 审计


# ── ROS 环境自动探测 ────────────────────────────────────────────
_ROS_ROOT = Path("/opt/ros")
_discovery_cache: dict | None = None
_discovery_done = False


def _probe_env(root: Path) -> dict[str, str] | None:
    """source 发行版 setup.bash 后抓取完整环境变量。

    命令为固定字符串拼扫描到的 /opt/ros 路径，无用户输入，无注入面。
    """
    setup = root / "setup.bash"
    if not setup.exists():
        return None
    cmd = f'source "{setup}" >/dev/null 2>&1 && env -0'
    try:
        proc = subprocess.run(
            ["/bin/bash", "-c", cmd],
            capture_output=True,
            timeout=20,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/")},
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    env: dict[str, str] = {}
    for entry in proc.stdout.split(b"\0"):
        if b"=" in entry:
            key, _, value = entry.partition(b"=")
            env[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return env or None


def discover_ros(force: bool = False) -> dict | None:
    """探测本机 ROS2 发行版。

    返回 {"distro", "root", "ros2_path", "env"}；未检测到返回 None。
    探测范围：/opt/ros/*/setup.bash 与 PATH 上的 ros2。结果缓存。
    """
    global _discovery_cache, _discovery_done
    if _discovery_done and not force:
        return _discovery_cache
    _discovery_done = True
    _discovery_cache = None

    candidates: list[Path] = []
    which = shutil.which("ros2")
    if which:
        # /opt/ros/X/bin/ros2 → /opt/ros/X
        candidates.append(Path(which).parent.parent)
    if _ROS_ROOT.is_dir():
        candidates.extend(sorted(p.parent for p in _ROS_ROOT.glob("*/setup.bash")))

    seen: set[Path] = set()
    for root in candidates:
        if root in seen:
            continue
        seen.add(root)
        env = _probe_env(root)
        if env is None:
            continue
        ros2 = shutil.which("ros2", path=env.get("PATH", ""))
        if not ros2:
            continue
        _discovery_cache = {
            "distro": root.name if root.parent == _ROS_ROOT else "unknown",
            "root": str(root),
            "ros2_path": ros2,
            "env": env,
        }
        break
    return _discovery_cache


def _ros_context() -> dict:
    ctx = discover_ros()
    if ctx is None:
        raise RunnerError(
            "本机未检测到 ROS2 环境（已扫描 /opt/ros 与 PATH）。"
            "可调用 ros_install_info 查看安装详情，或 machine_readiness 检查机器适配性。"
        )
    return ctx


# ── 安全围栏校验 ───────────────────────────────────────────────
def _validate_args(args: list[str]) -> None:
    if not args:
        raise SecurityError("空命令")
    if len(args) > _MAX_TOKENS:
        raise SecurityError(f"参数个数超过上限 {_MAX_TOKENS}")
    banned = [tok for tok in args if tok.lower() in _BANNED_TOKENS]
    if banned:
        raise SecurityError(f"包含被禁止的动词/令牌: {banned}")
    if not any(tuple(args[: len(p)]) == p for p in _ALLOWED_PREFIXES):
        raise SecurityError(f"子命令不在只读白名单内: {' '.join(args[:2])}")
    for tok in args:
        if len(tok) > _MAX_TOKEN_LEN:
            raise SecurityError(f"参数过长: {tok[:40]!r}...")
        if (
            _FLAG_RE.match(tok)
            or _ROS_NAME_RE.match(tok)
            or _PARAM_NAME_RE.match(tok)
            or _INTERFACE_RE.match(tok)
            or _NUMBER_RE.match(tok)
        ):
            continue
        raise SecurityError(
            f"参数含非法字符或格式不符: {tok!r}（禁止 ; | & ` $ ( ) 空格等）"
        )


# ── 执行器 ────────────────────────────────────────────────────
@dataclass
class RunResult:
    args: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass
class StreamResult:
    args: list[str]
    text: str = ""
    message_count: int = 0
    timed_out: bool = False
    hit_message_limit: bool = False
    duration_s: float = 0.0
    returncode: int | None = None


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except OSError:
            pass


def _audit(cmd: str, duration_s: float, returncode: int | None, timed_out: bool, out_size: int) -> None:
    status = "TIMEOUT" if timed_out else ("OK" if returncode == 0 else f"RC={returncode}")
    _log.info("ros2 %s | %s | %.2fs | %dB out", cmd, status, duration_s, out_size)


def run_ros2(args: list[str], timeout: float = DEFAULT_TIMEOUT_S) -> RunResult:
    """执行白名单内的只读 ros2 子命令，返回完整输出。"""
    _validate_args(args)
    ctx = _ros_context()
    timeout = min(float(timeout), MAX_TIMEOUT_S)
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            [ctx["ros2_path"], *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
            env=ctx["env"],
        )
    except OSError as exc:
        raise RunnerError(f"无法启动 ros2 CLI: {exc}") from exc
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        returncode, timed_out = proc.returncode, False
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        stdout, stderr = proc.communicate()
        returncode, timed_out = proc.returncode, True
    result = RunResult(
        args=list(args),
        returncode=returncode,
        stdout=stdout or "",
        stderr=stderr or "",
        timed_out=timed_out,
        duration_s=round(time.monotonic() - started, 3),
    )
    _audit(" ".join(result.args), result.duration_s, result.returncode, result.timed_out, len(result.stdout))
    return result


def stream_ros2(
    args: list[str],
    duration_s: float,
    max_messages: int | None = None,
    separator: str = "---",
) -> StreamResult:
    """执行流式命令（echo/hz），限时采样：抓满 max_messages 条或到时即强杀返回。

    stderr 并入输出流以便诊断（如"无法确定话题类型"）。
    """
    _validate_args(args)
    ctx = _ros_context()
    duration_s = min(max(float(duration_s), 1.0), MAX_TIMEOUT_S)
    started = time.monotonic()
    deadline = started + duration_s
    proc = subprocess.Popen(
        [ctx["ros2_path"], *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=ctx["env"],
    )
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    chunks: list[bytes] = []
    received = 0
    timed_out = False
    hit_limit = False
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready, _, _ = select.select([fd], [], [], min(remaining, 0.5))
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            if max_messages is not None:
                text_now = b"".join(chunks).decode("utf-8", errors="replace")
                received = text_now.count(f"\n{separator}")
                if text_now.lstrip().startswith(separator):
                    received += 1
                if received >= max_messages:
                    hit_limit = True
                    break
    finally:
        _kill_group(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    text = b"".join(chunks).decode("utf-8", errors="replace")
    result = StreamResult(
        args=list(args),
        text=text,
        message_count=received,
        timed_out=timed_out,
        hit_message_limit=hit_limit,
        duration_s=round(time.monotonic() - started, 3),
        returncode=proc.returncode,
    )
    _audit(
        " ".join(result.args),
        result.duration_s,
        result.returncode,
        timed_out,
        len(result.text),
    )
    return result


# ── 错误分类与工具兜底 ──────────────────────────────────────────
def describe_failure(res: RunResult) -> str:
    parts = [f"ros2 {' '.join(res.args)} 执行失败"]
    if res.timed_out:
        parts.append(f"（超过 {res.duration_s:.1f}s 已强制终止）")
    tail = [line for line in (res.stderr or "").strip().splitlines() if line.strip()]
    if tail:
        parts.append("stderr 末行: " + tail[-1][:300])
    low = (res.stderr or "").lower()
    if "daemon" in low:
        parts.append("提示: ROS2 daemon 可能异常，可在终端执行 `ros2 daemon stop && ros2 daemon start` 后重试")
    elif "not found" in low or "unknown" in low or "no node" in low:
        parts.append("提示: 名称需以 / 开头、大小写敏感，且目标可能已退出")
    if res.timed_out and (res.stdout or "").strip():
        parts.append("已捕获的部分输出:\n" + res.stdout[:2000])
    return "\n".join(parts)


def guard(fn):
    """工具异常兜底：RunnerError/意外异常转为 {"error": ...} 内容，会话不中断；
    SecurityError 保持抛出（宿主显示 isError，安全拦截要响亮）。"""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SecurityError:
            raise
        except RunnerError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}
    return wrapper


_setup_audit_logger()
