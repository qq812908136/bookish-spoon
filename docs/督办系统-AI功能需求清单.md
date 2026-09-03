文档状态：v1.0 已锁定（Phase 0 实现中；锁定前未写业务代码）

# 督办系统 AI 功能需求清单（SPEC）

> 版本：v1.0（已锁定）
> 日期：2026-09-03
> 来源：基于《督办系统引入 AI 能力可行性评估》收口（产品经理 许清楚），经主理人齐活林按用户「Please continue」指令采纳默认建议后锁定
> 模块归属：独立旁路 AI 通道，严格镜像 V4 邮件子系统模式

> **已锁定决策（采纳可行性评估 §7 标注 ★ 的推荐默认）**：经评审，本 SPEC 正式锁定以下默认建议——① 首版 MVP 先落「催办话术 / 邮件草稿」；② 模型部署默认本地私有化（Ollama，零出域）；③ AI 功能默认仅管理员可用；④ AI 产物必须人工确认后才落库 / 发出。其余待确认项（Q3/Q6/Q7）随 Q2 本地优先默认一并锁定为零出域推进。文末《决策记录》为正式结论，取代原「待评审确认清单」。

---

## 1. 问题陈述

当前督办系统已具备 5 态状态机、3 层预警、站内信 + 邮件双渠道，但**内容生产仍完全依赖人工**，存在三处明确痛点：

| 编号 | 痛点 | 现状证据（来自代码） | 业务影响 |
|---|---|---|---|
| PR-1 | **催办话术手写、风格不一** | 3 层预警正文为写死模板（"将在 N 天后到期，请及时跟进""已逾期，请尽快处理"）；`task_remind` 仅生成套话；手动邮件仅能附 ≤200 字自由留言 | 管理员对逾期 / 即将到期任务反复措辞，费时且语气分寸难统一 |
| PR-2 | **任务描述散落、难检索难结构化** | `tasks.description` 为自由文本；`risk_note`/`collaborators` 为可选空字段；用户常把会议纪要 / 口头交代整段贴入"工作要求" | 负责人、截止日、协同方、风险点散落长文，无法检索、统计、预警利用 |
| PR-3 | **周期性汇报费时** | 管理员日报（`mail_dispatcher.enqueue_daily_reports`）为纯模板罗列逾期任务；**无周报**；统计靠人工拼装 | 周期性督办汇报占用管理精力，且可读性一般 |
| PR-4 | **风险感知滞后** | 当前仅有"已逾期"的事后预警，无事前风险信号；`blockers`/`progress_percent` 未被主动归纳 | 卡点 / 停滞任务要人工逐个翻看才能发现 |

**为什么现在做 AI**：
- V4 已跑通「落库队列 + 复用 5 分钟扫描 + 密钥加密 + 熔断」的成熟管道（邮件子系统），AI 可直接镜像复用，认知与维护成本最低；
- 客户内网常无出网，本地私有化模型（Ollama）使"零出域"成为合规最优解，且离线 exe 定位与之天然契合；
- 现有 212 项回归测试为"改动不破坏主流程"提供了护栏，适合引入旁路式增强。

---

## 2. 拟定方案

### 2.0 总体策略

AI 一律定位为「**建议 / 草稿 / 预填**」层：**生成结果只用于展示或预填表单，人工确认后才落库或经既有双渠道发出**；绝不自动改状态、绝不自动发消息。所有调用经队列异步化，不在请求线程内同步等 LLM。

### 2.1 Phase 0 — 技术验证（零出域，打通管道）

| 项 | 内容 |
|---|---|
| **目标** | 验证"现有单体架构挂 AI"全链路可行：队列 + 5 分钟扫描 + 脱敏 + 密钥加密 + 熔断，全程不出域 |
| **涉及模块** | `ai_service.py`(local) / `ai_dispatcher.py` / `ai_templates.py` / `models._migrate_v4()` / `routes/ai_routes.py` / `config.py`(AI_*) / `.env.example`(AI_*) |
| **关键场景** | **任务智能摘要**：取「描述 + 进度 + 证据 + 阻塞」→ 生成一段中文摘要，存 `evidence(etype='ai_summary')` + 站内信通知（类型 `ai_summary_ready`） |
| **验证** | 内部 demo 库跑通全链路；**212 项既有测试不受影响**；**离线断网（本地 Ollama）也能跑** |
| **回滚** | `AI_ENABLED=false` 即完全关闭，队列停扫，对主流程零副作用 |

### 2.2 Phase 1 — 试点（落地三件 MVP，默认仅管理员）

> 落地顺序（已锁定）：**先「催办话术 / 邮件草稿」**，再「描述结构化抽取」，再「督办简报 / 周报」。

| 项 | 内容 |
|---|---|
| **目标** | 真实价值验证；AI 功能默认仅管理员可用（已锁定） |
| **涉及模块** | `ai_service.py` 补 `cloud` 端点（stdlib `http.client` 写 OpenAI 兼容客户端）；`ai_templates.py` 补 Prompt（催办话术 / 描述结构化 / 督办简报） |
| **关键场景** | ① **催办话术 / 邮件草稿**（预填发送框，**确认后**经现有站内信 + 邮件发出）② **描述结构化抽取**（从自由文本抽取负责人 / 协同方 / 风险点 / 建议优先级，预填表单，**确认后** `create_task`）③ **督办简报 / 周报**（按筛选维度汇总，复用现有双渠道投递） |
| **验证** | 试点单位小范围；监控 token 成本与延迟；`ai_log` 审计抽样；催办话术采纳率埋点 |
| **回滚** | 配置切回 `local` / `false` + 清空 `ai_queue`；未确认产物不落库 |

### 2.3 Phase 2 — 扩展（融入日常督办节奏）

| 项 | 内容 |
|---|---|
| **目标** | 把 AI 融入既有流程，提升日常效率 |
| **涉及模块** | 复用 `warning_engine` / `mail_dispatcher` 日报通道做「AI 督办简报」；强化限流 / 熔断；脱敏白名单可配；引入自然语言查询（只读） |
| **关键场景** | AI 督办简报（高风险任务 + 建议动作）、批量任务摘要、风险提示、**自然语言查询 / 报表**（只读："本月逾期最多的是谁"→ 转查询并以表格 / 摘要呈现，答案须可追溯到具体任务） |
| **验证** | 性能 / 成本监控看板；熔断演练（断网 / 错误 key 时系统不卡）；NL 查询结果可溯源校验 |
| **回滚** | 降级到非 AI 简报（`AI_ENABLED=false` 时日报退回原纯文本统计）；NL 查询关闭不影响筛选器 |

### 2.4 Phase 3 — 远景（可选，合规允许时）

| 项 | 内容 |
|---|---|
| **目标** | 智能化进阶 |
| **涉及模块** | 本地向量检索基建（RAG）、多模型路由调度 |
| **关键场景** | 本地任务库智能问答（RAG，零出域）、多模型路由（按场景选本地 / 云端）、自动调度建议（仅建议、不改状态机） |
| **验证** | 合规放行后试点；RAG 答案可引述任务原文 |
| **回滚** | 关闭对应 job_type 即退回 Phase 2 能力 |

---

## 3. 技术约束

> 全部约束镜像 V4 邮件子系统，降低认知与维护成本；违规即视为破坏铁律。

| 编号 | 约束项 | 要求 | 依据 |
|---|---|---|---|
| TC-1 | 管道模式 | 镜像「落库队列 + 复用 5 分钟扫描 + 密钥加密 + 熔断」 | V4 `mail_dispatcher` / `mail_service` |
| TC-2 | 新增模块 | `ai_service`(传输) / `ai_dispatcher`(队列+调度) / `ai_templates`(Prompt 构建+脱敏) / `ai_routes`(配置页+触发+展示) | 镜像 `mail_*` 四件套 |
| TC-3 | 线程模型 | **不新增任何线程 / 进程**；AI 扫描由 `scheduler` 现有 5 分钟循环调用 | 铁律：exe 内零新增线程 |
| TC-4 | 站内信边界 | **不改 `models.create_message()`**；AI 仅作为调用方写通知（类型如 `ai_summary_ready`） | 铁律④（同邮件） |
| TC-5 | 状态机边界 | **不碰 5 态状态机**；AI 摘要 / 建议只展示与预填，绝不自动改 `tasks.status` 或调 `change_task_status()` | 防 Prompt 注入越权写 |
| TC-6 | 依赖 | **零新增依赖**，用标准库 `http.client` 自写极简客户端（不引入 `requests` / `openai`） | 契合 `crypto_util` 零依赖哲学；避免四处重打包 |
| TC-7 | 总开关 | `AI_ENABLED` 默认 `false`；不配置 = 行为完全不变 | 沿用 V4 `MAIL_ENABLED` 铁律 |
| TC-8 | 摘要存储 | 不新建 `tasks` 列；复用 `evidence(etype='ai_summary')` 存摘要正文 | 避免动 `tasks` 表；与现有证据 UI 融合 |
| TC-9 | 数据表 | 新增 `ai_queue` / `ai_log`（幂等迁移，照搬 `_migrate_v3()` 套路，老库自动升级不丢数据） | 增量、低风险 |
| TC-10 | 密钥管理 | `AI_API_KEY` 复用 `crypto_util` 加密入库（同 SMTP 密码）；**密钥绝不进日志 / 页面 / 错误文本** | 安全硬约束 |
| TC-11 | 脱敏 | `AI_MASK_DATA` 默认 `true`；拼装 Prompt 前替换专名（标题→任务#id、人名→负责人/创建人），模型侧只见脱敏文本 | 合规默认开 |
| TC-12 | 注入防护 | 系统提示与用户内容严格分离；模型输出只用于展示 / 预填，绝不自动执行写操作；渲染前转义防 XSS | 安全硬约束 |
| TC-13 | 熔断 / 降级 | AI 持续不可用 → 熔断暂停 + 系统正常（用户见"AI 暂不可用"），绝不拖垮主流程；失败 silently 降级到无 AI | 同 V4 失败可见原则 |

### 3.1 新增配置项（沿用 `env > .env > 库 > 默认`，`AI_ENABLED` 默认 `false`）

| 键 | 含义 | 默认 |
|---|---|---|
| `AI_ENABLED` | 总开关 | `false` |
| `AI_PROVIDER` | `local` / `cloud`（OpenAI 兼容） | `local` |
| `AI_API_BASE_URL` | 端点（本地 `http://127.0.0.1:11434`，云端国内模型 `https://...`） | 空 |
| `AI_API_KEY` | 密钥（env/.env 明文 或 db 加密，复用 `crypto_util`） | 空 |
| `AI_MODEL` | 模型名（`qwen2.5:7b` / 国内模型名） | 空 |
| `AI_TIMEOUT` | 单次调用超时（秒） | `30` |
| `AI_BATCH_LIMIT` | 每轮最多处理几单（仿 `MAIL_BATCH_LIMIT`） | `5` |
| `AI_MASK_DATA` | 脱敏开关（仿 `MAIL_MASK_TITLE`） | `true` |
| `AI_RETRY_MAX` / `AI_RETRY_BACKOFF` / `AI_CIRCUIT_FAIL_THRESHOLD` / `AI_CIRCUIT_PAUSE_MINUTES` | 重试与熔断（仿邮件） | 同邮件默认 |
| `AI_LOG_RETENTION_DAYS` | 审计日志保留 | `90` |

### 3.2 调用边界（与现有模块耦合关系）

```
请求方(管理员按钮 / 定时扫描)
   │  enqueue_ai_job(task_id, job_type, operator_id)
   ▼
ai_dispatcher ──写──▶ ai_queue (SQLite, 复用 db.transaction 全局写锁)
   │  仅依赖: config / models / db / crypto_util（不碰 routes/mail 内部）
   ▼  (由 scheduler 每5分钟调用, 不新增线程)
scan_and_run() → ai_service.call_model(prompt)
   ▼
ai_service ──HTTP(stdlib http.client)──▶ 本地 Ollama / 云端模型 API
   ▼
成功: 结果存 ai_log + 作为 evidence(etype='ai_summary') 归档 + 以调用方身份写站内信通知
失败: 重试 / 熔断 / 归档(同邮件逻辑)
```

---

## 4. 非目标

| 编号 | 不做的事 | 原因 |
|---|---|---|
| NG-1 | **AI 自动流转状态机**（如"AI 判定该任务逾期→自动置 overdue"） | overdue 由扫描引擎按日期判定，AI 介入破坏单一可信源 |
| NG-2 | **AI 自动发送催办 / 邮件 / 站内信**（不经确认） | 失控且无审计；必须人工点「确认发送」（已锁定） |
| NG-3 | **用 AI 替代站内信 / 邮件双渠道** | AI 是内容生成层，触达仍走既有双渠道 |
| NG-4 | **在请求线程内同步阻塞等 LLM** | 会冻住 UI；全部队列化异步 |
| NG-5 | **境外模型（OpenAI / Claude）默认提供** | 数据出域 = 出内网 / 出境风险；优先国内模型，境外不推荐（已锁定） |
| NG-6 | **引入通用 ChatBot** | 与督办业务脱节、token 浪费、幻觉风险 |
| NG-7 | **新建独立 tags / 分类数据模型** | 用现有 `collaborators` / `risk_note` / `priority` 字段承载，控制迁移成本 |
| NG-8 | **无脱敏地把站内数据外传到不可控第三方** | 数据合规红线 |

---

## 5. 成功标准

> 每阶段通过条件须可验证、可回归；任何阶段 `AI_ENABLED=false` 时系统行为须与未引入 AI 前完全一致。

| 阶段 | 通过条件（可验证） |
|---|---|
| **Phase 0** | ① 离线断网（仅本地 Ollama）全链路跑通；② **212 项既有测试不受影响**；③ `AI_ENABLED=false` 时零副作用（无新线程、无新表写入、无报错）；④ 队列 + 5 分钟扫描 + 脱敏 + 密钥加密 + 熔断 五项机制 demo 通过；⑤ `ai_queue` / `ai_log` 幂等迁移在老库上升级成功 |
| **Phase 1** | ① 三件 MVP 均仅管理员可用（已锁定）；② 催办话术预填后**确认**才发出，未确认不落库；③ 描述结构化抽取预填表单后**确认**才 `create_task`；④ 督办简报 / 周报可生成并经双渠道投递；⑤ `ai_log` 审计抽样通过（含 `is_data_egress`、token 数、操作人）；⑥ token / 延迟监控看板可用；⑦ 采纳率埋点（采纳 / 忽略 / 重生成）生效 |
| **Phase 2** | ① 自然语言查询为**只读**，答案可追溯到具体任务（带链接），无编造数字；② 预警文案润色"增强模式"可关（`AI_ENABLED=false` 退回原模板）；③ 批量简报在模型不可用时干净降级；④ 熔断演练：断网 / 错误 key 时系统不卡、主流程正常 |
| **Phase 3** | ① RAG 问答零出域、答案可引述任务原文；② 多模型路由按场景正确选路；③ 自动调度建议仅展示、不改状态机 |

---

## 附录：决策记录（已锁定）

> 以下为 v1.0 正式锁定结论（采纳可行性评估 §7 标注 ★ 的推荐默认）。

- **Q1 首版场景优先级**：锁定 **A. 催办话术 / 邮件草稿先落地**（最贴合 3 层预警，复用双渠道，价值快显）。
- **Q2 模型部署形态**：锁定 **A. 本地私有化（Ollama，零出域，合规最优）**。
- **Q3 数据出域合规**：随 Q2 锁定为 **A. 不允许督办数据出域内网（零出域推进）**；若未来需云端，须另行合规审批。
- **Q4 使用对象范围**：锁定 **A. 仅管理员**（Phase 0/1 默认仅管理员）。
- **Q5 人工确认强度**：锁定 **A. 必须确认**（安全优先，AI 产物经人点「确认」才落库 / 发出）。
- **Q6 本地推理算力**：锁定 **A. 接受同机 / 同局域网跑一个本地推理服务（Ollama）**（exe 之外独立进程，不违反 exe 内零线程铁律）。
- **Q7 预算（若用云端）**：锁定 **A. 设月度预算上限 + 成本看板**（仅云端场景适用；当前零出域默认不触发）。

---

*本 SPEC 已锁定（v1.0）。Phase 0 基础设施骨架实现中；任何代码落子均在此 SPEC 框架内。*

---

## 实施进度（追加记录，不影响已锁定内容）

### Phase 0 — 已完成（2026-09-03，已提交推送）

基础设施骨架全部落地，严格镜像 V4 邮件子系统模式：

- `src/ai_templates.py`：提示词构建 + 送模前脱敏（手机号 / 邮箱 / 证件号）
- `src/ai_service.py`：零新增依赖（标准库 `urllib`）的本地 Ollama / 云端 OpenAI 兼容通道，错误信息脱敏（不含 API Key）
- `src/ai_dispatcher.py`：落库队列 + 复用 5 分钟扫描（零新增线程）+ 双重熔断 + 重启 sending→pending
- `src/routes/ai_routes.py` + `templates/ai/settings.html` / `result.html`：管理员控制台 + 触发 + 结果查看 + **人工确认采纳闸**（adopt 才发站内信）
- `src/models.py`：`_migrate_v4()` 幂等建 `ai_queue` / `ai_log`；新增 AI 队列 CRUD 与熔断状态函数
- `src/config.py`：`AI_*` 配置块（默认 `AI_ENABLED=false`，零副作用）；`src/scheduler.py` 5 分钟循环挂载 `ai_dispatcher.scan_and_run()`；`routes/__init__.py` 注册 `ai_bp`；`.env.example` 增补 AI 段

**验证**：

- 本地专属 17 项行为校验全过（默认关闭安全、脱敏、入队→生成→落库、熔断+密钥脱敏、熔断期暂停、人工确认闸）。
- 全量测试 **161 项全过**（0 失败 0 错误）；`AI_ENABLED=false` 时零副作用（无新线程 / 无新表写入 / 无报错）。

### Phase 1 ② — 催办话术「页面内预填 + 可编辑 + 确认发出」（已完成，2026-09-03，已提交推送，远端 main = c05e306f7f）

在 Phase 0 后端（触发 → 入队 → 生成 → 人工确认采纳）之上，把入口从「AI 控制台」下放到「任务详情页」，并支持生成后立即在页面内预填、可编辑、确认后才发出：

- `src/routes/ai_routes.py`：`/ai/trigger` 新增 `source=detail` 分支——详情页入口**同步生成并立即跳回详情页预填**，免去等 5 分钟扫描；`/ai/adopt` 支持接收 `content` 字段（页面内编辑后的内容）覆盖原稿，并支持 `next=detail` 确认后跳回详情页。空内容拒绝采纳，不发出空站内信。
- `src/ai_dispatcher.py`：新增 `run_job_now(queue_id)`——同步运行刚入队的单条任务并落 `ai_log`（失败以 `retry_max=0` 直接归档，方便页面回显错误），复用 `_run_one` 保证调模型/落库逻辑只在一处。
- `src/models.py`：`mark_ai_job_done` / `mark_ai_job_failed` 改为返回 `ai_log.log_id`；新增 `fetch_ai_job(queue_id)`。
- `src/routes/task_routes.py`：`task_detail` 读取 `?ai_log_id=` 并注入 `ai_enabled` / `can_use_ai` / `ai_log`。
- `src/templates/tasks/detail.html`：新增「AI 催办话术」卡片（管理员 + 已启用 AI 可见），三态：未生成→「生成催办话术」；已生成→可编辑文本框 + 「确认发送给负责人」；失败→回显错误 + 「重新生成」。所有 POST 表单均带 CSRF 令牌。

**验证**：

- 新增 `tests/test_suite.py::TestAIDraftReminder` 用例：入口渲染权限（管理员可见 / owner 不可见 / 未启用不可见）、生成后预填可编辑文本域、确认采纳把（编辑后）内容作为站内信发出、空内容拒绝、生成失败回显错误并可重生成。
- 全量测试通过（含上述新增用例）；`AI_ENABLED=false` 时详情页不渲染 AI 卡片，零副作用。

**下一步**：Phase 1 剩余 MVP —— 任务描述结构化抽取预填、督办简报 / 周报（仍仅管理员可用、仍须人工确认）。

### Phase 1 PR-2 — 任务描述结构化抽取预填（已完成，2026-09-03，已提交推送）

把 PR-2 从「自由文本」一键抽取为任务草稿字段，并**复用既有「新建任务」表单预填**，管理员核对后才点「创建任务」落库。AI 模块不碰 `create_task`（仅由 `task.task_new` 调用它），满足 SPEC 人工确认闸：

- `src/ai_templates.py`：新增 `build_structured_task_prompt(text)`（要求模型输出 JSON：title/priority/due_date/risk_note/collaborators/description，明确不臆造负责人）+ `parse_structured_task(text)`（去 ```json 围栏、截取首个 `{...}`、容错解析、优先级归一化到 `high/medium/low/urgent`、`due_date` 校验 `YYYY-MM-DD`，失败回 `None` 由调用方退化）。
- `src/routes/ai_routes.py`：新增 `GET/POST /ai/draft`（粘贴自由文本 → 同步生成）与 `GET /ai/draft/<log_id>`（展示结构化草稿）。`/ai/draft` 的 POST 复用 `ai_dispatcher.run_job_now()` 同步生成；`/ai/draft/<log_id>` **直接渲染 `tasks/form.html`** 并把抽取结果作为 `form_data` 预填——确认动作仍由 `task.task_new` 处理（仅调用 `create_task`，AI 不改动它）。生成失败 / 解析失败时退化为「把错误原文放进 description」的人工录入，仍由管理员补全后确认，**绝不自动建档**。
- `src/templates/ai/draft_input.html`：新增粘贴入口页（textarea `raw_text` + CSRF，提交到 `/ai/draft`），含「仅预填草稿、需人工核对后再建档」提示。
- 未新建 `ai/draft_task.html`：刻意复用 `tasks/form.html`，避免与既有建任务表单重复、保证将来表单改动能自动受益。

**验证**：

- 新增 `tests/test_suite.py::TestAIStructuredTaskDraft` 用例：管理员入口渲染（启用可见 / 未启用跳控制台 / owner 403）、提交后预填进建任务表单（标题/优先级选中/截止日/协同方/风险点/描述均预填、action 指向 `/tasks/new`）、确认后走 `task.task_new` 正常建档（字段与提交一致、`create_task` 未被 AI 改动）、生成失败回退人工录入（错误进 description、不自动建档）。
- 全量测试通过（含上述新增用例）；`AI_ENABLED=false` 时 `/ai/draft` 跳回控制台、零副作用。

**下一步**：Phase 1 剩余 MVP —— 督办简报 / 周报（PR-3），仍仅管理员可用、仍须人工确认。
