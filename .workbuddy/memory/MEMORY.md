# 督办系统项目长期记忆

## 技术栈与路径铁律
- Python + Flask / SQLite 单文件 / Jinja2 服务端模板（无前端框架）。PyInstaller onedir 打包 `督办系统.exe` + `_internal/`，Windows 专属，监听 5000。启动 `python src/app.py`。
- **`src/config.py` 用自身位置推导路径**：`BASE_DIR`=src 上一级=项目根（挂 `data/`、读 `.env`）；`BUNDLE_DIR`=`src/`（挂 templates/static）。**config.py 一动，数据库就换位置。**
- 目录：`src/`(源码) `tests/` `scripts/` `docs/`(文档唯一真相源) `data/` `deliverables/` `_archive/`(归档不入库)。详见 `docs/项目目录结构说明.md`。

## 核心业务规则
- 2 角色 admin + owner；统一任务池。负责人只读他人任务、仅改自己；消息永久保留。
- 5 态：待启动→进行中→已逾期→已闭环→已撤销；「已逾期」每 5 分钟自动触发；闭环/撤销为终态，管理员可重开。
- 3 层预警：即将到期(3天)/已逾期/长期待激活(7天)，可配；每日 09:00 + 每 5 分钟各扫一次。
- 首次启动初始化向导建管理员（不预置账号）。种子 `app.py --seed-demo` → 9 用户/45 任务/67 消息。

## V4 迭代：发送邮件（SPEC 已锁定，开发中）
- **SPEC：`docs/督办系统-V4邮件功能需求清单.md`**（含 55 项决策溯源 A1~I6）；概览 `docs/迭代记录/overview-V4邮件需求收口.md`。
- 新增模块：`crypto_util.py`(PBKDF2+shake256 XOR 加密，零新依赖) `mail_constants.py`(常量，避免循环依赖) `mail_service.py` `mail_templates.py` `mail_dispatcher.py` `routes/mail_routes.py` + 模板 `mail/status.html` `mail/my.html`。
- 数据：`_migrate_v3()` 幂等迁移（`users` 加 `email`/`mail_notify_level`，建 `email_queue`/`email_log`）。14 个 `MAIL_*` 配置，优先级 env > `.env` > 数据库(设置页) > config 默认值。
- **两条硬约束**：`MAIL_ENABLED` 默认 `False`（铁律「不配置=行为不变」，保护已发行 exe）；**SMTP 密码任何情况不入日志、不入页面**，日志只记元数据不记正文。
- 关键机制：落库队列 + 复用现有 5 分钟扫描（零新增线程）；邮件**独立去重键**；按人合并 + 管理员只收日报（500封/天→~30封/天）；**双重熔断**（认证失败立即熔断需人工恢复 + 连续失败通用熔断自动试探）；重启时 sending→pending（宁可重复不可丢失）。
- **挂钩点**：预警仅两出口 `_send_merged_warnings()` / `trigger_overdue_warning()`；**绝不改 `models.create_message()`**。
- 进度：任务 1-6（配置加密层→数据层→服务模板→调度器→业务挂钩→界面路由）已完成；剩 7（配置指南+CHANGELOG+.env.example）、8（冒烟并入正式套件）。

## 协作偏好（用户）
- 苏格拉底式编号选项；**SPEC 锁定前不动代码**；增量 + 审批门控。
- 需求访谈按「改动成本从高到低」排主题（先数据模型/选型/状态机耦合，后措辞细节）。
- 用户编程新手需通俗解释；**改页面/业务必须同步改文档**（docs/ 与交付包 01/02）。
- 承接文件 `docs/改动待办清单.md`：发现→改→验证→回写「处理结果」列；只改 `src/` 主源码，交付包副本定稿后统一同步。
- 术语统一用「任务」；`warning_engine` 的「逾期>待激活>到期」是预警优先级非状态名，不改。

## 文档组织
- `docs/` 唯一真相源；交付包 `01_需求文档/`、`02_设计文档/` 是副本**禁止手改**。入口 `docs/README.md`。
- 英文短名文档（`architecture-design.md` 等）被多处引用**保留不动**；新增一律中文长名。
- 两份「架构」互补不可合并：`architecture-design.md`（代码级手册，改代码前查它）vs `督办系统-系统架构设计.md`（架构决策，理解全貌看它）。
- `CHANGELOG.md` 在**仓库根**；只记用户可见变更，内部过程放 `docs/迭代记录/`。

## 配置与日志
- 优先级：系统环境变量 > `.env`(位于 BASE_DIR**非 cwd**) > 代码默认值（`src/config.py` `_env_str/_env_int/_env_bool`）。
- **铁律：新增 env 覆盖必须保证「不配置 = 行为不变」**——exe 环境通常无 `.env`，改默认值会破坏已发行离线程序。刻意不引入 python-dotenv（免重打包）。
- 可覆盖：`SECRET_KEY` `HOST` `PORT` `DEBUG` `LOG_LEVEL` `LOG_MAX_BYTES` `LOG_BACKUP_COUNT` + 全部 `MAIL_*`。
- 日志 `logs/supervision.log`（轮转 2MB×5）；`RotatingFileHandler` 判重 + `delay=True` 防测试堆积句柄；目录不可写静默降级控制台。
- CI 必须 `windows-latest`（bat 为 GBK、防火墙命令 Windows 专有）。

## 交付包生成（改完主源码必做）
- `python scripts/build_delivery_package.py vN`（默认 v4）。从 v3 只读复制 01/02/04/05 → 由当前源码实时装配 03_开发代码 → 用 `docs/测试报告/` 覆盖 04_测试 → 写 README → 打 zip。
- 安全闸门 `REBUILDABLE={'v4'..'v9','test'}`，v1/v2/v3 拒绝重建。key 须与白名单同格式。
- **三条硬规则**：① `05_离线程序/**/data/supervision.db` 是刻意内置的演示数据，过滤规则必须放行；② 重建前**必须先 `build.bat` 打包就位 `dist/督办系统/`**，否则退回 v3 旧 exe；③ `RENAME_MAP` 去「-最新」后缀，只作用于新版本。`dist/` 若为空先从 `_archive/dist/督办系统` `cp -a` 拷回。
- v3 已发行只读；**v4 当前版本**：259 文件 / zip 259 条目 13.8MB。复核：zip 条目数 + `testzip()` + bat 抽查 GBK/CRLF + 扫 `.db` 垃圾 + `git status`。
- **归档用 `mv` 到 `_archive/`，不要用删除**：旧交付包目录 / 旧 dist / 旧 zip 一律改名为 `_prev-xxx` 再 `mv` 进 `_archive/`，零删除操作。
- 交付包 README 的测试数**从 `docs/测试报告/test_summary.json` 真读**，不写死（写死的数字每加用例就腐一次，而 README 是最容易忘同步的地方）。
- `04_测试` 从 v3 基线整段复制会**每重建一次多留一代带日期的旧报告**；`make_ignore(skip_stale_reports=True)` 在复制时过滤非当日报告（比复制完再删少一次批量删除）。
- **secret.key 必须同时进 `.gitignore` 和构建脚本 `IGNORE_NAMES`**，每次复查 v4 zip 内计数为 0。

## bat/cmd 编码（GBK + CRLF 强制）
- cmd.exe 默认 GBK：必须 GBK/ANSI + CRLF，不能 UTF-8（含 BOM）、不能 LF。Edit/Write 默认写 UTF-8 会踩坑。
- 写法：Python `text.encode('gbk')` 二进制写、`\n`→`\r\n`；或从源头 `cp` 字节。改完跑 `scripts/check_bat_encoding.py`。`.gitattributes` 的 `*.bat text eol=crlf` 是第二道防线。
- 5 个启动 bat 已改为**运行方式自适应**（有 exe 跑 exe，否则 `src\app.py`），仓库根唯一真相源，构建时同步进 `05_离线程序/`。

## Git
- 默认分支 `main`。**分支名禁含 `/`**（本机 PortableGit 静默失败），一律连字符。诊断假成功：`.git/logs/refs/heads/` 有而 `.git/refs/heads/` 无 = 已回滚。
- ⚠️ **本沙箱禁用 `git filter-repo`/`filter-branch`**：末尾 `git gc --prune=now` 会清空 `.git/objects`，历史不可逆丢失（已踩过，原 183 提交全失）。
- 远端 `qq812908136/bookish-spoon`（私有）。TLS 推送用 `http.sslVerify=false`（仅本仓库）。token 经 `url.https://<token>@github.com/.insteadOf=` 注入，未落盘。

## 关键经验教训
- **哨兵值 0 的双重语义（通用坑）**：`0` 既表「未设置」又是「时间戳已过期」的合法取值，必须在**每个读取点**显式排除（如 `0 < x <= now`）。这类 bug 只有连续调用 3 次以上观察状态变化才能发现。
- **复选框未勾选 = 键不出现**：服务端必须用 `'key' in form` 判断并显式补 0，不能用 `form.get(key)` 判值。写测试模拟未勾选要把键从 dict 里 `del` 掉，传空字符串测不出来。
- **⚠️ 沙箱有批量删除守卫（单回合 50 个）**：PyInstaller 重打包会删 `dist/督办系统`（163 文件）、交付包脚本会删旧 v4 目录（50 文件），都会触发中断。**对策：① 先把旧目录 `mv` 成 `_prev-xxx` 再打包；② 能把「复制完再删」改成「复制时用 `ignore` 过滤」就改**。
- **静态资源版本号只能有一个来源**：`config.STATIC_VERSION` → `app.py` 的 `inject_globals()` 注入 → 模板写 `v=static_version`。**`login.html` / `setup.html` 不继承 `base.html` 是独立页面**，版本号写死在各自模板里必然漏改（2026-09-03 真实事故：改了 CSS 但登录页仍加载旧样式，只能靠实跑 exe 冒烟才发现）。已有 `TestStaticAssetVersion` 2 项测试守住。
- `PYZ` 里有模块 ≠ 运行时能跑：打包后必须**实跑 exe 冒烟**（临时脚本 `_smoke_exe.py` 21 项）。冒烟取任务 ID 用列表页的 `data-detail-url="/tasks/(\d+)"`——抽屉 URL `/tasks/<id>/drawer` 是 JS 拼的，页面源码里搜不到。
- **本机有 HTTP 代理会拦 localhost**：请求 `127.0.0.1:5000` 返回 **502 / WinError 10054**。冒烟必须 `urllib.request.ProxyHandler({})`（requests 用 `proxies={'http':None,'https':None}`）。
- **常驻进程必须用 Bash 的 `run_in_background: true`**：`cmd &` 起的进程随调用结束被回收 → WinError 10061。
- **杀进程用 PowerShell `Stop-Process -Id <pid> -Force`**（Git Bash 里 `taskkill /F` 和 `//F` 都失败）；禁止从 Bash 调 PowerShell 宿主（安全策略拦截整条命令）。Git Bash 的 `/tmp` 对托管 Python 不可见，临时脚本放项目目录。
- 测试：用 `run_in_background`（全量约 8 分钟）；子集 `python -m unittest tests.test_suite.TestStateMachine`。独立库 `tests/test_data/test_supervision.db`。报告 `python tests/generate_test_report.py` → `docs/测试报告/`（目录自适应）。
- **跑测试摘要要 `2>&1 >/dev/null | tail -N`**，直接 `2>&1 | tail` 会被 `[migrate_v2/v3]` 的 stdout 淹没 unittest 摘要。
- **新增 Python 依赖 → 三处都动 + 重打包**：requirements.txt + `督办系统.spec` hiddenimports + 装进托管解释器。打包 `python -m PyInstaller 督办系统.spec --noconfirm`（沙箱删文件需 dangerouslyDisableSandbox）。
- **改完代码必须重启**（reloader 关闭）；改 css/js 后 Ctrl+F5 强刷。
- HTTP header 中文必须 RFC 5987 双兜底 `filename="ascii"; filename*=UTF-8''%XX`；测试须真实 HTTP client 才复现。
- ProxyFix/WSGI 中间件要用 `test_client` 测，`test_request_context` 会绕过 wsgi_app。
- 依赖 request context 的函数（如 `auth._client_ip()`）要 try/except 兜底，否则命令行/单测调用崩。
- SQLite `connect` 静默建空库，排查后复核目录，正式库 `data/supervision.db`。
- 写冒烟脚本前先 `grep -n "route" src/routes/*.py` 确认路由，别凭印象猜（如导出是 `/tasks/export`）。
- V2 抽屉契约：行点击拦截排除列表绝不含 `form`；闭环矩阵负责人名用 `<span data-drawer>`。
- 端口 5000 冲突：测 exe 先停 Flask，`netstat -ano|grep :5000` 定位。
- 响应式断点：max-width 1280px；≥1200 双栏，<1200 矩阵独占，≤1024 三列，≤768 手机端。内置预览窄会触发手机样式，用独立浏览器最大化验证。

## 安全整改（上线前，见 `docs/上线前待办.md`）
- **DEF-002 全站无 CSRF（P1）仍待办**；DEF-004 部署侧（waitress + HTTPS + 备份）按 `docs/生产部署指南.md` 执行；DEF-001/004代码侧/005 已修。
- 会话密钥不写死源码，首次生成落盘 `data/secret.key`(600)，顺序 环境变量 > `.env` > 落盘文件 > 新生成。
- 监听 `HOST` 默认 `127.0.0.1`；开局域网需 `局域网启动.bat`(HOST=0.0.0.0) + `开启局域网访问.bat`(防火墙)**配合**。Cookie `HttpOnly`+`SameSite=Lax`；`SECURE` 仅 HTTPS 下 True。`SERVER=waitress` 可切生产 WSGI（缺包自动回退告警）。
- 登录限流（DEF-005）：维度 **IP+用户名组合键**；默认 5 次失败锁 15 分钟，**锁定期内密码正确也拒绝**；计数在内存不落库。反向代理须 `BEHIND_PROXY=True` 且 `TRUSTED_HOPS` 等于实际层数。
- 弱口令校验不追溯（仅新设/改密生效）：≥8 位、禁纯数字/纯字母、约 50 个黑名单、不得与用户名相同。演示库 `admin/admin123`、`owner/123456` 上线前须改。

## 版本状态
- V2→V3 开发线已归档（tag `v3.0`，提交 `3bc72b2`）；待办 001–059 全清。
- 关键提交：src 分层 `519d9d5`；exe 重打包 `255bb49`；CHANGELOG/logging/.env.example/CI `1090d13`+`5f03f7e`；登录安全 `51d9c66`。
- 远端现为重建后单笔提交 `7cb288c`，非原历史。
