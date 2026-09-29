# ros2-inspector v0.1.0 本地打包准备计划（不推远端）

## 范围（按用户指示）

**不做**：`uv publish`、PyPI 注册/token 等一切远端操作。将来想发时一条命令，前提清单写进文档备查。
**做**：本地备好一切可发布产物，wheel 经"陌生用户视角"完整验证。

**可改性说明**：本次填写的作者名/邮箱/LICENSE 版权行/GitHub URL 均可日后随时修改（纯元数据，每版可换）；唯一不可逆的是 PyPI 包名与账号名，本次均不涉及。

**环境影响承诺**：有下载（构建后端 + 缓存复用）、无编译（纯 Python wheel）、零污染（.venv / ~/.cache/uv / uv tools 三重隔离，不碰系统 Python、pip、ROS）；结束时复核系统 pip 列表前后无变化。

## 实施步骤

### ① `--version` 支持（~10 行）
- `server.py` 的 `main()` 加 argparse：`--version` 打印版本退出；无参数照常 stdio 模式。
- 版本单一来源 = pyproject；运行时 `importlib.metadata.version("ros2-inspector")` 读取，`__init__.py` 删除手工 `__version__`（兜底 `0.0.0.dev0`）。

### ② 元数据补全
- pyproject：`authors`（取 `git config user.name/email`）、`license = "MIT"`、`license-files`、`keywords`、`classifiers`、`urls`（取 `git remote -v`，无远程则占位并提醒）。
- 新增 `LICENSE`（MIT 全文）与 `CHANGELOG.md`（Keep a Changelog 格式，0.1.0 首发内容）。

### ③ 包名查重（只读）
- 检查 `pypi.org/project/ros2-inspector`：404 = 可用；被占则报告并商议换名。

### ④ 构建与本地验证（核心）
- `uv build` → `dist/`（wheel + sdist）。
- 陌生视角验证：`uvx --from ./dist/<wheel> ros2-inspector --version`；同方式起 MCP 服务跑最小冒烟（13 工具）。
- 工具三件套验证：`uv tool install --from ./dist/<wheel>` → `--version` → `uninstall`（确认卸载无残留）。
- 环境复核：前后对比系统 pip 用户包列表。

### ⑤ 版本管理落地 + 文档同步
- git：add + commit "v0.1.0" + 本地 tag `v0.1.0`（不推远程）。
- README 中英双份：License 章节与徽章 TODO → MIT；不加"从 PyPI 安装"节（未发布，发布时再加）。
- `_plans` 开发计划补"发版流程约定"与"发布前提清单"（PyPI 账号、API token、查重结论）。

## 验收标准
- 本地与 wheel 两种方式 `--version` 均输出 0.1.0
- wheel 在陌生目录以 uvx --from 起服务，13 工具冒烟通过
- `uv tool install/uninstall` 全流程干净
- LICENSE/CHANGELOG/元数据齐全，构建无错误
- git commit + tag v0.1.0 完成
- 系统 pip 前后对比无变化
- 文档中"将来发布要做什么"一目了然