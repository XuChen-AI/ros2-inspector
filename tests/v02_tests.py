"""v0.2 单元测试：目标配置/执行层改造/工具注册——全部不发起真实连接。

用法: uv run python tests/v02_tests.py
覆盖：
- targets：字段校验（含未知字段拒绝）、原子读写往返、热加载、resolve；
- runner：snippet 构造（quote/timeout 包裹）、围栏不变、缓存清理；
- server：17 个工具注册（进程内 list_tools，不起 stdio）。
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

from ros2_inspector import runner, targets
from ros2_inspector.targets import ConfigError, build_target

PASS = 0


def ok(label: str) -> None:
    global PASS
    PASS += 1
    print(f"  [通过] {label}")


def expect_config_error(label: str, **kwargs) -> None:
    try:
        build_target(
            name=kwargs.pop("name", "t"),
            description=kwargs.pop("description", "测试目标"),
            host=kwargs.pop("host", "192.0.2.1"),
            username=kwargs.pop("username", "ubuntu"),
            **kwargs,
        )
    except ConfigError as exc:
        print(f"  [拒绝] {label}\n         ← {str(exc).splitlines()[0]}")
        return
    raise SystemExit(f"校验失效！未拦截: {label}")


def test_build_target() -> None:
    print("== build_target：合法与非法 ==")
    cfg = build_target(
        name="lab-board", description="实验室小车主机", host="192.168.1.50",
        username="ubuntu", auth_method="password", password="secret",
        env={"ROS_DOMAIN_ID": "42"},
    )
    assert cfg.port == 22 and cfg.env == {"ROS_DOMAIN_ID": "42"}
    assert cfg.auth_method == "password" and cfg.key_path is None
    ok("合法 password 目标")

    with tempfile.NamedTemporaryFile(suffix=".key") as key_fh:
        cfg = build_target(
            name="a-b_1", description="x", host="my-board.local", username="robot.user",
            auth_method="key", key_path=key_fh.name,
        )
        assert cfg.container is None and cfg.passphrase is None
        ok("合法 key 目标（临时密钥文件 + domain 后缀主机名）")

    expect_config_error("保留名 local", name="local")
    expect_config_error("大写/非法起始名", name="Board1")
    expect_config_error("空描述", description=None)
    expect_config_error("描述非字符串", description=123)
    expect_config_error("描述超长", description="长" * 101)
    expect_config_error("host 带空格", host="1.2.3.4 rm -rf")
    expect_config_error("host 带协议前缀", host="ssh://1.2.3.4")
    expect_config_error("port 越界", port=70000)
    expect_config_error("port 非数字", port="abc")
    expect_config_error("未知认证方式", auth_method="kerberos")
    expect_config_error("password 认证缺密码", auth_method="password", password=None)
    expect_config_error("key_path 不存在", auth_method="key", key_path="/no/such/key")
    expect_config_error("容器名带分号", container="ctr; rm")
    expect_config_error("setup_file 相对路径", setup_file="opt/ros/setup.bash")
    expect_config_error("distro 大写", distro="Humble")
    expect_config_error("env 键小写", env={"ros_domain": "1"})
    expect_config_error("env 值带空格", env={"ROS_DOMAIN_ID": "4 2"})


def test_file_roundtrip_and_hot_reload() -> None:
    print("== 配置文件：读写往返 / 热加载 / resolve ==")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "targets.json"

        assert targets.load_all(path) == {}
        ok("缺文件时返回空目标表")

        cfg = build_target(
            name="board", description="测试板", host="10.0.0.5", username="u",
            auth_method="password", password="pw", container="ros_box",
        )
        targets.write_target(cfg, path)
        on_disk = json.loads(path.read_text())
        assert on_disk["targets"]["board"]["container"] == "ros_box"
        ok("原子写入后 JSON 结构正确")

        loaded = targets.load_all(path)
        assert loaded["board"].password == "pw" and loaded["board"].container == "ros_box"
        ok("读回往返一致")

        # 热加载：绕过 write_target 直接改文件（模拟人工编辑），mtime 变化后应重读
        data = json.loads(path.read_text())
        data["targets"]["board"]["description"] = "人工改过"
        path.write_text(json.dumps(data, ensure_ascii=False))
        stamp = (path.stat().st_mtime_ns, path.stat().st_size)
        while (path.stat().st_mtime_ns, path.stat().st_size) == stamp:  # 确保 mtime 变化
            time.sleep(0.01)
            data = json.loads(path.read_text())
            data["targets"]["board"]["description"] = "人工改过"
            path.write_text(json.dumps(data, ensure_ascii=False))
        assert targets.load_all(path)["board"].description == "人工改过"
        ok("手动编辑后热加载生效")

        # 未知字段拒绝
        data = json.loads(path.read_text())
        data["targets"]["board"]["sneaky"] = True
        path.write_text(json.dumps(data))
        try:
            targets.load_all(path)
            raise SystemExit("未拒绝未知字段")
        except ConfigError as exc:
            assert "sneaky" in str(exc)
        ok("文件中的未知字段响亮拒绝")

        # remove_target + resolve
        targets.remove_target("board", path)
        assert targets.load_all(path) == {}
        try:
            targets.resolve("board")
            raise SystemExit("resolve 未拒绝未知目标")
        except ConfigError as exc:
            assert "list_targets" in str(exc)
        ok("删除后 resolve 报错并提示 list_targets")

        assert targets.resolve("local").is_local
        ok("local 隐式目标恒可用")

        targets.write_target(cfg, path)
        runner.forget_target_cache("board")  # 不应抛错
        ok("forget_target_cache 安全")


def test_snippets() -> None:
    print("== runner：snippet 构造 ==")
    s = runner.build_ros2_snippet("/opt/ros/humble/setup.bash", {}, ["topic", "echo", "/chatter"])
    assert "source /opt/ros/humble/setup.bash" in s
    assert "exec ros2 topic echo /chatter" in s
    assert "timeout" not in s
    ok("基础 snippet：source + exec，无 timeout")

    s = runner.build_ros2_snippet(
        None, {"ROS_DOMAIN_ID": "42"}, ["topic", "hz", "/x"],
        kill_after=17.0, merge_stderr=True,
    )
    assert "export ROS_DOMAIN_ID=42" in s
    assert "exec timeout -k 1 17.0 ros2 topic hz /x 2>&1" in s
    ok("容器/远端 snippet：env 导出 + timeout 包裹 + stderr 合并")

    # 已过围栏但形状怪异的 token 必须被 quote 保护
    s = runner.build_ros2_snippet(None, {}, ["param", "get", "/n", "a.b-c_d"])
    assert "'a.b-c_d'" not in s  # 安全 token 不加引号也安全
    s = runner.build_ros2_snippet(None, {"A": "x;y"}, ["node", "list"])
    assert "'x;y'" in s, "env 值必须被 quote"
    ok("特殊字符经 shlex.quote 纵深防御")

    # 围栏对新旧用例仍然有效
    for bad in (["topic", "pub", "/x", "std_msgs/msg/String", "hi"], ["daemon", "stop"]):
        try:
            runner._validate_args(bad)
            raise SystemExit(f"围栏失效：{bad}")
        except runner.SecurityError:
            pass
    runner._validate_args(["daemon", "status"])
    ok("安全围栏不变（pub 拒绝、daemon status 放行）")


async def _count_tools() -> int:
    from ros2_inspector.server import mcp

    tools = await mcp.list_tools()
    return len(tools)


def test_registration() -> None:
    print("== server：工具注册 ==")
    count = asyncio.run(_count_tools())
    assert count == 17, f"应注册 17 个工具，实际 {count}"
    ok(f"17 个工具全部注册（13 查看 + 4 管理）")


def test_rate_verdict() -> None:
    print("== topics：频率语义结论 ==")
    from ros2_inspector.tools.topics import _rate_verdict

    assert "稳定" in _rate_verdict([10.0, 10.0, 10.0], 0, 0.0)
    ok("稳定频率 → 稳定")
    assert "断续" in _rate_verdict([10.0] * 5, 2, 3.0)
    ok("10Hz 话题 2 次间隙 → 断续")
    assert "低频" in _rate_verdict([0.1, 0.1], 2, 5.0)
    ok("0.1Hz 话题有静默 → 低频属正常（不算断流）")
    assert "波动" in _rate_verdict([2.0, 10.0, 2.0], 0, 0.0)
    ok("忽快忽慢 → 波动大")
    assert "未统计到" in _rate_verdict([], 0, 0.0)
    ok("无数据 → 明确说明")


def main() -> None:
    test_build_target()
    test_file_roundtrip_and_hot_reload()
    test_snippets()
    test_rate_verdict()
    test_registration()
    print(f"\n✅ v0.2 单元测试全部通过（{PASS} 项）")


if __name__ == "__main__":
    main()
