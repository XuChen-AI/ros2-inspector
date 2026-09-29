# ros2-inspector v0.1.0 发布 PyPI 计划（定稿）

## 第 0 步：作者信息修正（本轮新确认）

- pyproject.toml 的 authors 去掉邮箱，只留 `{ name = "XuChen" }`（避免 QQ 邮箱公开展示在 PyPI 页面；email 是可选字段）
- `uv build` 重建 dist/（版本仍 0.1.0，尚未上传过所以可以覆盖重建）
- 快速复核：wheel 元数据里 Author 显示 XuChen、无 Author-email

## 你在网站上做的（约 3 分钟）

1. 登录 pypi.org，确认邮箱已验证（Account settings；未验证先点邮件；若要求 2FA 按提示设置）
2. Account settings → **API tokens** → **Add API token**：名字随意；Scope 选 **Entire account**（首次创建新包必须）
3. 复制 `pypi-` 开头的完整字符串（只显示一次），粘贴到对话给我
4. （发布完成后建议回网站撤销该 token——对话内容有留存）

## 我在本地做的

1. 发布前最后查重包名（simple index 应 404）
2. `uv publish --token <token>` 上传 dist/（token 仅作命令行参数，不落盘不进文件）
3. 发布后三重验证：干净目录 `uvx ros2-inspector --version` → 0.1.0；PyPI 项目页可访问/README 渲染/MIT/作者正确；grep 全仓库无 token 痕迹
4. 文档收尾：README 中英加 **Install from PyPI**（uvx 配置置顶）；`_plans` 发布前提清单勾选
5. git 本地提交（含上轮清理改动 + 元数据修正 + 本轮文档更新；**不推远程**）

## Token 验证机制备忘

- 服务器生成（你账号里存哈希）+ 本地零预存（字符串即凭证）；`uv publish --token` 塞进请求头，服务器比对哈希定位账号再授权上传
- 作者信息（pyproject authors）是纯展示元数据，不参与验证，与 PyPI 账号无需一致；来源是本机 `~/.gitconfig`（git config user.name/email），非编造
- 持 token 者即身份——不进文件不进仓库即无泄漏面

## 验收标准

- wheel 元数据：Author=XuChen，无 email
- PyPI 项目页存在：ros2-inspector 0.1.0，MIT，README 渲染正常
- 干净目录 `uvx ros2-inspector --version` 输出 0.1.0
- 仓库 grep 无 token 字样
- 本地 git 提交完成（不推送）

## 风险与备注

- 同一版本号只能上传一次（0.1.0 推上去后改动需发 0.1.1+）
- 上传中断重跑 `uv publish` 即可；报 "file already exists" = 其实已成功
- 网站界面若改版找不到 "Entire account"，选允许创建新项目的最大权限项