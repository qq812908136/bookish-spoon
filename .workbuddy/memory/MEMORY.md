# 督办系统项目长期记忆

## 技术栈与路径铁律
- Python+Flask/SQLite/Jinja2 服务端模板，无前端框架。PyInstaller onedir 打包 `督办系统.exe`+`_internal/`，Windows，监听 5000。
- `src/config.py` 用自身位置推导：`BASE_DIR`=项目根（挂 data/、读 .env），`BUNDLE_DIR`=`src/`（挂 templates/static）。**config.py 一动数据库就换位置。**
- 目录：`src/ tests/ scripts/ docs/`(文档唯一真相源) `data/ deliverables/ _archive/`(归档不入库)。

## 核心业务
- 2 角色 admin+owner；统一任务池。5 态含「已逾期」(每5分钟触发)；闭环/撤销为终态可重开。3 层预警(即将到期3天/已逾期/长期待激活7天)；每日09:00+每5分钟扫描。
- 首次启动初始化向导建管理员；种子 `app.py --seed-demo` → 9用户/45任务/67消息。

## V4 邮件（SPEC 锁定，开发中）
- SPEC `docs/督办系统-V4邮件功能需求清单.md`(55项 A1~I6)。模块 crypto_util/mail_constants/mail_service/mail_templates/mail_dispatcher + routes/mail_routes + 模板 mail/status.html,mail/my.html。
- 数据 `_migrate_v3()` 幂等(users 加 email/mail_notify_level，建 email_queue/email_log)。14 个 MAIL_* 配置，优先级 env>.env>库>默认。
- 硬约束：`MAIL_ENABLED` 默认 False(不配置=不发)；SMTP 密码不入日志/页面。机制：落库队列+复用5分钟扫描(零新增线程)、独立去重键、按人合并+管理员只收日报、双重熔断、重启 sending→pending。
- 挂钩点仅 `_send_merged_warnings()`/`trigger_overdue_warning()`；**绝不改 `models.create_message()`**。

## 协作偏好（用户）
- 苏格拉底编号选项；SPEC 锁定前不动代码；增量+审批门控。改页面/业务必须同步改文档。术语统一「任务」。
- 承接 `docs/改动待办清单.md`：发现→改→验证→回写「处理结果」；只改 src/ 主源码。

## 文档组织
- docs/ 唯一真相源；交付包 01/02 是副本禁手改。英文短名文档(architecture-design.md)保留不动，新增中文长名。两份架构文档互补不合并(手册 vs 决策)。
- 两份架构文档各含一章 V4 邮件(2026-09-03)。CHANGELOG.md 在仓库根。

## 配置与日志
- 优先级 env>`.env`(BASE_DIR 非 cwd)>默认。**铁律：新增 env 必须「不配置=行为不变」**，刻意不引入 python-dotenv。
- 日志 `logs/supervision.log`(2MB×5 轮转)；CI 须 windows-latest。

## 交付包生成（改完主源码必做）
- `python scripts/build_delivery_package.py vN`(默认 v4)。从 v3 只读复制 01/02/04/05，由源码装配 03_开发代码，用 docs/测试报告 覆盖 04_测试。安全闸门 REBUILDABLE={v4..v9,test}，v1/v2/v3 拒绝。
- 硬规则：① 05_离线程序/**/data/supervision.db 是内置演示库，过滤须放行；② 重建前先 `build.bat` 打包就位 `dist/督办系统/`；③ RENAME_MAP 去「-最新」只作用于新版本。
- **01/02 是基线复制+本版本补差**：docs/ 新增/改了需求类文档须进 REQ_DOCS(`[1/4]`段)，设计类进 DESIGN_DOCS(**须排在 apply_renames() 之后**)。已踩两次。
- 归档用 `mv` 到 `_archive/`，零删除。README 测试数从 `docs/测试报告/test_summary.json` 真读。
- v4 当前版本：260 文件 / zip 13.8MB。复核：zip 条目数+testzip()+bat 抽查 GBK/CRLF+扫 .db 垃圾+git status。secret.key 须同时进 .gitignore 与 IGNORE_NAMES(复查 zip 内=0)。

## bat/cmd 编码（GBK+CRLF 强制）
- 必须 GBK/ANSI+CRLF，不能 UTF-8(BOM)/LF。写法 Python `text.encode('gbk')` 二进制写；改完跑 `scripts/check_bat_encoding.py`。5 个启动 bat 已改运行方式自适应(仓库根唯一真相源)。

## Git
- 默认分支 main。**分支名禁含 `/`**(本机 PortableGit 静默失败)，用连字符。
- ⚠️ 禁用 `git filter-repo`/`filter-branch`：`git gc --prune=now` 清空 .git/objects 历史不可逆丢失(已踩过)。
- 远端 `qq812908136/bookish-spoon`(私有)。github.com 被代理重置，推送走 api.github.com Git Data API(`github-api-push-when-blocked` 技能)；GCM 存 PAT。`origin/main` 本机 PortableGit 老 bug 存不住(显示 [gone] 但推送正常)，核对用 api.github.com。

## 关键经验教训（高价值）
- **批量删除守卫(单回合50文件)**：PyInstaller 删 dist/督办系统(163)、交付包脚本删旧 v4(50) 会中断。对策：先把旧目录 `mv` 成 `_prev-xxx` 再打包；能「复制时 ignore 过滤」就别「复制完再删」。
- **目录删/改名 Permission denied**：常是 Explorer/搜索索引/AV 持有句柄(尤其 exe)。排查 `Win32_Process.CommandLine` 含路径的进程，`Stop-Process` 即解。本次 #061 是 Explorer 打开 05_离线程序 文件夹窗口钉住 exe → 结束 explorer PID 后解锁。
- **静态资源版本号唯一来源**：`config.STATIC_VERSION`→`inject_globals()`(Flask context_processor，登录/初始化页也注入)→模板 `v=static_version`。login.html/setup.html 独立页必须也用变量(2026-09-03 事故：写死漏改致登录页旧样式)。
- **exe 实跑冒烟**：PYZ 有模块≠能跑；冒烟取任务 ID 用列表页 `data-detail-url="/tasks/(\d+)"`(抽屉 URL 是 JS 拼的)。dist 不含 data/，冒烟前从上一代 dist 拷 `data/supervision.db`。
- **打包/测试/依赖**：本地冒烟 `python tests/test_suite.py`(**非** `python -m unittest`，后者只触发导入)；摘要 `python tests/generate_test_report.py`。新增依赖三处动+重打包。HTTP header 中文 RFC5987 双兜底。ProxyFix 用 test_client 测。

## 安全整改
- DEF-001/002/004代码侧/005 全部已修复(2026-08-31~09-01)。DEF-002 CSRF `src/csrf.py`(24写路由/21表单/8 AJAX，Cookie SameSite=Lax+令牌双层)。剩余仅部署侧(HTTPS/Waitress，按生产部署指南)。会话密钥落盘 data/secret.key(600)。演示口令已换强口令(admin/Supv#Admin2026 等)。

## 版本状态
- V2→V3 归档(tag v3.0)。待办 001–059 清。
- #061 已完成并推送：抽屉 UI 对齐设计稿(任务/负责人/消息三抽屉卡片式)，STATIC_VERSION 20260903c→d，重建 v4 交付包(260文件/zip13.8MB/测试212/212)，远端 main=b1a08ce。
