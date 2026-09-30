# ros2-inspector

[English](README.md) | [简体中文](README.zh-CN.md)

[![PyPI](https://img.shields.io/pypi/v/ros2-inspector-mcp)](https://pypi.org/project/ros2-inspector-mcp/)
![ROS2](https://img.shields.io/badge/ROS2-Inspectable-green)
![只读](https://img.shields.io/badge/只读-无副作用-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-stdio-purple)
![License](https://img.shields.io/badge/license-MIT-green)

**让 AI 直接查看你的 ROS2 系统。** 这是一个 MCP Server：用自然语言问"系统现在怎么样"，AI 自动执行合适的只读查看命令、组合分析、给出结论。本机、ssh 远端板子、docker 容器里的 ROS 都能查。

```
  MCP 宿主（Claude Code / Qoder / Cursor / Claude Desktop…）
                      │ MCP 协议 (stdio)
                      ▼
          ros2-inspector MCP（纯 Python，零 ROS 依赖）
                      │ 只读命令（本机直跑 / ssh 远端 / docker exec）
                      ▼
                ROS2 系统（DDS 网络）
```

## 解决什么问题

- `ros2 node list` → `node info` → `topic info -v` → `topic echo` → `topic hz` → `param list`……排查一个问题要在十几个命令之间来回跳，命令多、参数杂、记不住；
- 每一步的输出都要自己读、自己拼出"谁连着谁、数据正不正常"的结论；
- ROS 经常装在无头板子、远程服务器或 docker 容器里，得先 ssh 上去才能敲命令。

ros2-inspector 把整件事交给 AI：你说一句"看看板子上的机械臂在干什么"，它自动完成总览、下钻、验证、给结论。监测类工具直接返回语义判断（"稳定 10Hz" / "断续：2 次超过 2 秒的间隙"），而不是一屏原始数字。

## 快速开始

前置：[uv](https://docs.astral.sh/uv/)（唯一依赖）；本机没装 ROS 也能跑。

在 MCP 宿主里添加（Claude Code / ZCode 放工作区 `.mcp.json`，Claude Desktop 放 `claude_desktop_config.json`，Qoder / Cursor 在设置界面粘贴同样的 JSON）：

```json
{
  "mcpServers": {
    "ros2-inspector": {
      "command": "uvx",
      "args": ["ros2-inspector-mcp"]
    }
  }
}
```

然后直接开始提问：

> "分析一下当前系统的运行状态" · "现在有哪些节点？" · "/joint_states 频率正常吗？" · "看看板子上的机械臂在干什么"

### 远程巡检（ssh / 容器）

ROS 装在无头板子、远程服务器或容器里？直接在对话里说：

> "帮我登记一台目标：192.168.1.50，用户 ubuntu，密码 xxx，实验室小车主机"

AI 会先出登记预览、你确认后写入（`add_target`）；首次使用前它会试连并把身份卡（主机名 / 系统 / ROS 发行版 / 主机指纹）亮给你确认（`check_target`）；之后所有工具带 `target="目标名"` 即可巡检远端，不填就是本机。密码和密钥认证都支持，配置热生效、无需重启，换目标只是对话里说一句话。

## 工具清单（17 个，全部只读）

| 工具 | 回答什么 |
|------|---------|
| `list_targets` | 有哪些可巡检目标（本机 + 已登记的远端/容器） |
| `check_target` | 试连目标并返回身份卡 |
| `add_target` / `remove_target` | 对话式登记 / 删除目标（预览确认后生效） |
| `ros_install_info` | 目标机器装没装 ROS？哪个发行版？ |
| `machine_readiness` | 目标机器适不适合装/跑 ROS？ |
| `system_overview` | 一页快照：节点 + 话题 + 连接关系 |
| `list_nodes` / `get_node_info` | 哪些节点在跑 / 某节点收发什么、连着谁 |
| `list_topics` / `get_topic_info` | 有哪些话题、什么类型 / 收发者数与 QoS |
| `sample_topic` | 话题数据内容（≤30s 采样 + 内容变化判定，识别"空转发常量"） |
| `get_topic_rate` | 发布频率（≤30s 统计 + 结论：稳定 / 断续 / 波动） |
| `params` | 节点参数列表 / 某参数当前值 |
| `actions` | 动作列表 / 某动作详情 |
| `show_interface` | 消息/服务/动作类型的字段定义 |
| `health_check` | ROS 环境健康：daemon 状态 + doctor 结论 |

## 安全

只读是设计出来的，不是约定出来的：四层围栏（只注册 17 个只读函数 / 动词白名单+黑名单令牌 / 参数格式校验拒绝注入字符 / 超时强杀 + 审计日志），任何"发布消息 / 调服务 / 改参数 / 启动节点"的代码不存在。远端命令自动限时防孤儿进程。目标登记同样四道围栏：填表式参数、逐字段校验、两步预览确认、统一序列化落盘。配置文件在 `~/.config/ros2-inspector/targets.json`（`--targets` 可改），升级卸载都不影响它。

## License

[MIT](LICENSE)
