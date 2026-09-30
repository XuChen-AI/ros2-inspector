# Changelog

本项目的所有重要变更都记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.3.0] - 2026-09-30

### Removed

- 可执行命令别名 `ros2-inspector`：只保留与包同名的 `ros2-inspector-mcp`（v0.1.1 为兼容而保留的双入口正式收敛为一个）。
  **升级注意**：若你的 MCP 配置用的是 `uv run ... ros2-inspector`（短命令），请改为 `ros2-inspector-mcp`；`uvx ros2-inspector-mcp` 与 `uv tool` 用户不受影响。

## [0.2.0] - 2026-09-30

### Added（ssh 远端巡检）

- **ssh 远端巡检**：server 常驻本机，通过 ssh 巡检远端板子/服务器/容器；本机、本机容器、ssh 远端、ssh 远端容器四种形态统一支持。新依赖 `paramiko`。
- **对话式目标管理 4 个新工具**（13 → 17）：
  - `list_targets`：列出全部可巡检目标（不发起连接），并返回 `config_path`（配置文件位置，便于备份/迁移）；
  - `check_target`：试连目标并返回身份卡（主机名/系统/ROS 发行版/容器/主机指纹），约定每会话首次使用新目标前先向用户确认；
  - `add_target` / `remove_target`：填表式参数 + 逐字段硬校验 + 两步预览确认（confirm=false 只出预览），配置文件由程序统一序列化落盘，热加载无需重启。
- **监测语义升级**：`sample_topic` / `get_topic_rate` 采样窗口上限 15s → 30s；新增内容变化判定（`distinct_messages`/`content_changed`，识别"空转发常量"）与频率稳定性结论（`samples`/`min`/`max`/`gap_count`/`verdict`：稳定/断续/波动；间隙只统计数据之间的静默（启动静默不计入），低频话题的静默间隔判定为正常而非断流）。
- 两个体检工具（`ros_install_info`/`machine_readiness`）改为命令式实现，体检"当前 target 指向的机器"。
- 远端/容器命令内嵌 `timeout -k` 防孤儿进程；审计日志增加目标名字段。
- **daemon 失效自动兜底**：容器/长命 daemon 常见缓存陈旧问题（node list 为空、endpoint 查询 xmlrpc 报错、param 服务调用挂起）触发 `--no-daemon` 直连 DDS 重试；两种路径均为空时返回明确诊断说明。源自真实容器实测（Franka ROS2 jazzy 开发容器）。
- `sample_topic` 识别 echo 的 Python traceback（话题无发布者时 jazzy CLI 抛异常）并转为友好错误而非原始堆栈。
- `key_path` 支持 `~/.ssh/id_rsa` 写法（自动展开）。
- server 新增 `--targets PATH` 参数（默认 `~/.config/ros2-inspector/targets.json`）。
- 测试：`tests/v02_tests.py`（配置校验/热加载/snippet 构造/注册数，15+ 项）；冒烟脚本升级至 17 工具；新增 `tests/remote_e2e.py` 远端端到端验证脚本（已在真实 ssh 容器目标上全程通过）。

## [0.1.1] - 2026-09-29

### Added

- 可执行文件别名 `ros2-inspector-mcp`：`uvx ros2-inspector-mcp` 可直接运行（原命令 `ros2-inspector` 继续可用）。

### Changed

- PyPI 发行名定为 `ros2-inspector-mcp`（原名 `ros2-inspector` 触发 PyPI 名称相似性拦截，无法注册）。

## [0.1.0] - 2026-09-29

### Added

- 首个版本：只读 ROS2 系统巡检 MCP Server（stdio 传输）。
- 13 个只读工具：
  - 零 ROS 依赖：`ros_install_info`（检测本机 ROS 安装情况）、`machine_readiness`（评估机器是否适合安装/运行 ROS）；
  - 系统巡检：`system_overview`（一页快照：节点+话题+连接关系）；
  - 节点：`list_nodes`、`get_node_info`；
  - 话题：`list_topics`、`get_topic_info`、`sample_topic`（限时采样）、`get_topic_rate`（限时频率统计）；
  - 参数：`params`（列表/取值二合一）；
  - 动作：`actions`（列表/详情二合一）；
  - 接口：`show_interface`；
  - 健康：`health_check`（daemon 状态 + doctor 结论）。
- 四层安全围栏（只读白名单 / 黑名单令牌 / 参数正则校验 / 超时强杀+审计日志）。
- 零 ROS 依赖设计：Server 纯 Python，不 import 任何 ROS 库；运行时自动探测 `/opt/ros/*` 并注入子进程环境。
- 流式命令（echo/hz）限时采样："N 条消息或 T 秒先到为准"，超时强杀并返回部分输出。
- `--version` 命令行参数。
- 中英双语 README、MIT License、uv 项目配置。

[Unreleased]: https://github.com/XuChen-AI/ros2-inspector/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/XuChen-AI/ros2-inspector/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/XuChen-AI/ros2-inspector/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/XuChen-AI/ros2-inspector/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/XuChen-AI/ros2-inspector/releases/tag/v0.1.0
