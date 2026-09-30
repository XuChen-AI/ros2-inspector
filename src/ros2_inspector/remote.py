"""paramiko SSH 传输：远端命令执行与流式采样。

- 连接按目标名缓存复用（工具可能并发调用，paramiko 传输层线程安全）；
- 断线自动重连一次；connect 超时 10s，杜绝挂死；
- 读取采用 recv_ready/recv_stderr_ready 轮询 + deadline，到点即返回已捕获
  输出（远端进程由外层 timeout 包裹自杀，见 runner）；
- 本模块只搬运字节，不构造命令——命令一律由 runner 的 snippet 构造器产出。
"""

from __future__ import annotations

import threading
import time

import paramiko

from .targets import TargetConfig

_CONNECT_TIMEOUT_S = 10.0
_POLL_INTERVAL_S = 0.02
_MAX_CAPTURE_BYTES = 4 * 1024 * 1024  # 防御性输出上限，超出即截断

_clients: dict[str, paramiko.SSHClient] = {}
_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


class SSHError(RuntimeError):
    """SSH 连接/执行失败（工具层转为友好 error 内容）。"""


def _lock_for(name: str) -> threading.Lock:
    with _registry_lock:
        return _locks.setdefault(name, threading.Lock())


def _new_client(cfg: TargetConfig) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    # 无头板子通常没走过人工指纹确认，采用 TOFU 策略：首连自动记录指纹。
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict = {
        "hostname": cfg.host,
        "port": cfg.port,
        "username": cfg.username,
        "timeout": _CONNECT_TIMEOUT_S,
        "banner_timeout": _CONNECT_TIMEOUT_S,
        "auth_timeout": _CONNECT_TIMEOUT_S,
        "look_for_keys": False,
        "allow_agent": False,
    }
    if cfg.auth_method == "password":
        kwargs["password"] = cfg.password
    elif cfg.key_path:
        kwargs["key_filename"] = cfg.key_path
        kwargs["passphrase"] = cfg.passphrase
    else:  # key 认证未指定私钥文件：走 agent 与默认密钥位置
        kwargs["allow_agent"] = True
        kwargs["look_for_keys"] = True
    try:
        client.connect(**kwargs)
    except Exception as exc:  # noqa: BLE001 — paramiko 异常族系庞杂，统一转译
        raise SSHError(f"ssh 连接失败 {cfg.username}@{cfg.host}:{cfg.port} → {exc}") from exc
    return client


def get_client(cfg: TargetConfig) -> paramiko.SSHClient:
    """取目标连接：缓存活跃连接，失效则重建一次。"""
    with _lock_for(cfg.name):
        client = _clients.get(cfg.name)
        if client is not None:
            transport = client.get_transport()
            if transport is not None and transport.is_active():
                return client
            try:
                client.close()
            except OSError:
                pass
        client = _new_client(cfg)
        _clients[cfg.name] = client
        return client


def drop_client(name: str) -> None:
    """显式断开（试连失败/目标删除后调用，避免半死连接残留）。"""
    with _lock_for(name):
        client = _clients.pop(name, None)
    if client is not None:
        try:
            client.close()
        except OSError:
            pass


def host_fingerprint(cfg: TargetConfig) -> str | None:
    """远端主机公钥指纹（SHA256），供 check_target 身份卡展示。"""
    try:
        key = get_client(cfg).get_transport().get_remote_server_key()
        return "SHA256:" + key.get_fingerprint().hex()
    except Exception:  # noqa: BLE001 — 指纹拿不到不影响主流程
        return None


def exec_command(
    cfg: TargetConfig,
    command: str,
    timeout: float,
) -> tuple[int | None, str, str, bool]:
    """远端执行命令，返回 (returncode, stdout, stderr, timed_out)。

    到 deadline 即停止读取并关闭通道；远端进程由 timeout 包裹自行了断。
    """
    started = time.monotonic()
    try:
        client = get_client(cfg)
        transport = client.get_transport()
        chan = transport.open_session(timeout=_CONNECT_TIMEOUT_S)
        chan.exec_command(command)
    except (paramiko.SSHException, OSError) as exc:
        # 连接可能中途坏死：重连一次再试，仍失败才报错
        drop_client(cfg.name)
        try:
            transport = get_client(cfg).get_transport()
            chan = transport.open_session(timeout=_CONNECT_TIMEOUT_S)
            chan.exec_command(command)
        except (paramiko.SSHException, OSError) as exc2:
            raise SSHError(f"ssh 执行失败: {exc2}") from exc2

    out = bytearray()
    err = bytearray()
    truncated = False
    deadline = started + timeout
    timed_out = False
    while True:
        progressed = False
        if chan.recv_ready():
            out += chan.recv(65536)
            progressed = True
        if chan.recv_stderr_ready():
            err += chan.recv_stderr(65536)
            progressed = True
        if len(out) + len(err) > _MAX_CAPTURE_BYTES:
            truncated = True
            break
        if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
            break
        if time.monotonic() > deadline:
            timed_out = True
            break
        if not progressed:
            time.sleep(_POLL_INTERVAL_S)

    returncode: int | None = None
    if not timed_out:
        try:
            returncode = chan.recv_exit_status()
        except paramiko.SSHException:
            returncode = None
    try:
        chan.close()
    except paramiko.SSHException:
        pass
    text_out = out.decode("utf-8", errors="replace")
    text_err = err.decode("utf-8", errors="replace")
    if truncated:
        text_err += f"\n[ros2-inspector] 输出超过 {_MAX_CAPTURE_BYTES // 1024 // 1024}MB 上限，已截断"
    return returncode, text_out, text_err, timed_out


def stream_command(
    cfg: TargetConfig,
    command: str,
    duration_s: float,
    max_messages: int | None = None,
    separator: str = "---",
) -> tuple[str, bool, bool, int, int, float]:
    """远端流式执行（stderr 已并入 stdout）。

    返回 (text, timed_out, hit_limit, message_count, gap_count, max_gap_s)。
    抓满 max_messages 条或到 duration_s 即停；gap 为超过 2s 无输出的间隙，
    供语义层判断断流。
    """
    started = time.monotonic()
    try:
        transport = get_client(cfg).get_transport()
        chan = transport.open_session(timeout=_CONNECT_TIMEOUT_S)
        chan.exec_command(command)
    except (paramiko.SSHException, OSError) as exc:
        drop_client(cfg.name)
        try:
            transport = get_client(cfg).get_transport()
            chan = transport.open_session(timeout=_CONNECT_TIMEOUT_S)
            chan.exec_command(command)
        except (paramiko.SSHException, OSError) as exc2:
            raise SSHError(f"ssh 流式执行失败: {exc2}") from exc2

    chunks: list[bytes] = []
    total = 0
    hit_limit = False
    timed_out = False
    gap_count = 0
    max_gap_s = 0.0
    last_data: float | None = None  # 首块数据前的启动静默不算间隙
    deadline = started + duration_s
    while True:
        progressed = False
        if chan.recv_ready():
            now = time.monotonic()
            if last_data is not None:
                idle = now - last_data
                if idle > 2.0:
                    gap_count += 1
                    max_gap_s = max(max_gap_s, idle)
            last_data = now
            chunk = chan.recv(65536)
            chunks.append(chunk)
            total += len(chunk)
            progressed = True
            if max_messages is not None:
                text_now = b"".join(chunks).decode("utf-8", errors="replace")
                received = text_now.count(f"\n{separator}")
                if text_now.lstrip().startswith(separator):
                    received += 1
                if received >= max_messages:
                    hit_limit = True
                    break
        if total > _MAX_CAPTURE_BYTES:
            break
        if chan.exit_status_ready() and not chan.recv_ready():
            break
        if time.monotonic() > deadline:
            timed_out = True
            break
        if not progressed:
            time.sleep(_POLL_INTERVAL_S)
    try:
        chan.close()
    except paramiko.SSHException:
        pass
    text = b"".join(chunks).decode("utf-8", errors="replace")
    message_count = text.count(f"\n{separator}") + (
        1 if text.lstrip().startswith(separator) else 0
    )
    return text, timed_out, hit_limit, message_count, gap_count, max_gap_s
