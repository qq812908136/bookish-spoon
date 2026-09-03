"""routes/ai_routes.py — AI 辅助生成路由（V5 迭代，Phase 0 / Phase 1）

包含：
- GET  /ai                AI 控制台（管理员）：功能开关状态 + 近期生成记录 + 触发入口
- POST /ai/trigger        为某任务入队一条「催办话术」生成任务（管理员）
- GET  /ai/result/<id>    查看某条 AI 生成结果（管理员）
- POST /ai/adopt/<id>     人工确认采纳：把生成结果作为站内信发给任务负责人（管理员）
- GET/POST /ai/draft      任务描述结构化抽取入口（管理员，PR-2）
- GET  /ai/draft/<id>     展示 AI 结构化草稿（可编辑预填，确认后交由建任务流程落库）

设计要点（对齐邮件子系统 + SPEC v1.0 铁律）：
1. AI_ENABLED=False 时所有页面仍可达（只读展示），但触发入队被拒并提示。
2. AI 输出只用于「展示 / 预填」，必须经管理员人工确认（adopt / 确认建任务）才会真正生效，
   绝不自动落库为站内信、证据或任务——这是 SPEC 明确的人工确认闸。
3. 调用模型失败不会抛异常到页面：由 ai_dispatcher 吞掉并记录，页面只显示状态。
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash

import config
import db
import models
import ai_templates
import ai_dispatcher
import mail_constants
from auth import login_required, admin_required, get_current_user
from state_machine import ALL_PRIORITIES, PRIORITY_LABELS

ai_bp = Blueprint('ai', __name__)


@ai_bp.route('/ai')
@admin_required
def console():
    """AI 控制台：开关状态 + 近期记录 + 触发入口。"""
    user = get_current_user()
    tasks = db.query(
        "SELECT task_id, title, status, assignee FROM tasks "
        "ORDER BY task_id DESC LIMIT 100")
    logs = models.list_ai_logs(50)
    circuit = models.get_ai_circuit_state()
    overview = {
        'enabled': bool(config.AI_ENABLED),
        'provider': config.AI_PROVIDER,
        'base_url': config.AI_API_BASE_URL,
        'model': config.AI_MODEL_NAME,
        'mask': bool(config.AI_MASK_DATA),
        'circuit': circuit,
    }
    return render_template(
        'ai/settings.html',
        current_user=user,
        overview=overview,
        tasks=tasks,
        logs=logs,
    )


@ai_bp.route('/ai/trigger', methods=['POST'])
@admin_required
def trigger():
    """为某任务入队「催办话术」生成任务。

    source=detail 时（任务详情页入口）同步生成并立即跳回详情页预填，
    免去等待 5 分钟扫描周期；其余来源仍只入队、由后台扫描处理。
    """
    if not config.AI_ENABLED:
        flash('AI 功能未启用，无法生成。请在 .env 中设置 AI_ENABLED=true 并配置本地模型。',
              'warning')
        task_id_arg = request.form.get('task_id', type=int)
        if request.form.get('source') == 'detail' and task_id_arg:
            return redirect(url_for('task.task_detail', task_id=task_id_arg))
        return redirect(url_for('ai.console'))

    task_id = request.form.get('task_id', type=int)
    if not task_id:
        flash('请先选择任务。', 'warning')
        return redirect(url_for('ai.console'))

    task = db.query_one("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    if not task:
        flash('任务不存在。', 'danger')
        return redirect(url_for('ai.console'))

    prompt = ai_templates.build_reminder_prompt(task)
    queue_id = ai_dispatcher.enqueue_ai_job(task_id, 'draft_reminder', prompt)
    if not queue_id:
        flash('入队失败，请稍后重试。', 'danger')
        if request.form.get('source') == 'detail':
            return redirect(url_for('task.task_detail', task_id=task_id))
        return redirect(url_for('ai.console'))

    # 详情页入口：同步生成，立即回到详情页预填
    if request.form.get('source') == 'detail':
        log_id = ai_dispatcher.run_job_now(queue_id)
        return redirect(url_for('task.task_detail',
                               task_id=task_id, ai_log_id=log_id or ''))

    flash(f'已为任务 #{task_id} 入队「催办话术」生成任务，将在下次扫描时处理。', 'success')
    return redirect(url_for('ai.console'))


@ai_bp.route('/ai/result/<int:log_id>')
@admin_required
def result(log_id):
    """查看某条 AI 生成结果。"""
    log = models.get_ai_log(log_id)
    if not log:
        flash('记录不存在。', 'danger')
        return redirect(url_for('ai.console'))
    task = None
    if log['task_id']:
        task = db.query_one(
            "SELECT task_id, title, assignee FROM tasks WHERE task_id = ?",
            (log['task_id'],))
    return render_template('ai/result.html', log=log, task=task)


@ai_bp.route('/ai/adopt/<int:log_id>', methods=['POST'])
@admin_required
def adopt(log_id):
    """人工确认采纳：把生成文本作为站内信发给任务负责人。

    这是 AI 输出唯一对外生效的出口——必须由管理员显式点击，
    绝不由调度器自动发出（SPEC v1.0 人工确认闸）。

    Phase 1 ②：支持管理员在页面内编辑后的内容（content 字段）覆盖原稿，
    真正发出的是「人改过的版本」，而非模型原话——仍属人工确认范畴。
    next=detail 时确认后跳回任务详情页。
    """
    log = models.get_ai_log(log_id)
    if not log or not log['success']:
        flash('该记录不可采纳。', 'danger')
        return redirect(url_for('ai.console'))
    if log['adopted']:
        flash('该结果已被采纳过。', 'info')
        return redirect(url_for('ai.console'))

    # 页面内可编辑：以人工修改后的内容为准。
    # content 字段缺省（控制台采纳、无编辑框）→ 用原稿；
    # content 字段存在但为空（用户在详情页清空文本框）→ 拒绝发送，不回落原稿。
    raw = request.form.get('content')
    if raw is None:
        content = log['result_text'] or ''
    else:
        content = raw.strip()
    if not content:
        flash('催办内容为空，无法发送。', 'danger')
        if request.form.get('next') == 'detail' and log['task_id']:
            return redirect(url_for('task.task_detail', task_id=log['task_id']))
        return redirect(url_for('ai.result', log_id=log_id))

    task = (db.query_one("SELECT assignee FROM tasks WHERE task_id = ?",
                          (log['task_id'],)) if log['task_id'] else None)
    if not task:
        flash('关联任务不存在，无法发送站内信。', 'danger')
        return redirect(url_for('ai.console'))

    admin = get_current_user()
    # 复用既有站内信写入通道（create_message 不在 AI 模块内修改，仅调用）
    models.create_message(
        recipient=task['assignee'],
        sender=admin['user_id'],
        msg_type='ai_reminder',
        content=content[:2000],
        task_id=log['task_id'],
    )
    models.mark_ai_log_adopted(log_id)
    flash('已作为站内信发送给任务负责人，等待其确认。', 'success')

    if request.form.get('next') == 'detail' and log['task_id']:
        return redirect(url_for('task.task_detail', task_id=log['task_id']))
    return redirect(url_for('ai.result', log_id=log_id))


# ============================================================
# PR-2：任务描述结构化抽取（管理员）
# ============================================================

@ai_bp.route('/ai/draft', methods=['GET', 'POST'])
@admin_required
def draft():
    """任务描述结构化抽取：粘贴自由文本 → 同步生成结构化草稿 → 预填建任务表单。

    同步生成复用 ai_dispatcher.run_job_now，免去等 5 分钟扫描周期。
    确认建任务仍走既有 task.task_new（仅调用 create_task，AI 模块不改它），
    所有字段经管理员人工确认后才落库。
    """
    if not config.AI_ENABLED:
        flash('AI 功能未启用，无法生成。请在 .env 中设置 AI_ENABLED=true 并配置本地模型。',
              'warning')
        return redirect(url_for('ai.console'))

    if request.method == 'POST':
        raw_text = (request.form.get('raw_text') or '').strip()
        if not raw_text:
            flash('请先粘贴需要整理的任务描述文本。', 'warning')
            return redirect(url_for('ai.draft'))

        prompt = ai_templates.build_structured_task_prompt(raw_text)
        queue_id = ai_dispatcher.enqueue_ai_job(None, 'draft_task', prompt)
        if not queue_id:
            flash('入队失败，请稍后重试。', 'danger')
            return redirect(url_for('ai.draft'))
        log_id = ai_dispatcher.run_job_now(queue_id)
        return redirect(url_for('ai.draft_result', log_id=log_id or ''))

    return render_template('ai/draft_input.html', current_user=get_current_user())


@ai_bp.route('/ai/draft/<int:log_id>', methods=['GET'])
@admin_required
def draft_result(log_id):
    """展示 AI 结构化草稿：可编辑预填表单，确认后交由既有建任务流程落库。

    解析失败或生成失败时，退化为「把原文/错误放进 description」的人工录入，
    仍由管理员补全后确认——绝不自动建任务。
    """
    log = models.get_ai_log(log_id)
    if not log:
        flash('记录不存在。', 'danger')
        return redirect(url_for('ai.console'))

    draft = ai_templates.parse_structured_task(log['result_text']) if log['success'] else None
    if not draft:
        draft = {
            'title': '',
            'priority': 'medium',
            'due_date': '',
            'risk_note': '',
            'collaborators': '',
            'description': (log['result_text'] or '') if log['success']
                           else ('生成失败：' + (log['error_message'] or '未知错误')),
        }

    # 复用既有「新建任务」表单（tasks/form.html），把 AI 抽取结果作为 form_data 预填。
    # 确认动作仍由 task.task_new 处理（仅调用 create_task，AI 模块不改动它），
    # 所有字段经管理员人工核对后才落库——满足 SPEC 人工确认闸。
    active_users = models.get_all_active_users()
    return render_template(
        'tasks/form.html',
        current_user=get_current_user(),
        active_users=active_users,
        priorities=ALL_PRIORITIES,
        priority_labels=PRIORITY_LABELS,
        form_data=draft,
        is_edit=False,
        ai_draft_log_id=log['log_id'],
    )


# ============================================================
# PR-3：督办简报 / 周报（管理员）
# ============================================================
_BRIEF_JOB_TYPES = {'daily': 'daily_brief', 'weekly': 'weekly_report'}
_BRIEF_LABELS = {'daily': '每日督办简报', 'weekly': '每周督办周报'}


@ai_bp.route('/ai/brief', methods=['GET', 'POST'])
@admin_required
def brief():
    if not config.AI_ENABLED:
        flash('AI 功能未启用，无法生成。请在 .env 中设置 AI_ENABLED=true 并配置本地模型。', 'warning')
        return redirect(url_for('ai.console'))
    if request.method == 'POST':
        brief_type = request.form.get('brief_type', 'daily')
        if brief_type not in _BRIEF_JOB_TYPES:
            brief_type = 'daily'
        ctx = models.get_brief_context(brief_type)
        prompt = (ai_templates.build_daily_brief_prompt(ctx) if brief_type == 'daily'
                  else ai_templates.build_weekly_report_prompt(ctx))
        queue_id = ai_dispatcher.enqueue_ai_job(None, _BRIEF_JOB_TYPES[brief_type], prompt)
        if not queue_id:
            flash('入队失败，请稍后重试。', 'danger')
            return redirect(url_for('ai.brief'))
        log_id = ai_dispatcher.run_job_now(queue_id)
        return redirect(url_for('ai.brief_result', log_id=log_id or ''))
    logs = [l for l in models.list_ai_logs(50) if l['job_type'] in ('daily_brief', 'weekly_report')]
    return render_template('ai/brief.html', current_user=get_current_user(), logs=logs, labels=_BRIEF_LABELS)


@ai_bp.route('/ai/brief/<int:log_id>', methods=['GET'])
@admin_required
def brief_result(log_id):
    log = models.get_ai_log(log_id)
    if not log:
        flash('记录不存在。', 'danger'); return redirect(url_for('ai.brief'))
    if log['job_type'] not in ('daily_brief', 'weekly_report'):
        flash('该记录不是简报/周报。', 'danger'); return redirect(url_for('ai.console'))
    is_weekly = log['job_type'] == 'weekly_report'
    label = _BRIEF_LABELS['weekly' if is_weekly else 'daily']
    content = (log['result_text'] or '') if log['success'] else ''
    error = '' if log['success'] else (log['error_message'] or '未知错误')
    return render_template('ai/brief_result.html', current_user=get_current_user(),
                           log=log, content=content, error=error, label=label,
                           mail_enabled=bool(config.MAIL_ENABLED))


@ai_bp.route('/ai/brief/<int:log_id>/send', methods=['POST'])
@admin_required
def brief_send(log_id):
    log = models.get_ai_log(log_id)
    if not log or not log['success']:
        flash('该记录不可发送（生成失败或不存在）。', 'danger'); return redirect(url_for('ai.brief'))
    if log['adopted']:
        flash('该简报已发送过。', 'danger'); return redirect(url_for('ai.brief'))
    raw = request.form.get('content')
    content = (raw if raw is not None else (log['result_text'] or '')).strip()
    if not content:
        flash('简报内容为空，无法发送。', 'danger'); return redirect(url_for('ai.brief_result', log_id=log_id))
    admin = get_current_user()
    # 站内信：发给全体活跃管理员（不依赖邮箱，确保管理员都能看到）
    admin_rows = db.query(
        "SELECT user_id FROM users WHERE role = 'admin' AND is_active = 1")
    admin_ids = [r['user_id'] for r in admin_rows]
    for uid in admin_ids:
        models.create_message(recipient=uid, sender=admin['user_id'],
                              msg_type='ai_brief', content=content[:2000], task_id=None)
    # 邮件：仅发给有邮箱且未关闭订阅的管理员（与站内信是两条独立渠道）
    mailed = 0
    is_weekly = log['job_type'] == 'weekly_report'
    label = _BRIEF_LABELS['weekly' if is_weekly else 'daily']
    if config.MAIL_ENABLED:
        subject = '督办' + label
        for a in models.get_mail_subscribers(role_filter='admin'):
            if (a['mail_notify_level'] or mail_constants.LEVEL_OVERDUE) == mail_constants.LEVEL_OFF:
                continue
            dedup = 'ai_brief:%d:%d' % (a['user_id'], log_id)
            if models.has_dedup_key(dedup):
                continue
            if models.enqueue_email(recipient_id=a['user_id'], recipient_email=a['email'],
                    mail_type=mail_constants.MAIL_TYPE_AI_BRIEF, subject=subject,
                    body=content, dedup_key=dedup):
                mailed += 1
    models.mark_ai_log_adopted(log_id)
    extra = ('，邮件 %d 封已入队' % mailed) if mailed else ''
    flash('已发送%s给 %d 位管理员（站内信%s）。' % (label, len(admin_ids), extra), 'success')
    return redirect(url_for('ai.brief'))
