# 迭代概览：V5 PR-3 后 v4 交付包重建

> 日期：2026-09-03 ｜ 触发：V5 Phase 1 PR-3（督办简报/周报）改完主源码，按「改完主源码必做」重建交付包。

## 背景

PR-3 在 `src/` 新增了 Jinja 模板（`templates/ai/brief.html`、`brief_result.html`）并改动了 `settings.html`。
PyInstaller 把 `templates/`、`static/` 装进 `dist/督办系统/_internal/`，所以**只重建交付包不重打包 = 离线程序仍是旧样式**。必须先重打包 exe，再重建交付包。

## 执行步骤

1. 旧产物归档到 `_archive/`（`_prev-dist-督办系统-pr3-29768b0`、`_prev-交付包-v4-pr3-29768b0.zip`），避开沙箱批量删除守卫。
2. `python -m PyInstaller 督办系统.spec --noconfirm`（沙箱关闭通道，后台 52s 完成）。
   - 校验：`dist/督办系统/督办系统.exe` 时间戳刷新；`_internal/templates/ai/brief.html`、`brief_result.html` 已随包。
3. `python scripts/build_delivery_package.py v4`（沙箱关闭通道）。
   - 从 v3 基线只读复制 01/02/04/05，03_开发代码 由当前 `src/` 实时装配，05_离线程序 exe+_internal 由新 `dist/督办系统` 覆盖同步。
   - 产出：`deliverables/督办系统-交付包-v4.zip` **274 条目 / 13.9 MB**。

## 复核结果（全过）

| 项 | 结果 |
|---|---|
| `testzip()` 完整性 | 通过（无损坏） |
| `secret.key` 入包 | 0（密钥不进交付包） |
| `.pyc` | 0 |
| `.db` | 仅内置演示库 `05_离线程序/督办系统/data/supervision.db`（过滤放行） |
| 新模板入离线程序 | `brief.html` / `brief_result.html` / `settings.html` 均在 |
| `.bat` 编码 | 32 个全部 GBK + CRLF ✅ |

## 新 exe 冒烟（遵守「每次重打包必须重新冒烟」）

- 备演示库 `dist/督办系统/data/supervision.db`（从归档旧 dist 拷入）→ 启动 exe → 监听 5000。
- 标准库 `urllib` + `ProxyHandler({})` 验证（用托管 python，本机代理不拦 localhost）：
  - `/login` 200 且含 csrf；admin 登录成功 → `/dashboard`。
  - `/ai/brief` 在 `AI_ENABLED=false` 时正确 302 跳 `/ai`（关闭守卫在打包程序中生效）。
  - `/ai` 控制台渲染出「生成简报 / 周报」入口。

## 提交与推送

- 交付包镜像（未压缩目录 `deliverables/督办系统-交付包-v4/03_开发代码` 等，仅 zip/exe/pyd/dll/05_离线程序 被 gitignore）随源码一并纳入版本管理（惯例见 `b1a08ce`）。
- 提交 `746ad58` → 经 `github-api-push-when-blocked` 技能 API 推送 `--align`，远端 `main` = `8d8766689`，工作树干净。
- 注：`git ls-remote`/`git push` 直连 github.com 被代理 502 挡住，走 api.github.com 通道是既定安全路径。

## 经验沉淀（已回写工作记忆）

- 交付包重建铁律：① 模板/静态进 `_internal` → 必重打包 exe；② 旧产物先 `mv` 归档再构建；③ zip 五项复核 + bat 编码检查；④ 新 exe 必冒烟。
- 本轮回填的 4 个 PR-3 阻断 bug（MAIL_TYPE_AI_BRIEF 未定义 / ai_templates 漏导入 / label 作用域 / 收件人误用 email-gated）见 `2026-09-03.md`。
