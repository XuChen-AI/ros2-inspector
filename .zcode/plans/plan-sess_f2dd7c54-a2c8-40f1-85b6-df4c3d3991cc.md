# ROS2 查看型 MCP Server（ros2-inspector）实施计划

## 目标

只读 ROS2 巡检 MCP Server：大模型通过 MCP 查看节点/话题/参数等状态，并能在**未装 ROS 的机器**上检测安装情况与机器适配性。

已确认决策：ros2 CLI 子进程路线；**13 个工具**；本地 uv 跑通；代码全部在 `test/ros2-inspector/`。

## 与 ROS 的解耦（本次确认的重点）

- **Server 本体零 ROS 依赖**：纯 Python + FastMCP，不 import 任何 ROS 库；启动脚本不 source ROS，裸机器可直接启动。
- **运行时自动探测**：首次调用查看类工具时，扫描 `/opt/ros/*/setup.bash`，用一次固定命令（`bash -c "source <setup> && env -0"`，无用户输入、无注入面）提取环境变量，后续所有子进程以 shell=False + 注入 env 执行。
- **未装 ROS 不崩溃**：探测失败时，查看类工具返回友好结论（"本机未检测到 ROS2"）；两个新工具完全不需要 ROS。
- **物理边界诚实声明**：查 ROS 网络的工具在没装 ROS 的机器上只能返回"未检测到"，不可能凭空查出节点。

## 安全围栏（四层纵深防御，集中在 runner.py）

1. 工具注册层：只注册 13 个只读函数，pub/call/set/launch 代码不存在
2. 命令白名单层：ros2 可执行文件由探测产生（仅接受 /opt/ros 下的合法路径）；子命令白名单精确到"动词+子动词"；黑名单令牌（pub/call/set/launch/delete/security…）兜底
3. 参数校验层：ROS 名称正则；含 `;`、`|`、`&`、反引号、`$` 拒绝；shell=False
4. 运行时兜底层：超时+进程组强杀；审计日志（时间/参数/耗时/结果）

新工具 machine_readiness / ros_install_info 用纯 Python 标准库实现，**零子进程**，天然安全。

## 协议原语

只做 Tools；不做 Resources（数据实时动态）；Prompts/Skills 留 v1.5（套路先写进 docstring）。

## 工具清单（13 个）

| 工具 | 依赖 ROS？ | 回答什么 |
|---|---|---|
| `ros_install_info` | 否（纯 Python） | 本机装没装 ROS？哪个发行版、什么路径？ |
| `machine_readiness` | 否（纯 Python） | 机器适不适合装/跑 ROS（OS/内存/磁盘/网络对照支持矩阵） |
| `health_check` | 需要 | ROS 环境本身健康吗（doctor + daemon） |
| `system_overview` | 需要 | 一页快照：节点+话题+连接关系 |
| `list_nodes` / `get_node_info` | 需要 | 哪些节点在跑 / 某节点收发什么 |
| `list_topics` / `get_topic_info` | 需要 | 有哪些话题 / 类型与 QoS |
| `sample_topic` / `get_topic_rate` | 需要 | 数据内容（限时采样原文）/ 频率 |
| `actions` / `params` / `show_interface` | 需要 | 动作 / 参数 / 消息接口定义 |

## 项目结构

```
test/ros2-inspector/
├── pyproject.toml        # 依赖 mcp[cli]
├── README.md             # 安装、三宿主 JSON 配置、工具表、故障排查
├── start_ros2_mcp.sh     # 纯 uv 启动（不碰 ROS 环境）
├── tests/                # 围栏测试 + MCP 客户端冒烟测试
└── src/ros2_inspector/
    ├── server.py         # FastMCP 实例 + 注册工具
    ├── runner.py         # ROS 探测 + 统一执行器 + 四层围栏 + 审计日志
    └── tools/            # rosenv/overview/nodes/topics/params/actions/interfaces/health
```

## 实施步骤

1. uv 建骨架，`uv sync` 安装依赖
2. 实现 runner.py（ROS 探测 + 四层围栏 + 超时强杀 + 审计）
3. 实现 13 个工具（docstring 五要素：功能/何时用/参数/返回/失败）
4. 启动脚本 + README + `.mcp.json`
5. 围栏测试：注入字符、黑名单动词全部拦截
6. 起 demo talker，真实 MCP 客户端全链路冒烟（列工具→调用→未装 ROS 场景→围栏端到端）

## 验收标准

- 13 个工具全部正常应答；围栏用例全部拦截
- 在探测不到 ROS 的场景下返回友好结论不崩溃
- sample_topic/get_topic_rate 超时返回部分数据不挂起
- MCP 客户端端到端通过