# ros2-inspector

[English](README.md) | [简体中文](README.zh-CN.md)

![ROS2](https://img.shields.io/badge/ROS2-Inspectable-green)
![Read-only](https://img.shields.io/badge/read--only-no%20side%20effects-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-stdio-purple)
![License](https://img.shields.io/badge/license-MIT-green)

**ros2-inspector lets an LLM automatically analyze the runtime state of your ROS 2 system.** It is an MCP server: ask "how is the system doing?" in natural language, and the model decides which ros2 inspection commands to run, in what order, and how to combine their outputs into a complete analysis.

```
┌────────────────────────────────────────────┐
│   MCP Host (Claude Code / ZCode / Qoder /  │
│   Cursor / Claude Desktop)                 │
│                    │ MCP protocol (stdio)  │
└────────────────────┼───────────────────────┘
                     ▼
        ┌─────────────────────────┐
        │   ros2-inspector MCP    │
        │  pure Python · zero ROS │
        │  dependency · read-only │
        └────────────┬────────────┘
                     │ subprocess (auto-detected ROS env)
                     ▼
              ROS 2 system (DDS)
```

## Why ros2-inspector?

Figuring out "what is the system doing right now" used to look like this:

- `ros2 node list` → a wall of nodes → pick one → `ros2 node info` → spot a suspicious topic → `ros2 topic info -v` → `ros2 topic echo` → `ros2 topic hz` → `ros2 param list`… **jumping back and forth between a dozen commands**;
- the command surface is huge and the syntax inconsistent — **nobody memorizes it**;
- at every step, **you** read the output and **you** connect the dots into "who talks to whom, and is the data healthy".

ros2-inspector hands the whole job to an LLM: **say "analyze the current system state" once, and it runs the entire loop — overview → spot anomalies → drill down → summarize.** Memorizing and composing commands, reading and correlating output: no longer your problem.

> **You**: Analyze the current runtime state of my ROS 2 system.
>
> **Model**: calls `system_overview` for the big picture → notices `/inspector_demo/chatter` has 0 subscribers → calls `get_topic_info` to confirm → calls `sample_topic` / `get_topic_rate` to verify the data itself is healthy → concludes: "One node is running normally, publishing at 6.1 Hz on `/inspector_demo/chatter` — but there are no subscribers, so the messages have no readers. Check whether the downstream node was started."

The guarantees that make this safe to actually run:

- __Read-only, by construction__ → a four-layer safety fence; there is simply no entry point for "publish / call a service / set a param / launch a node";
- __Zero ROS dependency__ → the server is pure Python, sources nothing at startup, and runs on machines without ROS 2 installed (it can even tell you whether ROS is installed and whether the machine is fit for it);
- __Never blocks__ → streaming commands are time-boxed ("N messages or T seconds, whichever comes first"), killed on timeout with the partial output already captured;
- __Distro-agnostic__ → auto-detects `/opt/ros/*` at runtime; Humble / Jazzy / Lyrical with zero configuration;
- __Works with any MCP host__ → Claude Code, ZCode, Qoder, Cursor, Claude Desktop.

---

## 🎥 Examples in Action

> 📌 *TODO: demo GIF here (a natural-language ROS 2 inspection session)*

**Example 1 — System inspection**

> **You**: Which nodes are running, and how are they connected?
>
> **Model**: (calls `system_overview`) The system has 1 node, `/inspector_demo_talker`, publishing `std_msgs/msg/String` messages on `/inspector_demo/chatter`. The topic currently has 0 subscribers…

**Example 2 — Data content & rate**

> **You**: What does the data on `/inspector_demo/chatter` look like? Is the rate normal?
>
> **Model**: (calls `sample_topic` for 3 messages + `get_topic_rate` for 3 seconds) The payload is an incrementing counter string — `hello 279`, `hello 280`… Measured average rate: 6.1 Hz…

**Example 3 — A machine without ROS**

> **You**: Can this machine run ROS?
>
> **Model**: (calls `machine_readiness`) Ubuntu 24.04 — inside the official support matrix (Jazzy / Kilted / Lyrical); 16 GB RAM and 120 GB free disk both sufficient; hostname resolves, network interfaces present. Verdict: ready to install.

---

## 🛠 Quick Start

**Prerequisites**: [uv](https://docs.astral.sh/uv/) — the only requirement. With ROS 2 on the machine the inspection tools work; without it the server still starts fine.

**1. Configure your host** — universal MCP JSON:

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

No install step, no local paths: `uvx` pulls the package from [PyPI](https://pypi.org/project/ros2-inspector-mcp/) on first run. Pin a version with `"args": ["ros2-inspector-mcp@0.1.1"]` if you need reproducibility.

**Install as a persistent tool instead (optional):**

```bash
uv tool install ros2-inspector-mcp   # install
ros2-inspector-mcp --version         # check version
uv tool upgrade ros2-inspector-mcp   # upgrade
uv tool uninstall ros2-inspector-mcp # uninstall
```

**From source (development):**

```bash
git clone https://github.com/XuChen-AI/ros2-inspector.git
cd ros2-inspector && uv sync
```

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

> If your host cannot find `uv`/`uvx` (GUI apps with a restricted PATH), use the absolute path to the uv binary (e.g. `/home/you/.local/bin/uvx`) in the `command` field.

| Host | Where to put it |
|------|----------------|
| ZCode / Claude Code | `.mcp.json` at the workspace root, or each app's MCP settings |
| Claude Desktop | the `mcpServers` block of `claude_desktop_config.json` |
| Qoder / Cursor | Settings → MCP → add server, paste the same JSON |

**2. Ask away**

> "Analyze the current system state" · "Which nodes are running?" · "What does the data on /chatter look like?" · "Is the environment healthy?"

**(Optional) Self-test**: see the `tests/` directory (safety-fence tests, end-to-end smoke test, and a demo publisher script).

---

## 📦 Tools (13, all read-only)

| Tool | Needs ROS? | What it answers |
|------|-----------|-----------------|
| `ros_install_info` | No | Is ROS installed? Which distro, where? |
| `machine_readiness` | No | Is this machine fit to install/run ROS (OS/RAM/disk/network vs. the support matrix)? |
| `system_overview` | Yes | One-page snapshot: nodes + topics + wiring + counts |
| `list_nodes` / `get_node_info` | Yes | Which nodes are running / what a node publishes & subscribes |
| `list_topics` / `get_topic_info` | Yes | Which topics exist & their types / type, endpoint counts, QoS |
| `sample_topic` / `get_topic_rate` | Yes | What the data looks like (time-boxed) / publish rate (time-boxed) |
| `params` | Yes | A node's parameter list / a parameter's current value |
| `actions` | Yes | Action list / one action's detail |
| `show_interface` | Yes | Field definitions of a message/service/action type |
| `health_check` | Yes | Environment health: daemon status + doctor verdict |

**Protocol primitives**: Tools only (works everywhere). Resources are deliberately omitted (our data is live and dynamic — Tool is the right primitive), as are Prompts (the analysis playbook lives in the tool descriptions; revisit in v1.5).

---

## 🔒 Safety Design

Read-only is designed, not promised. Four defense layers, centralized in the single executor (`runner.py`):

1. **Registration layer**: only the 13 read-only functions exist; mutating code is absent from the codebase;
2. **Allowlist layer**: subcommands allowlisted down to "verb + subverb" (13 groups); a banned-token denylist (`pub`/`call`/`set`/`launch`/`run`/`pkg`…) as backstop;
3. **Validation layer**: only flags, ROS names, interface types and numbers pass the format allowlist; `;` `|` `&` `` ` `` `$` are always rejected; `shell=False` throughout;
4. **Runtime layer**: timeout + process-group kill; every call is audit-logged (`audit.log`).

---

## ❓ Troubleshooting

| Symptom | Fix |
|---------|-----|
| Tools report "no ROS 2 environment detected" | Confirm with `ros_install_info`; check that `/opt/ros/<distro>/setup.bash` exists |
| `list_nodes` empty but the robot is clearly running | `ROS_DOMAIN_ID` mismatch between machines; stale daemon → `ros2 daemon stop && ros2 daemon start` |
| `sample_topic` returns no messages | The topic may have no publishers; check the publisher count with `get_topic_info` first |
| "topic/node not found" errors | Names must start with `/` and are case-sensitive; confirm exact names via `list_topics`/`list_nodes` first |
| `health_check` reports an incomplete verdict | `doctor` includes network checks and can take up to ~30 s; on slow networks the verdict may be truncated |

---

## 🗺 Roadmap

- [ ] v1.5: diagnostic Prompt templates (one-click system checkup); read-only `service list/type`
- [x] v2: PyPI release — `uvx ros2-inspector-mcp`, path-independent
- [ ] v2: Docker packaging (zero host dependencies)

---

## 🤝 Contributing

Issues and PRs are welcome: new tool suggestions (read-only only), host-configuration feedback, doc improvements.

---

## 📜 License

[MIT](LICENSE) — Copyright (c) 2026 XuChen
