"""routes/settings_routes.py — 设置路由

包含：
- GET  /settings/profile   个人设置页
- POST /settings/profile   修改显示名/密码
- POST /settings/mail      修改个人邮箱与邮件订阅等级（V4）
- GET  /settings/system    系统设置页（管理员，预警天数配置）
- POST /settings/system    保存系统设置
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

import config
import models
import auth
import mail_constants
from auth import login_required, admin_required, get_current_user

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/settings/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """个人设置：查看/修改显示名、修改密码。"""
    user = get_current_user()

    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        old_password = request.form.get('old_password', '')
        new_password = request.form.get('new_password', '')
        confirm      = request.form.get('confirm_password', '')

        errors = []

        # --- 修改显示名 ---
        if not display_name:
            errors.append('显示名不能为空')

        # --- 修改密码（可选，填了才校验） ---
        if new_password or old_password:
            # 验证原密码
            if not old_password:
                errors.append('修改密码需要输入原密码')
            elif not auth.verify_password(user['password_hash'], old_password):
                errors.append('原密码不正确')

            if not new_password:
                errors.append('请输入新密码')
            else:
                # DEF-005：统一走密码强度校验（长度 + 弱口令黑名单）
                _ok, pwd_errors = auth.check_password_strength(
                    new_password, user['username'])
                errors.extend(pwd_errors)

            if new_password != confirm:
                errors.append('两次输入的新密码不一致')

        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template(
                'settings/profile.html',
                current_user=user,
                notify_levels=mail_constants.NOTIFY_LEVELS,
                notify_level_labels=mail_constants.NOTIFY_LEVEL_LABELS,
            )

        # --- 执行更新 ---
        if display_name != user['display_name']:
            models.update_display_name(user['user_id'], display_name)
            # 更新 session 中的显示名
            session['display_name'] = display_name

        if new_password and not errors:
            password_hash = auth.hash_password(new_password)
            models.update_password(user['user_id'], password_hash)

        flash('设置已保存', 'success')
        return redirect(url_for('settings.profile'))

    return render_template(
        'settings/profile.html',
        current_user=user,
        notify_levels=mail_constants.NOTIFY_LEVELS,
        notify_level_labels=mail_constants.NOTIFY_LEVEL_LABELS,
    )


@settings_bp.route('/settings/mail', methods=['POST'])
@login_required
def mail_preference():
    """修改个人邮箱与邮件订阅等级（V4，H3-① 邮箱仅本人与管理员可见）。

    单独开一个路由而不是并进 profile 表单，是因为两者语义不同：
    profile 表单改的是账号本身（显示名/密码），这里改的只是通知偏好，
    混在一起会让「改个邮箱也要输原密码」这种体验问题变得很难解。
    """
    user = get_current_user()

    email = (request.form.get('email') or '').strip()
    level = (request.form.get('mail_notify_level') or '').strip()

    if email and '@' not in email:
        flash('邮箱地址格式不正确（需包含 @）', 'error')
        return redirect(url_for('settings.profile'))

    if level and level not in mail_constants.NOTIFY_LEVELS:
        flash('订阅等级不合法', 'error')
        return redirect(url_for('settings.profile'))

    # 邮箱：空串写入 NULL，与 get_mail_recipient 的判空逻辑保持一致
    stored_email = models.get_user(user['user_id'])['email']
    if email != (stored_email or ''):
        models.update_user_email(user['user_id'], email)

    if level:
        models.update_mail_notify_level(user['user_id'], level)

    flash('邮件通知设置已保存', 'success')
    return redirect(url_for('settings.profile'))


@settings_bp.route('/settings/system', methods=['GET', 'POST'])
@admin_required
def system():
    """系统设置：预警天数配置（管理员）。"""
    user = get_current_user()

    if request.method == 'POST':
        due_days      = request.form.get('warning_due_days', '').strip()
        inactive_days = request.form.get('warning_inactive_days', '').strip()

        errors = []
        try:
            due_days_int = int(due_days)
            if due_days_int < 1 or due_days_int > 30:
                errors.append('到期预警天数应在 1-30 之间')
        except ValueError:
            errors.append('到期预警天数必须是整数')

        try:
            inactive_days_int = int(inactive_days)
            if inactive_days_int < 1 or inactive_days_int > 90:
                errors.append('待激活预警天数应在 1-90 之间')
        except ValueError:
            errors.append('待激活预警天数必须是整数')

        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template(
                'settings/system.html',
                current_user=user,
                warning_due_days=due_days,
                warning_inactive_days=inactive_days,
            )

        # --- 保存配置 ---
        models.set_config('warning_due_days', str(due_days_int))
        models.set_config('warning_inactive_days', str(inactive_days_int))
        flash('系统设置已保存', 'success')
        return redirect(url_for('settings.system'))

    # GET：显示当前配置
    return render_template(
        'settings/system.html',
        current_user=user,
        warning_due_days=models.get_config('warning_due_days', str(config.DEFAULT_WARNING_DUE_DAYS)),
        warning_inactive_days=models.get_config('warning_inactive_days', str(config.DEFAULT_WARNING_INACTIVE_DAYS)),
    )
