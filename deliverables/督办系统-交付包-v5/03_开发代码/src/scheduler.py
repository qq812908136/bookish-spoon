"""scheduler.py — 后台守护线程调度

启动两个守护线程：
1. 逾期扫描线程：每 5 分钟扫描一次，将超期未闭环的任务自动置为"已逾期"
2. 预警扫描线程：每日固定时间（默认 09:00）执行三层预警扫描

两个线程均为 daemon=True，主进程退出时自动终止。
线程安全：SQLite 连接使用 threading.local 线程隔离 + 全局写锁。
"""

import threading
import time
from datetime import datetime

import config
import db
import mail_dispatcher
import ai_dispatcher
import models
import warning_engine
from state_machine import TaskStatus


def start_background_tasks(app):
    """启动后台守护线程（在 Flask 启动时由 app.py 调用）。

    Args:
        app: Flask 应用实例（用于 app_context 和日志）
    """
    # 逾期扫描线程（每 5 分钟）
    overdue_thread = threading.Thread(
        target=_overdue_scan_loop,
        args=(app,),
        daemon=True,
        name='overdue-scanner'
    )
    overdue_thread.start()

    # 预警扫描线程（每日 09:00）
    warning_thread = threading.Thread(
        target=_warning_scan_loop,
        args=(app,),
        daemon=True,
        name='warning-scanner'
    )
    warning_thread.start()


def _overdue_scan_loop(app):
    """逾期扫描循环：每 scan_interval_seconds 秒执行一次。

    扫描所有"待启动"和"进行中"且超过截止日期的任务，
    自动将其状态改为"已逾期"，并触发第二层预警消息。
    """
    with app.app_context():
        while True:
            try:
                _scan_and_mark_overdue(app)
            except Exception as e:
                app.logger.error(f'逾期扫描异常: {e}')

            # 邮件队列扫描（V4）：与逾期扫描共用同一个 5 分钟循环，
            # 不新增线程（C4-②）。未配置邮件时 scan_and_send 会立即返回，
            # 不会有任何额外开销（B5-① 静默降级）。
            try:
                mail_dispatcher.scan_and_send()
            except Exception as e:
                app.logger.error(f'邮件队列扫描异常: {e}')

            # 读取配置的扫描间隔（默认 300 秒 = 5 分钟）
            interval = int(models.get_config('scan_interval_seconds', str(config.OVERDUE_SCAN_INTERVAL)))
            time.sleep(interval)


def _scan_and_mark_overdue(app):
    """扫描并标记逾期任务。

    查找所有状态为 pending/in_progress 且 due_date < 今天的任务，
    将其状态改为 overdue，写系统进度日志，触发逾期预警消息。
    """
    now_date = datetime.now().strftime('%Y-%m-%d')
    now_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 查找超期任务
    overdue_tasks = models.get_tasks_for_overdue_check(now_date)

    if not overdue_tasks:
        return

    app.logger.info(f'逾期扫描：发现 {len(overdue_tasks)} 个超期任务')

    for task in overdue_tasks:
        with db.transaction() as conn:
            # 更新任务状态为已逾期
            conn.execute(
                "UPDATE tasks SET status = 'overdue', is_overdue = 1, updated_at = ? WHERE task_id = ?",
                (now_datetime, task['task_id'])
            )
            # 写系统进度日志（operator 为 NULL 表示系统自动操作）
            conn.execute(
                "INSERT INTO progress_logs (task_id, operator, operated_at, status_from, status_to, progress_note) "
                "VALUES (?, NULL, ?, ?, 'overdue', '系统自动标记：任务超过截止日期')",
                (task['task_id'], now_datetime, task['status'])
            )

        # 触发第二层逾期预警消息（在事务外调用，因为涉及多条消息写入）
        warning_engine.trigger_overdue_warning(task)

    app.logger.info(f'逾期扫描完成：已标记 {len(overdue_tasks)} 个任务为逾期')


def _warning_scan_loop(app):
    """预警扫描循环：每分钟检查一次是否到达每日扫描时间。

    到达配置的扫描时间（默认 09:00）且今天尚未扫描过时，执行预警扫描。
    """
    with app.app_context():
        last_scan_date = None  # 记录上次扫描的日期，防止一天内重复扫描

        while True:
            try:
                now = datetime.now()
                today = now.strftime('%Y-%m-%d')

                # 读取配置的扫描时间（默认 09:00）
                scan_time = models.get_config('warning_scan_time', config.WARNING_SCAN_TIME)
                scan_hour, scan_minute = scan_time.split(':')
                scan_hour = int(scan_hour)
                scan_minute = int(scan_minute)

                # 检查是否到达扫描时间且今天未扫描过
                if (now.hour > scan_hour or
                    (now.hour == scan_hour and now.minute >= scan_minute)):
                    if last_scan_date != today:
                        app.logger.info(f'开始每日预警扫描 ({today} {scan_time})')
                        warning_engine.run_warning_scan()
                        # PR-3：按 AI_BRIEF_SCHEDULE 可选定时生成简报/周报草稿（人工确认后才投递）
                        try:
                            ai_dispatcher.maybe_run_scheduled_briefs()
                        except Exception as e:
                            app.logger.error(f'定时简报生成异常: {e}')
                        last_scan_date = today
                        app.logger.info('每日预警扫描完成')

            except Exception as e:
                app.logger.error(f'预警扫描异常: {e}')

            # 每分钟检查一次
            time.sleep(config.WARNING_CHECK_INTERVAL)
