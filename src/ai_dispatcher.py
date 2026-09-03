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
import ai_templates


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


def _run_one(job, retry_max=None):
    """处理单条任务：调模型 → 落结果。返回 (log_id, success)。

    retry_max 缺省走 config.AI_RETRY_MAX；同步「立即生成」场景传入 0，
    让失败直接归档而非进重试队列（用户正等着结果，重试没有意义）。
    """
    queue_id = job['queue_id']
    result = ai_service.call_model(job['prompt'])
    if result['success']:
        log_id = models.mark_ai_job_done(queue_id, result['text'],
                                         job['task_id'], job['job_type']) or 0
        models.reset_ai_fail_streak()
        return log_id, True
    else:
        _, log_id = models.mark_ai_job_failed(
            queue_id, result.get('error') or '未知错误',
            retry_max=(retry_max if retry_max is not None else config.AI_RETRY_MAX),
            backoff=_parse_backoff(config.AI_RETRY_BACKOFF))
        return log_id or 0, False


def run_job_now(queue_id):
    """同步运行一条刚入队的 AI 任务，返回生成结果的 ai_log.log_id。

    用于任务详情页「立即生成」场景：免去等待 5 分钟扫描周期，
    且失败也会落一条失败日志（retry_max=0 直接归档），方便页面回显错误。
    复用 _run_one，保证调模型/落库逻辑只在一处。
    """
    if not config.AI_ENABLED:
        return 0
    job = models.fetch_ai_job(queue_id)
    if not job:
        return 0
    models.mark_ai_jobs_sending([queue_id])
    log_id, _ok = _run_one(job, retry_max=0)
    return log_id


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


# PR-3 定时生成映射：brief 类型 → ai_queue job_type
_BRIEF_JOB_TYPES = {
    'daily': 'daily_brief',
    'weekly': 'weekly_report',
}


def maybe_run_scheduled_briefs():
    """PR-3 可选定时：按 AI_BRIEF_SCHEDULE 在每日 09:00 扫描时自动生成简报/周报草稿。

    仅生成「待确认草稿」入队（由既有 5 分钟扫描顺带生成），不自动投递——
    投递仍需管理员在页面上人工确认（SPEC 人工确认闸）。
    AI_BRIEF_SCHEDULE='off' 或 AI_ENABLED=False 时立即返回，零副作用。
    同一天同一类型只入队一次（用 config 去重键按日期记）。
    """
    mode = (config.AI_BRIEF_SCHEDULE or 'off').lower()
    if mode == 'off' or not config.AI_ENABLED:
        return 0
    today = datetime.now().strftime('%Y-%m-%d')
    planned = []
    if mode in ('daily', 'both'):
        planned.append('daily')
    if mode in ('weekly', 'both'):
        planned.append('weekly')
    done = 0
    for btype in planned:
        job_type = _BRIEF_JOB_TYPES.get(btype, 'daily_brief')
        key = 'ai_sched_brief_' + job_type
        if models.get_config(key) == today:
            continue
        ctx = models.get_brief_context(btype)
        if btype == 'daily':
            prompt = ai_templates.build_daily_brief_prompt(ctx)
        else:
            prompt = ai_templates.build_weekly_report_prompt(ctx)
        qid = enqueue_ai_job(None, job_type, prompt)
        if qid:
            models.set_config(key, today)
            done += 1
    return done
