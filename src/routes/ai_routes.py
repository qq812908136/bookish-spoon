"""routes/ai_routes.py — AI 辅助生成路由（V5 迭代，Phase 0）

包含：
- GET  /ai                AI 控制台（管理员）：功能开关状态 + 近期生成记录 + 触发入口
- POST /ai/trigger        为某任务入队一条「催办话术」生成任务（管理员）
- GET  /ai/result/<id>    查看某条 AI 生成结果（管理员）
- POST /ai/adopt/<id>     人工确认采纳：把生成结果作为站内信发给任务负责人（管理员）

设计要点（对齐邮件子系统 + SPEC v1.0 铁律）：
1. AI_ENABLED=False 时所有页面仍可达（只读展示），但触发入队被拒并提示。
2. AI 输出只用于「展示 / 预填」，必须经管理员人工确认（adopt）才会真正发出，
   绝不自动落库为站内信或证据——这是 SPEC 明确的人工确认闸。
3. 调用模型失败不会抛异常到页面：由 ai_dispatcher 吞掉并记录，页面只显示状态。
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash

import config
import db
import models
import ai_templates
import ai_dispatcher
from auth import login_required, admin_required, get_current_user

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
