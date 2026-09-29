"""端到端冒烟测试：以真实 MCP 客户端身份连接 Server，验证协议层全链路。

用法: uv run python tests/client_smoke.py [采样用的话题名]
（默认采样 /chatter；话题不存在时相应调用返回友好提示，不影响测试结论）
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else "/chatter"
    params = StdioServerParameters(
        command="uv",
        args=["run", "--directory", str(ROOT), "ros2-inspector"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            print(f"注册工具数: {len(names)}")
            for name in names:
                print(f"  - {name}")
            assert len(names) == 13, f"工具数量应为 13，实际 {len(names)}: {names}"

            async def call(name: str, args: dict | None = None):
                res = await session.call_tool(name, args or {})
                body = "\n".join(
                    c.text for c in res.content if hasattr(c, "text")
                )
                preview = body[:700] + ("..." if len(body) > 700 else "")
                print(f"\n### {name}({args or ''}) isError={res.isError}\n{preview}")
                return res

            # 零 ROS 依赖工具
            res = await call("ros_install_info")
            assert '"installed"' in "\n".join(
                c.text for c in res.content if hasattr(c, "text")
            ), "ros_install_info 应返回 installed 字段"
            await call("machine_readiness")

            # ROS 查看类工具
            await call("list_nodes")
            await call("list_topics")
            await call("system_overview")
            await call("get_topic_info", {"topic": topic})
            await call("sample_topic", {"topic": topic, "max_messages": 3, "timeout_s": 5})
            await call("get_topic_rate", {"topic": topic, "duration_s": 3})
            await call("params", {"node": "/inspector_demo_talker"})
            await call("show_interface", {"interface_type": "std_msgs/msg/String"})
            await call("health_check")

            # 围栏端到端：注入参数必须被拒（isError=True）
            res = await call("get_node_info", {"node": "/x; rm -rf /"})
            assert res.isError, "注入参数应被安全围栏拒绝"
            res = await call("actions", {"action_name": "/a", "show_types": True})  # 正常放行
            assert not res.isError, "非法以外的正常调用不应报错"

            print("\n✅ 冒烟通过：协议层 + 13 工具 + 安全围栏 全链路 OK")


if __name__ == "__main__":
    asyncio.run(main())
