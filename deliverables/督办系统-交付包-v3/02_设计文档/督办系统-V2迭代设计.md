# 督办系统 V2 迭代 — 系统设计文档

> 阶段：系统设计（第 2/4 阶段）
> 输入：`iteration-v2-diff-analysis.md`（阶段 1 差异分析）+ 用户确认结论
> 状态：**待确认** —— 请审阅本文档，确认后进入阶段 3（开发）

---

## 1. 需求确认结论（已锁定）

| 问题 | 用户选择 | 含义 |
|------|---------|------|
| Q1 任务字段 | **B** | 只新增 3 字段：进度% + 风险点 + 协同方 |
| Q2 证据/阻塞 | **A** | 完整实现：证据三类型 + 阻塞两态 + 添加表单 |
| Q3 详情交互 | **A** | 列表点行开右侧抽屉 + 行内编辑；原详情页保留 |
| Q4 导航结构 | **A** | 顶栏主导航 + 铃铛消息抽屉，独立消息页移除 |
| Q5 深色模式 | **A** | 实现，手动切换 + 记忆偏好，默认浅色 |
| Q6 时间筛选 | **A** | 仅作用于仪表盘（统计卡+焦点+矩阵） |
| Q7 优先级 | **A** | 保留现有四级，仅视觉对齐模板 |
| Q8 推送提醒 | **A** | 复用站内信，admin 可用 |
| Q9 闭环率 | **A** | closed ÷ (总数 − 已撤销) |

---

## 2. UI 设计规范（对齐模板）

### 2.1 色板（浅色 / 深色双套 CSS 变量）

| 语义 | 浅色值 | 深色值 | 用途 |
|------|--------|--------|------|
| `--bg-page` | `#f5f5f7` | `#0f172a` | 页面底色 |
| `--bg-card` | `#ffffff` | `#1e293b` | 卡片 |
| `--brand-600` | `#2563eb` | `#3b82f6` | 主色（按钮/链接/选中态） |
| `--text-primary` | `#111827` | `#f1f5f9` | 主文字 |
| `--text-secondary` | `#6b7280` | `#94a3b8` | 次要文字 |
| `--border` | `#e5e7eb` | `#334155` | 边框/分隔线 |
| 状态·待启动 | 灰 `#6b7280` | 同色 | 药丸标签 |
| 状态·进行中 | 琥珀 `#f59e0b` | 同色 | 药丸标签 |
| 状态·已逾期 | 红 `#ef4444` | 同色 | 药丸标签 |
| 状态·已闭环 | 绿 `#10b981` | 同色 | 药丸标签 |
| 状态·已撤销 | 浅灰 `#9ca3af` | 同色 | 药丸标签 |

### 2.2 组件规范

- **卡片**：`border-radius: 12px`，浅阴影 `box-shadow: 0 1px 3px rgba(0,0,0,.08)`，hover 上浮 `translateY(-1px)` + 阴影加深
- **药丸标签**：`border-radius: 9999px`，浅色底（状态色 10% 透明度）+ 深色字（状态色 700）+ 左侧色点 6px
- **按钮**：主按钮品牌蓝实底白字；次按钮白底灰边框；危险按钮红系；全部 `rounded-lg`（8px）
- **Toast**：右下角滑入，3 秒自动消失，成功绿/失败红，替代部分 flash 消息（flash 保留为兜底）
- **抽屉**：右侧滑入，0.3s ease-out；桌面 560px 宽，移动端（<768px）全屏；背景遮罩 `rgba(0,0,0,.4)`
- **表格**：表头浅灰底，行 hover 浅蓝底，行高 48px，单元格垂直居中

### 2.3 字体与图标（离线化方案）

| 资源 | 方案 |
|------|------|
| 字体栈 | `'Inter','Segoe UI','PingFang SC','Microsoft YaHei',sans-serif` —— **不内嵌中文 web 字体**（Noto Sans SC 全量 8MB+ 会撑爆离线包），Inter 仅用于拉丁字符，中文走系统字体，视觉差异极小 |
| Inter 字体 | 下载 woff2（约 100KB×2 字重）放 `static/fonts/`，`@font-face` 引入 |
| Lucide 图标 | 不引入完整库。从模板提取**用到的约 25 个图标**的 SVG 源码，做成 Jinja2 宏文件 `templates/macros/icons.html`（`{{ icon('bell') }}` 输出内联 SVG），零外部依赖 |

### 2.4 响应式断点

**布局容器**：`.main-content` 限宽 `1600px` + `margin: 0 auto` 居中，内边距 `24px 32px 48px`。
超出容器宽度的部分即页面两侧留白。1600px 的取值依据：双栏等宽时半栏约 760px，
8 列闭环矩阵（最小需求 540px）余量充足；同时避免宽屏上正文行被拉得过长影响阅读。

> 断点针对**视口宽度**，与容器限宽无关。以下断点在容器限宽之内仍然生效：

| 断点 | 行为 |
|------|------|
| ≥1280px 宽屏桌面 | 统计卡 6 列；概览主区左右两栏（焦点列表 **1 : 闭环矩阵 1**，等宽） |
| 1024–1279px 桌面 | 统计卡 6 列；**概览单栏堆叠**（矩阵 8 列在半栏放不开，转整行） |
| 768–1023px 平板 | 统计卡 3 列；概览单栏堆叠 |
| <768px 手机 | 统计卡 2 列；顶栏导航收进汉堡菜单；表格横滑或卡片化；抽屉全屏 |

---

## 3. 信息架构与页面设计

### 3.1 顶栏（所有页面共享，重写 `base.html`）

```
┌────────────────────────────────────────────────────────────┐
│ ◆ 督办系统 · 2026年8月28日 周五   [概览|任务|设置|用户管理*|系统设置*]  🔓暗色切换  🔔(红点)  [👤张三 ▾] 退出 │
└────────────────────────────────────────────────────────────┘
```

- 日期副标题显示当天日期（模板同款）
- `*用户管理/系统设置` 仅 admin 可见（沿用现有权限）
- 移动端：导航项收进汉堡按钮展开的下拉面板
- 深色切换：太阳/月亮图标互切，偏好存 `localStorage`，页面加载时 `<html>` 加 `dark` class，无闪烁
- 铃铛：红点显示未读数（复用现有 `/messages/unread-count` 轮询），点击开**消息抽屉**
- **与正文左对齐**：顶栏背景通栏铺满，但内部元素与 `.main-content` 左边缘对齐。
  实现上不改模板、不加 wrapper，直接用同样的左偏移当内边距：
  `padding: 0 max(32px, calc((100% - 1600px) / 2 + 32px))`
  —— `100%` 按父元素内容宽度解析（已剔除滚动条），与内容区基准一致；
  视口 ≤1600px 时取 32px，与内容区内边距相同。移动断点另有 `0 14px` 覆盖。

### 3.2 仪表盘（重写 `templates/dashboard/overview.html`）

```
┌─ 时间范围下拉 [全部|本年|本季|本月|本周] ────────────────────┐
│ [任务总数] [待启动] [进行中] [已逾期] [已闭环] [闭环率]   ← 6 统计卡，可点击
├──────────────────────┬───────────────────────┤
│ 今日督办焦点（滚动列表） │ 任务闭环矩阵（按 Owner）      │
│  排序：已逾期>进行中>待启动 │  列：负责人|任务数|5 态|闭环率（共 8 列）│
│  每行：标题+状态药丸+到期日│  行：负责人，点名字开 Owner 抽屉   │
│  点击 → 任务详情抽屉     │  点数字 → 跳任务列表带筛选      │
└──────────────────────┴───────────────────────┘
```

- **时间范围口径**：按任务 `created_at`（创建时间）过滤，"本月"= 当月 1 号至今
- **统计卡点击**：跳 `/tasks?status=待启动` 等（闭环率卡跳全部）
- **闭环率口径（Q9）**：`closed ÷ (total − cancelled)`，分母为 0 时显示 `—`
- **焦点列表**：取非终态任务按 `已逾期 > 进行中 > 待启动` 再按到期日升序，最多 20 条
  - **限高 536px**（`.focus-list { max-height: 536px; overflow-y: auto }`），
    超出后列表内部滚动，约可见 8 条（条目高约 68px = 12×2 padding + 两行文字）
  - 另有 `padding: 8px; margin: -8px`：给 hover 的外扩阴影留出不被 `overflow` 裁掉的余量，
    再用负 margin 把视觉位置拉回原处
  - ⚠️ 这个值会**间接决定两栏的最终高度**：焦点卡通常是较高的一侧（约 644px），
    等高布局下矩阵卡被拉到同高。改它要重新评估矩阵侧的底部留白。
- **闭环矩阵**：按 assignee 分组统计**任务数 + 5 态数量 + 闭环率**，按任务数降序，每页 8 人分页
  - 共 8 列：**负责人 / 任务数 / 待启动 / 进行中 / 已逾期 / 已闭环 / 已撤销 / 闭环率**
  - 表头用**完整状态名**（`待启动` 而非 `待启`），避免缩写带来的歧义
  - 列宽兜底：负责人列 `min-width: 92px`、其余列 `min-width: 64px`，表格整体 `min-width: 540px`；
    宽度不足时横向滚动，不裁切文字
  - **分页改为 AJAX 原地刷新**（与任务列表同法）：`initPaginationAjax` 拦截 `.pagination a`，
    找到最近的带 `id` 祖先容器（矩阵页即 `#matrix-card`）作为作用域，`fetch` 新页后只替换该容器
    **内部**，滚动位置保持不变（既不回顶也不到底）。
    配套 `#matrix-card { scroll-margin-top: calc(var(--topbar-height) + 16px) }` 仍保留，
    但矩阵分页已不走锚点整页跳转，仅作备用。
  - 矩阵卡片仍保留 `id="matrix-card"`（CSS / 作用域定位需要），但分页链接不再带 `#matrix-card` 锚点。
- 原「我的待办」区块并入焦点列表（当前用户的任务加"我的"小标记）

**两栏等高**：`.dash-layout` 用 `align-items: stretch`（默认值），两张卡片拉伸到同一高度。
等高后较矮的一张底部会空出一截，因此卡片本身改为纵向 flex 容器
（`.dash-layout > .card { display: flex; flex-direction: column }`），
便于分配这部分空间。两侧策略不同：

- **焦点列表** `flex: 1 1 auto` —— 可伸缩。当矩阵卡较高时列表跟着变高（上限由自身 `max-height: 536px` 约束）
- **矩阵表格区** `flex: 1 1 auto; min-height: 488px` —— 高度锁死为「满页 8 行」，
  行数怎么变它都不动，紧贴其后的分页按钮位置也就固定了
- **分页** 保持全局的 `margin-top: 20px`：因为表格区高度恒定，
  按钮自然就固定在同一个位置，无需 `margin-top: auto` 钉底
  （钉底反而会在表格和按钮之间裂开一块随行数变化的空白）

**矩阵侧采用固定行高 + 固定表格区高度**（最终方案），而不是让表格拉伸去消化留白：

```css
.matrix-table thead th { height: 40px; padding: 0 16px; }
.matrix-table tbody td { height: 56px; padding: 0 16px; vertical-align: middle; }
.dash-layout > .card .matrix-scroll { flex: 1 1 auto; min-height: 488px; }
```

**为什么不拉伸**：拉伸会让空白平均分给每行，行数越少每行分到越多 ——
只剩 1~2 行时单行会被拉到几百像素高；更关键的是**翻页时行数一变，行高就跟着变**。

**为什么光固定行高还不够**：行高固定后表格总高仍随行数变化
（1 行 96px vs 8 行 488px），紧贴其后的分页按钮会跟着上下跑。
所以还要把**表格区高度锁死为满页高度** 488px，空白留在表格区内部。

**写法要点**：用 `height` 锁定 + `padding: 0` + `vertical-align: middle` 居中，
而不是靠 padding 撑高 —— padding 撑出来的是「最小值」，内容一变就会被顶开。
数值依据：自然行高约 45px（字号 14 × 行高 1.5 = 21 + 上下 padding 24）；
取 56px 是因为 8 行满页时正好填满（40 + 8×56 = 488），底部几乎不留白。

**翻页稳定性**（行高 56 / 表格区锁 488 / 焦点卡 644）：

| 行数 | 表格高 | 表格区 | 区内空白 | 卡片高 | 按钮 Y 偏移 |
|---:|---:|---:|---:|---:|---:|
| 1 | 96 | 488 | 392 | **648** | **616** |
| 2 | 152 | 488 | 336 | **648** | **616** |
| 4 | 264 | 488 | 224 | **648** | **616** |
| 6 | 376 | 488 | 112 | **648** | **616** |
| 8 | 488 | 488 | 0 | **648** | **616** |

→ **行高、表格区、卡片高、按钮位置全部恒定**，
翻页时唯一变化的只有「最后一行之下、表格区之内」的空白。眼睛不用重新找按钮。

> ⚠️ 内容区必须用 `flex: 1 1 auto`（保留 `flex-basis: auto`）。
> 若写成 `flex: 1`（basis 归 0），卡片不再按内容撑高，焦点列表会被压矮、少显示好几条任务。

### 3.3 任务列表（重构 `templates/tasks/list.html`）

- 保留：关键词搜索、4 维筛选排序、分页、批量操作、CSV 导出、新建按钮
- 新增：**点行开任务详情抽屉**（行内操作按钮保留：状态流转/编辑/删除）
- 视觉：表格按 2.2 规范重做，优先级用彩色药丸（urgent 红 / high 橙 / medium 蓝 / low 灰）
- 批量操作改为选中后底部浮出操作条（模板风格），功能不变
- **分页改为 AJAX 原地刷新**（不再整页跳转）：`main.js` 的 `initPaginationAjax` 拦截
  `.pagination a` 点击，向上找到最近的带 `id` 祖先容器作为作用域（`#batch-form` 或 `#matrix-card`），
  `fetch` 拉取新一页后**只替换该容器内部**（表格+分页+分页信息），并用 `history.replaceState`
  更新地址栏、**不触发滚动**。因此翻页时滚动条位置完全不变（既不回顶也不到底）。
  批量操作同步改为**事件委托**，分页刷新后新生成的行照样可勾选/全选/提交。
  （`#task-table` / `#matrix-card` 的 `scroll-margin-top` 规则保留备用，但两处分页均已不走锚点。）

> 📌 **通用约定（定稿）**：要「翻页但不让滚动条乱跳」，**统一用 AJAX 原地刷新**，
> 别依赖锚点。锚点只在「目标元素下方有足够内容」时才稳；列表页 / 矩阵页底部内容都偏短，
> 整页跳转 + 锚点必然在「顶 / 底」间二选一跳变（目标下方不够高就跳底）。
> AJAX 方案下，分页链接的 `href` 不再带 `#xxx` 锚点（即使 JS 未生效退化成整页跳转，也只回顶、不会跳底）。

### 3.4 任务详情抽屉（新增，Q3 核心）

```
┌─────────────────────────────┐
│ ✕ 任务标题            [状态药丸] │
│ [详情] [过程证据] [阻塞记录] 3 页签 │
├─────────────────────────────┤
│ 页签1 详情：                  │
│  进度条 + 百分比（可拖/可输）     │
│  负责人|优先级|截止日|协同方|风险点 │
│  → 全部行内可编辑（点字段变输入框，│
│    失焦或回车保存，保存调 API）   │
│  状态流转按钮组（沿用现有状态机）   │
│  进度时间线（合并现有 progress_logs）│
│ 页签2 过程证据：text/link/file 条目│
│  + 添加表单（类型+内容）          │
│ 页签3 阻塞记录：open/resolved 条目 │
│  + 添加表单 + "标记解决"按钮      │
└─────────────────────────────┘
```

- **数据加载**：点行 → `fetch('/tasks/<id>/drawer')` 返回 HTML 片段 → 注入抽屉（不刷新页面）
- **行内编辑权限**：严格复用现有 `can_edit_task`（admin 全部可改；owner 只能改自己的任务，他人任务字段只读展示）
- **行内编辑保存**：`fetch POST /tasks/<id>/field`（新增接口，见 §5），改状态仍走现有 `/tasks/<id>/status`
- **file 类证据**：存文件名+可选链接（不真正上传文件，模板亦是如此）；真实文件上传列为非目标
- 原 `/tasks/<id>` 独立详情页**保留**：消息点击跳转、JS 失效降级、浏览器直链三种场景使用，视觉同步重做

### 3.5 Owner 抽屉与推送提醒（Q8）

- 闭环矩阵点负责人名字 → Owner 抽屉：该负责人全部任务列表（复用详情抽屉骨架）+ 顶部「推送提醒」按钮（仅 admin 可见）
- 点击推送提醒 → 调 `POST /tasks/remind`（传 owner_id 或 task_id）→ 后端给该 Owner 发一条站内提醒消息（type=`admin_directive`，复用现有消息系统）→ Toast「已提醒」

### 3.6 消息抽屉（替代独立消息中心页，Q4）

- 顶栏铃铛点击 → 右侧抽屉：最近 50 条消息（类型筛选下拉保留）+ 单条已读 + 「全部已读」
- 消息点击 → 已读 + 关抽屉 → 打开关联任务详情抽屉（无关联任务则跳仪表盘）
- admin 的「发送站内信」（C7 保留）：抽屉顶部「发消息」按钮 → 跳现有 `/messages/send` 页（视觉重做）
- `/messages` 独立列表页**移除**（路由 301 跳转到 `/dashboard`，防止旧链接 404）

### 3.7 登录页（重做 `templates/login.html`）

- 左半屏品牌区（系统名 + 一句话介绍 + 简洁插画色块），右半屏登录卡片
- 字段级校验：用户名为空/密码为空/账号不存在/密码错误分别提示（后端返回错误码，前端定位到字段下方红字）
- 「记住我」勾选：勾选后用户名写 cookie（30 天），下次自动填充
- 密码可见切换（眼睛图标）

### 3.8 其余页面（视觉重做，功能不变）

| 页面 | 动作 |
|------|------|
| 初始化向导 `setup.html` | 挂新底座（无顶栏版），卡片视觉对齐 |
| 新建/编辑任务表单 `form.html` | 新增 3 字段：进度%（0-100 数字输入）、风险点（文本域）、协同方（文本，逗号分隔多人）；其余不变 |
| 个人设置 `profile.html` | 卡片视觉对齐 |
| 用户管理 `users/manage.html` | 表格视觉对齐 |
| 系统设置 `settings/system.html` | 表单卡片对齐 |
| 错误页 `errors/*` | 简单对齐新底座 |

---

## 4. 数据模型变更

### 4.1 `tasks` 表新增 3 列（Q1=B）

```sql
ALTER TABLE tasks ADD COLUMN progress_percent INTEGER NOT NULL DEFAULT 0;  -- 进度% 0-100
ALTER TABLE tasks ADD COLUMN risk_note        TEXT;                        -- 风险点
ALTER TABLE tasks ADD COLUMN collaborators    TEXT;                        -- 协同方（逗号分隔姓名）
```

### 4.2 新增 `evidence` 表（过程证据，Q2=A）

```sql
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER NOT NULL,
    etype        TEXT    NOT NULL,        -- 'text' / 'link' / 'file'
    content      TEXT    NOT NULL,        -- 文字内容 / URL / 文件名
    created_by   INTEGER,
    created_at   TEXT    NOT NULL,
    FOREIGN KEY (task_id)    REFERENCES tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_task ON evidence(task_id);
```

### 4.3 新增 `blockers` 表（阻塞记录，Q2=A）

```sql
CREATE TABLE IF NOT EXISTS blockers (
    blocker_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER NOT NULL,
    content      TEXT    NOT NULL,        -- 阻塞描述
    status       TEXT    NOT NULL DEFAULT 'open',  -- 'open' / 'resolved'
    created_by   INTEGER,
    created_at   TEXT    NOT NULL,
    resolved_at  TEXT,                    -- 解决时间
    resolved_by  INTEGER,
    FOREIGN KEY (task_id)    REFERENCES tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_blockers_task ON blockers(task_id);
```

### 4.4 迁移策略（老数据库无缝升级）

在 `init_db()` 末尾追加 `_migrate_v2()`：

1. `CREATE TABLE IF NOT EXISTS evidence/blockers`（同首次建库，天然幂等）
2. 对 tasks 三列逐个 `PRAGMA table_info(tasks)` 检查列名，不存在则 `ALTER TABLE ADD COLUMN`（SQLite 支持 ADD COLUMN，秒级完成，数据不丢）
3. 迁移过程打日志，异常不中断启动

**权限规则**：evidence/blockers —— owner 可为自己的任务添加；admin 可添加、可标记解决（blockers resolved 状态仅 admin 或创建者本人可操作）；删除仅 admin。所有操作写进 progress_logs 时间线留痕（type 备注）。

---

## 5. 路由与 API 变更清单

### 5.1 新增

| 路由 | 方法 | 说明 |
|------|------|------|
| `/tasks/<id>/drawer` | GET | 返回抽屉 HTML 片段（Jinja 局部模板，含权限标记） |
| `/tasks/<id>/field` | POST | 行内编辑单字段保存（JSON 请求/响应），校验 can_edit_task + 字段白名单（title/description/priority/due_date/progress_percent/risk_note/collaborators/assignee） |
| `/tasks/<id>/evidence` | POST | 添加证据条目 |
| `/tasks/<id>/blockers` | POST | 添加阻塞记录 |
| `/tasks/<id>/blockers/<bid>/resolve` | POST | 标记阻塞解决 |
| `/tasks/remind` | POST | 推送提醒（admin，发站内信） |
| `/dashboard/data` | GET | 可选：仪表盘时间范围切换的局部刷新接口（也可整页跳转带 `?range=` 参数，开发时定） |

### 5.2 修改

| 路由 | 变更 |
|------|------|
| `/dashboard` | 接受 `?range=all|year|quarter|month|week` 参数；返回 6 卡统计 + 焦点列表 + 闭环矩阵数据 |
| `/tasks` | 行数据加 progress_percent/collaborators；接受 `owner=` 矩阵跳转参数（映射到 assignee 筛选） |
| `/tasks/new` `/tasks/<id>/edit` | 表单加 3 字段 |
| `/login` | 返回字段级错误码；处理「记住我」cookie |

### 5.3 移除/降级

| 路由 | 处理 |
|------|------|
| `/messages` | 301 → `/dashboard`（消息中心页由抽屉替代） |
| `/messages/send` `/messages/read-all` `/messages/unread-count` 等 | 全部保留，供抽屉调用 |

### 5.4 models.py 新增函数

- `get_dashboard_stats_v2(range)` — 按时间范围统计 6 卡
- `get_today_focus(range, user_id)` — 焦点列表（已逾期>进行中>待启动，到期日升序，限 20）
- `get_closure_matrix(range, page)` — 按 Owner 聚合 + 闭环率 + 分页
- `add_evidence / get_evidence_list`、`add_blocker / get_blockers / resolve_blocker`
- 现有函数全部保留不动（get_dashboard_stats 保留，V2 统计新开函数避免破坏旧测试）

---

## 6. 前端结构变更

| 文件 | 动作 |
|------|------|
| `templates/base.html` | **重写**：顶栏 + 深色切换 + 铃铛 + Toast 容器 + 抽屉容器（全局 3 个：任务详情/Owner/消息） |
| `templates/macros/icons.html` | 新增：Lucide SVG 宏（约 25 个图标） |
| `static/css/main.css` | **重写**：CSS 变量双套（§2.1）+ 组件类（§2.2），`html.dark` 切换深色 |
| `static/js/main.js` | **重写**：抽屉管理器（open/close/URL 同步）、行内编辑、Toast、深色切换、未读轮询 |
| `templates/dashboard/overview.html` | 重写（§3.2） |
| `templates/tasks/list.html` | 重写（§3.3） |
| `templates/tasks/_drawer.html` | 新增：抽屉局部模板（3 页签） |
| `templates/tasks/detail.html` | 视觉重做，功能保留 |
| 其余模板 | 视觉对齐改造 |

**不引入** 前端框架、构建工具、CDN 依赖 —— 仍是 Flask + Jinja2 + 原生 JS + 单 CSS 文件，保证 PyInstaller 离线打包零风险。

---

## 7. 开发批次与验收标准（阶段 3）

| 批次 | 内容 | 验收标准 |
|------|------|---------|
| 1 · UI 底座 | base.html 重写（顶栏/暗色/铃铛/Toast）+ main.css 重写 + 图标宏 + 登录页 + 字体离线化 | 所有现有页面挂新底座无布局错乱；深色切换全页面生效；旧 73 项测试全绿 |
| 2 · 仪表盘 | 6 统计卡 + 焦点列表 + 闭环矩阵 + 时间范围筛选 + 数据库加列迁移 | 数字与手写 SQL 核对一致；点击筛选正确跳转；老库启动自动迁移 |
| 3 · 抽屉交互 | 详情抽屉 3 页签 + 行内编辑 + Owner 抽屉 + 消息抽屉 + 推送提醒 | owner 不可编辑他人任务（权限回归）；行内编辑即时保存；消息页 301 |
| 4 · 功能补全 | 证据/阻塞记录完整 CRUD + 新建表单 3 字段 + 全页面视觉扫尾 | 证据/阻塞增查留痕；V1 全功能回归通过 |

每批完成即自测 + 汇报，批次 4 结束后进入阶段 4（全量测试 + 文档同步 + 重新打包）。

---

## 8. 测试与文档计划（阶段 4 预告）

- `test_suite.py`：保留全部 73 项（消息中心页相关用例改为断言 301 跳转），新增预计 25–30 项：闭环率口径（含撤销任务场景）、矩阵聚合、时间范围、行内编辑权限矩阵（admin×owner×4 字段）、证据/阻塞 CRUD 与权限、暗色模式 class、登录字段级错误、记住我 cookie
- 文档同步：PRD 增补 V2 章节、架构文档更新数据模型与路由表、test-cases-report.html 重新生成
- 交付：重新 PyInstaller 打包 + 发行 zip + 变更摘要

---

## 9. 非目标（本次明确不做）

1. 真实文件上传（file 证据只记文件名/链接）
2. 邮件通道（Q8 已确认站内信）
3. P0/P1/P2 三级优先级改造（Q7 保留四级）
4. 前后端分离/SPA 改造
5. 部门、来源会议、会议日期、任务资产 ID、引用原话字段（Q1=B 排除）
