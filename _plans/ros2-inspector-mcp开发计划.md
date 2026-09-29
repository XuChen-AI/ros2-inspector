# ros2-inspector 开发计划

只读 ROS2 系统巡检 MCP Server——让大模型通过 MCP 自动查看 ROS2 系统（节点/话题/参数/动作/频率/健康状态），免除命令记忆负担，多条命令的"协调分析"交给模型组合完成。

> 状态：**v1 已完成并通过端到端验证**（2026-09-29）
> 位置：`test/`（仓库根即项目根，结构已拍平）

---

## 一、需求背景

- ROS2 查看命令体系庞大（`ros2 node/topic/param/action/...`）难记，且分析问题常需多条命令组合；
- 目标：大模型调用 MCP 工具自动执行查看类命令，用户只需自然语言提问；
- 硬性约束：**只读**（不发布、不调用服务、不改参数、不启动节点）、**零 ROS 依赖**（未装 ROS 的机器上 Server 照常运行，还能检测"装没装 ROS / 适不适合装 ROS"）。

## 二、关键架构决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 通信路线 | **ros2 CLI 子进程**（否决 rclpy 原生） | Server 进程零 ROS 导入；ROS 环境由 runner 运行时探测注入；rclpy 路线需 source 环境且版本耦合 |
| ROS 环境 | 运行时自动探测 `/opt/ros/*/setup.bash`，一次固定命令抓取 env（无注入面），子进程 `shell=False` + 注入 env | 启动脚本不 source ROS；多发行版自适应 |
| 未装 ROS | 查看类工具返回友好结论不崩溃；新增两个纯 Python 检测工具 | 用户核心诉求"不依赖 ROS 装没装" |
| 解析策略 | 混合：列表类解析成 JSON；自由文本（echo 内容）原样透传 | 消费方是大模型，读原文比自己写脆弱解析器更可靠 |
| 防阻塞 | 统一 runner：普通命令 10s 超时；流式命令（echo/hz）限时采样"N 条消息或 T 秒先到为准"；超时进程组强杀并返回已捕获输出 | 窗口/会话永不挂起 |
| 协议原语 | 只做 Tools | Resources 适合静态内容（我们的数据是实时动态查询）；Prompts/Skills 留 v1.5（套路先写进 docstring + server instructions） |
| SDK 版本 | `mcp[cli]>=1.10,<2` | 2.x 已把 FastMCP 改名 MCPServer，1.x 与现有生态/教程兼容 |
| 打包深度 | 本地 uv 跑通 | 先验证价值；发布 PyPI/Docker 留后续 |

## 三、安全围栏（四层纵深防御，集中在 runner.py）

1. **工具注册层**：只注册 13 个只读函数，`pub`/`call`/`set`/`launch` 的代码不存在；
2. **命令白名单层**：ros2 可执行文件仅接受探测发现的合法路径；子命令白名单精确到"动词+子动词"13 组（node list/info、topic list/info/echo/hz、param list/get、action list/info、interface show、doctor、daemon status）；黑名单令牌（pub/publish/call/set/launch/delete/security/run/pkg/service/bag/component/lifecycle/multicast/wasm）精确匹配兜底；
3. **参数校验层**：参数只允许标志位/ROS 名称/参数名/接口类型/数字五类白名单正则（禁止 `;` `|` `&` 反引号 `$` 括号空格）；参数个数 ≤8；
4. **运行时兜底层**：超时 + 进程组 SIGKILL；审计日志（`audit.log` + stderr：时间/命令/耗时/结果/输出量）。

## 四、工具清单（13 个，全部只读）

| 工具 | 需要 ROS？ | 回答什么 |
|------|-----------|---------|
| `ros_install_info` | 否（纯 Python 零子进程） | 本机装没装 ROS？哪个发行版、什么路径？ |
| `machine_readiness` | 否（纯 Python 零子进程） | 机器适不适合装/跑 ROS（OS/内核/内存/磁盘/网络对照支持矩阵） |
| `system_overview` | 是 | 一页快照：节点 + 话题 + 连接关系 + 数量统计 |
| `list_nodes` / `get_node_info` | 是 | 哪些节点在跑 / 某节点收发什么 |
| `list_topics` / `get_topic_info` | 是 | 有哪些话题 / 类型与 QoS |
| `sample_topic` / `get_topic_rate` | 是 | 话题内容（限时采样原文）/ 发布频率（限时统计） |
| `params` | 是 | 节点参数列表 / 某参数当前值 |
| `actions` | 是 | 动作列表 / 某动作详情 |
| `show_interface` | 是 | 消息/服务/动作类型的字段定义 |
| `health_check` | 是 | ROS 环境健康：daemon 状态 + doctor 结论（实测 doctor --report 需 52s，故用普通 doctor + 30s 超时） |

## 五、项目结构

```
（仓库根 = test/）
├── pyproject.toml        # uv 管理，依赖 mcp[cli]>=1.10,<2
├── README.md / README.zh-CN.md
├── tests/
│   ├── fence_tests.py    # 安全围栏单元测试（无需 ROS）
│   ├── client_smoke.py   # 真实 MCP 客户端端到端冒烟
│   └── demo_talker.py    # 测试辅助发布者（rclpy，仅测试用，非 Server 代码）
└── src/ros2_inspector/
    ├── server.py         # FastMCP 实例 + 工具注册 + instructions
    ├── runner.py         # ROS 探测 + 统一执行器 + 四层围栏 + 审计
    └── tools/            # rosenv / overview / nodes / topics / params / actions / interfaces / health + _parse
```

## 六、验证结果（2026-09-29 实测）

- ✅ 围栏测试：13 个恶意用例（pub/call/set/launch/注入字符/命令替换/反引号/参数超限）全部拒绝；13 个合法用例全部放行；
- ✅ 端到端冒烟（真实 demo 发布者 + 官方 MCP 客户端全协议）：13 工具全部正常应答；采样 3 条消息后在条数上限正常停止（不挂起）；实测频率 6.1Hz；QoS/接口定义真实返回；注入参数 `isError=True`；
- ✅ 审计日志落盘（26 条记录：命令/耗时/状态/输出量）；
- ✅ 零污染：src 无任何 ROS 导入（rclpy 仅存在于 tests/demo_talker.py 测试辅助）；依赖全部装在项目内 `.venv`；系统级 pip 无变化。

### 开发过程中发现并解决的真实问题

1. mcp SDK 已发布 2.x（FastMCP 改名 MCPServer）→ 依赖 pin `<2`；
2. 本机 `ros2 doctor --report` 耗时 52s → 改用普通 `doctor`（23s）+ 30s 超时兜底；
3. CLI 运行期警告（如 "Timed out waiting..."）混入参数列表 → 解析时过滤到 `cli_messages` 字段。

## 七、宿主接入

工作区已放置 `test/.mcp.json`（ZCode / Claude Code 通用格式，标准 uv 形式）：

```json
{
  "mcpServers": {
    "ros2-inspector": {
      "command": "uv",
      "args": ["run", "--directory", "/home/xuchen/XuChenCode/test", "ros2-inspector"]
    }
  }
}
```

Claude Desktop / Qoder 填同样的 JSON（位置见 README）。

## 八、后续路线（未实施）

| 阶段 | 内容 |
|------|------|
| v1.5 | Prompts 诊断模板（`diagnose_system` 等一键体检）；`service list/type` 只读查询；overview 连接关系图优化 |
| v2 | PyPI 发布（`uvx ros2-inspector` 一条命令可用；本地打包已于 2026-09-29 完成验证）；Docker 封装（镜像内含 ROS CLI，宿主机零依赖；需 `--net=host`） |
| 可选 | 话题采样结构化解析（按消息类型 JSON 化）；多发行版优先级配置；参数写入等控制类工具（需显式授权开关，默认关闭） |

## 九、发版流程约定（2026-09-29 打包准备时确立）

**每次发版五步**（版本单一来源 = pyproject，运行时经 importlib.metadata 读取）：

```
1. uv version 0.x.0            # 改版本号（同步 pyproject + uv.lock）
2. 更新 CHANGELOG.md            # 新版本改了什么（Keep a Changelog 格式）
3. git commit + git tag v0.x.0  # 提交并打 tag
4. uv build                     # 产出 dist/ 下 wheel + sdist
5. uv publish                   # 推到 PyPI（需要凭据，见下方前提清单）
```

**发版前提清单**（2026-09-29 全部完成，v0.1.0 与 v0.1.1 已上架）：

- [x] 包名：**最终发行名 `ros2-inspector-mcp`**。教训：`ros2-inspector` 本身虽未被占（simple index 404），但上传时被 PyPI **名称相似性拦截**（400 "too similar to an existing project"）——simple index 查重只能查"完全同名"，防不住相似性策略；选定新名后直接重试即可，无损失
- [x] pypi.org 注册账号（用户名注册后不可改）
- [x] 账号设置里生成 API token（scope 选 Entire account——首次创建新包必须）
- [x] `uv publish --token <token>` 上传成功（token 仅作命令行参数，不落盘；发布后已建议用户在网站撤销轮换）
- [ ] （可选）配置 GitHub Actions Trusted Publishing，之后打 tag 自动发布、无需本地 token
- [x] 发布后 README 补"Install from PyPI"章节（`uvx ros2-inspector-mcp` 配置置顶）

**发布实录**（2026-09-29）：

- v0.1.0：首次上传被名称相似性拦截 → 改名 `ros2-inspector-mcp` 后成功上架
- v0.1.1（当天）：发现 `uvx ros2-inspector-mcp` 默认找同名可执行文件而我们的命令叫 `ros2-inspector` → 加同名可执行别名（两个入口共存）→ 完整走了一遍"uv version → CHANGELOG → build → publish"迭代流程
- 发布后三重验证通过：干净目录 `uvx ros2-inspector-mcp --version` → 0.1.1；`--from` 方式同样 0.1.1；仓库 grep 无 token 痕迹
- 经验：PyPI simple index 走 CDN，刚发布的版本可能延迟几分钟才对解析器可见（JSON API 先更新）；本机 uvx 缓存可用 `uvx --reinstall <pkg>` 强制重新解析

**已验证的本地打包状态**（0.1.0，2026-09-29）：

- `uv run ros2-inspector --version` → 0.1.0（元数据读取正常）
- `uv build` → `dist/ros2_inspector-0.1.0-py3-none-any.whl`（纯 Python 通用 wheel）+ sdist
- 陌生目录 `uvx --from <wheel>` 启动 MCP 服务：13 工具注册正常
- `uv tool install/uninstall` 三件套：安装→`--version`→卸载无残留
- 环境零污染复核：系统 pip 用户包前后 0 变化；依赖仅在项目 .venv 与 uv 缓存

**升级语义**（已发布，自动成立）：uvx 用户下次启动自动解析新版（可 `ros2-inspector-mcp@0.x.y` 钉版本）；tool 用户 `uv tool upgrade ros2-inspector-mcp`；pip 用户 `pip install -U ros2-inspector-mcp`；MCP 配置文件全程不用改。

## 十、物理边界（诚实声明）

查 ROS 网络的工具在未安装/未运行 ROS 的机器上只能返回"未检测到/无节点"，不可能凭空查出节点——DDS 发现依赖本机或网络可达的 ROS 运行时。这个边界不可封装，只能友好呈现。
