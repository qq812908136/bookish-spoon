"""auth.py — 认证与权限模块

包含：
1. 密码哈希工具（基于 werkzeug.security）
2. 登录/登出流程
3. 权限装饰器（@login_required / @admin_required）
4. 数据级权限判断函数（can_edit_task / filter_tasks_by_permission）
5. 当前用户获取函数
6. 登录失败限流（DEF-005）与密码强度校验

权限模型（RBAC）：
- admin（管理员）：可管理所有任务、用户管理、系统设置
- owner（任务负责人）：可查看全部任务（只读他人），仅能编辑自己负责的任务
"""

import threading
import time
from functools import wraps

from flask import session, redirect, url_for, abort, jsonify, request, current_app
from werkzeug.security import generate_password_hash, check_password_hash

import config
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
# 密码强度校验（DEF-005）
# ============================================================

# 常见弱口令黑名单：只收真正高频、一眼能猜到的那些。
# 刻意**不做**「必须大小写 + 符号」这类强组合要求——内部督办系统用不上，
# 门槛太高只会让人把密码写到便利贴上贴显示器。
WEAK_PASSWORDS = frozenset({
    '123456', '1234567', '12345678', '123456789', '1234567890',
    '111111', '222222', '000000', '888888', '666666', '654321',
    '123123', '112233', '121212',
    'password', 'password1', 'password12', 'password123', 'passw0rd',
    'p@ssword', 'passwd', 'pwd123',
    'admin', 'admin123', 'admin1234', 'admin888', 'administrator',
    'root', 'root123', 'toor',
    'qwerty', 'qwerty123', 'qwertyuiop', 'abc123', 'abc123456',
    'a123456', 'a12345', 'aa123456', '123456a', '123456aa',
    'iloveyou', 'letmein', 'welcome', 'welcome1',
    'monkey', 'dragon', 'sunshine', 'princess',
    'test1234', 'test123', '1q2w3e4r', '1qaz2wsx', 'qazwsx', 'zxcvbnm',
    'woaini1314', '5201314', 'zhang123', 'wang123',
})


def check_password_strength(password, username=None):
    """校验密码强度。

    这是**设置密码那一刻**的门槛，**不追溯已有账号**——
    早期创建的 6 位密码账号仍可正常登录，只在下次改密码时才要求达标。

    规则（PASSWORD_REQUIRE_STRENGTH=False 时只保留长度校验）：
      1. 长度 >= config.PASSWORD_MIN_LENGTH（默认 8）
      2. 不能全是数字
      3. 不能全是字母
      4. 不在常见弱口令黑名单内（比较时不区分大小写）
      5. 不能与用户名相同

    Args:
        password: 明文密码
        username: 用户名（可选，用于规则 5）

    Returns:
        tuple: (是否合规: bool, 错误原因列表: list[str]) —— 合规时列表为空
    """
    if not password:
        return False, ['请输入密码']

    errors = []
    if len(password) < config.PASSWORD_MIN_LENGTH:
        errors.append(f'密码至少 {config.PASSWORD_MIN_LENGTH} 个字符')

    if config.PASSWORD_REQUIRE_STRENGTH:
        if password.isdigit():
            errors.append('密码不能全是数字')
        elif password.isalpha():
            errors.append('密码不能全是字母，请混合数字')

        if password.strip().lower() in WEAK_PASSWORDS:
            errors.append('该密码过于常见，容易被猜到，请换一个')

        if username and password.strip().lower() == username.strip().lower():
            errors.append('密码不能与用户名相同')

    return (len(errors) == 0), errors


# ============================================================
# 登录失败限流（DEF-005）
# ============================================================
# 计数存内存而非数据库，理由：
#   1. 限流状态是短时效的（默认 15 分钟），重启后清零不影响防护效果——
#      攻击者没有能力触发服务器重启来给自己解锁。
#   2. 登录失败时写库意味着「一次请求换一次磁盘 I/O」，
#      反而给爆破者提供了一个放大攻击效果的新杠杆。
#   3. 不改数据库结构，已部署的实例升级后无需任何迁移。
# 已知的代价：多进程部署（如 gunicorn 多 worker）时各进程独立计数。
# 本项目是单进程形态（Flask 开发服务器 / waitress），不触发这个问题。

_login_failures = {}
_login_lock = threading.Lock()


def _client_ip():
    """取客户端 IP。

    部署在反向代理后面时，需要在代理层设置 X-Forwarded-For 并开启
    `BEHIND_PROXY=True`，否则所有请求都会记成代理服务器的 IP——
    结果是登录限流变成「一人被锁、全员陪绑」，审计日志里的 IP 也失去意义。
    详见 docs/生产部署指南.md。
    """
    try:
        return request.remote_addr or 'unknown'
    except RuntimeError:
        # 脱离请求上下文时（命令行脚本、单元测试直接调用等）取不到 IP。
        # 用固定占位值兜底——绝不能因为拿不到 IP 就让整个调用崩掉。
        return 'no-request-context'


def _failure_key(username):
    """限流维度：客户端 IP + 用户名（用户名不区分大小写）。

    两个维度缺一不可：
      - 只看 IP：整个办公室共用一个出口 IP 时会互相误伤；
      - 只看用户名：攻击者拿常用密码遍历用户名时毫无阻挡。
    """
    return f'{_client_ip()}|{(username or "").strip().lower()}'


def _prune_failures(now):
    """清理过期记录，防止字典随攻击无限增长。必须在持有 _login_lock 时调用。"""
    # 记录数很少时不做清理，避免每次登录失败都全表扫描
    if len(_login_failures) < 256:
        return
    ttl = max(config.LOGIN_LOCKOUT_MINUTES, 1) * 60
    expired = [k for k, v in _login_failures.items() if now - v['last'] > ttl]
    for k in expired:
        del _login_failures[k]


def is_login_locked(username):
    """判断该「IP + 用户名」是否处于锁定期。

    Returns:
        int: 剩余锁定秒数；0 表示未锁定，可以正常尝试登录。
    """
    if config.LOGIN_MAX_ATTEMPTS <= 0 or config.LOGIN_LOCKOUT_MINUTES <= 0:
        return 0
    key = _failure_key(username)
    now = time.time()
    with _login_lock:
        rec = _login_failures.get(key)
        if not rec:
            return 0
        # locked_until == 0 表示**从未被锁定**（只是失败计数在累积），
        # 不能落进下面的"已过期"分支——否则会把正在累积的计数删掉，
        # 导致每一轮都从 1 重新数，限流永远不会触发。
        if rec['locked_until'] <= 0:
            return 0
        remain = rec['locked_until'] - now
        if remain <= 0:
            # 锁定期确实已过：清掉旧账，让用户重新计满次数而不是一上来就被锁
            del _login_failures[key]
            return 0
        return int(remain + 0.999)


def record_login_failure(username):
    """记录一次登录失败；达到阈值则开始锁定。

    Returns:
        int: 本次失败后剩余的可尝试次数；0 表示已被锁定。
    """
    key = _failure_key(username)
    now = time.time()
    with _login_lock:
        _prune_failures(now)
        rec = _login_failures.get(key)
        lockout = max(config.LOGIN_LOCKOUT_MINUTES, 0) * 60
        max_attempts = config.LOGIN_MAX_ATTEMPTS

        # 上一轮锁定已过期 —— 重新计数，不把旧账算进来。
        # 注意 locked_until == 0 表示**从未被锁定过**，此时必须继续累加，
        # 不能当成"已过期"丢掉重来（否则计数永远停在 1，限流形同虚设）。
        if rec and 0 < rec['locked_until'] <= now:
            rec = None

        if rec is None:
            rec = {'count': 0, 'first': now, 'last': now, 'locked_until': 0.0}
            _login_failures[key] = rec

        rec['count'] += 1
        rec['last'] = now

        if max_attempts > 0 and rec['count'] >= max_attempts and lockout > 0:
            rec['locked_until'] = now + lockout
            return 0
        if max_attempts <= 0:
            return 1
        return max(max_attempts - rec['count'], 0)


def clear_login_failures(username):
    """登录成功：清空该「IP + 用户名」的失败计数。"""
    key = _failure_key(username)
    with _login_lock:
        _login_failures.pop(key, None)


def reset_login_attempts(username=None):
    """手动解锁（运维排障 / 测试清理用）。

    Args:
        username: 指定用户名则只清当前 IP 下该用户的记录；None 表示清空全部。

    Returns:
        int: 被清除的记录条数
    """
    with _login_lock:
        if username is None:
            n = len(_login_failures)
            _login_failures.clear()
            return n
        key = _failure_key(username)
        return 1 if _login_failures.pop(key, None) is not None else 0


def _log_login_event(level, message):
    """登录审计日志。

    刻意吞掉所有异常：日志写不出去（目录只读、磁盘满）绝不能反过来
    阻断登录流程本身。
    """
    try:
        getattr(current_app.logger, level)(message)
    except Exception:
        pass


# ============================================================
# 登录 / 登出
# ============================================================

def do_login(username, password):
    """执行登录流程。

    流程：
    1. 检查「IP + 用户名」是否处于锁定期（DEF-005）
    2. 根据用户名查用户
    3. 校验账号是否启用
    4. 校验密码哈希
    5. 写入 session，清空失败计数

    Args:
        username: 用户名
        password: 明文密码

    Returns:
        tuple: (是否成功: bool, 错误原因: str)
    """
    # --- DEF-005：锁定检查放在密码校验之前 ---
    # 锁定期内即使密码正确也一律拒绝，否则限流形同虚设
    locked = is_login_locked(username)
    if locked > 0:
        minutes, seconds = divmod(locked, 60)
        hint = f'{minutes} 分 {seconds} 秒' if minutes else f'{seconds} 秒'
        _log_login_event('warning',
                         f'登录被限流拦截: username={username} '
                         f'ip={_client_ip()} 剩余锁定 {hint}')
        return False, f'登录失败次数过多，请 {hint}后再试'

    user = models.get_user_by_username(username)
    # 不暴露用户是否存在，统一返回"用户名或密码错误"
    if not user or not user['is_active']:
        left = record_login_failure(username)
        _log_login_event('warning',
                         f'登录失败: username={username} ip={_client_ip()} '
                         f'原因={"账号不存在或已停用"} 剩余尝试 {left}')
        return False, _failure_message(left)

    if not verify_password(user['password_hash'], password):
        left = record_login_failure(username)
        _log_login_event('warning',
                         f'登录失败: username={username} ip={_client_ip()} '
                         f'原因=密码错误 剩余尝试 {left}')
        return False, _failure_message(left)

    # 登录成功，写入 session
    clear_login_failures(username)

    # DEF-002：登录成功即换掉 CSRF 会话密钥。
    # 登录前后的身份是两回事，不该让登录前拿到的令牌继续用于登录后的写操作。
    try:
        import csrf
        csrf.rotate_csrf_token()
    except Exception:
        # 令牌轮换失败不该阻断登录本身；换不了最坏结果是沿用旧令牌，
        # 防护仍然生效（令牌依然绑定在同一个会话上）。
        pass

    session['user_id'] = user['user_id']
    session['username'] = user['username']
    session['display_name'] = user['display_name']
    session['role'] = user['role']
    session.permanent = True  # 启用持久化 session（7天有效期）

    _log_login_event('info',
                     f'登录成功: username={username} ip={_client_ip()} '
                     f'role={user["role"]}')
    return True, ''


def _failure_message(left):
    """拼装登录失败提示。

    带上剩余次数是刻意的：真实用户手滑输错时「还可尝试 3 次」比干巴巴一句
    「用户名或密码错误」有用得多。这不泄露账号是否存在——
    因为账号不存在时同样计数、同样递减。

    left == 0 表示这一脚正好踩爆阈值、刚刚被锁定，此时给出锁定时长，
    与后续被拦截时的提示口径保持一致（否则用户看到「已锁定」却不知道等多久）。
    """
    if left > 0:
        return f'用户名或密码错误，还可尝试 {left} 次'
    minutes = max(config.LOGIN_LOCKOUT_MINUTES, 1)
    return f'登录失败次数过多，账号已临时锁定，请 {minutes} 分钟后再试'


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
