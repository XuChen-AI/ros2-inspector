#!/usr/bin/env bash
# ros2-inspector MCP 启动脚本。
#
# 特点：不依赖、不 source 任何 ROS 环境——Server 本体是纯 Python，
# ROS 环境由它在运行时自动探测 /opt/ros 并注入子进程。
# 宿主（ZCode / Claude Code / Qoder 等）的 MCP 配置直接指向本脚本即可。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

UV="${UV:-$HOME/.local/bin/uv}"
if [[ ! -x "$UV" ]]; then
  UV="$(command -v uv)"
fi

exec "$UV" run ros2-inspector
