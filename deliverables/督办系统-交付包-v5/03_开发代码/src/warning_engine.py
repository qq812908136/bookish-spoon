"""warning_engine.py — 三层预警引擎

包含三层预警判定逻辑：
1. 第一层：即将到期预警（截止日期前 N 天，状态为待启动/进行中）
2. 第二层：已逾期预警（状态已逾期，每日提醒一次）
3. 第三层：长期待激活预警（创建超过 N 天仍未启动）

特性：
- 多层预警可合并为一条消息（避免消息轰炸）
- 同一任务同一接收人同一天同一类型只发一条（去重）
- 通知对象：第一层仅负责人；第二/三层抄送管理员
"""

from datetime import datetime

import mail_dispatcher
import models
from state_machine import TaskStatus


def run_warning_scan():
    """每日预警扫描主入口（由 scheduler 每日 09:00 调用）。

    遍历所有活跃任务（非终态），判定并生成三层预警消息。
    采用"当天是否已发"去重，避免重复消息轰炸。
    """
    # 读取配置的预警天数
    due_days      = int(models.get_config('warning_due_days', '3'))
    inactive_days = int(models.get_config('warning_inactive_days', '7'))
    today         = datetime.now().strftime('%Y-%m-%d')
    now           = datetime.now()

    # 只扫描待启动、进行中、已逾期的任务（终态不预警）
    active_tasks = models.get_active_tasks_for_warning()

    for task in active_tasks:
        warnings = []  # 本任务触发的预警列表

        # ── 第一层：即将到期预警 ──
        # 条件：状态为待启动/进行中，且截止日期在今天到 due_days 天后之间
        if task['status'] in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS):
            try:
                due_date = datetime.strptime(task['due_date'], '%Y-%m-%d')
                days_to_due = (due_date - now).days
                if 0 <= days_to_due <= due_days:
                    warnings.append({
                        'type': 'warning_due',
                        'content': f'任务「{task["title"]}」将在 {days_to_due} 天后到期，请及时跟进。',
                    })
            except (ValueError, TypeError):
                pass  # 日期解析失败，跳过

        # ── 第二层：已逾期预警 ──
        # 条件：状态为已逾期（每日提醒一次）
        if task['status'] == TaskStatus.OVERDUE:
            warnings.append({
                'type': 'warning_overdue',
                'content': f'任务「{task["title"]}」已逾期，请尽快处理或更新进度。',
            })

        # ── 第三层：长期待激活预警 ──
        # 条件：状态仍为待启动，且创建超过 inactive_days 天
        # 频率：每 inactive_days 天提醒一次（如每 7 天）
        if task['status'] == TaskStatus.PENDING:
            try:
                created_date = datetime.strptime(task['created_at'][:10], '%Y-%m-%d')
                days_since_create = (now - created_date).days
                if days_since_create >= inactive_days and days_since_create % inactive_days == 0:
                    warnings.append({
                        'type': 'warning_inactive',
                        'content': f'任务「{task["title"]}」创建 {days_since_create} 天仍未启动，请尽快处理。',
                    })
            except (ValueError, TypeError):
                pass

        # ── 合并去重发送 ──
        if warnings:
            _send_merged_warnings(task, warnings, today)

    # ── 邮件通道（V4）──
    # 位置刻意在循环**之后**：邮件是按「人」合并的（F2-②），
    # 必须等全部任务扫描完、拿到每人完整的逾期清单，才能生成合并邮件。
    # 若在循环内逐任务入队，同一负责人会被去重键挡住，导致清单不完整。
    _enqueue_warning_mails()


def _enqueue_warning_mails():
    """把本次预警扫描的结果投递到邮件队列。

    三层预警各自的入队函数内部都会检查用户的订阅等级（C1-③④），
    未配置邮件时则直接返回（B5-① 静默降级）。

    任何异常都不能影响站内信流程——邮件只是附加通道，
    它挂了不该让预警本身消失，所以这里吞掉所有异常并记日志。
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        mail_dispatcher.enqueue_overdue_warnings()
        mail_dispatcher.enqueue_due_soon_warnings()
        mail_dispatcher.enqueue_inactive_warnings()
        # 管理员日报放在最后：此时当天的逾期邮件已入队，
        # 日报统计到的是最完整的数据（D2-②）
        mail_dispatcher.enqueue_daily_reports()
    except Exception as e:
        logger.error(f'预警邮件入队异常（不影响站内信）：{e}', exc_info=True)


def _send_merged_warnings(task, warnings, today):
    """将一个任务的多个预警合并为一条消息发送（避免消息轰炸）。

    去重策略：同一任务同一接收人同一天同一主类型只发一条。
    通知对象：
    - 第一层（即将到期）→ 仅负责人
    - 第二层（已逾期）→ 负责人 + 所有管理员
    - 第三层（长期待激活）→ 负责人 + 所有管理员

    Args:
        task: 任务对象
        warnings: 预警列表，每项含 type 和 content
        today: 今天的日期字符串 YYYY-MM-DD
    """
    # 确定通知对象集合
    recipients = {task['assignee']}  # 负责人始终收到
    # 第二、三层抄送管理员
    if any(w['type'] in ('warning_overdue', 'warning_inactive') for w in warnings):
        recipients.update(models.get_admin_user_ids())

    # 合并消息内容（多条预警用换行连接）
    content_parts = [w['content'] for w in warnings]
    merged_content = '\n'.join(content_parts)

    # 取最严重的类型作为消息主类型（逾期 > 待激活 > 到期）
    type_priority = {'warning_overdue': 0, 'warning_inactive': 1, 'warning_due': 2}
    primary_type = min(warnings, key=lambda w: type_priority[w['type']])['type']

    # 逐个接收人发送（带去重检查）
    for recipient_id in recipients:
        if not models.has_warning_today(task['task_id'], recipient_id, primary_type, today):
            models.create_message(
                recipient=recipient_id,
                sender=None,  # 系统消息
                msg_type=primary_type,
                content=merged_content,
                task_id=task['task_id'],
            )


def trigger_overdue_warning(task):
    """触发第二层逾期预警（任务被自动标记为逾期时调用）。

    通知负责人 + 所有管理员。
    与每日扫描的逾期预警去重（当天只发一次）。

    Args:
        task: 被标记为逾期的任务对象
    """
    today = datetime.now().strftime('%Y-%m-%d')

    # 通知对象：负责人 + 所有管理员
    recipients = {task['assignee']}
    recipients.update(models.get_admin_user_ids())

    content = f'任务「{task["title"]}」已超过截止日期，系统已自动标记为逾期，请尽快处理。'

    for recipient_id in recipients:
        if not models.has_warning_today(task['task_id'], recipient_id, 'warning_overdue', today):
            models.create_message(
                recipient=recipient_id,
                sender=None,
                msg_type='warning_overdue',
                content=content,
                task_id=task['task_id'],
            )

    # ── 邮件通道（V4）：任务刚被标记为逾期时立刻通知 ──
    # 传 task 参数 → 只处理这位负责人，避免每 5 分钟全表扫描。
    # 与每日扫描共用同一个去重键（overdue:{人}:{日期}），
    # 因此同一天无论触发多少次都只会发一封。
    import logging
    try:
        mail_dispatcher.enqueue_overdue_warnings(task=task)
    except Exception as e:
        logging.getLogger(__name__).error(
            f'逾期邮件入队异常（不影响站内信）：{e}', exc_info=True)
