"""routes/dashboard_routes.py — 仪表盘路由（V2）

包含：
- GET /dashboard  仪表盘概览（6 统计卡 + 今日督办焦点 + 任务闭环矩阵）

V2 变更：
- 接受 ?range=all|year|quarter|month|week 时间范围参数（按任务创建时间过滤）
- 数据改用 models.get_dashboard_stats_v2 / get_today_focus / get_closure_matrix
"""

from flask import Blueprint, render_template, redirect, url_for, request

import models
import auth
from auth import login_required, get_current_user
from state_machine import STATUS_LABELS, PRIORITY_LABELS

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/dashboard')
@login_required
def overview():
    """仪表盘概览页：6 统计卡 + 焦点列表 + 闭环矩阵（支持时间范围筛选）。"""
    user = get_current_user()
    if not user:
        from flask import session
        session.clear()
        return redirect(url_for('auth.login'))

    # 时间范围参数（非法值回落到 all）
    range_key = request.args.get('range', 'all')
    if range_key not in models.RANGE_KEYS:
        range_key = 'all'

    # 闭环矩阵分页参数
    try:
        matrix_page = max(1, int(request.args.get('mpage', 1)))
    except (TypeError, ValueError):
        matrix_page = 1

    stats = models.get_dashboard_stats_v2(range_key)
    focus = models.get_today_focus(range_key, user['user_id'], limit=20)
    matrix, matrix_total, matrix_pages, matrix_page = models.get_closure_matrix(
        range_key, page=matrix_page, per_page=6
    )

    return render_template(
        'dashboard/overview.html',
        stats=stats,
        focus=focus,
        matrix=matrix,
        matrix_total=matrix_total,
        matrix_pages=matrix_pages,
        matrix_page=matrix_page,
        range_key=range_key,
        range_labels=models.RANGE_LABELS,
        status_labels=STATUS_LABELS,
        priority_labels=PRIORITY_LABELS,
        current_user=user,
    )
