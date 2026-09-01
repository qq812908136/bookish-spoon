"""routes/auth_routes.py — 认证路由

包含：
- GET  /          根路由重定向（到 dashboard 或 login）
- GET  /login     显示登录页
- POST /login     提交登录
- GET  /logout    登出
- GET  /setup     显示初始化向导（仅当无管理员时）
- POST /setup     创建首个管理员账号
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import models
import auth

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    """根路由：已登录跳转仪表盘，未登录跳转登录页。

    首次启动（无管理员）跳转初始化向导。
    """
    if models.has_admin():
        if 'user_id' in session:
            return redirect(url_for('dashboard.overview'))
        return redirect(url_for('auth.login'))
    # 无管理员，进入初始化向导
    return redirect(url_for('auth.setup'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面：GET 显示表单，POST 提交登录。

    V2：支持字段级错误提示（error_field / general_error）与「记住用户名」cookie。
    """
    # 如果尚未创建管理员，跳转到初始化向导
    if not models.has_admin():
        return redirect(url_for('auth.setup'))

    # 读取「记住我」cookie（30 天有效）
    remembered_username = request.cookies.get('remember_username', '')

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', '') == '1'

        # 字段级校验：定位到具体字段
        if not username:
            return render_template('login.html', error_field='username',
                                   general_error=None, username='',
                                   remembered_username=remembered_username), 400
        if not password:
            return render_template('login.html', error_field='password',
                                   general_error=None, username=username,
                                   remembered_username=remembered_username), 400

        ok, reason = auth.do_login(username, password)
        if ok:
            # 登录成功，跳转仪表盘；按勾选写/清「记住用户名」cookie
            resp = redirect(url_for('dashboard.overview'))
            if remember:
                resp.set_cookie('remember_username', username, max_age=30 * 24 * 3600)
            else:
                resp.delete_cookie('remember_username')
            return resp

        # 登录失败：通用错误（不暴露账号是否存在）
        return render_template('login.html', error_field=None,
                               general_error=reason, username=username,
                               remembered_username=remembered_username), 401

    return render_template('login.html', error_field=None, general_error=None,
                           username='', remembered_username=remembered_username)


@auth_bp.route('/logout')
def logout():
    """登出：清除 session，跳转登录页。"""
    auth.do_logout()
    flash('您已安全退出', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    """初始化向导：首次启动创建管理员账号。

    仅当系统中无管理员时可访问；已有管理员后访问自动跳转登录。
    """
    # 已有管理员，不允许再访问初始化向导
    if models.has_admin():
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        username     = request.form.get('username', '').strip()
        display_name = request.form.get('display_name', '').strip()
        password     = request.form.get('password', '')
        confirm      = request.form.get('confirm_password', '')

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
        else:
            # DEF-005：初始化向导是整套系统的第一个账号，
            # 它的密码强度由这里把关（长度 + 弱口令黑名单 + 不能等于用户名）
            _ok, pwd_errors = auth.check_password_strength(password, username)
            errors.extend(pwd_errors)

        if password != confirm:
            errors.append('两次输入的密码不一致')

        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template('setup.html')

        # --- 创建管理员账号 ---
        password_hash = auth.hash_password(password)
        models.create_user(username, display_name, password_hash, role='admin')
        flash('管理员账号创建成功，请登录', 'success')
        return redirect(url_for('auth.login'))

    return render_template('setup.html')
