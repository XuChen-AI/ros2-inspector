"""安全围栏单元测试：只测拦截逻辑，不真正执行 ros2（无需 ROS 环境）。

用法: uv run python tests/fence_tests.py
"""

from __future__ import annotations

from ros2_inspector import runner


def expect_reject(args: list[str]) -> None:
    try:
        runner._validate_args(args)
    except runner.SecurityError as exc:
        print(f"  [拒绝] {' '.join(args)}\n         ← {exc}")
        return
    raise SystemExit(f"围栏失效！未拦截: {args}")


def expect_pass(args: list[str]) -> None:
    runner._validate_args(args)
    print(f"  [放行] {' '.join(args)}")


def main() -> None:
    print("== 应当拒绝 ==")
    expect_reject(["topic", "pub", "/chatter", "std_msgs/msg/String", "{data: hi}"])  # 发布消息
    expect_reject(["service", "call", "/add_two_ints", "example_interfaces/srv/AddTwoInts"])  # 服务调用
    expect_reject(["param", "set", "/talker", "foo", "1"])  # 参数写入
    expect_reject(["launch", "demo.py"])  # 启动节点
    expect_reject(["pkg", "list"])  # 非白名单动词
    expect_reject(["run", "demo_nodes_cpp", "talker"])  # 运行可执行文件
    expect_reject(["node", "info", "/n; rm -rf /"])  # shell 注入
    expect_reject(["node", "info", "/n$(whoami)"])  # 命令替换
    expect_reject(["topic", "echo", "/x`id`"])  # 反引号
    expect_reject(["topic", "echo", "/a & /b"])  # 空格与后台符
    expect_reject(["topic", "list", "-t;"])  # 标志位夹带
    expect_reject(["param", "get", "/n", "p", "1", "2", "3", "4", "5", "6"])  # 参数个数超限
    expect_reject([])  # 空命令

    print("\n== 应当放行（校验层） ==")
    expect_pass(["node", "list"])
    expect_pass(["node", "info", "/talker"])
    expect_pass(["topic", "list", "-t"])
    expect_pass(["topic", "info", "-v", "/chatter"])
    expect_pass(["topic", "echo", "/chatter"])
    expect_pass(["topic", "hz", "/chatter"])
    expect_pass(["param", "list", "/talker"])
    expect_pass(["param", "get", "/talker", "use_sim_time"])
    expect_pass(["action", "list", "-t"])
    expect_pass(["action", "info", "/rotate_absolute"])
    expect_pass(["interface", "show", "std_msgs/msg/String"])
    expect_pass(["doctor", "--report"])
    expect_pass(["daemon", "status"])

    print("\n✅ 安全围栏测试全部通过")


if __name__ == "__main__":
    main()
