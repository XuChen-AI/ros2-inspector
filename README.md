# ros2-inspector

[English](README.md) | [简体中文](README.zh-CN.md)

[![PyPI](https://img.shields.io/pypi/v/ros2-inspector-mcp)](https://pypi.org/project/ros2-inspector-mcp/)
![ROS2](https://img.shields.io/badge/ROS2-Inspectable-green)
![Read-only](https://img.shields.io/badge/read--only-no%20side%20effects-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-stdio-purple)
![License](https://img.shields.io/badge/license-MIT-green)

**Let your AI inspect your ROS 2 system.** This is an MCP Server: ask "how is the system doing?" in natural language and the AI picks the right read-only commands, correlates the outputs, and hands you a conclusion. Works on the local machine, over ssh to headless boards, and inside docker containers.

```
  MCP host (Claude Code / Qoder / Cursor / Claude Desktop…)
                      │ MCP protocol (stdio)
                      ▼
       ros2-inspector MCP (pure Python, zero ROS deps)
                      │ read-only commands (local / ssh / docker exec)
                      ▼
                ROS 2 system (DDS network)
```

## The problem it solves

- Answering "what is the system doing?" means jumping between a dozen commands — `ros2 node list`, `node info`, `topic info -v`, `topic echo`, `topic hz`, `param list`… — none of which are memorable;
- Every step's raw output has to be read and correlated by hand;
- ROS often lives on headless boards, remote servers, or inside containers, so you have to ssh in first.

ros2-inspector hands all of that to the AI: say "what is the robot arm on the board doing?" and it takes the overview → drills into suspects → verifies → concludes. Monitoring tools return semantic verdicts ("stable 10 Hz" / "intermittent: 2 gaps over 2 s"), not walls of raw numbers.

## Quick start

Prerequisite: [uv](https://docs.astral.sh/uv/) (the only dependency); no ROS installation required on this machine.

Add to your MCP host (Claude Code / ZCode: workspace `.mcp.json`; Claude Desktop: `claude_desktop_config.json`; Qoder / Cursor: paste in settings):

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

Then just ask:

> "Analyze the current system state" · "Which nodes are running?" · "Is /joint_states healthy?" · "What is the arm on the board doing?"

### Remote inspection (ssh / containers)

ROS living on a headless board, a remote server, or in a container? Just say it in the conversation:

> "Register a target: 192.168.1.50, user ubuntu, password xxx — that's my lab car host"

The AI shows a registration preview and writes it only after your confirmation (`add_target`); before first use it connects, shows you the identity card (hostname / OS / ROS distro / host-key fingerprint) and waits for your go-ahead (`check_target`); then every tool accepts `target="name"` to inspect the remote, or omits it for local. Password and key auth are both supported; config hot-reloads, no restarts, and switching targets is just conversation.

## Tools (17, all read-only)

| Tool | What it answers |
|------|-----------------|
| `list_targets` | Which inspection targets exist (local + registered remotes/containers) |
| `check_target` | Probe a target and return its identity card |
| `add_target` / `remove_target` | Conversational target registration / removal (preview → confirm) |
| `ros_install_info` | Is ROS installed on the target? Which distro? |
| `machine_readiness` | Is the target machine fit to install/run ROS? |
| `system_overview` | One-page snapshot: nodes + topics + wiring |
| `list_nodes` / `get_node_info` | Which nodes run / what a node publishes & subscribes |
| `list_topics` / `get_topic_info` | Which topics exist & their types / endpoint counts and QoS |
| `sample_topic` | Topic data (≤30s sampling + content-change detection) |
| `get_topic_rate` | Publish rate (≤30s + verdict: stable / intermittent / erratic) |
| `params` | A node's parameter list / a parameter's current value |
| `actions` | Action list / one action's detail |
| `show_interface` | Field definitions of a message/service/action type |
| `health_check` | ROS environment health: daemon status + doctor verdict |

## Safety

Read-only is designed, not promised: four defense layers (only 17 read-only functions exist in the code / verb allowlist + banned-token denylist / parameter format validation that rejects injection / hard timeouts + audit log). No code path for publishing, calling services, setting parameters, or launching nodes exists. Remote commands self-terminate to prevent orphans. Target management has its own four fences: typed parameters, per-field validation, preview-then-confirm, single serializer. Config lives at `~/.config/ros2-inspector/targets.json` (override with `--targets`) and survives upgrades and uninstalls.

## License

[MIT](LICENSE)
