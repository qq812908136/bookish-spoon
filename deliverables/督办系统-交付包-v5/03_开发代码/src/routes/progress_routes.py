"""routes/progress_routes.py — 进度记录路由

包含：
- POST /tasks/<id>/progress  提交进度备注（不改状态）
- GET  /tasks/<id>/logs      查看进度记录（JSON，供面板异步加载）
"""

from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort

import models
import auth
from auth import login_required, get_current_user, can_edit_task

progress_bp = Blueprint('progress', __name__)


@progress_bp.route('/tasks/<int:task_id>/progress', methods=['POST'])
@login_required
def submit_progress(task_id):
    """提交进度备注（不改变任务状态，仅记录一条进度日志）。"""
    user = get_current_user()
    task = models.get_task(task_id)
    if not task:
        abort(404)

    # 权限校验：owner 只能对自己的任务提交进度
    if not can_edit_task(task, user):
        flash('您无权对此任务提交进度', 'error')
        return redirect(url_for('task.task_list'))

    progress_note = request.form.get('progress_note', '').strip()
    if not progress_note:
        flash('请填写进度备注', 'error')
        return redirect(url_for('task.task_detail', task_id=task_id))

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 写进度日志（不改状态，status_from = status_to = 当前状态）
    models.create_progress_log(
        task_id=task_id,
        operator=user['user_id'],
        operated_at=now,
        status_from=task['status'],
        status_to=task['status'],
        progress_note=progress_note,
    )

    # 更新任务的 updated_at
    models.update_task(task_id, updated_at=now)

    flash('进度已更新', 'success')
    return redirect(url_for('task.task_detail', task_id=task_id))


@progress_bp.route('/tasks/<int:task_id>/logs')
@login_required
def get_logs(task_id):
    """查看任务的进度记录（JSON 格式，供侧滑面板异步加载）。"""
    task = models.get_task(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404

    logs = models.get_progress_logs(task_id)

    # 转换为可序列化的字典列表
    log_list = []
    for log in logs:
        log_list.append({
            'log_id': log['log_id'],
            'operator_name': log['operator_name'] or '系统',
            'operated_at': log['operated_at'],
            'status_from': log['status_from'],
            'status_to': log['status_to'],
            'progress_note': log['progress_note'] or '',
        })

    return jsonify({'success': True, 'data': log_list})
