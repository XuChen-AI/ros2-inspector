"""远端端到端验证：真实 MCP 客户端 → 新 server → ssh 目标（容器/板子）。

用法: uv run python tests/remote_e2e.py <name> <host> <port> <user> <key_path> [description]
例:   uv run python tests/remote_e2e.py franka-dev 127.0.0.1 2222 root ~/.ssh/id_rsa "ROS开发容器"
前置: 目标 ssh 可达且装有 ROS2。登记+巡检全程只读；目标登记保留（不自动删除）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    try:
        name, host, port, user, key_path = sys.argv[1:6]
    except ValueError:
        raise SystemExit(__doc__)
    key_path = os.path.expanduser(key_path)
    desc = sys.argv[6] if len(sys.argv) > 6 else "远端测试目标"

    params = StdioServerParameters(
        command="uv", args=["run", "--directory", str(ROOT), "ros2-inspector"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print(f"注册工具数: {len(names)}")
            assert len(names) == 17, f"应为 17 个工具: {names}"

            async def call(fn: str, args: dict | None = None, must_ok: bool = False) -> str:
                res = await session.call_tool(fn, args or {})
                body = "\n".join(c.text for c in res.content if hasattr(c, "text"))
                head = json.dumps(args or {}, ensure_ascii=False)[:110]
                print(f"\n### {fn}({head}) {'❌isError' if res.isError else '✅'}")
                print(body[:900] + ("..." if len(body) > 900 else ""))
                if must_ok:
                    assert not res.isError and '"error"' not in body, f"{fn} 必须成功却失败"
                return body

            def pick(body: str, *path):
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    return None
                for key in path:
                    if isinstance(data, dict):
                        data = data.get(key)
                    elif isinstance(data, list) and isinstance(key, int) and key < len(data):
                        data = data[key]
                    else:
                        return None
                    if data in (None, [], {}):
                        return None
                return data

            # ── 目标登记：预览 → 确认落盘（两步围栏真实走一遍） ──
            reg = dict(
                name=name, description=desc, host=host, username=user,
                port=int(port), auth_method="key", key_path=key_path,
            )
            preview = await call("add_target", reg)
            if "已存在" not in preview:
                assert "preview" in preview, "第一步应返回预览而非直接写入"
            written = await call("add_target", {**reg, "confirm": True})
            assert "已生效" in written or "已存在" in written, "登记未生效"
            await call("check_target", {"target": name}, must_ok=True)

            # ── 体检类 ──
            await call("ros_install_info", {"target": name})
            await call("machine_readiness", {"target": name})

            # ── 巡检类 ──
            await call("list_nodes", {"target": name})
            topics_body = await call("list_topics", {"target": name})
            topic = pick(topics_body, "topics", 0, "name")
            if topic:
                await call("get_topic_info", {"topic": topic, "target": name})
                await call("sample_topic", {"topic": topic, "max_messages": 3, "timeout_s": 8, "target": name})
                await call("get_topic_rate", {"topic": topic, "duration_s": 8, "target": name})
            else:
                print("\n（无话题可下钻——容器里可能没跑节点，跳过话题类）")

            await call("system_overview", {"target": name})
            nodes_body = await call("list_nodes", {"target": name})
            node = pick(nodes_body, "nodes", 0)
            if node:
                await call("get_node_info", {"node": node, "target": name})
                await call("params", {"node": node, "target": name})

            await call("actions", {"target": name})
            await call("show_interface", {"interface_type": "std_msgs/msg/String", "target": name})
            await call("health_check", {"target": name})

            # ── 远端围栏：注入参数必须被拒 ──
            res = await session.call_tool(
                "get_node_info", {"node": "/x; rm -rf /", "target": name}
            )
            assert res.isError, "远端目标上注入参数应被围栏拒绝"

            await call("list_targets")
            print("\n✅ 远端端到端验证通过（目标已保留，可直接继续使用）")


if __name__ == "__main__":
    asyncio.run(main())
