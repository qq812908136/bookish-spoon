# 督办系统项目长期记忆（精简版）

## 技术栈与部署
- 后端 Python + Flask；数据库 SQLite 单文件；前端 Jinja2 服务端模板（无前端框架）。
- 部署：PyInstaller onedir 打包 `督办系统.exe` + `_internal/`，解压后双击 .bat 启动（仅 Windows），Flask 开发服务器监听 5000。

## 目录结构（2026-08-31 src 分层后，提交 519d9d5）
- 顶层：`src/`（应用源码：9 个 py + routes/ + templates/ + static/）、`tests/`（test_suite.py 121 项 + generate_test_report.py + test_data/）、`scripts/`（build_delivery_package.py）、`docs/`（全部文档，含 `docs/迭代记录/`、`docs/测试报告/`）、`data/`（库 + backup/）、`deliverables/`（v3 已发行 + v4 当前）、`_archive/`（归档，117MB 不入库）。
- **路径推导铁律**：`src/config.py` 用自身位置推导——`BASE_DIR` = src 的上一级 = 项目根（挂 `data/`）；`BUNDLE_DIR` = `src/`（挂 templates/static）。**config.py 一动，数据库就换位置。**
- 根目录只剩 5 个 bat（start/build/清除数据/灌入演示数据/开启局域网访问）+ `督办系统.spec` + `requirements.txt` + `README.md`。启动命令 `python src/app.py`。
- 完整说明见 `docs/项目目录结构说明.md`（唯一真相源，交付包 03_开发代码 从此复制）。

## 核心设计决策
- 2 角色：admin（管理员）+ owner（负责人）；统一任务池，权限按角色区分。
- 5 态状态机：待启动→进行中→已逾期→已闭环→已撤销；「已逾期」由系统每 5 分钟自动触发（非标签）；闭环/撤销为终态，管理员可重开。
- 3 层预警：即将到期（默认3天）/已逾期/长期待激活（默认7天），可配置；每日 09:00 扫一层、每5分钟扫逾期。
- 首次启动初始化向导建管理员（不预置默认账号）；负责人只读他人任务、仅改自己；消息永久保留。

## 协作偏好
- 苏格拉底式编号选项；SPEC 锁定前不动代码；增量 + 审批门控。
- 用户编程新手，需通俗解释；改动页面/业务时**必须同步改文档**（docs/ 与交付包 01/02）。
- 承接文件 `docs/改动待办清单.md`：发现→改→验证→回写「处理结果」列；只改 `src/` 下主源码，交付包副本定稿后统一同步。

## 术语规范（行动→任务，2026-08-30 收口）
- 统一用「任务」：任务总数/任务数/任务闭环矩阵。批量替换长词优先（矩阵→总数→数）。
- 保留不改动：`iteration-v2-diff-analysis.md:128`（对比语义）、历史记忆旧词、`warning_engine` 的「逾期>待激活>到期」（是预警类型优先级非状态名）。

## 文档组织（2026-08-31 收口，详见 `docs/README.md`）
- `docs/` 是文档**唯一真相源**；交付包 `01_需求文档/` `02_设计文档/` 是副本，**禁止手改**（下次同步会被覆盖）。入口索引 `docs/README.md`。
- **命名两套并存是刻意的**：英文短名（`architecture-design.md` / `iteration-v2-design.md` / `iteration-v2-diff-analysis.md`）被 7 处引用（`docs/改动待办清单.md:379/380/381/439`、`PRD-draft-v1.md:541/705`、`src/static/css/main.css:4`），改名会断链 → **保留不动**；中文长名为交付包正式名，**今后新增一律用中文长名**。
- **两份「架构」文档互补，不可合并**：`architecture-design.md`（76789，代码级手册：Schema/路由/状态机/预警/权限，改代码前查它） vs `督办系统-系统架构设计.md`（27251，架构决策：选型/分层/部署/线程模型/权衡，理解全貌看它）。
- 已确认的**真重复**（英文短名版已在 git 中，中文副本未纳入）：`督办系统-V2迭代设计.md` == `iteration-v2-design.md`；`督办系统-V2迭代差异分析.md` == `iteration-v2-diff-analysis.md`。
- 交付包设计文档已去掉易腐的「-最新」后缀（v4 起为 `督办系统-架构设计.md`；v3 已发行，保持原样）。
- **CHANGELOG.md 在仓库根**（不在 docs/）；只记用户可见变更，内部过程放 `docs/迭代记录/`。

## 配置与日志（2026-08-31 建立）
- **配置三级优先级**：系统环境变量 > `.env` 文件 > 代码默认值（`src/config.py` 的 `_env_str/_env_int/_env_bool`）。
- **铁律：新增 env 覆盖时必须保证「不配置 = 行为不变」**——打包成 exe 后 `.env` 通常不存在，任何默认值改动都会破坏已发行的离线程序。
- `.env` 读取位置是 **`BASE_DIR`**（由 config.py 位置推导：项目根 / 打包后 exe 同级），**不是 cwd**。调试时别在别的目录放 `.env` 然后以为没生效。
- **刻意不引入 python-dotenv**：新增依赖要重打包 exe，成本过高；内置 20 行极简解析已够用。
- 可覆盖项：`SECRET_KEY` / `HOST` / `PORT` / `DEBUG` / `LOG_LEVEL` / `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT`。
- **日志**：`src/app.py` 的 `setup_logging()` 写 `logs/supervision.log`（轮转 2MB×5，UTF-8）。目录不可写时静默降级为仅控制台；handler 用 `isinstance(..., RotatingFileHandler)` 判重 + `delay=True`，避免测试反复 `create_app()` 堆积句柄。
- **CI 必须用 `windows-latest`**：部署目标是 Windows，启动 bat 为 GBK、防火墙命令 Windows 专有，在 Linux 上跑会产生与目标环境无关的假失败。test job 只装 Flask+openpyxl（不装 pyinstaller）；package job 仅 push tag 触发。⚠️ 当前 `git remote` 为空，CI 需推送远端才生效。

## 交付包生成（改完主源码必做）
- 仓库：`deliverables/督办系统-交付包-vX/`；`.gitignore` 排除 `05_离线程序/`、`*.zip`、`*.exe/*.pyd/*.dll`、`dist/`、`data/*.db`、`__pycache__`、`_archive/`。提交只记录 `01/02/03/04` 的文档与源码副本，离线程序/zip 不入 git（含 36 个 .pyd 会撑大）。
- **生成命令**：`python scripts/build_delivery_package.py vN`（默认 v4）。脚本会自动：从 v3 只读复制 01/02/04/05 → 由当前源码实时装配 03_开发代码 → 用 `docs/测试报告/` 覆盖 04_测试 → 写 README → 打 zip。
- **安全闸门**：`REBUILDABLE = {'v4'..'v9','test'}`，v1/v2/v3 一律拒绝重建（防误删已发行包）。踩过的坑：key 必须与白名单元素同格式（都带 v 前缀），否则连 v4 都会被拒。
- 人工复核（脚本已覆盖大部分）：zip 条目数 + `testzip()` 无损坏 + bat 抽查 GBK/CRLF + 扫 `.db` 垃圾 + `git status`。
- **v3 已发行，只读不写**（mtime 01:18 / zip 01:47，git 干净）。**v4 为当前版本**：232 文件、zip 232 条目 13.4MB、测试 121/121；离线 exe 已用新 spec 重打包（6,206,682 字节，与 src 分层后源码同源），离线包自带 9/45 演示库，冒烟 6/6。
- **交付包生成的三条硬规则**：① 过滤「运行产物」不能一刀切——`05_离线程序/**/data/supervision.db` 是**刻意内置**的演示数据，必须放行（曾因 `.db` 一刀切把演示库滤掉，导致离线包启动进初始化向导）；② 重建前**必须先 `build.bat` 打包就位 `dist/督办系统/`**——脚本的 `sync_offline_exe()` 会自动替换 exe 与 `_internal`（保留 `data/` 与 4 个离线 bat），`dist` 缺失会打警告并退回 v3 旧 exe；③ `RENAME_MAP` 自动去掉「-最新」等易腐命名，只作用于新版本，v3 基线不在写入路径上。
- **`dist/` 已被归档清空**（档位3重构时移入 `_archive/dist/`）。若需重建且 `dist/` 为空，先从 `_archive/dist/督办系统` 用 `cp -a` 拷回，否则会永久丢失与 src 分层同源的 exe。

## bat/cmd 编码（GBK + CRLF 强制）
- cmd.exe 默认 GBK 解码，所有 .bat/.cmd 必须 GBK/ANSI + CRLF，不能 UTF-8（含 BOM）、不能 LF，否则中文乱码且被当命令执行。
- 正确做法：Python `text.encode('gbk')` 以二进制写、`\n`→`\r\n`；或从源头 `cp` 字节，不读文本再写（防双重编码损坏）。
- 校验：`data.decode('gbk')` 不抛异常 + `b'\r\n' in data` + LF-only 数=0。`.gitattributes` 配 `*.bat text eol=crlf` 作第二道防线，勿删。

## 双种子问题（已修复，2026-08-31）
- 旧：`app.py` 内嵌精简种子(5用户/12任务)被 `--seed-demo` 调用；完整扩充(9/45)在 `seed_demo_data.py:main()`，当初只直接灌源码库，exe 的 bat 永远只复现 5/12。
- 修复：`app.py --seed-demo` 改委托 `seed_demo_data.main()`；扩充数据同步进 v3 离线 `data/`；重建 exe；v2/v3 文档与 `灌入演示数据.bat` 提示改「9用户/45任务/67消息」。
- 现 `督办系统.exe --seed-demo` 复现 9/45，v3 离线 data 即 45 任务。

## Git（2026-08-30 初始化）
- 默认分支 `main`；入库：源码(`src/`)/tests/scripts/docs/交付包文档源码/`.workbuddy/memory/`；不入库：`_archive/`（build、dist、发行版 zip、env_info、v1-v2 交付包目录，约 117MB）、05_离线程序、zip、db。v1/v2 交付包已随归档从版本库移除（源码改动 184 文件的提交 519d9d5）。
- **分支铁律：禁止 `/`**，本机 PortableGit 会静默失败；一律连字符（feature-x）。诊断假成功：`.git/logs/refs/heads/` 有而 `.git/refs/heads/` 无 = 已回滚。
- Worktree 实测可用（连字符分支）。提交身份仓库级（user.name=王蓟冬）。

## 关键经验教训
- **HTTP header 中文**：必须 RFC 5987 双兜底 `filename="ascii"; filename*=UTF-8''%XX`；Werkzeug dev 用 latin-1 strict，中文 Unicode 抛错；测试须真实 HTTP client（urllib/requests）才能复现。
- **测试套件**：**145 项**（原 121 + DEF-005 新增 24），跑完约 7 分钟（430s）；用 `run_in_background` 跑全量。日常改跑子集：`python -m unittest tests.test_suite.TestStateMachine`（26 项约 63s）。测试用独立库 `tests/test_data/test_supervision.db`，不污染演示库。全量命令：`python -m unittest tests.test_suite`（或 `python tests/test_suite.py`）。
- **⚠️ 哨兵值 0 的双重语义（2026-08-31 踩坑，通用）**：用 `0` 表示「尚未发生/未设置」时，它同时也是「时间戳已过期」的合法取值。DEF-005 限流里 `locked_until=0`（从未锁定）被两个函数各自误判为「已过期」→ 一个删掉正在累积的计数、一个每次丢弃重来，结果**限流完全不生效**，但日志和提示看起来一切正常（「还可尝试 2 次」那个 2 永远是 2）。修复：`0 < x <= now` 显式排除未设置。**教训**：哨兵值必须在每个读取点显式排除，不能指望比较运算符顺带处理；且这类 bug 只有**连续调用 3 次以上**观察状态是否变化才能发现，单点验证永远测不出来。
- **ProxyFix / WSGI 中间件要用 `test_client` 测**：`test_request_context` 会**绕过 wsgi_app**，中间件不生效。可临时注册一个 `/_probe_ip` 路由返回 `request.remote_addr` 来观察。
- **依赖 request context 的工具函数要兜底**：`auth._client_ip()` 等函数脱离请求调用会抛 `RuntimeError`，已加 try/except 返回占位值 —— 命令行脚本和单测直接调用不会崩。
- **测试报告生成**：`python tests/generate_test_report.py` → 默认输出到 `docs/测试报告/`（MD + HTML + 用例清单 + test_summary.json）。脚本**目录自适应**：在交付包 `04_测试/` 下运行时会自动把根定位到 `03_开发代码/` 并输出到本目录。
- **新增 Python 依赖（如 openpyxl）→ 三处都动 + 重打包**：requirements.txt + `督办系统.spec` 的 hiddenimports + 装进托管解释器（`build.bat` 已改为直接调 spec，不再重复写 `--hidden-import`）；打包命令 `python -m PyInstaller 督办系统.spec --noconfirm`（沙箱删文件需 dangerouslyDisableSandbox）；重打包后替换离线目录的 `_internal/`，再重生成交付包。
- **改完任何文件都要重启**：reloader 关闭，改 .py/.html 必须重启进程；改 .css/.js 重启后 Ctrl+F5 强刷。临时 DEBUG=True 仅本地，打包前改回 False。
- **响应式断点**：内容区 max-width 1280px；≥1200 双栏，<1200 矩阵独占，≤1024 三列，≤768 手机端。WorkBuddy 内置预览窄会触发手机样式，建议独立浏览器最大化验证。
- **SQLite 静默建库**：`connect` 不存在文件会建空库，排查后必复核目录，正式库是 `data/supervision.db`。
- **V2 抽屉契约**：行点击拦截排除列表绝不含 `form`；抽屉选择器见 main.js；闭环矩阵负责人名用 `<span data-drawer>` 非 `<a>`。
- **端口冲突**：exe 与开发服务都占 5000，测 exe 先停 Flask；`netstat -ano|grep :5000` + `taskkill /F /PID` 强制清理残留。
- **冒烟脚本必须禁用代理**：本环境有 HTTP 代理，urllib 直接请求 `127.0.0.1:5000` 会返回 **502 / WinError 10054 ConnectionReset**。解法：`urllib.request.build_opener(..., urllib.request.ProxyHandler({}))`。
- **exe/服务要常驻必须用 `run_in_background: true`**：用 `cmd &` 启动的进程会随该次 Bash 调用结束被回收，后续请求报 WinError 10061 ConnectionRefused。
- **导出路由是 `/tasks/export`（xlsx）**，不是 `/export/tasks?format=csv`——写冒烟脚本前先 `grep -n "route" src/routes/*.py` 确认，别凭印象猜。

## 版本状态
- **V2 迭代 → V3 交付整条开发线已归档（2026-08-31）**：tag `v3.0`，最终提交 `3bc72b2`；分支仅 main、工作区干净；待办 001–059 全清（54 已修复/3 已回退/1 已放弃）；测试 121/121；v3 交付包五段式齐全 + zip 已发行。
- **结构性重构已落地（提交 `519d9d5`，2026-08-31 21:15）**：src 分层 + 产物隔离 + 补齐 2 个 bat；业务代码零改动，测试 121/121；v4 交付包（231 文件 / zip 13.4MB）接棒成为当前版本，v3 保持只读。概览见 `docs/迭代记录/overview-档位3重构.md`。
- **exe 重打包已完成（提交 `255bb49`）**：新 spec 打包 51 秒；`--seed-demo` 复现 9/45/67；HTTP 冒烟 6/6；v4 离线程序自带演示库。构建产物已归档 `_archive/`。
- 遗留未办：~~架构文档三份重复~~（已澄清：仅 2 份真重复，已删；`architecture-design.md` 与 `督办系统-系统架构设计.md` 互补保留）；~~CHANGELOG / logging / `.env.example` / CI~~（2026-08-31 已补齐，提交 `1090d13` + `5f03f7e`）。
- 缺陷 17 条：DEF-015/016/017 已修复；**DEF-001 ✅ / DEF-004 代码侧 ✅ / DEF-005 ✅**（均 2026-08-31）。
- **独立的「上线前安全整改」任务**（见 `docs/上线前待办.md`，不随开发任务关闭）：
  ~~DEF-001~~ ✅、~~DEF-004 代码侧~~ ✅、~~DEF-005 登录限流/弱口令~~ ✅。
  **仅剩 DEF-002（全站无 CSRF，P1）**；另 DEF-004 **部署侧**（waitress + HTTPS + 备份）待上线时在目标机器按 `docs/生产部署指南.md` 执行。

## 会话签名密钥（DEF-001 已修复，2026-08-31）
- 密钥**不再写死在源码**：首次启动 `secrets.token_hex(32)` 生成 → 落盘 `data/secret.key`（chmod 600）→ 之后复用。取值顺序：环境变量 > `.env` > 落盘文件 > 新生成。
- **防分发是修复的一半**：`data/secret.key` 必须同时进 `.gitignore` **和** 构建脚本 `IGNORE_NAMES`，否则密钥随交付包分发给所有部署方 = 等同没修。每次改这块都要复查 v4 zip 内 `secret.key` 计数为 0。
- 只读目录时静默降级为内存随机值（重启需重新登录），不阻塞启动。
- 副作用：升级后旧会话全部失效，用户需重新登录一次。

## 监听与部署（DEF-004 代码侧已修复，2026-08-31）
- `HOST` 默认 `127.0.0.1`（原 `0.0.0.0`）。局域网开放是**显式动作**：`局域网启动.bat`（设 `HOST=0.0.0.0`）。
  `开启局域网访问.bat` 只管防火墙，两者必须配合 —— 少了前者端口开再大也没人连得进。
- 会话 Cookie：`HttpOnly` + `SameSite=Lax`（挡跨站表单型 CSRF，是 DEF-002 的部分缓解）；`SECURE` 默认 False，启用 HTTPS 后才设 True。
- `SERVER=waitress` 可切生产级 WSGI；waitress 是**可选依赖**，未装自动回退 Flask 并告警，绝不因缺包起不来。
- 部署形态与步骤的唯一真相源：`docs/生产部署指南.md`。

## 登录安全（DEF-005 已修复，2026-08-31，提交 `51d9c66`）
- **限流维度是「客户端 IP + 用户名」组合键**，两者缺一不可：只看 IP 会让共用出口 IP 的同事互相误伤，只看用户名挡不住遍历账号。
- 默认 5 次失败锁 15 分钟（`LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES`）。**锁定期内即使密码正确也拒绝** —— 否则攻击者穿插一次正确密码就清零，限流形同虚设。
- 计数存**内存**不存库：短时效状态重启清零不影响防护（攻击者无法触发重启解锁），且避免「一次请求换一次磁盘 I/O」给爆破者放大杠杆，还免去数据库迁移。已知限制：多进程部署时各进程独立计数（本项目单进程，不触发）。
- **弱口令校验不追溯**：历史 6 位密码账号仍可登录，只在改密码时要求达标。规则：长度≥8、禁纯数字、禁纯字母、约 50 个常见弱口令黑名单、不得与用户名相同。刻意不要求「大小写+符号」强组合。
- 覆盖 4 个设置入口：初始化向导 / 新建用户 / 重置密码 / 个人改密码。重置密码要**先查 target_user 再校验**（「密码 != 用户名」需要用户名）。
- **反向代理必须开 `BEHIND_PROXY=True`**，否则所有请求都记成代理 IP → 一人被锁、全员陪绑。默认关闭（开启 = 信任 X-Forwarded-*，没代理时人人可伪造绕过限流），`TRUSTED_HOPS` 要**等于**实际层数，填大会留伪造空间。
- 遗留：演示库 `admin/admin123`、`owner/123456` 本身仍是弱口令（限流挡爆破不挡已知弱口令），上线前须改掉或重置后重建。

## bat 脚本（2026-08-31 统一改造）
- 5 个启动 bat 改为**运行方式自适应**：目录里有 `督办系统.exe` 就跑 exe，没有就用 Python 跑 `src\app.py`。
  **仓库根 = 唯一真相源**，构建时 `sync_offline_bats()` 同步进 `05_离线程序/`。
- 历史坑（已修）：离线 bat 每次构建都从 v3 基线重拷，**根目录改了根本不生效**；交付包 `04_测试/缺陷清单` 同理永远是 v3 旧版。
  现在这两个都会同步。改完记得确认包内文件确已更新，别只看构建日志。
- 新增 `scripts/check_bat_encoding.py`（GBK+CRLF 守卫）。**改任何 bat 后都要跑一次**，Edit/Write 工具默认写 UTF-8 会直接踩坑。

## 远端仓库（用户决定：暂不推送，2026-08-31）
- **决定：CI 当模板留着，不建远端**。已在 `.github/workflows/ci.yml` 头部 + 根 `README.md` 新增「持续集成（当前未启用）」小节写明状态与激活步骤（提交 `46e8d93`），避免后续误以为在生效。
- 原因：GitHub 连接器是受限 OAuth 集成，**不能建仓**（403 Resource not accessible by integration）；本机无 `gh` CLI、无 `~/.ssh`、无 token 环境变量。
- 将来要激活只有两步：`git remote add origin <地址>`（**建议私有**——仓库含交付包文档与源码副本）+ `git push -u origin main`。若届时只有连接器可用，备选是让用户先建空仓再走 `mcp__github__push_files`（缺点：220 文件分批、丢提交历史）。
