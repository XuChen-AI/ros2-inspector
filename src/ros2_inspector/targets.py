"""目标配置模型：远端/容器巡检目标的登记、校验、读写与热加载。

配置文件是目标信息的唯一来源（默认 ~/.config/ros2-inspector/targets.json）：
- 程序侧只允许经 write_target/remove_target 落盘，序列化格式在此定死；
- 人工手动编辑永远允许——resolve 前比对 mtime，变更即重读+重新校验；
- 校验失败响亮报错（指明目标与字段），绝不让半成品配置悄悄生效。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

LOCAL_TARGET_NAME = "local"

# ── 字段格式白名单（校验层：读取与写入共用同一套规则） ──────────────
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SETUP_RE = re.compile(r"^/[\w./-]{1,200}$")
_DISTRO_RE = re.compile(r"^[a-z0-9]{1,32}$")
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_ENV_VAL_RE = re.compile(r"^[\w./:+-]{0,120}$")

_DEFAULT_PATH = Path.home() / ".config" / "ros2-inspector" / "targets.json"

_config_path: Path = _DEFAULT_PATH
# 热加载缓存：path → (mtime_ns, size, targets)；mtime 变了才重读
_cache: dict[str, tuple[int, int, dict[str, "TargetConfig"]]] = {}


class ConfigError(RuntimeError):
    """目标配置非法（工具层转为 error 内容，指明目标与字段）。"""


@dataclass
class TargetConfig:
    """一个巡检目标的完整描述。host 为 None 表示本机（隐式目标，不入文件）。"""

    name: str
    description: str
    host: str | None = None
    port: int = 22
    username: str | None = None
    auth_method: str = "key"  # "password" | "key"
    password: str | None = None
    key_path: str | None = None
    passphrase: str | None = None
    container: str | None = None
    setup_file: str | None = None
    distro: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    @property
    def is_local(self) -> bool:
        return self.host is None

    def card(self) -> dict:
        """对外展示卡：密码/口令不展开，其余字段如实呈现。"""
        auth: dict = {"method": self.auth_method}
        if self.auth_method == "password":
            auth["password"] = self.password
        else:
            auth["key_path"] = self.key_path
            if self.passphrase:
                auth["passphrase"] = self.passphrase
        out: dict = {
            "name": self.name,
            "description": self.description,
            "transport": "local" if self.is_local else "ssh",
        }
        if not self.is_local:
            out.update(
                host=self.host,
                port=self.port,
                username=self.username,
                auth=auth,
            )
        for key in ("container", "setup_file", "distro"):
            value = getattr(self, key)
            if value:
                out[key] = value
        if self.env:
            out["env"] = dict(self.env)
        return out


def local_target() -> TargetConfig:
    return TargetConfig(name=LOCAL_TARGET_NAME, description="运行 MCP server 的本机")


# ── 配置文件路径 ────────────────────────────────────────────────
def set_config_path(path: str | Path) -> None:
    global _config_path
    _config_path = Path(path).expanduser()


def get_config_path() -> Path:
    return _config_path


# ── 逐字段校验（管理工具 add_target 与文件加载共用） ──────────────
def build_target(
    *,
    name: str,
    description: str,
    host: str,
    username: str,
    auth_method: str = "key",
    password: str | None = None,
    key_path: str | None = None,
    passphrase: str | None = None,
    port: int | str = 22,
    container: str | None = None,
    setup_file: str | None = None,
    distro: str | None = None,
    env: dict[str, str] | None = None,
) -> TargetConfig:
    """校验全部字段并构造 TargetConfig；任何字段不合法抛 ConfigError。"""
    errors: list[str] = []

    if name == LOCAL_TARGET_NAME:
        errors.append(f"目标名不能使用保留名 {LOCAL_TARGET_NAME!r}")
    elif not isinstance(name, str) or not _NAME_RE.match(name):
        errors.append("name 需以小写字母开头，仅含小写字母/数字/-/_，≤32 字符")

    if not isinstance(description, str) or not description.strip():
        errors.append("description 必填：一句人话描述（给连接前确认用）")
    elif len(description) > 100:
        errors.append("description 过长（≤100 字符）")

    if not isinstance(host, str) or not _HOST_RE.match(host):
        errors.append("host 需为合法主机名或 IP（不含空格/协议前缀）")

    if not isinstance(username, str) or not _USER_RE.match(username):
        errors.append("username 需为合法 Linux 用户名（字母/数字/_/.-，≤64 字符）")

    try:
        port_i = int(port)
    except (TypeError, ValueError):
        port_i = -1
    if not 1 <= port_i <= 65535:
        errors.append("port 需在 1–65535 之间")

    if auth_method not in ("password", "key"):
        errors.append("auth_method 只能是 password 或 key")
    elif auth_method == "password":
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            errors.append("password 认证需提供 1–128 字符的 password")
    else:
        if key_path is not None:
            if isinstance(key_path, str) and key_path.startswith("~"):
                key_path = str(Path(key_path).expanduser())  # 容错 "~/.ssh/id_rsa" 写法
            if not isinstance(key_path, str) or not _SETUP_RE.match(key_path):
                errors.append("key_path 需为本机私钥绝对路径（受限字符集）")
            elif not Path(key_path).is_file():
                errors.append(f"key_path 文件不存在: {key_path}")

    if container is not None and (not isinstance(container, str) or not _CONTAINER_RE.match(container)):
        errors.append("container 需为合法容器名/ID（字母数字开头，_ . - 组合）")

    if setup_file is not None and (not isinstance(setup_file, str) or not _SETUP_RE.match(setup_file)):
        errors.append("setup_file 需为目标机器上 setup.bash 的绝对路径（受限字符集）")

    if distro is not None and (not isinstance(distro, str) or not _DISTRO_RE.match(distro)):
        errors.append("distro 仅允许小写字母/数字（如 humble、jazzy）")

    env_norm: dict[str, str] = {}
    if env:
        if not isinstance(env, dict):
            errors.append("env 需为 {\"变量名\": \"值\"} 形式的对象")
        else:
            for key, value in env.items():
                if not isinstance(key, str) or not _ENV_KEY_RE.match(key):
                    errors.append(f"env 变量名不合法: {key!r}（大写字母/数字/下划线）")
                elif not isinstance(value, str) or not _ENV_VAL_RE.match(value):
                    errors.append(f"env 变量值不合法: {key}={value!r}（禁止空格与特殊字符）")
                else:
                    env_norm[key] = value

    if errors:
        raise ConfigError(f"目标 {name!r} 配置不合法：\n- " + "\n- ".join(errors))

    return TargetConfig(
        name=name,
        description=description.strip(),
        host=host,
        port=port_i,
        username=username,
        auth_method=auth_method,
        password=password if auth_method == "password" else None,
        key_path=key_path if auth_method == "key" else None,
        passphrase=passphrase if auth_method == "key" else None,
        container=container,
        setup_file=setup_file,
        distro=distro,
        env=env_norm,
    )


def _from_file_entry(name: str, raw: object) -> TargetConfig:
    """文件条目 → TargetConfig。未知字段一律拒绝（防止随手塞字段）。"""
    if not isinstance(raw, dict):
        raise ConfigError(f"目标 {name!r} 的配置必须是对象")
    allowed = {
        "description", "host", "port", "username", "auth",
        "container", "setup_file", "distro", "env",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(f"目标 {name!r} 含未知字段: {sorted(unknown)}，合法字段: {sorted(allowed)}")
    auth = raw.get("auth") or {}
    if not isinstance(auth, dict):
        raise ConfigError(f"目标 {name!r} 的 auth 必须是对象（method/password/key_path/passphrase）")
    try:
        return build_target(
            name=name,
            description=raw.get("description"),
            host=raw.get("host"),
            username=raw.get("username"),
            auth_method=auth.get("method", "key"),
            password=auth.get("password"),
            key_path=auth.get("key_path"),
            passphrase=auth.get("passphrase"),
            port=raw.get("port", 22),
            container=raw.get("container"),
            setup_file=raw.get("setup_file"),
            distro=raw.get("distro"),
            env=raw.get("env"),
        )
    except ConfigError:
        raise
    except Exception as exc:  # noqa: BLE001 — 类型烂掉的字段给出可读错误
        raise ConfigError(f"目标 {name!r} 配置不合法: {exc}") from exc


# ── 序列化与落盘（唯一写入口，格式定死） ─────────────────────────
def _serialize(cfg: TargetConfig) -> dict:
    entry: dict = {
        "description": cfg.description,
        "host": cfg.host,
        "port": cfg.port,
        "username": cfg.username,
        "auth": (
            {"method": "password", "password": cfg.password}
            if cfg.auth_method == "password"
            else {"method": "key", "key_path": cfg.key_path, "passphrase": cfg.passphrase}
        ),
        "container": cfg.container,
        "setup_file": cfg.setup_file,
        "distro": cfg.distro,
        "env": cfg.env or None,
    }
    return entry


def _read_raw(path: Path) -> dict:
    """读原始 JSON：容忍缺文件；缺 targets 包裹层时按名字→条目直读。"""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"配置文件无法解析 {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件顶层必须是对象: {path}")
    entries = raw.get("targets")
    if entries is None:
        entries = {k: v for k, v in raw.items() if isinstance(v, dict)}
    if not isinstance(entries, dict):
        raise ConfigError("配置文件的 targets 必须是 {名字: 配置} 形式")
    return entries


def load_all(path: Path | None = None) -> dict[str, TargetConfig]:
    """加载全部目标（带 mtime 热加载缓存）。文件坏/字段非法时响亮报错。"""
    path = Path(path) if path else _config_path
    try:
        st = path.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        _cache.pop(str(path), None)
        return {}
    key = str(path)
    if key in _cache and _cache[key][:2] == stamp:
        return _cache[key][2]
    entries = _read_raw(path)
    targets_map = {name: _from_file_entry(name, raw) for name, raw in entries.items()}
    _cache[key] = (stamp[0], stamp[1], targets_map)
    return targets_map


def resolve(name: str) -> TargetConfig:
    """名字 → 目标配置。local 返回本机隐式目标；未知名字报错并列出可选值。"""
    if name == LOCAL_TARGET_NAME:
        return local_target()
    all_targets = load_all()
    cfg = all_targets.get(name)
    if cfg is None:
        known = ", ".join(sorted(all_targets)) or "（尚未登记任何目标）"
        raise ConfigError(
            f"未知目标 {name!r}。可选：{LOCAL_TARGET_NAME}（本机）、{known}。"
            "可先调用 list_targets 查看清单。"
        )
    return cfg


def write_target(cfg: TargetConfig, path: Path | None = None) -> None:
    """原子写入单个目标（读-改-写，临时文件+rename；目录自动创建）。"""
    path = Path(path) if path else _config_path
    entries = _read_raw(path)
    entries[cfg.name] = _serialize(cfg)
    _atomic_write(path, entries)
    _cache.pop(str(path), None)


def remove_target(name: str, path: Path | None = None) -> None:
    """原子删除单个目标；不存在时抛 ConfigError。"""
    path = Path(path) if path else _config_path
    entries = _read_raw(path)
    if name not in entries:
        raise ConfigError(f"目标 {name!r} 不存在，无需删除")
    del entries[name]
    _atomic_write(path, entries)
    _cache.pop(str(path), None)


def _atomic_write(path: Path, entries: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"targets": entries}, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".targets-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
