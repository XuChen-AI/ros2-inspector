# Changelog

本项目的所有重要变更都记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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

[Unreleased]: https://github.com/XuChen-AI/ros2-inspector/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/XuChen-AI/ros2-inspector/releases/tag/v0.1.0
