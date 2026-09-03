"""ai_dispatcher.py — AI 任务调度（V5 迭代「AI 辅助生成」，Phase 0）

完全对齐 V4 邮件子系统（mail_dispatcher）：
- 任务先落 ai_queue，由 scheduler._overdue_scan_loop 复用 5 分钟循环调用 scan_and_run()
  —— 零新增线程（C4-② 原则）
- AI_ENABLED=False 时 scan_and_run() 立即返回，零开销（B5-① 静默降级）
- 双重熔断：连续失败超阈值则熔断暂停，到时自动试探恢复
- 重启发送中状态：扫描前把卡在 sending 的记录重置回 pending（G5-① 取舍：宁可重发不可丢失）

⚠️ 本模块只负责「取任务 → 调模型 → 落结果」，绝不修改 create_message()，
   也绝不自动把 AI 输出发出去——发出动作必须经由 routes 的人工确认（adopt）。
"""

from datetime import datetime, timedelta

import config
import db
import models
import ai_service


def enqueue_ai_job(task_id, job_type, prompt):
    """把一个 AI 生成任务放进队列。"""
    return models.enqueue_ai_job(task_id, job_type, prompt)


def scan_and_run():
    """被 scheduler 的 5 分钟循环调用。未启用则直接返回。"""
    if not config.AI_ENABLED:
        return

    # 熔断中：未到恢复时间则跳过；到时间了先把状态置 closed，交由后续失败再熔断
    state = models.get_ai_circuit_state()
    if state.get('state') == 'open':
        resume = state.get('resume_at')
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if resume and resume > now:
            return
        models.set_ai_circuit_state('closed')

    # 重启保护：把上一次被强杀卡在 sending 的记录拉回 pending
    try:
        models.reset_stuck_ai_jobs()
    except Exception:
        pass

    jobs = models.fetch_due_ai_jobs(config.AI_BATCH_LIMIT)
    if not jobs:
        return

    ids = [j['queue_id'] for j in jobs]
    models.mark_ai_jobs_sending(ids)
    for job in jobs:
        _run_one(job)


def _run_one(job):
    queue_id = job['queue_id']
    result = ai_service.call_model(job['prompt'])
    if result['success']:
        models.mark_ai_job_done(queue_id, result['text'],
                                job['task_id'], job['job_type'])
        models.reset_ai_fail_streak()
    else:
        _handle_failure(queue_id, result.get('error') or '未知错误')


def _handle_failure(queue_id, error):
    streak = models.bump_ai_fail_streak()
    if streak >= config.AI_CIRCUIT_FAIL_THRESHOLD:
        resume = (datetime.now() +
                  timedelta(minutes=config.AI_CIRCUIT_PAUSE_MINUTES))\
            .strftime('%Y-%m-%d %H:%M:%S')
        models.set_ai_circuit_state(
            'open',
            reason=f'连续失败 {streak} 次，已熔断',
            resume_at=resume,
            fail_streak=streak)
    models.mark_ai_job_failed(queue_id, error,
                              retry_max=config.AI_RETRY_MAX,
                              backoff=_parse_backoff(config.AI_RETRY_BACKOFF))


def _parse_backoff(raw):
    """把 '1,5,15' 解析成 [1,5,15] 分钟列表，解析失败给兜底。"""
    try:
        vals = [int(x.strip()) for x in raw.split(',') if x.strip()]
        if vals:
            return vals
    except (ValueError, AttributeError):
        pass
    return [1, 5, 15]
