"""mail_dispatcher.py — 邮件队列调度（V4 迭代核心）

职责：把「该发什么邮件」和「怎么把邮件发出去」两件事接起来。

    ┌──────────────┐   入队    ┌──────────────┐  扫描发送  ┌──────────────┐
    │ 业务触发点    │ ───────→ │ email_queue  │ ─────────→ │ mail_service │
    │ 预警引擎/分配 │          │  （待发队列） │            │   （SMTP）    │
    └──────────────┘          └──────────────┘            └──────────────┘

关键决策的实现位置：
    F2-② 同一负责人多个逾期任务合并成一封  → 在**入队阶段**完成
        （enqueue_overdue_warnings 每人每天只生成一条记录，
          正文里列出他名下的全部逾期任务）。
        这样队列记录与物理邮件一一对应，发送阶段无需再聚合，
        失败重试、限流、去重都变得直白。
    C6-② 邮件独立去重键，不与站内信共用      → dedup_key 列
    F1-② 逾期降频（1/2/3 天每天，之后每 3 天）→ mail_constants.should_remind_overdue
    F3-② 每轮最多发 N 封                    → scan_and_send 的 LIMIT
    G1-① 重试 3 次（5/15/30 分钟）          → models.mark_email_failed
    G3-③ 认证失败立即熔断                    → _open_circuit
    G4-② 连续失败 10 次熔断 60 分钟          → _check_circuit_after_failure
    G5-① 重启时 sending 重置为 pending        → reset_stuck_emails
    G6-① 停机期间不追溯补生成                 → 本模块从不回溯历史，只处理"当下"
    I2-② 发送记录保留 90 天                  → _maybe_cleanup_logs

线程模型：本模块由 scheduler 的逾期扫描线程每 5 分钟调用一次，
不新增线程。所有写操作走 db.transaction 保证原子性。
"""

import logging
from datetime import datetime, timedelta

import config
import db
import mail_constants
import mail_service
import mail_templates
import models

# 模块级 logger：不依赖 Flask app，命令行脚本与单元测试也能用
logger = logging.getLogger(__name__)

# 上次清理 email_log 的日期（模块级，避免每 5 分钟都跑一次 DELETE）
_last_cleanup_date = None


# ============================================================
# 一、入队：把「该发的邮件」写进队列
# ============================================================

def enqueue_overdue_warnings(task=None, today=None):
    """为逾期任务生成提醒邮件（F2-② 按负责人合并）。

    Args:
        task: 只处理该任务的负责人（任务刚被标记为逾期时用）；
              为 None 时全量扫描（每日 09:00 预警扫描用）。
        today: 日期 YYYY-MM-DD，默认今天

    Returns:
        int: 本次入队的邮件数

    说明：
        去重键是「负责人 + 日期」而非「任务 + 负责人 + 日期」——
        因为合并后每人每天只有一封，用任务维度去重反而会导致
        第二个任务入不了队（而它本该被合并进同一封里）。
    """
    if not models.is_mail_configured():
        return 0

    if today is None:
        today = datetime.now().strftime('%Y-%m-%d')

    # 全量取一次，避免多人场景下重复查询
    grouped = models.get_overdue_tasks_by_assignee()
    if not grouped:
        return 0

    # 只处理指定任务的负责人（刚逾期场景）
    target_ids = None
    if task is not None:
        target_ids = {task['assignee']}

    count = 0
    for assignee_id, tasks in grouped.items():
        if target_ids is not None and assignee_id not in target_ids:
            continue

        recipient = models.get_mail_recipient(assignee_id)
        if not recipient:
            continue  # 无邮箱或已停用：静默跳过（D4-②）

        if not models.user_wants_mail(recipient, mail_constants.MAIL_TYPE_OVERDUE):
            continue  # 订阅等级不含逾期（C1-③④）

        # F1-②：只要名下有任何一项任务「今天该提醒」，就发这封合并邮件，
        # 邮件里列出他全部逾期任务（对他来说这才是有用的信息）
        if not any(mail_constants.should_remind_overdue(
                mail_templates.overdue_days(t, today)) for t in tasks):
            continue

        dedup_key = f'overdue:{assignee_id}:{today}'
        if models.has_dedup_key(dedup_key):
            continue  # 今天已经排过了

        cfg = models.get_mail_config()
        subject = mail_templates.render_overdue_subject(tasks, cfg.get('mask_title'))
        body = mail_templates.render_overdue_grouped(
            assignee_id, tasks, cfg=cfg, today=today)

        if models.enqueue_email(
                recipient_id=assignee_id,
                recipient_email=recipient['email'],
                mail_type=mail_constants.MAIL_TYPE_OVERDUE,
                subject=subject,
                body=body,
                dedup_key=dedup_key,
        ):
            count += 1

    return count


def enqueue_due_soon_warnings(today=None):
    """即将到期提醒（只有订阅等级为 overdue_due / all 的用户才会收到）。"""
    if not models.is_mail_configured():
        return 0
    if today is None:
        today = datetime.now().strftime('%Y-%m-%d')

    due_days = int(models.get_config('warning_due_days', str(config.DEFAULT_WARNING_DUE_DAYS)))
    now = datetime.now()
    count = 0

    # 复刻预警引擎的第一层判定：待启动/进行中且截止日在窗口内
    for task in models.get_active_tasks_for_warning():
        if task['status'] not in ('pending', 'in_progress'):
            continue
        try:
            due = datetime.strptime(task['due_date'], '%Y-%m-%d')
            days_to_due = (due - now).days
        except (ValueError, TypeError):
            continue
        if not (0 <= days_to_due <= due_days):
            continue

        recipient = models.get_mail_recipient(task['assignee'])
        if not recipient:
            continue
        if not models.user_wants_mail(recipient, mail_constants.MAIL_TYPE_DUE_SOON):
            continue

        dedup_key = f'due_soon:{task["task_id"]}:{task["assignee"]}:{today}'
        if models.has_dedup_key(dedup_key):
            continue

        cfg = models.get_mail_config()
        subject = mail_templates.render_due_soon_subject(task, days_to_due, cfg.get('mask_title'))
        body = mail_templates.render_due_soon(task, days_to_due, cfg=cfg)

        if models.enqueue_email(
                recipient_id=task['assignee'],
                recipient_email=recipient['email'],
                mail_type=mail_constants.MAIL_TYPE_DUE_SOON,
                subject=subject,
                body=body,
                dedup_key=dedup_key,
                task_id=task['task_id'],
        ):
            count += 1

    return count


def enqueue_inactive_warnings(today=None):
    """长期待激活提醒（只有订阅等级为 all 的用户才会收到）。"""
    if not models.is_mail_configured():
        return 0
    if today is None:
        today = datetime.now().strftime('%Y-%m-%d')

    inactive_days = int(models.get_config(
        'warning_inactive_days', str(config.DEFAULT_WARNING_INACTIVE_DAYS)))
    now = datetime.now()
    count = 0

    for task in models.get_active_tasks_for_warning():
        if task['status'] != 'pending':
            continue
        try:
            created = datetime.strptime(task['created_at'][:10], '%Y-%m-%d')
            days_since = (now - created).days
        except (ValueError, TypeError):
            continue
        if days_since < inactive_days or days_since % inactive_days != 0:
            continue

        recipient = models.get_mail_recipient(task['assignee'])
        if not recipient:
            continue
        if not models.user_wants_mail(recipient, mail_constants.MAIL_TYPE_INACTIVE):
            continue

        dedup_key = f'inactive:{task["task_id"]}:{task["assignee"]}:{today}'
        if models.has_dedup_key(dedup_key):
            continue

        cfg = models.get_mail_config()
        subject = mail_templates.render_inactive_subject(task, days_since, cfg.get('mask_title'))
        body = mail_templates.render_inactive(task, days_since, cfg=cfg)

        if models.enqueue_email(
                recipient_id=task['assignee'],
                recipient_email=recipient['email'],
                mail_type=mail_constants.MAIL_TYPE_INACTIVE,
                subject=subject,
                body=body,
                dedup_key=dedup_key,
                task_id=task['task_id'],
        ):
            count += 1

    return count


def enqueue_assignment(task_id, operator_id=None, is_transfer=False, operator_email=None):
    """任务分配 / 改派通知（C5-①：任务生命周期的起点，漏了就是漏了）。

    Args:
        task_id: 任务 ID
        operator_id: 操作人（创建人 / 改派人）
        is_transfer: True 表示改派，False 表示新建分配
        operator_email: 操作人邮箱（用于 Reply-To，B2-③）

    Returns:
        int: 0 或 1
    """
    if not models.is_mail_configured():
        return 0

    task = models.get_task(task_id)
    if not task:
        return 0

    # 分配给自己的情况在业务层已经拦过了，这里再兜一次底：
    # 给自己发"你有新任务"的邮件毫无意义
    if operator_id and task['assignee'] == operator_id:
        return 0

    recipient = models.get_mail_recipient(task['assignee'])
    if not recipient:
        return 0
    if not models.user_wants_mail(recipient, mail_constants.MAIL_TYPE_ASSIGN):
        return 0

    today = datetime.now().strftime('%Y-%m-%d')
    dedup_key = f'assign:{task_id}:{task["assignee"]}:{today}'
    if models.has_dedup_key(dedup_key):
        return 0

    operator_name = '-'
    if operator_id:
        op = models.get_user(operator_id)
        operator_name = op['display_name'] if op else '-'

    cfg = models.get_mail_config()
    subject = mail_templates.render_assign_subject(task, cfg.get('mask_title'))
    body = mail_templates.render_assign(
        task, operator_name, cfg=cfg, is_transfer=is_transfer)

    return 1 if models.enqueue_email(
        recipient_id=task['assignee'],
        recipient_email=recipient['email'],
        mail_type=mail_constants.MAIL_TYPE_ASSIGN,
        subject=subject,
        body=body,
        dedup_key=dedup_key,
        task_id=task_id,
        reply_to=operator_email,
        operator_id=operator_id,
    ) else 0


def enqueue_daily_reports(today=None):
    """为管理员生成每日汇总日报（D2-②）。

    把「50 封 × 10 人 = 500 封」压缩成 10 封，
    这是整个方案能把邮件量控制在个人邮箱安全区间的关键一招。

    Returns:
        int: 入队的日报数
    """
    if not models.is_mail_configured():
        return 0
    if today is None:
        today = datetime.now().strftime('%Y-%m-%d')

    tasks = models.get_overdue_tasks_with_names()
    admins = models.get_mail_subscribers(role_filter='admin')
    if not admins:
        return 0

    cfg = models.get_mail_config()
    subject = mail_templates.render_daily_report_subject(len(tasks))
    body = mail_templates.render_daily_report(tasks, cfg=cfg, today=today)

    count = 0
    for admin in admins:
        # 日报不受「三级预警类型」限制——它是管理员的全局视图，
        # 只要订阅等级不是「关闭」就照发（D6-②）。
        if (admin['mail_notify_level'] or mail_constants.LEVEL_OVERDUE) == mail_constants.LEVEL_OFF:
            continue

        dedup_key = f'daily_report:{admin["user_id"]}:{today}'
        if models.has_dedup_key(dedup_key):
            continue

        if models.enqueue_email(
                recipient_id=admin['user_id'],
                recipient_email=admin['email'],
                mail_type=mail_constants.MAIL_TYPE_DAILY_REPORT,
                subject=subject,
                body=body,
                dedup_key=dedup_key,
        ):
            count += 1

    return count


def enqueue_manual(task_id, operator_id, note='', operator_email=None):
    """手动发送提醒邮件（C3-① 任务详情页按钮）。

    注意：本函数只负责入队与冷却判定，**不直接发信**。
    调用方（mail_routes / task_routes）会在入队后立刻触发一次
    针对这条记录的同步发送，让操作人当场看到结果；
    发送失败也没关系，记录留在队列里由后台自动重试。

    Returns:
        tuple: (queue_id 或 None, 错误文案或 None)
    """
    if not models.is_mail_configured():
        return None, '邮件功能未配置或未启用'

    task = models.get_task(task_id)
    if not task:
        return None, '任务不存在'

    operator = models.get_user(operator_id) if operator_id else None
    if not operator:
        return None, '操作人不存在'

    recipient = models.get_mail_recipient(task['assignee'])
    if not recipient:
        return None, '该任务负责人未填写邮箱或账号已停用，无法发送邮件'

    # 不给自己发（与现有 task_remind 行为保持一致）
    if task['assignee'] == operator_id:
        return None, '不能给自己发送提醒邮件'

    cfg = models.get_mail_config()

    # F4-② 冷却：同一任务 + 同一操作人 5 分钟内只能发一次
    if models.has_recent_manual_mail(task_id, operator_id, cfg.get('manual_cooldown')):
        minutes = max(1, int(cfg.get('manual_cooldown') or 300) // 60)
        return None, f'发送过于频繁，请 {minutes} 分钟后再试'

    # H4-② 留言限 200 字纯文本
    note = (note or '').strip()[:200]

    subject = mail_templates.render_manual_subject(task, cfg.get('mask_title'))
    body = mail_templates.render_manual(
        task, operator['display_name'], note, cfg=cfg)

    queue_id = models.enqueue_email(
        recipient_id=task['assignee'],
        recipient_email=recipient['email'],
        mail_type=mail_constants.MAIL_TYPE_MANUAL,
        subject=subject,
        body=body,
        dedup_key=f'manual:{task_id}:{operator_id}:{datetime.now().strftime("%Y%m%d%H%M%S")}',
        task_id=task_id,
        reply_to=operator_email or (operator['email'] or None),
        operator_id=operator_id,
    )
    if not queue_id:
        return None, '入队失败，请稍后重试'

    return queue_id, None


# ============================================================
# 二、发送：扫描队列并逐封投递
# ============================================================

def _open_circuit(reason, resume_minutes=None):
    """触发熔断（G3-③ / G4-②）。

    Args:
        reason: 展示给管理员的原因文案
        resume_minutes: 多少分钟后自动试探恢复；None 表示需人工恢复
    """
    resume_at = None
    if resume_minutes:
        resume_at = (datetime.now() + timedelta(minutes=resume_minutes)).strftime('%Y-%m-%d %H:%M:%S')
    models.set_circuit_state(
        mail_constants.CIRCUIT_OPEN, reason=reason, resume_at=resume_at,
        fail_streak=models.get_circuit_state().get('fail_streak') or 0)
    logger.error(f'邮件功能已熔断，停止发送。原因：{reason}'
                 f'（{"%d 分钟后自动试探恢复" % resume_minutes if resume_minutes else "需管理员手动恢复"}）')


def _circuit_allows_sending(cfg):
    """检查熔断状态是否允许发送，顺带处理自动恢复。

    Returns:
        tuple: (是否允许 bool, 熔断状态 dict)
    """
    state = models.get_circuit_state()
    if state.get('state') != mail_constants.CIRCUIT_OPEN:
        return True, state

    # 通用熔断到了试探时间 → 半开：先放行一封试试，失败会再次熔断
    resume_at = state.get('resume_at')
    if resume_at and datetime.now() >= datetime.strptime(resume_at, '%Y-%m-%d %H:%M:%S'):
        logger.info('邮件熔断已到自动试探时间，本轮放出一封试探')
        models.set_circuit_state(mail_constants.CIRCUIT_CLOSED)
        return True, state

    # 认证失败的熔断没有 resume_at，必须人工在设置页点「恢复」
    return False, state


def _handle_send_failure(queue_id, result, cfg):
    """处理一次发送失败：分类、归档或排期重试、必要时熔断。

    Returns:
        str: 'retrying' / 'failed'
    """
    error_type = result.get('error_type')
    message = result.get('error_message') or '未知错误'

    # --- 永久性错误：不重试，直接归档 ---
    if error_type == mail_constants.PERMANENT_ERROR_AUTH:
        # G3-③ 这是最危险的场景：密码错了还一直试，
        # 一天就是几千次失败登录，很可能把发件邮箱账号直接封掉。
        _open_circuit(f'SMTP 认证失败：{message}')
        return models.mark_email_failed(
            queue_id, message, cfg['retry_max'], cfg['retry_backoff'], permanent=True)

    if error_type == mail_constants.PERMANENT_ERROR_SPAM:
        _open_circuit(f'邮件被判定为垃圾邮件：{message}')
        return models.mark_email_failed(
            queue_id, message, cfg['retry_max'], cfg['retry_backoff'], permanent=True)

    if error_type == mail_constants.PERMANENT_ERROR_REJECTED:
        # 只是这一个收件地址有问题，不牵连全局，不熔断
        logger.warning(f'邮件被拒收（收件人不存在）：{message}')
        return models.mark_email_failed(
            queue_id, message, cfg['retry_max'], cfg['retry_backoff'], permanent=True)

    # --- 可恢复错误：排期重试 ---
    outcome = models.mark_email_failed(
        queue_id, message, cfg['retry_max'], cfg['retry_backoff'])

    # G4-② 连续失败达到阈值 → 通用熔断，避免断网时傻傻重试一整天
    streak = models.bump_fail_streak()
    threshold = int(cfg.get('circuit_threshold') or 10)
    if streak >= threshold:
        _open_circuit(
            f'连续 {streak} 封发送失败，疑似服务商故障或网络中断',
            resume_minutes=int(cfg.get('circuit_pause_minutes') or 60))
    return outcome


def send_one(queue_id, cfg=None):
    """发送队列中的指定一条记录。

    Args:
        queue_id: 队列记录 ID
        cfg: 邮件配置；为 None 时自动读取

    Returns:
        dict: {'success': bool, 'error_type': ..., 'error_message': ...}
    """
    if cfg is None:
        cfg = models.get_mail_config()

    row = db.query_one("SELECT * FROM email_queue WHERE queue_id = ?", (queue_id,))
    if not row:
        return {'success': False, 'error_type': 'rejected', 'error_message': '队列记录不存在'}

    models.mark_emails_sending([queue_id])
    result = mail_service.send_email(
        cfg, row['recipient_email'], row['subject'], row['body'], reply_to=row['reply_to'])

    if result['success']:
        models.mark_email_sent(queue_id, attempts=int(row['retry_count'] or 0) + 1)
        models.reset_fail_streak()
        logger.info(f'邮件已发送：queue_id={queue_id} → {row["recipient_email"]}')
    else:
        outcome = _handle_send_failure(queue_id, result, cfg)
        logger.warning(
            f'邮件发送失败：queue_id={queue_id} → {row["recipient_email"]} '
            f'类型={result["error_type"]} 结果={outcome} 原因={result["error_message"]}')

    return result


def scan_and_send(cfg=None):
    """扫描队列并发送（由 scheduler 每 5 分钟调用一次）。

    流程：
        1. 未配置 / 未启用 → 直接返回（B5-① 静默降级，绝不报错）
        2. 熔断检查 → 未恢复则返回
        3. 重置卡住的 sending（G5-①）
        4. 取本轮待发记录（F3-② 限流）
        5. 逐封发送，成功清零失败计数，失败分类处理
        6. 每日一次清理过期日志（I2-②）

    Returns:
        dict: {'sent': 成功数, 'failed': 失败数, 'skipped': 跳过原因或 None}
    """
    if cfg is None:
        cfg = models.get_mail_config()

    # --- 1. 未配置：静默降级 ---
    if not models.is_mail_configured(cfg):
        return {'sent': 0, 'failed': 0, 'skipped': 'not_configured'}

    # --- 2. 熔断检查 ---
    allowed, state = _circuit_allows_sending(cfg)
    if not allowed:
        return {'sent': 0, 'failed': 0, 'skipped': 'circuit_open'}

    # --- 3. 重启后清理卡在 sending 的记录（G5-① 宁可重复不可丢失）---
    try:
        reset_count = models.reset_stuck_emails()
        if reset_count:
            logger.info(f'重置 {reset_count} 条卡在「发送中」的邮件为待发送')
    except Exception as e:
        logger.warning(f'重置 sending 状态失败：{e}')

    # --- 4. 取本轮待发 ---
    batch_limit = max(1, int(cfg.get('batch_limit') or 20))
    try:
        rows = models.fetch_due_emails(batch_limit)
    except Exception as e:
        logger.error(f'读取邮件队列失败：{e}')
        return {'sent': 0, 'failed': 0, 'skipped': 'queue_error'}

    sent = failed = 0
    for row in rows:
        # 每封都重新检查熔断：上一封如果触发了认证失败，本轮就该停下了
        allowed, _ = _circuit_allows_sending(cfg)
        if not allowed:
            break

        result = send_one(row['queue_id'], cfg)
        if result['success']:
            sent += 1
        else:
            failed += 1

    # --- 5. 每日清理过期发送记录 ---
    _maybe_cleanup_logs(cfg)

    return {'sent': sent, 'failed': failed, 'skipped': None}


def _maybe_cleanup_logs(cfg):
    """每天只清理一次过期邮件日志（I2-②，避免每 5 分钟跑一次 DELETE）。"""
    global _last_cleanup_date
    today = datetime.now().strftime('%Y-%m-%d')
    if _last_cleanup_date == today:
        return
    _last_cleanup_date = today
    try:
        removed = models.cleanup_email_logs(cfg.get('retention_days'))
        if removed:
            logger.info(f'已清理 {removed} 条过期邮件发送记录')
    except Exception as e:
        logger.warning(f'清理邮件日志失败：{e}')


# ============================================================
# 三、测试邮件（I1-④）
# ============================================================

def send_test_mail(recipient_id):
    """给指定用户发一封测试邮件。

    这是全流程中**唯一不走队列**的发送路径——有意为之：
    测试邮件的全部意义就是「立刻知道配置对不对」，
    如果也排队等 5 分钟，排查周期就被无谓地拉长了。

    Returns:
        dict: {'success': bool, 'message': 给管理员看的中文提示}
    """
    cfg = models.get_mail_config()

    if not cfg.get('enabled'):
        return {'success': False, 'message': '邮件功能未启用，请先在下方开启并保存配置'}
    if not models.is_mail_configured(cfg):
        return {'success': False, 'message': '邮件配置不完整，请填写 SMTP 服务器与发件箱地址'}
    if not cfg.get('smtp_password'):
        return {'success': False, 'message': '未配置 SMTP 密码（授权码），请先填写'}

    user = models.get_user(recipient_id)
    if not user or not (user['email'] or '').strip():
        return {'success': False, 'message': '请先在你的个人设置中填写邮箱地址'}

    result = mail_service.send_test_email(cfg, user['email'].strip(), user['display_name'])

    # 测试邮件也写进历史，便于管理员在记录列表里核对
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db.execute(
        "INSERT INTO email_log "
        "(recipient_id, recipient_email, task_id, mail_type, subject, operator_id, "
        " success, error_message, attempts, created_at, finished_at) "
        "VALUES (?, ?, NULL, ?, ?, ?, ?, ?, 1, ?, ?)",
        (user['user_id'], user['email'].strip(), mail_constants.MAIL_TYPE_TEST,
         '[督办系统] 测试邮件：配置验证', recipient_id,
         1 if result['success'] else 0,
         result['error_message'] or None, now, now))

    if result['success']:
        return {'success': True, 'message': f'测试邮件已发送至 {user["email"].strip()}，请查收'}

    # 认证失败要顺带熔断，与正式发送保持同一套保护
    if result['error_type'] == mail_constants.PERMANENT_ERROR_AUTH:
        _open_circuit(f'SMTP 认证失败：{result["error_message"]}')
        return {'success': False, 'message': 'SMTP 认证失败，邮件功能已自动暂停，请检查账号与授权码'}

    return {'success': False, 'message': f'发送失败：{result["error_message"]}'}


def resume_circuit():
    """管理员在设置页手动恢复熔断（G3-③）。

    Returns:
        str: 提示文案
    """
    models.set_circuit_state(mail_constants.CIRCUIT_CLOSED)
    logger.info('管理员已手动恢复邮件发送功能')
    return '邮件发送已恢复，下一轮扫描将继续发送'
