"""routes/user_routes.py — 用户管理路由（P1）

包含：
- GET  /users                   用户管理页（管理员）
- POST /users/new               新增用户
- POST /users/<id>/toggle       启用/停用用户
- POST /users/<id>/reset-password  重置密码
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash

import models
import auth
from auth import admin_required, get_current_user

user_bp = Blueprint('user', __name__)


@user_bp.route('/users')
@admin_required
def user_manage():
    """用户管理页（仅管理员）。"""
    user = get_current_user()
    users = models.get_all_users()

    return render_template(
        'users/manage.html',
        users=users,
        current_user=user,
    )


@user_bp.route('/users/new', methods=['POST'])
@admin_required
def user_new():
    """新增用户。"""
    username     = request.form.get('username', '').strip()
    display_name = request.form.get('display_name', '').strip()
    password     = request.form.get('password', '')
    role         = request.form.get('role', 'owner')

    # --- 表单校验 ---
    errors = []
    if not username:
        errors.append('请输入用户名')
    elif len(username) < 3:
        errors.append('用户名至少 3 个字符')
    elif models.get_user_by_username(username):
        errors.append('该用户名已被使用')

    if not display_name:
        errors.append('请输入显示姓名')

    if not password:
        errors.append('请输入密码')
    elif len(password) < 6:
        errors.append('密码至少 6 个字符')

    if role not in ('admin', 'owner'):
        role = 'owner'

    if errors:
        for err in errors:
            flash(err, 'error')
        return redirect(url_for('user.user_manage'))

    # --- 创建用户 ---
    password_hash = auth.hash_password(password)
    models.create_user(username, display_name, password_hash, role=role)
    flash(f'用户「{display_name}」创建成功', 'success')
    return redirect(url_for('user.user_manage'))


@user_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def user_toggle(user_id):
    """启用/停用用户切换。"""
    current = get_current_user()

    # 不允许停用自己
    if user_id == current['user_id']:
        flash('不能停用自己的账号', 'error')
        return redirect(url_for('user.user_manage'))

    target_user = models.get_user(user_id)
    if not target_user:
        flash('用户不存在', 'error')
        return redirect(url_for('user.user_manage'))

    # 不允许停用最后一个管理员
    if target_user['role'] == 'admin' and target_user['is_active']:
        admin_ids = models.get_admin_user_ids()
        if len(admin_ids) <= 1:
            flash('不能停用最后一个管理员账号', 'error')
            return redirect(url_for('user.user_manage'))

    models.toggle_user_active(user_id)
    action = '停用' if target_user['is_active'] else '启用'
    flash(f'用户「{target_user["display_name"]}」已{action}', 'success')
    return redirect(url_for('user.user_manage'))


@user_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def user_reset_password(user_id):
    """重置用户密码。"""
    new_password = request.form.get('new_password', '')

    if not new_password:
        flash('请输入新密码', 'error')
        return redirect(url_for('user.user_manage'))
    if len(new_password) < 6:
        flash('密码至少 6 个字符', 'error')
        return redirect(url_for('user.user_manage'))

    target_user = models.get_user(user_id)
    if not target_user:
        flash('用户不存在', 'error')
        return redirect(url_for('user.user_manage'))

    password_hash = auth.hash_password(new_password)
    models.update_password(user_id, password_hash)
    flash(f'用户「{target_user["display_name"]}」的密码已重置', 'success')
    return redirect(url_for('user.user_manage'))
