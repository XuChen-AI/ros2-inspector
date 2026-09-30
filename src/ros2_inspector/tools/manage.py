"""目标管理工具：语义化增删查巡检目标，用户可全程不碰配置文件。

防误配的四道围栏（全部代码级，不靠约定）：
1. 填表式参数——工具签名即 schema，AI 没有自由文本写配置的入口；
2. 逐字段硬校验（targets.build_target，格式不合法直接拒绝并指明字段）；
3. 增删两步预览确认——confirm=False 只出预览，confirm=True 才落盘；
4. 落盘由 targets 统一序列化，格式定死，未知字段一律拒绝。

约定流程（写进 server instructions）：首次使用某个远端目标前，先 check_target
把身份卡亮给用户确认，再开始查询。
"""

from __future__ import annotations

from .. import remote
from .. import runner
from .. import targets
from ..targets import ConfigError, TargetConfig

_IDENTITY_SNIPPET = (
    'echo "HOST $(hostname 2>/dev/null)"; '
    'echo "KERNEL $(uname -sr 2>/dev/null)"; '
    '(. /etc/os-release 2>/dev/null && echo "OS ${PRETTY_NAME:-unknown}") || echo "OS unknown"'
)


def register(mcp) -> None:
    @mcp.tool()
    @runner.guard
    def list_targets() -> dict:
        """列出全部已登记的巡检目标（含本机），**不发起任何连接**。

        何时用：开始巡检前先看有哪些可选目标、各自是干什么的。
        返回：targets 列表（name/description/transport/container 等）。
        每个 name 可作为其余工具的 target 参数值。
        """
        configured = targets.load_all()
        cards = [targets.local_target().card()]
        cards.extend(cfg.card() for cfg in configured.values())
        return {
            "target_count": len(cards),
            "targets": cards,
            "config_path": str(targets.get_config_path()),
            "note": "不填 target 参数即巡检本机(local)；新增/删除目标用 add_target/remove_target",
        }

    @mcp.tool()
    @runner.guard
    def check_target(target: str = "local") -> dict:
        """试连目标并返回身份卡：主机名、系统、ROS 发行版、容器、描述、主机指纹。

        何时用：**每次会话第一次使用某个（新的）远端目标前必须先调本工具**，
        并把返回的身份卡亮给用户确认后再继续查询；连接失败时返回具体原因。
        参数 target：目标名（list_targets 可查）。
        """
        cfg = _resolve_or_fail(target)
        identity: dict = {"name": cfg.name, "description": cfg.description}
        if cfg.is_local:
            identity["transport"] = "local"
            returncode, out, err = runner.run_probe(cfg, _IDENTITY_SNIPPET)
            if returncode != 0:
                return {"error": f"本机探测失败: {(err or out).strip()[:300]}"}
            identity.update(_parse_identity(out))
        else:
            identity["transport"] = "ssh"
            identity.update(
                host=cfg.host, port=cfg.port, username=cfg.username,
                container=cfg.container,
            )
            try:
                fingerprint = remote.host_fingerprint(cfg)
                returncode, out, err = runner.run_probe(cfg, _IDENTITY_SNIPPET)
            except remote.SSHError as exc:
                remote.drop_client(cfg.name)
                return {
                    "error": f"目标 {target!r} 连接失败: {exc}",
                    "hint": "检查地址/端口/用户名/认证方式；密钥认证可先用终端手动 ssh 一次排除问题",
                }
            if returncode != 0:
                remote.drop_client(cfg.name)
                return {"error": f"目标 {target!r} 已连通但探测失败: {(err or out).strip()[:300]}"}
            identity.update(_parse_identity(out))
            if fingerprint:
                identity["host_key_fingerprint"] = fingerprint
        env = runner.resolve_ros_env(cfg, force=True)
        identity["ros"] = (
            {"distro": env.distro, "setup_file": env.setup_file, "ros2_path": env.ros2_path}
            if env
            else None
        )
        if env is None:
            identity["note"] = "连接正常，但目标上未检测到 ROS2 环境——查看类工具将不可用"
        return identity

    @mcp.tool()
    @runner.guard
    def add_target(
        name: str,
        description: str,
        host: str,
        username: str,
        auth_method: str = "key",
        password: str | None = None,
        key_path: str | None = None,
        passphrase: str | None = None,
        port: int = 22,
        container: str | None = None,
        setup_file: str | None = None,
        distro: str | None = None,
        env: dict[str, str] | None = None,
        confirm: bool = False,
    ) -> dict:
        """登记一个新巡检目标（写入配置文件，热生效，无需重启）。

        何时用：用户想在对话里新增一台可巡检的机器/容器时。
        参数：name（小写字母开头的短名）、description（一句人话描述，必填）、
        host/username/port、auth_method（password 或 key，默认 key）、
        container（ROS 在目标机器的 docker 容器里时填容器名）、
        setup_file/distro（目标装了多个 ROS 发行版或非标准安装时的逃生门）、
        env（如 {"ROS_DOMAIN_ID": "42"}）、confirm（两步确认：先预览后写入）。
        """
        cfg = targets.build_target(
            name=name, description=description, host=host, username=username,
            auth_method=auth_method, password=password, key_path=key_path,
            passphrase=passphrase, port=port, container=container,
            setup_file=setup_file, distro=distro, env=env,
        )
        if name in targets.load_all():
            return {"error": f"目标 {name!r} 已存在。如需修改，先 remove_target 再重新添加"}
        if not confirm:
            return {
                "preview": cfg.card(),
                "note": "以上为将写入的完整配置（尚未写入）。请亮给用户确认；"
                        "确认无误后带 confirm=true 重新调用本工具完成登记。",
            }
        targets.write_target(cfg)
        return {
            "written": cfg.card(),
            "note": f"目标 {name!r} 已生效，立即可用 target={name!r} 巡检。"
                    "建议先 check_target 向用户确认连接，再开始查询。",
        }

    @mcp.tool()
    @runner.guard
    def remove_target(name: str, confirm: bool = False) -> dict:
        """删除一个已登记的巡检目标（两步确认：先预览后删除）。

        何时用：用户明确要求移除某台机器的登记时。
        参数 name：目标名；confirm：先 False 出预览，用户确认后 True 才真删。
        """
        if name == targets.LOCAL_TARGET_NAME:
            raise ConfigError("本机目标(local)是隐式目标，不可删除")
        existing = targets.load_all()
        cfg: TargetConfig | None = existing.get(name)
        if cfg is None:
            raise ConfigError(f"目标 {name!r} 不存在。可选：{', '.join(sorted(existing)) or '（无）'}")
        if not confirm:
            return {
                "preview": cfg.card(),
                "note": "以上目标将被删除（尚未删除）。请亮给用户确认；"
                        "确认后带 confirm=true 重新调用本工具完成删除。",
            }
        targets.remove_target(name)
        remote.drop_client(name)
        runner.forget_target_cache(name)
        return {"removed": name, "note": f"目标 {name!r} 已删除并断开连接（配置文件中已移除）"}


def _resolve_or_fail(target: str) -> TargetConfig:
    return targets.resolve(target)


def _parse_identity(out: str) -> dict:
    info: dict[str, str] = {}
    for line in out.splitlines():
        label, _, value = line.partition(" ")
        info[label] = value.strip()
    return {
        "hostname": info.get("HOST") or None,
        "kernel": info.get("KERNEL") or None,
        "os": info.get("OS") or None,
    }
