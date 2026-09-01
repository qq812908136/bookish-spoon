"""routes/message_routes.py — 消息通知路由

包含：
- GET  /messages              V2：301 跳转到 /dashboard（消息中心页由抽屉替代）
- GET  /messages/drawer       消息抽屉 HTML 片段（V2 新增，Q4，最近 50 条）
- POST /messages/<id>/read    标记单条已读
- POST /messages/read-all     全部标记已读
- GET  /messages/unread-count  未读数（JSON，导航栏轮询用，C2 确认每30秒）
- GET  /messages/send         管理员发消息页面（C3 确认）
- POST /messages/send         管理员发送消息（C3 确认）
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort, session

import models
import auth
from auth import login_required, admin_required, get_current_user
from state_machine import STATUS_LABELS

message_bp = Blueprint('message', __name__)


# 消息类型中文映射
MESSAGE_TYPE_LABELS = {
    'assignment':         '任务指派',
    'status_change':      '状态变更',
    'warning_due':        '到期预警',
    'warning_overdue':    '逾期预警',
    'warning_inactive':   '待激活预警',
    'admin_directive':    '管理员指令',
}

# 消息类型颜色映射
MESSAGE_TYPE_COLORS = {
    'assignment':         'blue',
    'status_change':      'gray',
    'warning_due':        'orange',
    'warning_overdue':    'red',
    'warning_inactive':   'yellow',
    'admin_directive':    'purple',
}


@message_bp.route('/messages')
@login_required
def message_list():
    """V2：消息中心页由消息抽屉替代，旧链接 301 跳转到仪表盘（防 404）。"""
    return redirect(url_for('dashboard.overview'), code=301)


@message_bp.route('/messages/drawer')
@login_required
def message_drawer():
    """消息抽屉 HTML 片段（Q4）：最近 50 条消息，支持类型筛选。

    由 main.js 注入抽屉容器。消息条目带 data-message-id / data-task-drawer 属性，
    点击 → 标记已读 + 打开关联任务详情抽屉（无关联任务则不跳转）。
    """
    user = get_current_user()

    # 类型筛选（非法值回落全部）
    msg_type = request.args.get('type', '')
    filters = {}
    if msg_type in MESSAGE_TYPE_LABELS:
        filters['type'] = msg_type
    else:
        msg_type = ''

    messages = models.get_messages(user['user_id'], filters)[:50]

    return render_template(
        'messages/_drawer.html',
        messages=messages,
        current_type=msg_type,
        type_labels=MESSAGE_TYPE_LABELS,
        type_colors=MESSAGE_TYPE_COLORS,
        current_user=user,
    )


@message_bp.route('/messages/<int:message_id>/read', methods=['POST'])
@login_required
def mark_read(message_id):
    """标记单条消息为已读（JSON 响应，供前端异步调用）。"""
    user = get_current_user()
    models.mark_message_read(message_id, user['user_id'])
    return jsonify({'success': True, 'message': '已标记为已读'})


@message_bp.route('/messages/read-all', methods=['POST'])
@login_required
def mark_all_read():
    """全部标记已读（JSON 响应）。"""
    user = get_current_user()
    count = models.mark_all_read(user['user_id'])
    return jsonify({'success': True, 'message': f'已标记 {count} 条消息为已读', 'count': count})


@message_bp.route('/messages/unread-count')
@login_required
def unread_count():
    """获取未读消息数（JSON，供导航栏红点轮询，C2 确认每 30 秒）。"""
    user = get_current_user()
    count = models.get_unread_count(user['user_id'])
    return jsonify({'count': count})


@message_bp.route('/messages/tasks-search')
@admin_required
def tasks_search():
    """任务名称模糊搜索（JSON，发送消息页关联任务下拉用）。

    参数：keyword（至少 1 个字符），返回前 20 条匹配任务。
    """
    keyword = request.args.get('keyword', '').strip()
    if not keyword:
        return jsonify({'tasks': []})

    filters = {'keyword': keyword, 'sort': 'updated_desc'}
    tasks, _ = models.get_tasks(filters, page=1, per_page=20)

    result = []
    for t in tasks:
        result.append({
            'task_id': t['task_id'],
            'title': t['title'],
            'status': t['status'],
            'status_label': STATUS_LABELS.get(t['status'], t['status']),
            'assignee_name': t['assignee_name'] or '',
        })
    return jsonify({'tasks': result})


@message_bp.route('/messages/send', methods=['GET', 'POST'])
@admin_required
def send_message():
    """管理员发送指令消息（C3 确认：P0 就做独立入口）。

    GET  显示发消息表单（选择接收人 + 输入内容）
    POST 发送消息给指定接收人
    """
    user = get_current_user()

    if request.method == 'POST':
        recipient_id = request.form.get('recipient', '').strip()
        content      = request.form.get('content', '').strip()
        task_id      = request.form.get('task_id', '').strip()

        # --- 表单校验 ---
        errors = []
        if not recipient_id:
            errors.append('请选择接收人')
        else:
            recipient = models.get_user(int(recipient_id))
            if not recipient:
                errors.append('所选接收人不存在')
            elif not recipient['is_active']:
                errors.append('该接收人账号已停用')

        if not content:
            errors.append('请输入消息内容')

        # --- 关联任务ID校验 ---
        tid = None
        if task_id:
            try:
                tid = int(task_id)
                if tid <= 0:
                    errors.append('关联任务ID必须是正整数')
                elif not models.get_task(tid):
                    errors.append('关联任务不存在')
            except ValueError:
                errors.append('关联任务ID必须是正整数')

        if errors:
            for err in errors:
                flash(err, 'error')
            active_users = models.get_all_active_users()
            task = models.get_task(tid) if tid else None
            return render_template(
                'messages/send.html',
                active_users=active_users,
                form_data=request.form,
                task=task,
                current_user=user,
            )

        # --- 发送消息 ---
        models.create_message(
            recipient=int(recipient_id),
            sender=user['user_id'],
            msg_type='admin_directive',
            content=content,
            task_id=tid,
        )

        flash('消息已发送', 'success')
        # V2：消息中心页已由抽屉替代，发送成功后跳转仪表盘
        return redirect(url_for('dashboard.overview'))

    # GET：显示发消息表单
    active_users = models.get_all_active_users()
    return render_template(
        'messages/send.html',
        active_users=active_users,
        form_data={},
        task=None,
        current_user=user,
    )
