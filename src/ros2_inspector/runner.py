"""统一执行器：所有 ros2 CLI 调用与环境探测命令的唯一出口。

职责：
- 目标分发：本地 / 本机容器 / ssh 远端 / ssh 远端容器，四种形态走同一条
  snippet 构造路径（参数先过四层围栏，再由可信代码 shlex.quote 拼装，无注入面）；
- ROS 环境解析：按目标探测 /opt/ros 与 PATH 上的 ros2（结果按目标缓存）；
  Server 本体不 import 任何 ROS 库，未安装 ROS 时相关工具返回友好结论而非崩溃；
- 四层安全围栏：动词白名单 / 黑名单令牌 / 参数正则校验 / 审计日志（含目标名）；
- 超时控制：本地 Popen 超时+进程组强杀；容器/远端命令内嵌 `timeout -k` 自了断，
  杜绝孤儿进程；ssh 路径另有建连预算，到点即返回已捕获输出。

工具函数不允许自行 subprocess/paramiko，必须经由本模块。
"""

from __future__ import annotations

import functools
import logging
import os
import re
import select
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import remote
from .targets import TargetConfig, resolve as resolve_target

DEFAULT_TIMEOUT_S = 10.0
MAX_TIMEOUT_S = 30.0
_CONNECT_SLACK_S = 8.0  # 远端/容器路径的建连与命令启动预算
_KILL_AFTER_SLACK_S = 2.0  # 内嵌 timeout 相对窗口的宽限
_GAP_THRESHOLD_S = 2.0  # 流式采样中超过该时长的静默记为一次"间隙"

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
    """ros2 CLI 无法执行（如目标未检测到 ROS 环境）；工具层转为友好内容。"""


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


# ── ROS 环境解析（按目标探测并缓存） ──────────────────────────────
@dataclass
class RosEnv:
    """目标机器上解析出的 ROS 环境。setup_file 为 None 表示仅 PATH 上有 ros2。"""

    setup_file: str | None
    distro: str | None
    ros2_path: str | None


_PROBE_SNIPPET = (
    'echo "DISTROS $(ls /opt/ros 2>/dev/null | tr \'\\n\' \' \')"; '
    'echo "ROS2 $(command -v ros2 2>/dev/null)"'
)

_ros_env_cache: dict[str, RosEnv | None] = {}


def _quote_argv(argv: list[str]) -> str:
    return " ".join(shlex.quote(tok) for tok in argv)


shlex_quote = shlex.quote


def build_ros2_snippet(
    setup_file: str | None,
    env: dict[str, str],
    args: list[str],
    *,
    kill_after: float | None = None,
    merge_stderr: bool = False,
) -> str:
    """构造远端/容器 bash -c 用的 snippet：source setup → export env → exec ros2。

    kill_after 不为 None 时以 `timeout -k 1 <T>` 包裹 ros2（容器/远端场景的
    防孤儿自杀机制）。token 已过围栏，此处 quote 是纵深防御。
    """
    parts: list[str] = []
    if setup_file:
        parts.append(f"source {shlex_quote(setup_file)}")
    for key, value in env.items():
        parts.append(f"export {key}={shlex_quote(value)}")
    argv = ["ros2", *args]
    if kill_after is not None:
        argv = ["timeout", "-k", "1", f"{kill_after:.1f}", *argv]
    command = _quote_argv(argv)
    if merge_stderr:
        command += " 2>&1"
    parts.append(f"exec {command}")
    return " && ".join(parts)


def _probe_ros_env(cfg: TargetConfig) -> RosEnv | None:
    """在目标上探测 ROS：/opt/ros 发行版目录 + PATH 上的 ros2。"""
    returncode, out, _ = run_probe(cfg, _PROBE_SNIPPET, timeout=15.0)
    if returncode not in (0, None):
        return None
    distros: list[str] = []
    ros2_path: str | None = None
    for line in out.splitlines():
        label, _, value = line.partition(" ")
        if label == "DISTROS":
            distros = value.split()
        elif label == "ROS2":
            ros2_path = value.strip() or None
    if cfg.distro:
        return RosEnv(f"/opt/ros/{cfg.distro}/setup.bash", cfg.distro, ros2_path)
    if distros:
        distro = sorted(distros)[0]
        return RosEnv(f"/opt/ros/{distro}/setup.bash", distro, ros2_path)
    if ros2_path:
        return RosEnv(None, None, ros2_path)
    return None


def resolve_ros_env(cfg: TargetConfig, force: bool = False) -> RosEnv | None:
    """目标 ROS 环境解析（带缓存；check_target 用 force=True 重探）。"""
    key = f"{cfg.name}@{cfg.container or ''}"
    if not force and key in _ros_env_cache:
        return _ros_env_cache[key]
    if cfg.setup_file:
        env = RosEnv(cfg.setup_file, cfg.distro, None)
    else:
        env = _probe_ros_env(cfg)
    _ros_env_cache[key] = env
    return env


def forget_target_cache(name: str) -> None:
    """目标被删除/重写后清空其 ROS 环境缓存。"""
    for key in [k for k in _ros_env_cache if k.split("@", 1)[0] == name]:
        _ros_env_cache.pop(key, None)


# ── 执行器 ────────────────────────────────────────────────────
@dataclass
class RunResult:
    args: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_s: float = 0.0
    target: str = "local"

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
    target: str = "local"
    gap_count: int = 0
    max_gap_s: float = 0.0


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except OSError:
            pass


def _audit(cmd: str, target: str, duration_s: float, returncode: int | None,
           timed_out: bool, out_size: int) -> None:
    status = "TIMEOUT" if timed_out else ("OK" if returncode == 0 else f"RC={returncode}")
    _log.info("%s | %s | %s | %.2fs | %dB out", target, cmd, status, duration_s, out_size)


def _exec_local(
    argv: list[str], timeout: float, merge_stderr: bool
) -> tuple[int | None, str, str, bool]:
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=(subprocess.STDOUT if merge_stderr else subprocess.PIPE),
            text=True,
            errors="replace",
            start_new_session=True,
            env={**os.environ},
        )
    except OSError as exc:
        raise RunnerError(f"无法启动本地命令: {exc}") from exc
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        returncode, timed_out = proc.returncode, False
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        stdout, stderr = proc.communicate()
        returncode, timed_out = proc.returncode, True
    return returncode, stdout or "", stderr or "", timed_out


def _wrap_container_local(snippet: str, cfg: TargetConfig, kill_after: float | None) -> list[str]:
    """本机容器：docker exec + 内嵌 timeout 防孤儿（容器内进程杀不到）。"""
    if kill_after is not None:
        snippet = f"timeout -k 1 {kill_after:.1f} /bin/bash -c {shlex_quote(snippet)}"
    return ["docker", "exec", "-i", cfg.container, "/bin/bash", "-c", snippet]


def run_ros2(
    args: list[str], timeout: float = DEFAULT_TIMEOUT_S, target: str = "local"
) -> RunResult:
    """执行白名单内的只读 ros2 子命令，返回完整输出。"""
    _validate_args(args)
    cfg = resolve_target(target)
    timeout = min(float(timeout), MAX_TIMEOUT_S)
    renv = resolve_ros_env(cfg)
    if renv is None:
        raise RunnerError(
            f"目标 {target!r} 未检测到 ROS2 环境（已探测 /opt/ros 与 PATH）。"
            "可调用 check_target 查看目标详情，或 ros_install_info 查看安装情况。"
        )
    started = time.monotonic()
    if cfg.is_local:
        if cfg.container:
            snippet = build_ros2_snippet(
                renv.setup_file, cfg.env, args, kill_after=timeout + _KILL_AFTER_SLACK_S
            )
            argv = _wrap_container_local(snippet, cfg, kill_after=None)  # timeout 已在 snippet 内
        else:
            argv = ["/bin/bash", "-c", build_ros2_snippet(renv.setup_file, cfg.env, args)]
        returncode, stdout, stderr, timed_out = _exec_local(argv, timeout, merge_stderr=False)
    else:
        snippet = build_ros2_snippet(
            renv.setup_file, cfg.env, args, kill_after=timeout + _KILL_AFTER_SLACK_S
        )
        command = f"timeout -k 1 {timeout + _KILL_AFTER_SLACK_S:.1f} /bin/bash -c {shlex_quote(snippet)}"
        if cfg.container:
            command = f"docker exec -i {shlex_quote(cfg.container)} {command}"
        returncode, stdout, stderr, timed_out = remote.exec_command(
            cfg, command, timeout + _CONNECT_SLACK_S
        )
        if returncode in (124, 137):
            timed_out = True
    result = RunResult(
        args=list(args),
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_s=round(time.monotonic() - started, 3),
        target=target,
    )
    _audit("ros2 " + " ".join(result.args), target, result.duration_s,
           result.returncode, result.timed_out, len(result.stdout))
    return result


def stream_ros2(
    args: list[str],
    duration_s: float,
    max_messages: int | None = None,
    separator: str = "---",
    target: str = "local",
) -> StreamResult:
    """执行流式命令（echo/hz），限时采样：抓满 max_messages 条或到时即停。

    stderr 并入输出流以便诊断。静默超过 _GAP_THRESHOLD_S 记为间隙，
    供语义层判断断流。本地走 select 循环；容器/远端内嵌 timeout 自了断。
    """
    _validate_args(args)
    cfg = resolve_target(target)
    duration_s = min(max(float(duration_s), 1.0), MAX_TIMEOUT_S)
    renv = resolve_ros_env(cfg)
    if renv is None:
        raise RunnerError(
            f"目标 {target!r} 未检测到 ROS2 环境（已探测 /opt/ros 与 PATH）。"
            "可调用 check_target 查看目标详情，或 ros_install_info 查看安装情况。"
        )
    started = time.monotonic()
    if cfg.is_local and not cfg.container:
        snippet = build_ros2_snippet(renv.setup_file, cfg.env, args, merge_stderr=True)
        result = _stream_local(
            ["/bin/bash", "-c", snippet], args, duration_s, max_messages,
            separator, target, started, deadline_slack=0.0,
        )
    elif cfg.is_local:
        snippet = build_ros2_snippet(
            renv.setup_file, cfg.env, args,
            kill_after=duration_s + _KILL_AFTER_SLACK_S, merge_stderr=True,
        )
        argv = _wrap_container_local(snippet, cfg, kill_after=None)  # timeout 已在 snippet 内
        result = _stream_local(
            argv, args, duration_s, max_messages, separator, target,
            started, deadline_slack=_KILL_AFTER_SLACK_S,
        )
    else:
        snippet = build_ros2_snippet(
            renv.setup_file, cfg.env, args,
            kill_after=duration_s + _KILL_AFTER_SLACK_S, merge_stderr=True,
        )
        command = f"timeout -k 1 {duration_s + _KILL_AFTER_SLACK_S:.1f} /bin/bash -c {shlex_quote(snippet)}"
        if cfg.container:
            command = f"docker exec -i {shlex_quote(cfg.container)} {command}"
        text, timed_out, hit_limit, received, gap_count, max_gap = remote.stream_command(
            cfg, command, duration_s + _CONNECT_SLACK_S, max_messages, separator
        )
        result = StreamResult(
            args=list(args),
            text=text,
            message_count=received,
            timed_out=timed_out,
            hit_message_limit=hit_limit,
            duration_s=round(time.monotonic() - started, 3),
            target=target,
            gap_count=gap_count,
            max_gap_s=round(max_gap, 2),
        )
    _audit("ros2 " + " ".join(result.args) + " [stream]", target, result.duration_s,
           result.returncode, result.timed_out, len(result.text))
    return result


def _stream_local(
    argv: list[str],
    args: list[str],
    duration_s: float,
    max_messages: int | None,
    separator: str,
    target: str,
    started: float,
    deadline_slack: float,
) -> StreamResult:
    deadline = started + duration_s + deadline_slack
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=False,
        env={**os.environ},
    )
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    chunks: list[bytes] = []
    received = 0
    timed_out = False
    hit_limit = False
    gap_count = 0
    max_gap_s = 0.0
    last_data: float | None = None  # 首块数据前的启动静默不算间隙
    try:
        while True:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                timed_out = True
                break
            ready, _, _ = select.select([fd], [], [], min(remaining, 0.5))
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if last_data is not None:
                idle = now - last_data
                if idle > _GAP_THRESHOLD_S:
                    gap_count += 1
                    max_gap_s = max(max_gap_s, idle)
            last_data = time.monotonic()
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
    return StreamResult(
        args=list(args),
        text=text,
        message_count=received,
        timed_out=timed_out,
        hit_message_limit=hit_limit,
        duration_s=round(time.monotonic() - started, 3),
        returncode=proc.returncode,
        target=target,
        gap_count=gap_count,
        max_gap_s=round(max_gap_s, 2),
    )


def run_ros2_daemon_fallback(
    args: list[str],
    timeout: float = DEFAULT_TIMEOUT_S,
    target: str = "local",
    fallback_on_empty: bool = False,
) -> tuple[RunResult, bool, bool]:
    """run_ros2 + daemon 失效兜底：失败（或可选地为空结果）时以 --no-daemon 直连重试。

    容器/长命 daemon 常见病：daemon 缓存陈旧导致 node list 为空、endpoint
    查询 xmlrpc 报错、param 服务调用挂起——直连 DDS 发现往往仍然可用。
    返回 (结果, 是否采用了兜底结果, 是否尝试过兜底)。
    """
    res = run_ros2(args, timeout=timeout, target=target)
    daemon_empty = fallback_on_empty and res.ok and not res.stdout.strip()
    if res.ok and not daemon_empty:
        return res, False, False
    retry = run_ros2([*args, "--no-daemon"], timeout=timeout, target=target)
    if retry.ok and (retry.stdout.strip() or not fallback_on_empty):
        return retry, True, True
    return res, False, True


def run_probe(cfg: TargetConfig, snippet: str, timeout: float = 15.0) -> tuple[int | None, str, str]:
    """在目标上执行**代码内固定**的探测 snippet（体检/身份卡用，不经过 ros2 围栏）。

    snippet 必须是本模块/工具模块里的字面量，禁止拼接用户输入。
    """
    if cfg.is_local:
        argv = (
            ["docker", "exec", "-i", cfg.container, "/bin/bash", "-c", snippet]
            if cfg.container
            else ["/bin/bash", "-c", snippet]
        )
        try:
            returncode, stdout, stderr, _ = _exec_local(argv, timeout, merge_stderr=False)
        except RunnerError as exc:
            return -1, "", str(exc)
        return returncode, stdout, stderr
    command = f"/bin/bash -c {shlex_quote(snippet)}"
    if cfg.container:
        command = f"docker exec -i {shlex_quote(cfg.container)} {command}"
    try:
        returncode, stdout, stderr, _ = remote.exec_command(cfg, command, timeout + _CONNECT_SLACK_S)
    except remote.SSHError as exc:
        return -1, "", str(exc)
    return returncode, stdout, stderr


# ── 错误分类与工具兜底 ──────────────────────────────────────────
def describe_failure(res: RunResult) -> str:
    where = f"（目标: {res.target}）" if res.target != "local" else ""
    parts = [f"ros2 {' '.join(res.args)} 执行失败{where}"]
    if res.timed_out:
        parts.append(f"（超过 {res.duration_s:.1f}s 已强制终止）")
    tail = [line for line in (res.stderr or "").strip().splitlines() if line.strip()]
    if tail:
        parts.append("stderr 末行: " + tail[-1][:300])
    low = (res.stderr or "").lower()
    if "daemon" in low:
        parts.append("提示: ROS2 daemon 可能异常，可在目标终端执行 `ros2 daemon stop && ros2 daemon start` 后重试")
    elif "not found" in low or "unknown topic" in low or "unknown node" in low or "no node" in low:
        parts.append("提示: 名称需以 / 开头、大小写敏感，且目标可能已退出")
    if res.timed_out:
        parts.append("提示: 服务调用在限时内无响应——目标机器 DDS/服务可达性问题（在目标终端直跑同样命令可对照确认），稍后重试或重启目标 ROS daemon")
    if res.timed_out and (res.stdout or "").strip():
        parts.append("已捕获的部分输出:\n" + res.stdout[:2000])
    return "\n".join(parts)


def guard(fn):
    """工具异常兜底：RunnerError/ConfigError/意外异常转为 {"error": ...} 内容，
    会话不中断；SecurityError 保持抛出（宿主显示 isError，安全拦截要响亮）。"""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SecurityError:
            raise
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}
    return wrapper


_setup_audit_logger()
