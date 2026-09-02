"""mail_templates.py — 邮件正文渲染（V4 迭代）

四套模板（E 组决策）：
    1. 逾期提醒（发给负责人，同一人的多个逾期任务**合并成一封** —— F2-②）
    2. 任务分配 / 改派通知（C5-①：任务生命周期的起点，漏了就是漏了）
    3. 管理员日报（D2-②：按负责人分组，回答"谁拖得最多"）
    4. 手动提醒（C3-①：固定模板 + 操作人留言，H4-②）

统一约定：
    - 纯文本 text/plain，UTF-8（N-4，HTML 邮件更易进垃圾箱）
    - 主题带固定前缀 [督办系统]，便于收件人设过滤规则（E1-①）
    - 主题中的任务标题超 20 字截断，避免手机端被截掉关键信息
    - 正文末尾固定引导语 + 可配落款 MAIL_FOOTER（E5-①）
    - 不放任何链接（E3-②），因此无需 SITE_URL 配置项

脱敏（H5-②）：
    MAIL_MASK_TITLE 开启后，邮件里不显示完整任务标题，
    只显示「任务 #123」。默认关闭。
"""

import models
import mail_constants

# 主题里任务标题的最大长度（超过则截断加省略号）
TITLE_MAX_LEN = 20

# 正文固定引导语（E3-② 不放链接，用文字引导代替）
GUIDE_LINE = '请登录督办系统查看详情。'


def _truncate(text, limit=TITLE_MAX_LEN):
    """截断文本，超长加省略号。"""
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    return text[:limit] + '…'


def _title_of(task, mask_title=False):
    """按脱敏开关返回任务标题。"""
    if mask_title:
        return f'任务 #{task["task_id"]}'
    return task['title']


def prepare_task(task):
    """把任务行规整成可直接用于渲染的 dict。

    做两件事：
    1. sqlite3.Row 不支持 .get()，转 dict 后渲染代码可以无差别取值；
    2. 补齐 assignee_name / creator_name —— models.get_task() 返回的行
       不含这两个 join 出来的列（日报专用查询才有），缺了会显示成 "-"。
       这里缺哪个就按需查一次用户表；邮件是低频批量动作，这点开销无所谓。

    Args:
        task: sqlite3.Row 或 dict

    Returns:
        dict
    """
    if isinstance(task, dict):
        d = dict(task)
    else:
        d = {k: task[k] for k in task.keys()}

    if not d.get('assignee_name') and d.get('assignee'):
        u = models.get_user(d['assignee'])
        d['assignee_name'] = u['display_name'] if u else '-'
    if not d.get('creator_name') and d.get('created_by'):
        u = models.get_user(d['created_by'])
        d['creator_name'] = u['display_name'] if u else '-'
    return d


def priority_label(priority):
    """优先级中文名（与前端保持一致）。"""
    return {'high': '高', 'medium': '中', 'low': '低'}.get(priority, priority or '中')


def _footer(cfg):
    return (cfg.get('footer') or '本邮件由督办系统自动发送，请勿直接回复。').strip()


def overdue_days(task, today):
    """计算已逾期天数（最小为 1，即刚逾期当天）。"""
    from datetime import datetime
    try:
        due = datetime.strptime(task['due_date'], '%Y-%m-%d').date()
        now = datetime.strptime(today, '%Y-%m-%d').date()
        days = (now - due).days
        return days if days >= 1 else 1
    except (ValueError, TypeError, KeyError):
        return 1


def _task_block(task, mask_title=False, today=None, show_title=True):
    """渲染单个任务的正文块（逾期/手动提醒场景用）。

    Args:
        show_title: 是否输出「任务：xxx」这一行。合并邮件里标题已经
                    作为序号行的前缀输出了，这里就不重复。
    """
    title = _title_of(task, mask_title)
    days = overdue_days(task, today) if today else 1

    lines = []
    if show_title:
        lines.append(f'  任务：{title}')
    lines.extend([
        f'  负责人：{task.get("assignee_name") or "-"}',
        f'  截止日期：{task["due_date"]}（已逾期 {days} 天）',
        f'  优先级：{priority_label(task.get("priority"))}',
        f'  创建人：{task.get("creator_name") or "-"}',
    ])
    return '\n'.join(lines)


# ============================================================
# 1. 逾期提醒（合并）
# ============================================================

def render_overdue_subject(tasks, mask_title=False):
    """逾期提醒邮件主题（E1-①）。

    单任务：`[督办系统] 任务逾期提醒：{标题}`
    多任务：`[督办系统] 任务逾期提醒：您有 N 项任务已逾期`
    """
    if len(tasks) == 1:
        return f'[督办系统] 任务逾期提醒：{_truncate(_title_of(tasks[0], mask_title))}'
    return f'[督办系统] 任务逾期提醒：您有 {len(tasks)} 项任务已逾期'


def render_overdue_grouped(recipient_id, tasks, cfg=None, mask_title=False, today=None):
    """渲染逾期提醒正文（一个收件人 + 他的全部逾期任务）。

    Args:
        recipient_id: 收件人 user_id（用于取姓名）
        tasks: 该收件人名下的逾期任务列表
        cfg: 邮件配置（取落款用）
        mask_title: 标题脱敏开关
        today: 今天日期 YYYY-MM-DD

    Returns:
        str: 邮件正文
    """
    if cfg is None:
        cfg = models.get_mail_config()
        mask_title = mask_title or bool(cfg.get('mask_title'))
    if today is None:
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')

    tasks = [prepare_task(t) for t in tasks]

    user = models.get_user(recipient_id)
    name = user['display_name'] if user else '同事'

    lines = [f'您好，{name}：', '']

    if len(tasks) == 1:
        lines.append('您有 1 项任务已逾期，请尽快处理：')
    else:
        lines.append(f'您有 {len(tasks)} 项任务已逾期，请尽快处理：')
    lines.append('')

    for idx, task in enumerate(tasks, 1):
        if len(tasks) > 1:
            lines.append(f'{idx}. {_title_of(task, mask_title)}')
            lines.append(_task_block(task, mask_title, today, show_title=False))
        else:
            lines.append(_task_block(task, mask_title, today))
        lines.append('')

    lines.append(GUIDE_LINE)
    lines.append('')
    lines.append(f'—— {_footer(cfg)}')
    return '\n'.join(lines)


# ============================================================
# 2. 任务分配 / 改派通知
# ============================================================

def render_assign_subject(task, mask_title=False):
    return f'[督办系统] 新任务分配：{_truncate(_title_of(task, mask_title))}'


def render_assign(task, operator_name, cfg=None, mask_title=False, is_transfer=False):
    """渲染任务分配 / 改派通知正文（C5-①）。

    Args:
        task: 任务行
        operator_name: 操作人（创建人 / 改派人）显示名
        is_transfer: True 表示改派，False 表示新建分配
    """
    task = prepare_task(task)
    if cfg is None:
        cfg = models.get_mail_config()
        mask_title = mask_title or bool(cfg.get('mask_title'))

    user = models.get_user(task['assignee'])
    name = user['display_name'] if user else '同事'
    action = '把任务转交给你' if is_transfer else '向你分配了新任务'

    lines = [
        f'您好，{name}：',
        '',
        f'{operator_name} {action}：',
        '',
        f'  任务：{_title_of(task, mask_title)}',
        f'  负责人：{name}',
        f'  截止日期：{task["due_date"]}',
        f'  优先级：{priority_label(task.get("priority"))}',
        '',
        GUIDE_LINE,
        '',
        f'—— {_footer(cfg)}',
    ]
    return '\n'.join(lines)


# ============================================================
# 3. 管理员日报
# ============================================================

def render_daily_report_subject(count):
    return f'[督办系统] 督办日报：今日 {count} 项逾期任务'


def get_overdue_tasks_for_report():
    """取得日报所需的逾期任务（含负责人/创建人姓名，按负责人、截止日期排序）。"""
    return models.get_overdue_tasks_with_names()


def render_daily_report(tasks, cfg=None, mask_title=False, today=None):
    """渲染管理员日报正文（E6-②：按负责人分组）。

    Args:
        tasks: 逾期任务列表（应已按负责人排序）
        cfg: 邮件配置
        mask_title: 脱敏开关
        today: 今天日期

    Returns:
        str: 邮件正文
    """
    if cfg is None:
        cfg = models.get_mail_config()
        mask_title = mask_title or bool(cfg.get('mask_title'))
    if today is None:
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')

    # --- 按负责人分组 ---
    tasks = [prepare_task(t) for t in tasks]
    groups = {}
    for task in tasks:
        name = task['assignee_name'] or f'用户#{task["assignee"]}'
        groups.setdefault(name, []).append(task)

    lines = ['您好：', '']
    lines.append(f'截至 {today}，系统共有 {len(tasks)} 项逾期任务，按负责人分组如下：')
    lines.append('')

    if not groups:
        lines.append('（今日无逾期任务）')
        lines.append('')
    else:
        # 组内按逾期天数降序：拖得最久的排最前
        for name, items in groups.items():
            items.sort(key=lambda t: t['due_date'])
            lines.append(f'【{name}】（{len(items)} 项）')
            for idx, task in enumerate(items, 1):
                days = overdue_days(task, today)
                lines.append(
                    f'  {idx}. {_title_of(task, mask_title)}'
                    f' ｜ 截止 {task["due_date"]}'
                    f' ｜ 已逾期 {days} 天'
                    f' ｜ {priority_label(task.get("priority"))}'
                )
            lines.append('')

        # --- 汇总行（E6-② 建议） ---
        all_days = [overdue_days(t, today) for t in tasks]
        lines.append(
            f'共 {len(tasks)} 项逾期任务，涉及 {len(groups)} 位负责人，'
            f'最久已逾期 {max(all_days)} 天。'
        )
        lines.append('')

    lines.append(GUIDE_LINE)
    lines.append('')
    lines.append(f'—— {_footer(cfg)}')
    return '\n'.join(lines)


def render_daily_report_for_user(user_id, cfg=None, mask_title=False):
    """为指定管理员渲染日报正文（重发时复用，见 models._rebuild_body_for_retry）。"""
    tasks = get_overdue_tasks_for_report()
    return render_daily_report(tasks, cfg=cfg, mask_title=mask_title)


# ============================================================
# 4. 手动提醒
# ============================================================

def render_manual_subject(task, mask_title=False):
    return f'[督办系统] 督办提醒：{_truncate(_title_of(task, mask_title))}'


def render_manual(task, operator_name, note='', cfg=None, mask_title=False, today=None):
    """渲染手动提醒正文（H4-②：可附 ≤200 字留言）。

    Args:
        task: 任务行
        operator_name: 操作人显示名（H1-②：管理员或任务创建人）
        note: 留言（纯文本，调用方已截断到 200 字）
    """
    if cfg is None:
        cfg = models.get_mail_config()
        mask_title = mask_title or bool(cfg.get('mask_title'))
    if today is None:
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')

    task = prepare_task(task)
    user = models.get_user(task['assignee'])
    name = user['display_name'] if user else '同事'

    lines = [
        f'您好，{name}：',
        '',
        f'{operator_name} 提醒你尽快推进以下任务：',
        '',
        _task_block(task, mask_title, today),
        '',
    ]

    if note:
        lines.append(f'{operator_name} 留言：')
        lines.append(note.strip())
        lines.append('')

    lines.append(GUIDE_LINE)
    lines.append('')
    lines.append(f'—— {_footer(cfg)}')
    return '\n'.join(lines)


# ============================================================
# 5. 即将到期 / 长期待激活（订阅等级升级后才发，C1-④）
# ============================================================

def render_due_soon_subject(task, days, mask_title=False):
    return (f'[督办系统] 任务到期提醒：{_truncate(_title_of(task, mask_title))}'
            f'（{days} 天后到期）')


def render_due_soon(task, days, cfg=None, mask_title=False):
    """即将到期提醒正文。"""
    task = prepare_task(task)
    if cfg is None:
        cfg = models.get_mail_config()
        mask_title = mask_title or bool(cfg.get('mask_title'))

    user = models.get_user(task['assignee'])
    name = user['display_name'] if user else '同事'
    return '\n'.join([
        f'您好，{name}：',
        '',
        f'你负责的任务将在 {days} 天后到期，请及时跟进：',
        '',
        f'  任务：{_title_of(task, mask_title)}',
        f'  截止日期：{task["due_date"]}',
        f'  优先级：{priority_label(task.get("priority"))}',
        f'  创建人：{task.get("creator_name") or "-"}',
        '',
        GUIDE_LINE,
        '',
        f'—— {_footer(cfg)}',
    ])


def render_inactive_subject(task, days, mask_title=False):
    return (f'[督办系统] 任务待激活提醒：{_truncate(_title_of(task, mask_title))}'
            f'（已创建 {days} 天）')


def render_inactive(task, days, cfg=None, mask_title=False):
    """长期待激活提醒正文。"""
    task = prepare_task(task)
    if cfg is None:
        cfg = models.get_mail_config()
        mask_title = mask_title or bool(cfg.get('mask_title'))

    user = models.get_user(task['assignee'])
    name = user['display_name'] if user else '同事'
    return '\n'.join([
        f'您好，{name}：',
        '',
        f'你负责的任务创建 {days} 天仍未启动，请尽快处理：',
        '',
        f'  任务：{_title_of(task, mask_title)}',
        f'  截止日期：{task["due_date"]}',
        f'  优先级：{priority_label(task.get("priority"))}',
        '',
        GUIDE_LINE,
        '',
        f'—— {_footer(cfg)}',
    ])
