"""auth.py — 认证与权限模块

包含：
1. 密码哈希工具（基于 werkzeug.security）
2. 登录/登出流程
3. 权限装饰器（@login_required / @admin_required）
4. 数据级权限判断函数（can_edit_task / filter_tasks_by_permission）
5. 当前用户获取函数

权限模型（RBAC）：
- admin（管理员）：可管理所有任务、用户管理、系统设置
- owner（任务负责人）：可查看全部任务（只读他人），仅能编辑自己负责的任务
"""

from functools import wraps

from flask import session, redirect, url_for, abort, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash

import models


# ============================================================
# 密码哈希工具
# ============================================================

def hash_password(password):
    """将明文密码哈希存储（werkzeug PBKDF2 算法）。

    Args:
        password: 明文密码

    Returns:
        str: 哈希后的密码字符串
    """
    return generate_password_hash(password)


def verify_password(password_hash, password):
    """校验密码是否匹配。

    Args:
        password_hash: 数据库中存储的密码哈希
        password: 用户输入的明文密码

    Returns:
        bool: True 表示密码正确
    """
    return check_password_hash(password_hash, password)


# ============================================================
# 登录 / 登出
# ============================================================

def do_login(username, password):
    """执行登录流程。

    流程：
    1. 根据用户名查用户
    2. 校验账号是否启用
    3. 校验密码哈希
    4. 写入 session

    Args:
        username: 用户名
        password: 明文密码

    Returns:
        tuple: (是否成功: bool, 错误原因: str)
    """
    user = models.get_user_by_username(username)
    # 不暴露用户是否存在，统一返回"用户名或密码错误"
    if not user or not user['is_active']:
        return False, '用户名或密码错误'
    if not verify_password(user['password_hash'], password):
        return False, '用户名或密码错误'

    # 登录成功，写入 session
    session['user_id'] = user['user_id']
    session['username'] = user['username']
    session['display_name'] = user['display_name']
    session['role'] = user['role']
    session.permanent = True  # 启用持久化 session（7天有效期）

    return True, ''


def do_logout():
    """执行登出：清除 session。"""
    session.clear()


# ============================================================
# 权限装饰器
# ============================================================

def login_required(f):
    """登录校验装饰器：未登录或 session 失效时重定向到登录页。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        # 校验用户是否仍然存在（防止 session 过期或数据被清空后报错）
        user = models.get_user(session['user_id'])
        if not user:
            session.clear()
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """管理员校验装饰器：非管理员返回 403。

    判断逻辑：
    - 未登录 → 重定向登录页
    - 已登录但非 admin → HTML 请求返回 403 页面，JSON 请求返回错误 JSON
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        if session.get('role') != 'admin':
            # JSON 请求返回错误 JSON，HTML 请求返回 403 页面
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'success': False, 'message': '权限不足，仅管理员可访问'}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ============================================================
# 当前用户获取
# ============================================================

def get_current_user():
    """获取当前登录用户对象（从 session 取 user_id 查库）。

    Returns:
        sqlite3.Row 或 None: 用户对象，未登录或用户不存在时返回 None
    """
    user_id = session.get('user_id')
    if not user_id:
        return None
    return models.get_user(user_id)


# ============================================================
# 数据级权限判断
# ============================================================

def can_edit_task(task, user):
    """判断用户是否有权编辑某任务。

    权限规则：
    - admin：可编辑所有任务
    - owner：仅可编辑自己负责的任务

    Args:
        task: 任务对象（Row/dict，需含 assignee 字段）
        user: 用户对象（Row/dict，需含 role 和 user_id 字段）

    Returns:
        bool: True 表示有权编辑
    """
    if user is None:
        return False
    if user['role'] == 'admin':
        return True
    # owner 只能编辑自己负责的任务
    return task['assignee'] == user['user_id']


def can_delete_task(task, user):
    """判断用户是否有权删除某任务。

    权限规则：
    - 仅 admin 可删除
    - 仅允许删除"已撤销"状态的任务（PRD Q6-B）

    Args:
        task: 任务对象
        user: 用户对象

    Returns:
        bool: True 表示有权删除
    """
    if user is None or user['role'] != 'admin':
        return False
    # 仅允许删除已撤销的任务
    return task['status'] == 'cancelled'


def filter_tasks_by_permission(tasks, user, edit_mode=False):
    """列表数据权限过滤。

    - edit_mode=False（查看列表）：admin 和 owner 均可看全部任务（PRD Q4-B）
    - edit_mode=True（编辑操作）：owner 只能操作自己负责的任务

    Args:
        tasks: 任务列表
        user: 用户对象
        edit_mode: 是否为编辑模式

    Returns:
        list: 过滤后的任务列表
    """
    if user is None:
        return []
    if user['role'] == 'admin':
        return tasks
    if edit_mode:
        return [t for t in tasks if t['assignee'] == user['user_id']]
    # 查看模式：owner 可看全部（只读他人任务，模板层限制编辑按钮）
    return tasks
