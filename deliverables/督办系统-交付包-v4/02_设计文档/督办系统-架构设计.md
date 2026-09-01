# 督办系统 — 架构设计文档

> **文档状态**：已确认（2026-08-25），交付工程师实施；**V2 迭代增补**（2026-08-28）：数据模型 / 路由表 / 前端交互契约 / 数据库迁移已按 V2 交付代码同步
> **编写人**：架构师（高见远 / Bob）
> **日期**：2025-08-25
> **依据**：PRD-draft-v1.md（已确认）+ iteration-v2-design.md（V2 设计，Q1–Q9 已确认）
> **适用对象**：开发工程师、用户（编程新手）

---

## 一、系统架构概览

### 1.1 整体架构图（分层说明）

本系统采用经典的**单体分层架构**，所有逻辑在一个 Python 进程内运行，适合小团队 5-20 人规模。

```
┌─────────────────────────────────────────────────────────┐
│                    浏览器（用户端）                        │
│         HTML 页面 + CSS 样式 + 少量原生 JS 交互            │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP 请求/响应
┌────────────────────────▼────────────────────────────────┐
│  ① 表现层 (Presentation Layer)                            │
│     Jinja2 模板渲染 + static/ 静态资源                     │
│     base.html 基础骨架 + 子模板继承                        │
├──────────────────────────────────────────────────────────┤
│  ② 路由层 (Route Layer)                                   │
│     Flask Blueprint 按模块分组                             │
│     auth / task / progress / message / user / settings    │
│     装饰器统一校验登录与权限                                │
├──────────────────────────────────────────────────────────┤
│  ③ 业务逻辑层 (Service Layer)                             │
│     state_machine.py  状态转换校验                         │
│     warning_engine.py 三层预警引擎                         │
│     auth.py           密码哈希、会话管理、权限判断          │
├──────────────────────────────────────────────────────────┤
│  ④ 数据访问层 (Data Access Layer)                         │
│     models.py  表结构定义 + 增删改查封装函数               │
│     db.py      SQLite 连接管理（应用级连接池）             │
├──────────────────────────────────────────────────────────┤
│  ⑤ 存储层 (Storage Layer)                                 │
│     data/supervision.db  单文件 SQLite 数据库              │
├──────────────────────────────────────────────────────────┤
│  ⑥ 后台任务层 (Background Layer)                          │
│     scheduler.py  守护线程：逾期扫描(5min) + 预警扫描(每日) │
└─────────────────────────────────────────────────────────┘
```

**各层职责**：

| 层 | 职责 | 关键文件 |
|----|------|----------|
| ① 表现层 | 渲染 HTML，呈现界面，处理前端交互 | `templates/`、`static/` |
| ② 路由层 | 接收请求，参数校验，调用业务逻辑，返回响应 | `routes/*.py` |
| ③ 业务逻辑层 | 状态机校验、预警触发、权限判断等核心规则 | `state_machine.py`、`warning_engine.py`、`auth.py` |
| ④ 数据访问层 | 封装 SQL 操作，管理数据库连接 | `models.py`、`db.py` |
| ⑤ 存储层 | 持久化数据 | `data/supervision.db` |
| ⑥ 后台任务层 | 定时扫描逾期任务、定时生成预警消息 | `scheduler.py` |

### 1.2 技术选型说明

| 技术 | 选择 | 理由 |
|------|------|------|
| 编程语言 | **Python 3.10+** | 语法简洁，新手易读易维护；生态成熟 |
| Web 框架 | **Flask 3.x** | 轻量级，不强制架构模式，适合服务端模板渲染；学习曲线平缓 |
| 模板引擎 | **Jinja2**（Flask 内置） | 服务端渲染，无需前端构建工具链；支持模板继承，复用基础布局 |
| 数据库 | **SQLite 3** | 零配置，单文件存储，无需安装数据库服务；Python 标准库自带 `sqlite3` 模块 |
| 密码加密 | **werkzeug.security**（Flask 依赖） | `generate_password_hash` / `check_password_hash`，安全且无需额外依赖 |
| 后台调度 | **Python 原生 threading** | 守护线程 + `time.sleep` 循环，零额外依赖，避免引入 APScheduler 增加打包复杂度 |
| 打包工具 | **PyInstaller** | 将 Python + 依赖打包为单目录，配合 `.bat` 双击启动 |
| CSS 方案 | **原生 CSS + CSS 变量** | 不引入 Tailwind 等构建工具，降低新手理解成本；用 CSS 变量实现主题色统一管理 |
| JS 方案 | **原生 JavaScript（ES6）** | 仅用于侧滑面板、筛选交互、消息红点轮询等轻量交互；不引入前端框架 |

**为什么不用其他方案**：
- **不用 Vue/React**：用户是编程新手，前端框架需要构建工具链（webpack/vite），打包复杂度上升；服务端模板渲染对新手更直观，改完 Python 刷新即可看到效果。
- **不用 FastAPI**：FastAPI 偏 API 开发，本系统以服务端渲染为主，Flask 的 Jinja2 集成更自然。
- **不用 MySQL/PostgreSQL**：需要单独安装数据库服务，违背"零配置"目标；SQLite 单文件足够支撑 5-20 人。
- **不用 APScheduler**：增加一个依赖，且其线程模型在 PyInstaller 打包时偶有兼容问题；原生 threading 足够简单可靠。

### 1.3 运行流程

一次典型的用户请求（查看任务列表）完整链路：

```
用户浏览器
  │  GET /tasks?status=in_progress
  ▼
Flask 路由层 (routes/task_routes.py)
  │  @login_required 装饰器校验 session
  │  @role 装饰器（如需）校验角色权限
  ▼
视图函数 task_list()
  │  解析查询参数（status、priority、assignee、keyword、sort）
  │  调用 models.get_tasks(filters)
  ▼
数据访问层 (models.py)
  │  构造 SQL 查询，带 WHERE 条件和 ORDER BY
  │  db.execute(sql, params) → 返回 Row 列表
  ▼
SQLite (data/supervision.db)
  │  执行查询，返回结果集
  ▼
视图函数 task_list()
  │  组装模板上下文 {tasks, filters, current_user, unread_count}
  │  return render_template('tasks/list.html', **context)
  ▼
Jinja2 模板 (templates/tasks/list.html)
  │  继承 base.html，渲染任务表格、筛选器、分页
  │  模板内调用过滤器格式化日期、状态颜色
  ▼
Flask 响应
  │  组装完整 HTML，返回 200
  ▼
用户浏览器渲染页面
```

---

## 二、目录结构

```
task_supervision_system/
│
├── app.py                        # 【入口】Flask 应用工厂 + 启动主程序，注册蓝图、初始化数据库、启动后台线程
├── config.py                     # 【配置】所有配置项集中管理（数据库路径、密钥、扫描间隔、默认预警天数）
├── db.py                         # 【数据库】SQLite 连接管理，应用级线程安全连接，提供 query/execute 封装
├── models.py                     # 【模型】所有表的建表 SQL、CRUD 封装函数（get_tasks、create_task 等）
├── auth.py                       # 【认证】密码哈希、登录登出、session 管理、权限装饰器（@login_required/@admin_required）
├── state_machine.py              # 【状态机】状态枚举、转换矩阵、转换校验函数、自动逾期逻辑
├── warning_engine.py             # 【预警引擎】三层预警判定逻辑、消息生成、去重合并
├── scheduler.py                  # 【后台调度】守护线程，定时执行逾期扫描（5min）和预警扫描（每日）
│
├── routes/                       # 【路由模块】按功能拆分为多个 Flask Blueprint
│   ├── __init__.py               #   蓝图注册汇总（供 app.py 调用）
│   ├── auth_routes.py            #   认证路由：登录、登出、初始化向导
│   ├── task_routes.py            #   任务路由：列表、详情、创建、编辑、删除、状态变更
│   ├── progress_routes.py        #   进度路由：提交进度备注、查看进度记录
│   ├── message_routes.py         #   消息路由：消息列表、标记已读、全部已读
│   ├── user_routes.py            #   用户管理路由（P1）：新增、停用、重置密码
│   ├── settings_routes.py        #   设置路由：系统设置（预警天数）、个人设置
│   └── dashboard_routes.py       #   仪表盘路由（P1）：统计概览
│
├── templates/                    # 【Jinja2 模板】服务端渲染
│   ├── base.html                 #   基础骨架（V2 重写）：顶栏导航、铃铛、深色切换、Toast 容器、全局抽屉容器
│   ├── login.html                #   登录页（V2 重做：左右分栏 + 字段级校验 + 记住我 + 密码可见切换）
│   ├── setup.html                #   首次启动初始化向导（创建管理员）
│   ├── macros/
│   │   └── icons.html            #   Lucide SVG 图标宏（V2 新增，约 25 个图标，{{ icon('bell') }} 内联输出）
│   ├── tasks/
│   │   ├── list.html             #   任务列表页（表格 + 筛选 + 搜索 + 批量操作 + CSV 导出；点行开抽屉）
│   │   ├── detail.html           #   任务详情独立页（V2 保留：消息跳转 / JS 失效降级 / 浏览器直链）
│   │   ├── form.html             #   任务新建/编辑表单（V2：新增进度%/风险点/协同方 3 字段）
│   │   ├── _drawer.html          #   任务详情抽屉片段（V2 新增：详情/证据/阻塞 3 页签 + 行内编辑）
│   │   └── _owner_drawer.html    #   Owner 抽屉片段（V2 新增：负责人任务列表 + 推送提醒按钮）
│   ├── messages/
│   │   ├── send.html             #   管理员发消息页（C3 确认）
│   │   └── _drawer.html          #   消息抽屉片段（V2 新增，替代独立消息中心页）
│   ├── dashboard/
│   │   └── overview.html         #   仪表盘概览页（V2 重写：6 统计卡 + 焦点列表 + 闭环矩阵 + 时间范围）
│   ├── users/
│   │   └── manage.html           #   用户管理页（管理员）
│   ├── settings/
│   │   ├── profile.html          #   个人设置页
│   │   └── system.html           #   系统设置页（管理员，预警天数配置）
│   └── errors/
│       ├── 403.html              #   权限不足提示页
│       ├── 404.html              #   未找到提示页
│       └── 500.html              #   服务器错误提示页
│
├── static/                       # 【静态资源】Flask 直接服务
│   ├── css/
│   │   └── main.css              #   全局样式（V2 重写）：CSS 变量双套（浅色 + html.dark 深色），无外部依赖
│   └── js/
│       └── main.js               #   交互脚本（V2 重写）：抽屉管理器/行内编辑/Toast/深色切换/未读轮询
│   # 注：不内嵌字体文件，字体走系统字体栈；图标以 SVG 宏内联（离线打包零依赖）
│
├── data/                         # 【运行时数据】运行时自动创建
│   └── supervision.db            #   SQLite 数据库文件（.gitignore）
│
├── requirements.txt              # 【依赖】Python 第三方包清单
├── start.bat                     # 【启动脚本】Windows 双击启动（激活虚拟环境 + 运行 app.py + 自动打开浏览器）
├── build.bat                     # 【打包脚本】PyInstaller 打包为可分发目录
└── README.md                     # 【说明】安装与使用说明
```

**目录设计原则**：
- **扁平优先**：核心逻辑文件（`models.py`、`auth.py`、`state_machine.py` 等）放在根目录，新手一眼可见，无需深入子目录查找。
- **路由按模块拆分**：`routes/` 下每个文件对应一个功能模块，用 Flask Blueprint 组织，避免单文件过大。
- **模板按页面分组**：`templates/` 下用子目录对应功能模块，与路由模块一一映射。
- **数据与代码分离**：`data/` 目录存放运行时生成的数据库，打包时不包含（首次启动自动创建）。

---

## 三、数据库设计（SQLite Schema）

### 3.1 设计要点

- **外键约束**：SQLite 默认不启用外键，需在每次连接后执行 `PRAGMA foreign_keys = ON`。
- **级联策略**：进度日志和消息通过外键关联任务/用户，删除任务时级联删除其进度日志；消息设为 `SET NULL`（保留历史消息体）。
- **时间存储**：统一使用 ISO 8601 字符串（`TEXT` 类型，格式 `YYYY-MM-DD HH:MM:SS`），SQLite 无原生日期类型，字符串排序天然有序。
- **密码存储**：使用 werkzeug 的 PBKDF2 哈希，不存明文。

### 3.2 完整建表语句

```sql
-- ============================================================
-- 1. 用户表 (users)
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    user_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT    NOT NULL UNIQUE,             -- 登录账号，唯一
    display_name   TEXT    NOT NULL,                    -- 界面显示姓名
    password_hash  TEXT    NOT NULL,                    -- 密码哈希（werkzeug PBKDF2）
    role           TEXT    NOT NULL DEFAULT 'owner',    -- 角色：admin / owner
    is_active      INTEGER NOT NULL DEFAULT 1,          -- 是否启用：1=启用 0=停用
    created_at     TEXT    NOT NULL                     -- 创建时间 ISO 8601
);

-- ============================================================
-- 2. 任务表 (tasks)
-- ============================================================
CREATE TABLE IF NOT EXISTS tasks (
    task_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT    NOT NULL,                  -- 任务标题（限100字，应用层校验）
    description      TEXT,                              -- 工作要求/详细描述（长文本）
    created_by       INTEGER NOT NULL,                  -- 创建人 user_id
    assignee         INTEGER NOT NULL,                  -- 负责人 user_id
    status           TEXT    NOT NULL DEFAULT 'pending',-- 状态：pending/in_progress/overdue/closed/cancelled
    priority         TEXT    NOT NULL DEFAULT 'medium', -- 优先级：urgent/high/medium/low
    due_date         TEXT    NOT NULL,                  -- 截止日期 YYYY-MM-DD
    created_at       TEXT    NOT NULL,                  -- 创建时间
    updated_at       TEXT    NOT NULL,                  -- 更新时间
    closed_at        TEXT,                              -- 闭环时间（状态变 closed 时填写）
    completion_note  TEXT,                              -- 完成说明
    is_overdue       INTEGER NOT NULL DEFAULT 0,        -- 是否逾期标记：0/1（冗余字段，加速筛选）
    progress_percent INTEGER NOT NULL DEFAULT 0,        -- V2 新增：进度百分比 0-100
    risk_note        TEXT,                              -- V2 新增：风险点说明（上限500字，应用层校验）
    collaborators    TEXT,                              -- V2 新增：协同方（逗号分隔姓名，上限500字）
    FOREIGN KEY (created_by) REFERENCES users(user_id),
    FOREIGN KEY (assignee)    REFERENCES users(user_id)
);

-- ============================================================
-- 3. 进度更新记录表 (progress_logs)
-- ============================================================
CREATE TABLE IF NOT EXISTS progress_logs (
    log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id        INTEGER NOT NULL,                    -- 关联任务
    operator       INTEGER NOT NULL,                    -- 操作人 user_id
    operated_at    TEXT    NOT NULL,                    -- 操作时间
    status_from    TEXT,                                -- 变更前状态（创建任务时为 NULL）
    status_to      TEXT,                                -- 变更后状态
    progress_note  TEXT,                                -- 进度备注
    FOREIGN KEY (task_id)  REFERENCES tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY (operator) REFERENCES users(user_id)
);

-- ============================================================
-- 4. 站内消息表 (messages)
-- ============================================================
CREATE TABLE IF NOT EXISTS messages (
    message_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient    INTEGER NOT NULL,                     -- 接收人 user_id
    sender       INTEGER,                              -- 发送人 user_id（系统消息为 NULL）
    type         TEXT    NOT NULL,                     -- 消息类型：assignment/status_change/warning_due/warning_overdue/warning_inactive/admin_directive
    content      TEXT    NOT NULL,                     -- 消息正文
    task_id      INTEGER,                              -- 关联任务（可空，用于点击跳转）
    is_read      INTEGER NOT NULL DEFAULT 0,           -- 是否已读：0/1
    created_at   TEXT    NOT NULL,                     -- 创建时间
    FOREIGN KEY (recipient) REFERENCES users(user_id),
    FOREIGN KEY (sender)   REFERENCES users(user_id),
    FOREIGN KEY (task_id)  REFERENCES tasks(task_id) ON DELETE SET NULL
);

-- ============================================================
-- 5. 系统配置表 (system_config) —— 可配置参数
-- ============================================================
CREATE TABLE IF NOT EXISTS system_config (
    config_key    TEXT    PRIMARY KEY,                  -- 配置键
    config_value  TEXT    NOT NULL,                    -- 配置值（均存为字符串，应用层按需转换）
    updated_at    TEXT    NOT NULL                     -- 更新时间
);

-- ============================================================
-- 6. 过程证据表 (evidence) —— V2 新增
-- ============================================================
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id  INTEGER PRIMARY KEY AUTOINCREMENT,    -- 证据ID
    task_id      INTEGER NOT NULL,                     -- 关联任务（删任务级联删除）
    etype        TEXT    NOT NULL,                     -- 证据类型：text（文字）/ link（链接）/ file（文件名，不真正上传）
    content      TEXT    NOT NULL,                     -- 文字内容 / URL / 文件名（上限500字，应用层校验）
    created_by   INTEGER,                              -- 创建人 user_id（可空）
    created_at   TEXT    NOT NULL,                     -- 创建时间
    FOREIGN KEY (task_id)    REFERENCES tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(user_id)
);

-- ============================================================
-- 7. 阻塞记录表 (blockers) —— V2 新增
-- ============================================================
CREATE TABLE IF NOT EXISTS blockers (
    blocker_id   INTEGER PRIMARY KEY AUTOINCREMENT,    -- 阻塞ID
    task_id      INTEGER NOT NULL,                     -- 关联任务（删任务级联删除）
    content      TEXT    NOT NULL,                     -- 阻塞描述（上限500字，应用层校验）
    status       TEXT    NOT NULL DEFAULT 'open',      -- 状态：open（待解决）/ resolved（已解决）
    created_by   INTEGER,                              -- 创建人 user_id（可空）
    created_at   TEXT    NOT NULL,                     -- 创建时间
    resolved_at  TEXT,                                 -- 解决时间（标记解决时填写）
    resolved_by  INTEGER,                              -- 解决人 user_id（标记解决时填写）
    FOREIGN KEY (task_id)    REFERENCES tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(user_id)
);
```

### 3.3 索引创建语句

```sql
-- 用户表：username 已有 UNIQUE 隐含索引，无需额外创建

-- 任务表索引（高频查询：按状态筛选、按负责人筛选、按截止日期排序、按逾期筛选）
CREATE INDEX IF NOT EXISTS idx_tasks_status      ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee    ON tasks(assignee);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date    ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_is_overdue  ON tasks(is_overdue);
CREATE INDEX IF NOT EXISTS idx_tasks_created_by  ON tasks(created_by);

-- 进度日志表索引（高频查询：按任务查进度记录、按时间排序）
CREATE INDEX IF NOT EXISTS idx_logs_task_id      ON progress_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_logs_operated_at  ON progress_logs(operated_at);

-- 消息表索引（高频查询：按接收人查未读、按时间排序）
CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient);
CREATE INDEX IF NOT EXISTS idx_messages_is_read   ON messages(is_read);
CREATE INDEX IF NOT EXISTS idx_messages_created   ON messages(created_at);

-- V2 新增表索引（高频查询：按任务查证据/阻塞列表）
CREATE INDEX IF NOT EXISTS idx_evidence_task ON evidence(task_id);
CREATE INDEX IF NOT EXISTS idx_blockers_task ON blockers(task_id);
```

### 3.4 初始配置数据

首次初始化数据库时插入默认配置：

```sql
INSERT OR IGNORE INTO system_config (config_key, config_value, updated_at) VALUES
('warning_due_days',      '3',  datetime('now','localtime')),  -- 即将到期预警天数（默认3天）
('warning_inactive_days', '7',  datetime('now','localtime')),  -- 长期待激活预警天数（默认7天')
('scan_interval_seconds', '300',datetime('now','localtime')),  -- 逾期扫描间隔（默认300秒=5分钟）
('warning_scan_time',     '09:00', datetime('now','localtime'));-- 预警每日扫描时间（默认09:00)
```

### 3.5 外键关系与级联策略总览

```
users (1) ──< tasks (N)          created_by: 任务由谁创建
users (1) ──< tasks (N)          assignee:   任务指派给谁
tasks (1) ──< progress_logs (N)  ON DELETE CASCADE: 删任务时进度日志一起删
tasks (1) ──< messages (N)       ON DELETE SET NULL: 删任务时消息保留（task_id 置空）
users (1) ──< messages (N)       recipient / sender
tasks (1) ──< evidence (N)       ON DELETE CASCADE: 删任务时过程证据一起删（V2 新增）
tasks (1) ──< blockers (N)       ON DELETE CASCADE: 删任务时阻塞记录一起删（V2 新增）
users (1) ──< evidence (N)       created_by（V2 新增）
users (1) ──< blockers (N)       created_by / resolved_by（V2 新增）
```

### 3.6 V2 数据库迁移（老库无缝升级）

V1 老数据库无需手工操作，启动时自动升级到 V2 结构。迁移逻辑位于 **`models.py` 的 `_migrate_v2()`**（`db.py` 仅提供连接与事务，不含迁移逻辑），由 `init_db()` 末尾调用：

```
init_db()
 ├── 建表（CREATE TABLE IF NOT EXISTS × 5 张 V1 表）
 ├── 建索引 + 写默认配置
 └── _migrate_v2()                     # V2 迁移，幂等可重复调用
      ├── ① CREATE TABLE IF NOT EXISTS evidence / blockers + 索引
      │      （IF NOT EXISTS 天然幂等，新老库统一走这一步）
      └── ② tasks 补 3 列
             PRAGMA table_info(tasks) 取现有列名集合
             逐列检查 progress_percent / risk_note / collaborators
             缺列才执行 ALTER TABLE tasks ADD COLUMN <col> <def>
             （SQLite ADD COLUMN 秒级完成，数据不丢）
```

**设计要点**：

| 要点 | 说明 |
|------|------|
| 幂等性 | 建表走 IF NOT EXISTS；补列先查 `PRAGMA table_info` 再 ALTER，重复启动零副作用 |
| 数据安全 | 只做加表/加列（带默认值），不修改、不删除任何 V1 数据 |
| 容错 | 迁移整体 try/except，异常打印日志（`[migrate_v2]` 前缀）但**不中断启动** |
| 时机 | 应用启动 `init_db()` 时执行，与首次建库共用同一条路径 |

---

## 四、Flask 路由与 API 设计

### 4.1 路由总览表

> **权限标记**：`🔓 公开` = 无需登录；`👤 登录` = 任意登录用户；`👑 管理员` = 仅 admin 角色

#### 模块一：认证（auth_routes.py）

| URL | 方法 | 功能 | 权限 | 请求参数 | 返回内容 |
|-----|:----:|------|:----:|----------|----------|
| `/` | GET | 根路由重定向 | 🔓 公开 | — | 重定向到 `/dashboard` 或 `/login`（无管理员时 `/setup`） |
| `/login` | GET | 显示登录页 | 🔓 公开 | — | login.html（自动填充「记住我」cookie 中的用户名） |
| `/login` | POST | 提交登录 | 🔓 公开 | `username`, `password`, `remember` | 成功重定向 `/dashboard`（按勾选写/清 30 天用户名 cookie）；V2：用户名/密码为空返回 **400** + 字段级错误（`error_field`），凭据错误返回 **401** 通用错误 |
| `/logout` | GET | 登出 | 👤 登录 | — | 清除 session，重定向 `/login` |
| `/setup` | GET | 显示初始化向导 | 🔓 公开 | — | setup.html（仅当无管理员时可访问） |
| `/setup` | POST | 创建首个管理员 | 🔓 公开 | `username`, `display_name`, `password`, `confirm_password` | 成功重定向 `/login` |

#### 模块二：任务 CRUD（task_routes.py）

> 标记 **V2** 的为 V2 迭代新增/变更路由；其余为 V1 保留路由。

| URL | 方法 | 功能 | 权限 | 请求参数 | 返回内容 |
|-----|:----:|------|:----:|----------|----------|
| `/tasks` | GET | 任务列表页 | 👤 登录 | `status`, `priority`, `assignee`, `keyword`, `sort`, `page`；V2 兼容 `owner=`（闭环矩阵跳转，映射到 assignee 筛选） | list.html（含筛选后的任务列表） |
| `/tasks/new` | GET | 显示新建任务表单 | 👤 登录 | — | form.html（管理员可指定负责人；负责人默认自己） |
| `/tasks/new` | POST | 创建任务 | 👤 登录 | `title`, `description`, `assignee`, `priority`, `due_date`；**V2** 新增 `progress_percent`, `risk_note`, `collaborators` | 成功重定向任务列表；失败回显错误 |
| `/tasks/<id>` | GET | 任务详情独立页（V2 保留：消息跳转 / JS 失效降级 / 浏览器直链） | 👤 登录 | 路径参数 `id` | detail.html（含进度时间线 + 证据/阻塞只读展示） |
| `/tasks/<id>/drawer` | GET | **V2 新增** 任务详情抽屉 HTML 片段（详情/证据/阻塞 3 页签） | 👤 登录 | 路径参数 `id` | `tasks/_drawer.html` 片段（无 base.html 包裹，供抽屉注入；含行内编辑权限标记） |
| `/tasks/owner/<uid>/drawer` | GET | **V2 新增** Owner 抽屉 HTML 片段（该负责人最近 50 条任务 + admin 推送提醒按钮） | 👤 登录 | 路径参数 `uid` | `tasks/_owner_drawer.html` 片段 |
| `/tasks/<id>/field` | POST | **V2 新增** 行内编辑单字段保存 | 👤 登录（owner 仅自己的；`assignee` 字段仅 admin） | JSON `{field, value}`，字段白名单：`title`/`description`/`priority`/`due_date`/`progress_percent`/`risk_note`/`collaborators`/`assignee` | JSON `{success, message}`（progress_percent 时附 `progress`） |
| `/tasks/<id>/evidence` | POST | **V2 新增** 添加过程证据 | 👤 登录（owner 仅自己的） | `etype`（text/link/file）, `content`（≤500 字） | JSON（成功并写时间线留痕） |
| `/tasks/<id>/evidence/<eid>/delete` | POST | **V2 新增** 删除过程证据 | 👑 管理员 | 路径参数 `id`, `eid`（证据须属于该任务） | AJAX 返回 JSON；普通 POST 重定向回详情页 |
| `/tasks/<id>/blockers` | POST | **V2 新增** 添加阻塞记录 | 👤 登录（owner 仅自己的） | `content`（≤500 字） | JSON（成功并写时间线留痕） |
| `/tasks/<id>/blockers/<bid>/resolve` | POST | **V2 新增** 标记阻塞解决 | 👤 登录（admin 或记录创建者本人） | 路径参数 `id`, `bid` | JSON（成功并写时间线留痕） |
| `/tasks/<id>/blockers/<bid>/delete` | POST | **V2 新增** 删除阻塞记录 | 👑 管理员 | 路径参数 `id`, `bid`（记录须属于该任务） | AJAX 返回 JSON；普通 POST 重定向回详情页 |
| `/tasks/remind` | POST | **V2 新增** 推送提醒（admin 发站内信，type=admin_directive） | 👤 登录（内部校验 admin，非 admin 返回 JSON 403） | `task_id` 或 `owner_id` 二选一（兼容 form / JSON / query 参数） | JSON（不能给自己推送，返回 400） |
| `/tasks/<id>/edit` | POST | 编辑任务字段 | 👤 登录（owner 仅自己的） | `title`, `description`, `assignee`, `priority`, `due_date`；**V2** 新增 3 字段（表单未携带时保留原值，向后兼容） | 成功重定向列表；失败回显错误 |
| `/tasks/<id>/status` | POST | 变更任务状态 | 👤 登录（owner 仅自己的） | `status`, `progress_note` | **V2**：AJAX 请求（`X-Requested-With` 头）返回 JSON；普通请求成功更新状态+记录进度+生成消息后重定向详情 |
| `/tasks/<id>/delete` | POST | 物理删除任务 | 👑 管理员 | 路径参数 `id`（仅允许删除已撤销任务） | 重定向列表页 |
| `/tasks/export` | GET | 导出 CSV（P1-004，utf-8-sig 带 BOM，文件名 RFC 5987 双 fallback） | 👤 登录 | 筛选参数同 `/tasks`（不分页） | text/csv 附件下载 |
| `/tasks/batch` | POST | 批量操作（P1-003：批量改状态 / 批量指派） | 👤 登录（reassign 仅 admin；owner 仅自己的任务） | `task_ids[]`, `action`, `target_status` / `new_assignee` + 回跳筛选参数 | 重定向列表页（flash 汇总成功/失败数） |

#### 模块三：进度记录（progress_routes.py）

| URL | 方法 | 功能 | 权限 | 请求参数 | 返回内容 |
|-----|:----:|------|:----:|----------|----------|
| `/tasks/<id>/progress` | POST | 提交进度备注（不改状态） | 👤 登录（owner 仅自己的） | `progress_note` | 成功生成进度记录，返回详情 |
| `/tasks/<id>/logs` | GET | 查看进度记录（JSON） | 👤 登录 | 路径参数 `id` | JSON 进度记录列表（供面板异步加载） |

#### 模块四：消息通知（message_routes.py）

| URL | 方法 | 功能 | 权限 | 请求参数 | 返回内容 |
|-----|:----:|------|:----:|----------|----------|
| `/messages` | GET | **V2 变更**：消息中心页由抽屉替代，旧链接 301 跳转 `/dashboard`（防 404） | 👤 登录 | — | 301 重定向 |
| `/messages/drawer` | GET | **V2 新增** 消息抽屉 HTML 片段（最近 50 条，类型筛选） | 👤 登录 | `type`（消息类型，非法值回落全部） | `messages/_drawer.html` 片段 |
| `/messages/<id>/read` | POST | 标记单条已读 | 👤 登录 | 路径参数 `id` | JSON `{success: true}` |
| `/messages/read-all` | POST | 全部标记已读 | 👤 登录 | — | JSON `{success: true, count: N}` |
| `/messages/unread-count` | GET | 获取未读数（导航栏铃铛轮询用，30 秒） | 👤 登录 | — | JSON `{count: N}` |
| `/messages/send` | GET | 显示管理员发消息表单（C3 确认） | 👑 管理员 | — | send.html |
| `/messages/send` | POST | 发送指令消息（type=admin_directive） | 👑 管理员 | `recipient`, `content`, `task_id`（可选） | 成功重定向 `/dashboard`；失败回显错误 |

#### 模块五：用户管理（user_routes.py，P1）

| URL | 方法 | 功能 | 权限 | 请求参数 | 返回内容 |
|-----|:----:|------|:----:|----------|----------|
| `/users` | GET | 用户管理页 | 👑 管理员 | — | manage.html（用户列表） |
| `/users/new` | POST | 新增用户 | 👑 管理员 | `username`, `display_name`, `password`, `role` | 重定向用户管理页 |
| `/users/<id>/toggle` | POST | 启用/停用用户 | 👑 管理员 | 路径参数 `id` | 重定向用户管理页 |
| `/users/<id>/reset-password` | POST | 重置密码 | 👑 管理员 | `new_password` | 重定向用户管理页 |

#### 模块六：设置（settings_routes.py）

| URL | 方法 | 功能 | 权限 | 请求参数 | 返回内容 |
|-----|:----:|------|:----:|----------|----------|
| `/settings/profile` | GET | 个人设置页 | 👤 登录 | — | profile.html |
| `/settings/profile` | POST | 修改显示名/密码 | 👤 登录 | `display_name`, `old_password`, `new_password`（可选） | 重定向个人设置页 |
| `/settings/system` | GET | 系统设置页 | 👑 管理员 | — | system.html（预警天数配置） |
| `/settings/system` | POST | 保存系统设置 | 👑 管理员 | `warning_due_days`, `warning_inactive_days` | 重定向系统设置页 |

#### 模块七：仪表盘（dashboard_routes.py）

| URL | 方法 | 功能 | 权限 | 请求参数 | 返回内容 |
|-----|:----:|------|:----:|----------|----------|
| `/dashboard` | GET | 仪表盘概览（**V2 重写**：6 统计卡 + 今日督办焦点 + 任务闭环矩阵） | 👤 登录 | **V2 新增** `range=all|year|quarter|month|week`（时间范围，按任务创建时间过滤，非法值回落 all）、`mpage`（闭环矩阵分页，每页 8 人） | overview.html |

> 说明：V2 设计文档 §5.1 曾预留可选接口 `/dashboard/data`（局部刷新），实际实现采用整页跳转带 `?range=` 参数的方案，该接口**未实现**。

### 4.2 路由设计约定

- **GET 用于展示页面，POST 用于提交操作**，遵循 RESTful 简化版（不引入 PUT/DELETE，降低新手理解成本）。
- **JSON 接口**仅用于前端异步交互（如标记已读、轮询未读数、加载进度记录、行内编辑），其余均为 HTML 响应。
- **统一响应格式**：JSON 接口返回 `{"success": bool, "message": str, "data": obj}`。
- **重定向**：所有 POST 操作成功后使用 `redirect()`（PRG 模式，防止刷新重复提交）。
- **片段路由（V2 新增）**：`/tasks/<id>/drawer`、`/tasks/owner/<uid>/drawer`、`/messages/drawer` 返回**无 base.html 包裹的 HTML 片段**，仅供 `main.js` 抽屉管理器注入，不用于独立访问。
- **AJAX 双通道（V2 新增）**：前端所有 fetch 请求统一携带请求头 `X-Requested-With: XMLHttpRequest`；后端据此判断返回 JSON 还是重定向/页面（如 `/tasks/<id>/status`、证据/阻塞删除路由同时兼容抽屉 AJAX 与独立详情页普通表单提交）。
- **权限校验优先返回 JSON**：供 AJAX 调用的路由（如 `/tasks/remind`）在权限不足时手动校验并返回 JSON 403，避免装饰器重定向导致前端拿到 302。

---

## 五、状态机实现设计

### 5.1 状态枚举定义

```python
# state_machine.py

# 状态枚举（与数据库 status 字段值一致）
class TaskStatus:
    PENDING      = 'pending'       # 待启动
    IN_PROGRESS  = 'in_progress'   # 进行中
    OVERDUE      = 'overdue'       # 已逾期
    CLOSED       = 'closed'        # 已闭环
    CANCELLED    = 'cancelled'     # 已撤销

# 状态中文映射（模板渲染用）
STATUS_LABELS = {
    'pending':      '待启动',
    'in_progress':  '进行中',
    'overdue':      '已逾期',
    'closed':       '已闭环',
    'cancelled':    '已撤销',
}

# 状态颜色映射（前端样式用）
STATUS_COLORS = {
    'pending':      'gray',     # 灰色
    'in_progress':  'blue',     # 蓝色
    'overdue':      'red',      # 红色
    'closed':       'green',    # 绿色
    'cancelled':    'darkgray', # 深灰色
}

# 优先级枚举
class TaskPriority:
    URGENT = 'urgent'
    HIGH   = 'high'
    MEDIUM = 'medium'
    LOW    = 'low'

PRIORITY_LABELS = {
    'urgent': '紧急', 'high': '高', 'medium': '中', 'low': '低'
}
```

### 5.2 状态转换矩阵

```python
# state_machine.py

# 转换矩阵：key=当前状态，value=允许转到的目标状态集合
# 注意：自动逾期（overdue）不在此矩阵中，由后台扫描强制触发
TRANSITIONS = {
    'pending':      {'in_progress', 'closed', 'cancelled'},
    'in_progress':  {'closed', 'cancelled'},
    'overdue':      {'in_progress', 'closed', 'cancelled'},
    'closed':       {'in_progress'},       # 仅管理员，需角色校验
    'cancelled':    {'pending'},           # 仅管理员，需角色校验
}

# 需要管理员角色的转换（角色级权限）
ADMIN_ONLY_TRANSITIONS = {
    ('closed', 'in_progress'),     # 重新打开
    ('cancelled', 'pending'),      # 重新激活
}


def validate_transition(current_status, target_status, user_role):
    """
    校验状态转换是否合法。
    
    Args:
        current_status: 当前状态
        target_status:  目标状态
        user_role:      操作者角色 ('admin' / 'owner')
    
    Returns:
        (bool, str): (是否允许, 不允许时的错误原因)
    """
    # 相同状态不允许
    if current_status == target_status:
        return False, '状态未发生变化'
    
    # 查转换矩阵
    allowed = TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        return False, f'不允许从「{STATUS_LABELS[current_status]}」转换到「{STATUS_LABELS[target_status]}」'
    
    # 检查是否需要管理员权限
    if (current_status, target_status) in ADMIN_ONLY_TRANSITIONS:
        if user_role != 'admin':
            return False, '此操作仅管理员可执行'
    
    return True, ''
```

### 5.3 状态变更的完整处理流程

```python
# state_machine.py

def change_task_status(task_id, target_status, operator_id, operator_role, progress_note=''):
    """
    执行状态变更的完整流程（事务性操作）：
    1. 校验转换合法性
    2. 更新任务状态 + updated_at
    3. 写入进度日志
    4. 触发副作用消息（通知负责人/创建人）
    
    Returns:
        (bool, str): (是否成功, 错误原因或空)
    """
    task = models.get_task(task_id)
    if not task:
        return False, '任务不存在'
    
    current_status = task['status']
    
    # 1. 校验合法性
    ok, reason = validate_transition(current_status, target_status, operator_role)
    if not ok:
        return False, reason
    
    # 2. 准备副作用数据
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    extra_updates = {'updated_at': now}
    
    # 闭环时记录闭环时间
    if target_status == TaskStatus.CLOSED:
        extra_updates['closed_at'] = now
    # 从闭环/撤销重新激活时清空闭环时间
    if current_status == TaskStatus.CLOSED and target_status == TaskStatus.IN_PROGRESS:
        extra_updates['closed_at'] = None
    
    # 3. 事务执行：更新状态 + 写日志 + 发消息
    with db.transaction():
        # 更新任务状态
        models.update_task(task_id, status=target_status, **extra_updates)
        
        # 写进度日志
        models.create_progress_log(
            task_id=task_id,
            operator=operator_id,
            operated_at=now,
            status_from=current_status,
            status_to=target_status,
            progress_note=progress_note
        )
        
        # 4. 生成状态变更消息（通知任务的另一相关方）
        # owner 操作 → 通知 admin（创建人）；admin 操作 → 通知 owner（负责人）
        notify_target = task['created_by'] if operator_role == 'owner' else task['assignee']
        if notify_target != operator_id:  # 不给自己发消息
            models.create_message(
                recipient=notify_target,
                sender=operator_id,
                type='status_change',
                content=f'任务「{task["title"]}」状态变更为「{STATUS_LABELS[target_status]}」'
                        + (f'，备注：{progress_note}' if progress_note else ''),
                task_id=task_id
            )
    
    return True, ''
```

### 5.4 "已逾期"自动触发实现方案

**方案选择：后台守护线程（不用 APScheduler）**

理由：零额外依赖，打包简单，逻辑透明，新手易理解。

```python
# scheduler.py

import threading
import time
from datetime import datetime

def start_background_tasks(app):
    """
    在 Flask 启动时调用，启动两个守护线程：
    1. 逾期扫描线程：每 5 分钟扫描一次，将超期未闭环的任务自动置为"已逾期"
    2. 预警扫描线程：每日固定时间（默认09:00）执行三层预警扫描
    """
    # 逾期扫描线程
    overdue_thread = threading.Thread(
        target=_overdue_scan_loop, args=(app,), daemon=True, name='overdue-scanner'
    )
    overdue_thread.start()
    
    # 预警扫描线程
    warning_thread = threading.Thread(
        target=_warning_scan_loop, args=(app,), daemon=True, name='warning-scanner'
    )
    warning_thread.start()


def _overdue_scan_loop(app):
    """逾期扫描循环：每 scan_interval_seconds 秒执行一次"""
    with app.app_context():
        while True:
            try:
                _scan_and_mark_overdue()
            except Exception as e:
                app.logger.error(f'逾期扫描异常: {e}')
            # 读取配置间隔（默认300秒）
            interval = int(models.get_config('scan_interval_seconds', '300'))
            time.sleep(interval)


def _scan_and_mark_overdue():
    """
    扫描所有"待启动"和"进行中"且超过截止日期的任务，
    自动将其状态改为"已逾期"，并触发第二层预警消息。
    """
    now_date = datetime.now().strftime('%Y-%m-%d')
    # 查找超期任务：状态在 pending/in_progress 且 due_date < 今天
    overdue_tasks = models.get_tasks_for_overdue_check(now_date)
    
    for task in overdue_tasks:
        with db.transaction():
            # 更新状态
            models.update_task(
                task['task_id'],
                status=TaskStatus.OVERDUE,
                is_overdue=1,
                updated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
            # 写系统日志（操作人为系统，operator 用 NULL 或特殊标识）
            models.create_progress_log(
                task_id=task['task_id'],
                operator=None,  # 系统自动操作
                operated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                status_from=task['status'],
                status_to=TaskStatus.OVERDUE,
                progress_note='系统自动标记：任务超过截止日期'
            )
            # 触发第二层预警消息（通知负责人 + 管理员）
            warning_engine.trigger_overdue_warning(task)
```

### 5.5 状态变更副作用汇总

| 触发动作 | 副作用 | 实现位置 |
|----------|--------|----------|
| 任何手动状态变更 | 写入 progress_logs 记录 | `change_task_status()` |
| 转为"已闭环" | 记录 closed_at 时间 | `change_task_status()` |
| 手动状态变更 | 生成 status_change 消息通知相关方 | `change_task_status()` |
| 系统自动转"已逾期" | 写入 progress_logs（operator=NULL） | `_scan_and_mark_overdue()` |
| 系统自动转"已逾期" | 生成 warning_overdue 消息（负责人+管理员） | `warning_engine.trigger_overdue_warning()` |
| 创建任务并指派 | 生成 assignment 消息通知负责人 | `task_routes.create_task()` |

---

## 六、预警系统设计

### 6.1 三层预警触发逻辑

```python
# warning_engine.py

def run_warning_scan():
    """
    每日预警扫描主入口（由 scheduler 每日 09:00 调用）。
    遍历所有活跃任务（非终态），判定并生成三层预警消息。
    采用"当天是否已发"去重，避免重复消息轰炸。
    """
    due_days      = int(models.get_config('warning_due_days', '3'))
    inactive_days = int(models.get_config('warning_inactive_days', '7'))
    today         = datetime.now().strftime('%Y-%m-%d')
    
    # 只扫描待启动、进行中、已逾期的任务（终态不预警）
    active_tasks = models.get_active_tasks_for_warning()
    
    for task in active_tasks:
        warnings = []  # 本任务触发的预警列表
        
        # ── 第一层：即将到期预警 ──
        # 条件：状态为待启动/进行中，且截止日期在今天到 due_days 天后之间
        if task['status'] in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS):
            days_to_due = (datetime.strptime(task['due_date'], '%Y-%m-%d') 
                           - datetime.now()).days
            if 0 <= days_to_due <= due_days:
                warnings.append({
                    'type': 'warning_due',
                    'content': f'任务「{task["title"]}」将在 {days_to_due} 天后到期，请及时跟进。'
                })
        
        # ── 第二层：已逾期预警 ──
        # 条件：状态为已逾期（每日提醒一次）
        if task['status'] == TaskStatus.OVERDUE:
            warnings.append({
                'type': 'warning_overdue',
                'content': f'任务「{task["title"]}」已逾期，请尽快处理或更新进度。'
            })
        
        # ── 第三层：长期待激活预警 ──
        # 条件：状态仍为待启动，且创建超过 inactive_days 天
        if task['status'] == TaskStatus.PENDING:
            days_since_create = (datetime.now() 
                                 - datetime.strptime(task['created_at'][:10], '%Y-%m-%d')).days
            if days_since_create >= inactive_days and days_since_create % inactive_days == 0:
                warnings.append({
                    'type': 'warning_inactive',
                    'content': f'任务「{task["title"]}」创建 {days_since_create} 天仍未启动，请尽快处理。'
                })
        
        # ── 合并去重发送 ──
        if warnings:
            _send_merged_warnings(task, warnings, today)


def _send_merged_warnings(task, warnings, today):
    """
    将一个任务的多个预警合并为一条消息发送（避免消息轰炸）。
    去重策略：同一任务同一天只发一条合并消息。
    
    通知对象：
    - 第一层（即将到期）→ 仅负责人
    - 第二层（已逾期）→ 负责人 + 所有管理员
    - 第三层（长期待激活）→ 负责人 + 所有管理员
    """
    # 确定通知对象
    recipients = {task['assignee']}  # 负责人始终收到
    if any(w['type'] in ('warning_overdue', 'warning_inactive') for w in warnings):
        recipients.update(models.get_admin_user_ids())  # 二、三层抄送管理员
    
    # 合并消息内容
    content_parts = [w['content'] for w in warnings]
    merged_content = '\n'.join(content_parts)
    
    # 取最严重的类型作为消息主类型（逾期 > 待激活 > 到期）
    type_priority = {'warning_overdue': 0, 'warning_inactive': 1, 'warning_due': 2}
    primary_type = min(warnings, key=lambda w: type_priority[w['type']])['type']
    
    # 去重：检查今天是否已对该任务发过同类型预警
    for recipient_id in recipients:
        if not models.has_warning_today(task['task_id'], recipient_id, primary_type, today):
            models.create_message(
                recipient=recipient_id,
                sender=None,  # 系统消息
                type=primary_type,
                content=merged_content,
                task_id=task['task_id']
            )
```

### 6.2 后台扫描调度方案

```
┌──────────────────────────────────────────────────┐
│              scheduler.py 调度方案                │
├──────────────────────────────────────────────────┤
│                                                  │
│  线程1: 逾期扫描 (_overdue_scan_loop)             │
│  ┌──────────────────────────────────────┐        │
│  │  while True:                          │        │
│  │    scan overdue tasks                 │        │
│  │    sleep(300s)  ← 每5分钟             │        │
│  └──────────────────────────────────────┘        │
│                                                  │
│  线程2: 预警扫描 (_warning_scan_loop)             │
│  ┌──────────────────────────────────────┐        │
│  │  while True:                          │        │
│  │    if 当前时间 >= 09:00               │        │
│  │       and 今天未扫描过:               │        │
│  │      run_warning_scan()               │        │
│  │      记录今天已扫描                   │        │
│  │    sleep(60s)   ← 每分钟检查一次时间  │        │
│  └──────────────────────────────────────┘        │
│                                                  │
│  两个线程均为 daemon=True，主进程退出时自动终止    │
└──────────────────────────────────────────────────┘
```

**线程安全说明**：
- SQLite 连接使用 `check_same_thread=False` + 应用级锁（`threading.Lock`），确保多线程并发安全。
- 每个线程使用独立的数据库连接（线程局部存储 `threading.local()`）。
- 所有写操作通过 `db.transaction()` 上下文管理器加锁，保证原子性。

### 6.3 消息生成逻辑汇总

| 触发场景 | 消息类型 | 接收人 | 发送人 | 生成位置 |
|----------|----------|--------|--------|----------|
| 管理员创建任务并指派 | `assignment` | 负责人 | 创建人 | `task_routes.create_task()` |
| 手动变更任务状态 | `status_change` | 相关方 | 操作人 | `change_task_status()` |
| 系统自动转逾期 | `warning_overdue` | 负责人+管理员 | 系统(NULL) | `_scan_and_mark_overdue()` |
| 每日预警扫描-到期 | `warning_due` | 负责人 | 系统(NULL) | `run_warning_scan()` |
| 每日预警扫描-逾期 | `warning_overdue` | 负责人+管理员 | 系统(NULL) | `run_warning_scan()` |
| 每日预警扫描-待激活 | `warning_inactive` | 负责人+管理员 | 系统(NULL) | `run_warning_scan()` |
| 管理员发送指令（P1预留） | `admin_directive` | 指定负责人 | 管理员 | 预留接口 |

---

## 七、权限控制设计

### 7.1 基于角色的访问控制（RBAC）

两种角色：`admin`（管理员）、`owner`（任务负责人）。

| 能力 | admin | owner |
|------|:-----:|:-----:|
| 创建任务（指派给任何人） | ✅ | ✅（仅指派给自己） |
| 查看所有任务列表 | ✅ | ✅（只读他人任务） |
| 编辑任务字段 | ✅（所有任务） | ✅（仅自己负责的） |
| 变更任务状态 | ✅（所有任务） | ✅（仅自己负责的） |
| 重新打开已闭环任务 | ✅ | ❌ |
| 重新激活已撤销任务 | ✅ | ❌ |
| 物理删除已撤销任务 | ✅ | ❌ |
| 用户管理（增删停用） | ✅ | ❌ |
| 系统设置（预警天数） | ✅ | ❌ |
| 查看仪表盘 | ✅ | ✅ |
| 接收逾期预警消息 | ✅ | ✅ |

### 7.2 路由级权限校验（装饰器）

```python
# auth.py

from functools import wraps
from flask import session, redirect, url_for, abort, jsonify

def login_required(f):
    """登录校验装饰器：未登录重定向到登录页"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """管理员校验装饰器：非管理员返回 403"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        if session.get('role') != 'admin':
            # HTML 请求返回 403 页面，JSON 请求返回错误
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'success': False, 'message': '权限不足，仅管理员可访问'}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    """获取当前登录用户对象（从 session 取 user_id 查库）"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return models.get_user(user_id)
```

### 7.3 数据级权限过滤

```python
# auth.py

def can_edit_task(task, user):
    """
    判断用户是否有权编辑某任务。
    - admin：可编辑所有任务
    - owner：仅可编辑自己负责的任务
    """
    if user['role'] == 'admin':
        return True
    return task['assignee'] == user['user_id']


def filter_tasks_by_permission(tasks, user, edit_mode=False):
    """
    列表数据权限过滤。
    - edit_mode=False（查看列表）：owner 可看全部（只读），admin 可看全部
    - edit_mode=True（编辑操作）：owner 只能操作自己的
    """
    if user['role'] == 'admin':
        return tasks
    if edit_mode:
        return [t for t in tasks if t['assignee'] == user['user_id']]
    return tasks  # 查看模式：owner 可看全部（模板层限制编辑按钮显示）
```

**模板层配合**：在 `detail.html` 中，通过 `can_edit_task(task, current_user)` 判断是否显示编辑表单/状态下拉框；owner 查看他人任务时，所有字段只读显示。

### 7.4 登录会话管理

```python
# auth.py —— 登录流程

def do_login(username, password):
    """
    登录流程：
    1. 查用户，校验 is_active
    2. 校验密码哈希
    3. 写入 session
    Returns: (bool, str)
    """
    user = models.get_user_by_username(username)
    if not user or not user['is_active']:
        return False, '用户名或密码错误'  # 不暴露用户是否存在
    if not check_password_hash(user['password_hash'], password):
        return False, '用户名或密码错误'
    
    session['user_id']      = user['user_id']
    session['username']     = user['username']
    session['display_name'] = user['display_name']
    session['role']         = user['role']
    session.permanent       = True  # 启用持久化 session
    return True, ''
```

---

## 八、依赖包列表

### 8.1 requirements.txt 完整内容

```
# ===== 核心框架 =====
Flask==3.0.3              # Web 框架，路由 + Jinja2 模板渲染

# ===== 数据库 =====
# sqlite3 为 Python 标准库自带，无需安装
# 如需更方便的 Row 对象操作，可选装：
# （不额外安装，使用标准库即可）

# ===== 密码加密 =====
# werkzeug 随 Flask 安装，提供 generate_password_hash / check_password_hash
# 无需单独列出

# ===== 打包工具（仅开发/打包环境需要，运行环境不需要） =====
pyinstaller==6.10.0       # 将 Python 应用打包为 Windows 可执行文件
```

**依赖极简说明**：

| 包 | 版本 | 用途 | 是否运行时必需 |
|----|------|------|:--------------:|
| Flask | 3.0.3 | Web 框架、路由、Jinja2 模板、session 管理 | ✅ 是 |
| werkzeug | (随 Flask) | 密码哈希加密、HTTP 工具 | ✅ 是（自动安装） |
| Jinja2 | (随 Flask) | 服务端模板渲染 | ✅ 是（自动安装） |
| sqlite3 | (标准库) | SQLite 数据库驱动 | ✅ 是（Python 内置） |
| threading | (标准库) | 后台守护线程 | ✅ 是（Python 内置） |
| pyinstaller | 6.10.0 | 打包为 .exe/.zip | ❌ 仅打包时需要 |

> **设计决策**：本系统刻意保持依赖极简，运行时实际只需 Flask 一个第三方包（其余均为 Python 标准库或 Flask 依赖）。这大幅降低了 PyInstaller 打包的复杂度和体积，也避免了新手处理依赖冲突的困扰。

---

## 九、开发任务列表（给工程师的）

> 遵循"基础设施先行、逐层向上"原则。第一版聚焦 P0，但任务划分预留 P1/P2 扩展空间。

### T01：项目基础设施

| 项 | 内容 |
|----|------|
| **任务名** | 项目基础设施（配置 + 入口 + 数据库 + 依赖 + 启动脚本） |
| **优先级** | P0 |
| **涉及文件** | `app.py`、`config.py`、`db.py`、`models.py`（建表部分）、`requirements.txt`、`start.bat`、`build.bat`、`data/.gitkeep` |
| **依赖** | 无（最先做） |
| **描述** | 搭建 Flask 应用骨架：应用工厂模式创建 app、配置项集中管理、SQLite 连接管理（线程安全）、所有表的建表与初始化配置数据写入、依赖清单、Windows 启动脚本和打包脚本。完成后应能 `python app.py` 启动并访问空白页面。 |

### T02：认证与权限基础模块

| 项 | 内容 |
|----|------|
| **任务名** | 认证与权限模块（登录 + 初始化向导 + 权限装饰器 + 基础模板） |
| **优先级** | P0 |
| **涉及文件** | `auth.py`、`routes/__init__.py`、`routes/auth_routes.py`、`templates/base.html`、`templates/login.html`、`templates/setup.html`、`templates/errors/403.html`、`static/css/main.css`、`static/js/main.js`（基础部分） |
| **依赖** | T01 |
| **描述** | 实现密码哈希、登录登出、session 管理、权限装饰器（@login_required/@admin_required）、首次启动初始化向导（创建管理员）。同时完成 base.html 基础骨架（导航栏、侧边栏、消息红点占位）和 Linear 风格全局 CSS。完成后应能登录系统看到空白主框架。 |

### T03：任务核心模块

| 项 | 内容 |
|----|------|
| **任务名** | 任务核心模块（状态机 + 任务 CRUD + 进度记录 + 任务页面） |
| **优先级** | P0 |
| **涉及文件** | `state_machine.py`、`routes/task_routes.py`、`routes/progress_routes.py`、`models.py`（CRUD 函数部分）、`templates/tasks/list.html`、`templates/tasks/detail.html`、`templates/tasks/form.html` |
| **依赖** | T01、T02 |
| **描述** | 实现状态机（枚举、转换矩阵、校验函数、变更流程含副作用）、任务列表页（筛选/搜索/排序）、任务详情侧滑面板、新建/编辑表单、进度记录提交与时间线展示、数据级权限过滤。完成后应能完整使用任务的创建、查看、编辑、状态流转、进度更新功能。 |

### T04：消息与预警模块

| 项 | 内容 |
|----|------|
| **任务名** | 消息通知 + 预警引擎 + 后台调度 |
| **优先级** | P0 |
| **涉及文件** | `warning_engine.py`、`scheduler.py`、`routes/message_routes.py`、`models.py`（消息与预警查询函数）、`templates/messages/list.html`、`static/js/main.js`（消息红点轮询部分） |
| **依赖** | T01、T02、T03 |
| **描述** | 实现三层预警引擎（到期/逾期/待激活判定 + 合并去重）、后台守护线程（逾期扫描 5min + 预警扫描每日）、消息列表页、标记已读/全部已读、导航栏未读数轮询。完成后系统应能自动标记逾期任务、自动生成预警消息、用户可查看和标记消息已读。 |

### T05：管理与扩展模块

| 项 | 内容 |
|----|------|
| **任务名** | 用户管理 + 设置 + 仪表盘（P1 功能 + 收尾集成） |
| **优先级** | P1（含部分 P0 收尾） |
| **涉及文件** | `routes/user_routes.py`、`routes/settings_routes.py`、`routes/dashboard_routes.py`、`templates/users/manage.html`、`templates/settings/profile.html`、`templates/settings/system.html`、`templates/dashboard/overview.html`、`README.md` |
| **依赖** | T01、T02、T03、T04 |
| **描述** | 实现管理员用户管理（新增/停用/重置密码）、个人设置（修改显示名/密码）、系统设置（预警天数配置）、仪表盘概览（统计卡片+状态分布）。最后完成全系统集成测试和 README 使用说明。此任务使系统达到 P1 完整度，并为 P2 扩展预留接口。 |

### 任务依赖关系

```
T01 (基础设施)
 ├──> T02 (认证权限)
 │     ├──> T03 (任务核心)
 │     │     └──> T04 (消息预警)
 │     │           └──> T05 (管理扩展)
 │     └──> T04
 │     └──> T05
 └──> T03
```

---

## 十、共享约定（跨文件规范）

### 10.1 命名规范

| 对象 | 规范 | 示例 |
|------|------|------|
| 文件名 | 全小写 + 下划线 | `state_machine.py`、`task_routes.py` |
| Python 变量/函数 | 小写 + 下划线（snake_case） | `get_tasks_by_status()`、`current_user` |
| Python 类 | 大驼峰（PascalCase） | `TaskStatus`、`WarningEngine` |
| 数据库表名 | 全小写 + 下划线，复数 | `tasks`、`progress_logs`、`users`、`messages` |
| 数据库字段 | 全小写 + 下划线 | `task_id`、`created_at`、`is_overdue` |
| 路由 URL | 全小写 + 连字符或斜线分层 | `/tasks/<id>/status`、`/settings/profile` |
| 模板文件 | 全小写 + 下划线 | `list.html`、`detail.html` |
| CSS 类名 | 小写 + 连字符（kebab-case） | `task-row`、`status-badge`、`nav-sidebar` |
| 常量 | 全大写 + 下划线 | `TRANSITIONS`、`STATUS_LABELS` |

### 10.2 模板组织方式

```django
{# base.html —— 全局骨架 #}
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}督办系统{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/main.css') }}">
</head>
<body>
    {% block sidebar %}
        {# 左侧导航栏：任务/概览/通知/设置 #}
        {# 通知项显示未读红点数 #}
    {% endblock %}
    
    <main class="content">
        {% block content %}{% endblock %}  {# 子模板填充主内容 #}
    </main>
    
    {% block detail_panel %}{% endblock %}  {# 侧滑详情面板占位 #}
    
    <script src="{{ url_for('static', filename='js/main.js') }}"></script>
    {% block scripts %}{% endblock %}       {# 子模板追加脚本 #}
</body>
</html>
```

```django
{# tasks/list.html —— 子模板继承示例 #}
{% extends "base.html" %}
{% block title %}任务列表 - 督办系统{% endblock %}
{% block content %}
    <div class="task-toolbar">...</div>
    <table class="task-table">...</table>
{% endblock %}
```

**模板规范**：
- 所有页面继承 `base.html`，只填充 `content` block。
- 侧滑面板通过 `detail_panel` block 注入，由 JS 控制显隐。
- 公共片段（如状态标签）抽取为宏（macro）或 include 复用。
- 模板内禁止写复杂业务逻辑，只做数据展示和简单条件判断。

### 10.3 错误处理约定

```python
# 统一错误处理策略：

# 1. 路由层：捕获业务异常，回显用户友好提示
@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def server_error(e):
    app.logger.error(f'服务器错误: {e}')
    return render_template('errors/500.html'), 500

# 2. 业务层：操作失败返回 (False, reason) 元组，路由层据 reason 回显
ok, reason = change_task_status(...)
if not ok:
    flash(reason, 'error')  # Flask flash 消息

# 3. 数据库层：事务失败自动回滚，抛出异常由上层捕获
# 4. 后台线程：异常捕获并记录日志，不中断循环
```

### 10.4 代码注释规范

```python
def get_tasks(filters):
    """
    根据筛选条件查询任务列表。
    
    Args:
        filters: dict，支持的键：
            - status:    状态筛选（可选）
            - priority:  优先级筛选（可选）
            - assignee:  负责人ID筛选（可选）
            - keyword:   标题模糊搜索（可选）
            - sort:      排序字段，默认 due_date_asc
    
    Returns:
        list[dict]: 任务记录列表，每条为字段名→值的字典
    
    Note:
        owner 角色调用时，模板层负责只读展示他人任务，
        本函数不做权限过滤（数据可见性由 PRD 决策 Q4-B 决定）。
    """
```

**注释原则**：
- 每个模块文件顶部写文件级 docstring，说明该文件职责。
- 每个函数写 docstring（Args / Returns / Note）。
- 复杂业务逻辑（状态机转换、预警判定）写行内注释说明判定依据。
- 不注释显而易见的代码，注释解释"为什么"而非"做什么"。

### 10.5 数据库操作约定

```python
# db.py —— 统一连接与事务管理

import sqlite3
import threading
from contextlib import contextmanager

_lock = threading.Lock()
_local = threading.local()  # 线程局部存储

def get_db():
    """获取当前线程的数据库连接（线程安全）"""
    if not hasattr(_local, 'connection'):
        _local.connection = sqlite3.connect(
            config.DATABASE_PATH,
            row_factory=sqlite3.Row,  # 返回字典式 Row 对象
            check_same_thread=False
        )
        _local.connection.execute('PRAGMA foreign_keys = ON')  # 启用外键
    return _local.connection


@contextmanager
def transaction():
    """事务上下文管理器，自动提交或回滚，加线程锁保证并发安全"""
    with _lock:
        conn = get_db()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def query(sql, params=()):
    """查询快捷方法，返回 Row 列表"""
    return get_db().execute(sql, params).fetchall()


def execute(sql, params=()):
    """执行快捷方法（INSERT/UPDATE/DELETE），返回 lastrowid"""
    cursor = get_db().execute(sql, params)
    get_db().commit()
    return cursor.lastrowid
```

### 10.6 时间处理约定

- **存储格式**：统一 ISO 8601 字符串，日期 `YYYY-MM-DD`，日期时间 `YYYY-MM-DD HH:MM:SS`。
- **生成方式**：`datetime.now().strftime('%Y-%m-%d %H:%M:%S')`，使用本地时间（非 UTC），因为小团队本地部署，无需时区转换。
- **模板格式化**：注册 Jinja2 自定义过滤器 `format_date` / `format_datetime` / `time_ago`（如"2小时前"）。

---

## 十一、待明确事项

以下为架构设计中做的假设和需用户进一步确认的问题：

### 11.1 已做的假设（如不符可调整）

| 编号 | 假设内容 | 理由 |
|------|----------|------|
| A1 | 后台调度使用原生 threading 守护线程，而非 APScheduler | 零依赖、打包简单、逻辑透明 |
| A2 | 预警去重策略为"同一任务同一接收人同一天同一类型只发一条" | 避免消息轰炸，PRD 要求合并通知 |
| A3 | 第三层"长期待激活预警"频率为每 inactive_days 天一次（默认每7天） | PRD 写"每7天提醒1次" |
| A4 | owner 创建任务时只能指派给自己（assignee 默认且固定为自己） | PRD O-US-01 "自主新增个人任务" |
| A5 | 系统消息的 sender 字段存 NULL 表示系统自动发送 | 与用户消息区分 |
| A6 | 物理删除仅允许删除"已撤销"状态的任务 | PRD Q6-B 确认 |
| A7 | session 使用 Flask 默认客户端 session（签名 cookie），不引入服务端 session 存储 | 单进程部署，默认方案足够 |
| A8 | 逾期判定按"日期"比较（due_date < 今天），不考虑小时分钟 | 截止日期为日期类型，PRD 未要求精确到时分 |

### 11.2 用户确认结果（2026-08-25 已确认）

| 编号 | 问题 | 确认结果 |
|------|------|----------|
| C1 | 任务列表是否需要分页？ | **B — 第一版就做分页**（每页 20 条，底部分页导航） |
| C2 | 消息红点轮询频率？ | **A — 每 30 秒自动轮询** |
| C3 | 是否需要管理员直接发指令消息？ | **B — P0 就做独立入口**（管理员有专门发消息页面） |
| C4 | 打包产物形式？ | **A — 文件夹 + .bat**（PyInstaller onedir 模式） |

**确认后的设计调整说明**：

1. **C1-B 分页**：`task_routes.task_list()` 需增加 `page` 参数，`models.get_tasks()` 增加 `LIMIT/OFFSET` 分页，模板增加底部分页导航组件。
2. **C3-B 独立发消息入口**：需在 `routes/message_routes.py` 新增 `/messages/send` 路由（GET 显示发消息表单 + POST 发送），模板新增 `messages/send.html`，管理员可在通知页直接给指定负责人发送指令消息。

---

## 十二、V2 前端交互架构（抽屉体系）

> V2 重写 `static/js/main.js` 与 `templates/base.html`，建立"整页渲染 + 局部片段注入"的混合模式：页面主体仍由 Jinja2 服务端整页渲染，抽屉内容通过片段路由按需 fetch 注入。**不引入前端框架、构建工具、CDN 依赖**。

### 12.1 抽屉管理器（drawer 对象）

`base.html` 提供全局**唯一**抽屉容器，三类抽屉（任务详情 / Owner / 消息）共用：

| DOM 节点 | 职责 |
|----------|------|
| `#drawer-main` | 抽屉主体（加/去 `open` class 控制滑入滑出） |
| `#drawer-main-body` | 片段注入区（innerHTML 替换） |
| `#drawer-overlay` | 背景遮罩（点击关闭） |
| `#toast-container` | Toast 通知容器（右下角） |

`main.js` 中 `drawer` 对象的三个方法：

- **`drawer.open(url)`**：`fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}})` → 响应为 HTML 片段，注入 `#drawer-main-body`；若 `resp.redirected`（如登录态失效被重定向到 `/login`）则整页跳转；请求失败展示错误占位。
- **`drawer.reload()`**：用记录的 `currentUrl` 重新 `open()` —— 所有抽屉内操作成功后的统一刷新方式（服务端重新渲染权限与数据，前端不维护状态）。
- **`drawer.close()`**：移除 `open` class、清空注入区、恢复页面滚动；ESC 键 / `.drawer-close` 按钮 / 点击遮罩三种途径触发。

页面级脚本通过 `window.DB = {toast, drawer, pollUnreadCount}` 访问这些能力。

### 12.2 选择器契约（事件委托）

所有抽屉内交互均通过 `document` 级**事件委托**绑定（片段动态注入后无需重新绑定），选择器与行为的对应关系是模板片段与 `main.js` 之间的硬契约：

| 选择器 / 属性 | 行为 |
|---------------|------|
| `[data-drawer]`（任务行/焦点列表行） | 打开 `data-drawer` 属性值指定的任务抽屉 URL；点击目标命中 `a, button, input, select, textarea, label` 时忽略（不拦截行内操作按钮） |
| `.drawer-close`、`#drawer-overlay`、ESC 键 | 关闭抽屉 |
| `.drawer-tabs button[data-tab]` | 页签切换：激活对应 `.drawer-tab-pane`（`active` class 互斥） |
| `.inline-field.editable .field-value` | 行内编辑：点击原位变输入框；容器属性见 12.3 |
| `form.drawer-form` | AJAX 表单提交（FormData + `X-Requested-With` 头）→ JSON → Toast + `drawer.reload()`（响应含 `reload_page` 时整页刷新） |
| `.remind-btn[data-url]` | POST 推送提醒 → Toast |
| `.resolve-blocker-btn[data-url]` | POST 标记阻塞解决 → Toast + reload |
| `.delete-evidence-btn / .delete-blocker-btn [data-url]` | `confirm` 二次确认 → POST 删除 → Toast + reload（仅 admin 可见） |
| `.drawer .message-item[data-message-id][data-task-drawer]` | 未读则 POST 标记已读；有 `data-task-drawer` 则打开关联任务抽屉 |
| `#drawer-mark-all-read` | POST 全部已读 → Toast + reload + 刷新红点 |
| `#bell-btn` | 打开 `/messages/drawer` 消息抽屉 |
| `#unread-badge` | 未读数徽标（`/messages/unread-count` 30 秒轮询，>99 显示 `99+`，0 时隐藏） |
| `#theme-toggle` | 切换 `html.dark` class，偏好存 `localStorage('db-theme')`，默认浅色 |
| `#nav-toggle` / `#mobile-nav` | 移动端汉堡菜单展开/收起 |

### 12.3 行内编辑契约

抽屉详情页签中每个可编辑字段为一个 `.inline-field` 容器，携带以下 data 属性：

| 属性 | 含义 |
|------|------|
| `data-field` | 字段名（须在路由层白名单内） |
| `data-type` | 控件类型：`text` / `textarea` / `number`（进度，min 0 max 100）/ `date` / `select` |
| `data-url` | 保存端点，固定为 `/tasks/<id>/field` |
| `data-options` | select 类型的选项 JSON（`[[value, label], ...]`，如优先级、负责人下拉） |
| `data-raw` | 当前原始值（编辑起点与回滚值） |

编辑流：点击 `.field-value` → 按类型构造控件 → 失焦或回车保存（值未变化则跳过）→ `POST /tasks/<id>/field`（JSON `{field, value}`）→ 成功 Toast + 进度% 联动刷新进度条；失败 Toast + 回滚显示原值；ESC 取消。

**权限下沉到模板**：片段渲染时由 `can_edit` 决定容器是否携带 `editable` class（无该 class 点击无反应）；`assignee` 字段额外要求 `current_user.role == 'admin'` 才带 `editable`。前端只做展示控制，最终权限由路由层白名单 + `can_edit_task` 二次校验。

### 12.4 片段渲染模式

- 后端提供 3 个片段路由（§4.1 模块二/四），渲染 `_` 前缀局部模板（`tasks/_drawer.html`、`tasks/_owner_drawer.html`、`messages/_drawer.html`），**不含 base.html 骨架**。
- 片段模板顶部注释声明其选择器契约（与 12.2 表格对应）。
- 所有写操作成功后 `drawer.reload()` 重新拉取片段，服务端重算权限与数据，杜绝前端状态陈旧。

### 12.5 视觉体系（V2）

- **CSS 变量双套**：`:root` 浅色默认 + `html.dark` 覆盖深色（`main.css` 单文件，无 CSS 框架）。
- **状态徽章**：`.status-badge.st-<status>`（`st-pending` 灰 / `st-in_progress` 琥珀 / `st-overdue` 红 / `st-closed` 绿 / `st-cancelled` 浅灰）；优先级药丸四级配色不变。
- **图标**：`templates/macros/icons.html` 以 Jinja2 宏（`{{ icon('bell', 14) }}`）内联 Lucide SVG，约 25 个图标，零外部依赖。
- **字体**：系统字体栈（`Inter, Segoe UI, PingFang SC, Microsoft YaHei` 等），**不内嵌字体文件**（离线打包体积考虑）。
- **Toast**：`#toast-container` 右下角滑入，3 秒自动消失（成功绿/失败红/信息蓝）；flash 消息自动转发为 Toast，flash 本体保留 3 秒淡出作兜底。
- **响应式断点**：≥1024px 桌面两栏 / 768–1023px 平板单栏 / <768px 手机（抽屉全屏、导航收进汉堡菜单）。

---

## 附录：架构关键决策速查

| 决策点 | 选择 | 一句话理由 |
|--------|------|-----------|
| 前后端 | 服务端渲染（Jinja2） | 新手友好，无需前端构建 |
| 数据库 | SQLite 单文件 | 零配置，单文件足够 |
| 后台调度 | 原生 threading | 零依赖，打包简单 |
| 打包 | PyInstaller onedir + .bat | 双击启动，调试方便 |
| 依赖数量 | 仅 Flask 一个第三方包 | 极简，降低维护负担 |
| 状态机 | 字典矩阵 + 校验函数 | 透明可读，新手易懂 |
| 权限 | 装饰器 + 数据过滤函数 | 路由级 + 数据级双层防护 |
| 消息去重 | 按天+类型+接收人去重 | 避免轰炸，合并通知 |
| V2 抽屉交互 | 整页渲染 + 片段注入混合模式 | 保留多页架构，零框架实现模板交互 |
| V2 数据库升级 | init_db 内幂等迁移（models._migrate_v2） | 老库启动自动升级，数据不丢 |
| V2 深色模式 | CSS 变量双套 + html.dark | 单 CSS 文件实现，零构建成本 |

---

> **下一步**：将本文档交付工程师，按 T01→T05 顺序实施。每个任务完成后进行集成测试，确保功能串联正确。C1-C4 已全部确认，可进入开发阶段。
