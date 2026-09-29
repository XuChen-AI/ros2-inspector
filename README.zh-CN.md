# ros2-inspector

[English](README.md) | [简体中文](README.zh-CN.md)

![ROS2](https://img.shields.io/badge/ROS2-Inspectable-green)
![只读](https://img.shields.io/badge/只读-无副作用-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-stdio-purple)
![License](https://img.shields.io/badge/license-MIT-green)

**ros2-inspector 让大模型自动分析你的 ROS2 系统运行状态。** 它是一个 MCP Server：你用自然语言问"系统现在怎么样"，大模型自动决定执行哪些 ros2 查看命令、按什么顺序查、怎么把多个命令的输出拼成完整的分析结论。

```
┌────────────────────────────────────────────┐
│        MCP 宿主（Claude Code / ZCode /      │
│        Qoder / Cursor / Claude Desktop）    │
│                    │ MCP 协议 (stdio)       │
└────────────────────┼───────────────────────┘
                     ▼
        ┌─────────────────────────┐
        │   ros2-inspector MCP    │
        │  （纯 Python，零 ROS 依赖）│
        │     四层安全围栏·只读      │
        └────────────┬────────────┘
                     │ subprocess（自动探测并注入 ROS 环境）
                     ▼
              ROS2 系统（DDS 网络）
```

## Why ros2-inspector?

想搞清楚"系统现在什么状态"，以前是这样的：

- `ros2 node list` → 看到一堆节点 → 挑一个 `ros2 node info` → 发现可疑话题 → `ros2 topic info -v` → `ros2 topic echo` → `ros2 topic hz` → `ros2 param list`……**在十几个命令之间来回跳转**；
- 命令体系庞大、参数格式各异，**根本记不住**；
- 每一步的输出都要**自己读、自己对着分析**，拼出"谁连着谁、数据正不正常"的结论。

ros2-inspector 把这整件事交给大模型：**你说一句"分析一下当前系统的运行状态"，它自动完成"总览 → 发现可疑点 → 下钻查询 → 汇总结论"的全过程。** 命令的记忆和组合、输出的阅读和关联分析，都不再是你的负担。

> **你**：分析一下当前 ROS2 系统的运行状态
>
> **模型**：先调 `system_overview` 拿到全貌 → 注意到 `/inspector_demo/chatter` 订阅者为 0 → 调 `get_topic_info` 确认 → 调 `sample_topic`/`get_topic_rate` 验证数据本身正常 → 给出结论："系统有 1 个节点正常运行，话题数据 6.1Hz 正常发布，但没有任何订阅者——消息发出去没人收，检查下游节点是否启动。"

支撑这件事可靠运行的底层保障：

- __只读，绝对安全__ → 四层安全围栏，不存在任何"发布消息 / 调服务 / 改参数 / 启动节点"的入口；
- __零 ROS 依赖__ → Server 纯 Python、不 source 任何环境，没装 ROS 的机器也能跑（还能检测装没装、适不适合装）；
- __永不阻塞__ → 流式命令全部限时采样，超时强杀并返回已捕获的部分输出；
- __多发行版自适应__ → 运行时自动探测 `/opt/ros/*`，Humble/Jazzy/Lyrical 不用改配置；
- __任何 MCP 宿主通用__ → Claude Code、ZCode、Qoder、Cursor、Claude Desktop。

---

## 🎥 Examples in Action

> 📌 *TODO：此处放一段演示 GIF（自然语言问答排查 ROS2 系统的录屏）*

**例 1 —— 系统巡检**

> **你**：现在 ROS 系统里跑着哪些节点？互相怎么连接的？
>
> **模型**：（调用 `system_overview`）当前系统有 1 个节点 `/inspector_demo_talker`，它向 `/inspector_demo/chatter`（`std_msgs/msg/String`）发布消息，当前该话题订阅者数量为 0……

**例 2 —— 数据内容与频率**

> **你**：/inspector_demo/chatter 上数据长什么样？频率正常吗？
>
> **模型**：（调用 `sample_topic` 采样 3 条 + `get_topic_rate` 统计 3 秒）内容是递增计数字符串 `hello 279`、`hello 280`……实测平均频率 6.1 Hz……

**例 3 —— 没装 ROS 的机器**

> **你**：这台机器能跑 ROS 吗？
>
> **模型**：（调用 `machine_readiness`）Ubuntu 24.04，在官方支持矩阵内（Jazzy/Kilted/Lyrical）；16GB 内存、剩余磁盘 120GB，均满足；主机名可解析，网络接口正常。结论：适合安装。

---

## 🛠 Quick Start

**前置**：[uv](https://docs.astral.sh/uv/)（唯一必需）；本机有 ROS2 则查看类工具可用，没有也不影响启动。

**1. 安装**

```bash
cd ros2-inspector
uv sync
```

**2. 配置宿主**（MCP 配置通用 JSON，`--directory` 后面改成你的项目路径）：

```json
{
  "mcpServers": {
    "ros2-inspector": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/ros2-inspector", "ros2-inspector"]
    }
  }
}
```

> 发布 PyPI 之后会简化为 `"command": "uvx", "args": ["ros2-inspector"]`——路径无关，见 Roadmap。
> 若宿主找不到 `uv`（PATH 受限的图形应用），可改用 uv 的绝对路径，或使用仓库里的 `start_ros2_mcp.sh` 启动脚本兜底。

| 宿主 | 配置位置 |
|------|---------|
| ZCode / Claude Code | 工作区根目录 `.mcp.json`，或各自 MCP 设置界面 |
| Claude Desktop | `claude_desktop_config.json` 的 `mcpServers` |
| Qoder / Cursor | 设置 → MCP → 添加服务器，粘贴同样的 JSON |

**3. 开始提问**

> "分析一下当前系统的运行状态" · "看看现在有哪些节点" · "/chatter 上数据长什么样" · "环境健康吗？"

**（可选）自测**：想先本地验证一遍，见仓库 `tests/` 目录（安全围栏测试 + 端到端冒烟 + 测试用发布者脚本）。

---

## 📦 工具清单（13 个，全部只读）

| 工具 | 需要 ROS？ | 回答什么 |
|------|-----------|---------|
| `ros_install_info` | 否 | 本机装没装 ROS？哪个发行版、什么路径？ |
| `machine_readiness` | 否 | 机器适不适合装/跑 ROS（OS/内存/磁盘/网络对照支持矩阵） |
| `system_overview` | 是 | 一页快照：节点 + 话题 + 连接关系 + 数量统计 |
| `list_nodes` / `get_node_info` | 是 | 哪些节点在跑 / 某节点收发什么、连着谁 |
| `list_topics` / `get_topic_info` | 是 | 有哪些话题、什么类型 / 类型、收发者数、QoS |
| `sample_topic` / `get_topic_rate` | 是 | 话题数据内容（限时采样）/ 发布频率（限时统计） |
| `params` | 是 | 节点参数列表 / 某参数当前值 |
| `actions` | 是 | 动作列表 / 某动作详情 |
| `show_interface` | 是 | 消息/服务/动作类型的字段定义 |
| `health_check` | 是 | 环境健康：daemon 状态 + doctor 体检结论 |

**协议原语**：只实现 Tools（所有宿主通用）。有意不做 Resources（数据是实时动态查询，Tool 才是正确语义）与 Prompts（分析套路已写进工具描述，v1.5 再评估）。

---

## 🔒 安全设计

只读是设计出来的，不是约定出来的。四层纵深防御，集中在统一执行器 `runner.py`：

1. **注册层**：只注册 13 个只读函数，写操作的代码不存在；
2. **白名单层**：子命令精确到"动词+子动词"13 组；黑名单令牌（`pub`/`call`/`set`/`launch`/`run`/`pkg`…）兜底；
3. **校验层**：参数只放行标志位/ROS 名称/接口类型/数字等白名单格式，`;` `|` `&` `` ` `` `$` 一律拒绝，全程 `shell=False`；
4. **兜底层**：超时 + 进程组强杀；每次调用写审计日志（`audit.log`）。

---

## ❓ 故障排查

| 现象 | 处理 |
|------|------|
| 工具说"未检测到 ROS2 环境" | `ros_install_info` 确认安装；确认 `/opt/ros/<发行版>/setup.bash` 存在 |
| `list_nodes` 为空但机器人在跑 | 两边 `ROS_DOMAIN_ID` 是否一致；daemon 缓存过期就 `ros2 daemon stop && ros2 daemon start` |
| `sample_topic` 返回无消息 | 话题可能没有发布者；先用 `get_topic_info` 看发布者数量 |
| 报话题/节点不存在 | 名称需 `/` 开头、大小写敏感；先 `list_topics`/`list_nodes` 确认确切名称 |
| `health_check` 提示不完整 | doctor 含网络检查最长约 30 秒，慢网络下结论可能被截断 |

---

## 🗺 Roadmap

- [ ] v1.5：Prompts 诊断模板（一键系统体检）；`service list/type` 只读查询
- [ ] v2：PyPI 发布（`uvx ros2-inspector` 一条命令可用）；Docker 封装（宿主机零依赖）

---

## 🤝 Contributing

欢迎 issue 与 PR：新工具建议（保持只读）、宿主配置反馈、文档改进。

---

## 📜 License

[MIT](LICENSE) — Copyright (c) 2026 XuChen
