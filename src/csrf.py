"""csrf.py — 跨站请求伪造（CSRF）防护

解决的问题（DEF-002）：
    攻击者可以在自己的页面里放一个自动提交的表单，指向已登录用户的督办系统。
    浏览器会**自动带上**受害者的会话 Cookie，于是「删除任务」「改状态」「新建
    管理员账号」这些操作会在受害者毫不知情的情况下以他的身份执行。

防护原理：
    每个会话持有一个只有它自己知道的随机密钥（存在 session 里）。
    页面渲染时，用这个密钥签出一个**带过期时间**的令牌塞进表单；
    提交时服务端重新算一遍签名，对得上才放行。
    攻击者拿不到受害者会话里的密钥，因此伪造不出能通过校验的令牌。

为什么是「签名 + 时间戳」而不是「存一个固定令牌比字符串」：
    固定令牌方案一次只能有一个有效值 —— 用户开了两个标签页，
    在 B 标签页重新登录后 A 标签页的令牌就作废了，提交时莫名其妙报安全错误。
    改成把过期时间签进令牌里（令牌 = 过期时间戳 + HMAC 签名），
    校验是**现算**的而不是比对现值，于是同一会话下多个令牌可以同时有效，
    只要都还在有效期内。这是 Flask-WTF 的做法，这里用标准库自己实现了一遍。

为什么不用 Flask-WTF：
    引入新依赖要同时改 requirements.txt、PyInstaller spec 的 hiddenimports、
    托管解释器安装、重新打包 exe 四处。本项目只需要令牌这一小块能力，
    全部逻辑不到 150 行，自己写更可控，也不增加离线程序的体积。

使用方式：
    - 表单：`<input type="hidden" name="csrf_token" value="{{ csrf_token }}">`
    - AJAX：请求头 `X-CSRF-Token`，或 JSON body 里的 `csrf_token` 字段
    - 豁免：`@csrf.csrf_exempt`（仅限确实没有副作用的内部接口）
"""

import hashlib
import hmac
import secrets
import time
from functools import wraps

from flask import current_app, jsonify, render_template, request, session

import config

# session 中存放会话密钥的键名
SESSION_KEY = '_csrf_secret'

# 表单字段名与 AJAX 请求头名
FIELD_NAME = 'csrf_token'
HEADER_NAMES = ('X-CSRF-Token', 'X-CSRFToken')

# 不需要校验的请求方法（只读方法不应产生副作用）
SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS', 'TRACE'})

# 豁免标记：装饰器打在视图函数上的属性名
_EXEMPT_ATTR = '_csrf_exempt'


# ============================================================
# 令牌生成与校验
# ============================================================

def _sign(payload):
    """用实例密钥（config.SECRET_KEY）对 payload 做 HMAC-SHA256 签名。"""
    key = (config.SECRET_KEY or '').encode('utf-8')
    return hmac.new(key, payload.encode('utf-8'), hashlib.sha256).hexdigest()


def _get_session_secret():
    """取得当前会话的随机密钥；没有就生成一个存进 session。

    这个密钥**只存在服务端签名的 session Cookie 里**，永远不会出现在 HTML 之外
    的地方，攻击者无法读取，因此也就无法伪造令牌。
    """
    raw = session.get(SESSION_KEY)
    if not isinstance(raw, str) or not raw:
        raw = secrets.token_urlsafe(32)
        session[SESSION_KEY] = raw
    return raw


def generate_csrf_token():
    """生成一个 CSRF 令牌（每次调用都会带一个新的过期时间）。

    Returns:
        str: 形如 "<过期时间戳>.<HMAC 签名>" 的令牌

    注意：同一会话内多次调用会返回**不同**的令牌串，
    但它们在有效期内都能通过校验 —— 这正是多标签页能同时正常工作的原因。
    """
    raw = _get_session_secret()
    expires_at = int(time.time()) + max(config.CSRF_TOKEN_MAX_AGE, 60)
    return f'{expires_at}.{_sign(f"{raw}.{expires_at}")}'


def validate_csrf_token(token):
    """校验 CSRF 令牌。

    Args:
        token: 客户端提交的令牌

    Returns:
        bool: True 表示通过
    """
    if not isinstance(token, str) or not token:
        return False

    raw = session.get(SESSION_KEY)
    if not isinstance(raw, str) or not raw:
        # 会话里没有密钥 —— 说明从未渲染过我们的页面，或 session 已被清空
        return False

    try:
        expires_str, signature = token.rsplit('.', 1)
        expires_at = int(expires_str)
    except (ValueError, AttributeError):
        return False

    if expires_at < int(time.time()):
        return False  # 令牌已过期（页面开太久没动，刷新即可）

    expected = _sign(f'{raw}.{expires_at}')
    # 常量时间比较，避免通过响应耗时逐字节爆破签名
    return hmac.compare_digest(signature, expected)


def rotate_csrf_token():
    """作废当前会话已发出的所有令牌，重新签发。

    用在登录成功时：登录前的匿名会话和登录后的身份是两回事，
    换掉密钥可以避免登录前拿到的令牌继续用于登录后的操作
    （与「登录后更换 session id」是同一类防护）。
    """
    session.pop(SESSION_KEY, None)
    return generate_csrf_token()


# ============================================================
# 豁免装饰器
# ============================================================

def csrf_exempt(f):
    """标记某个视图不做 CSRF 校验。

    仅用于确实无副作用、或由服务端内部调用的接口。
    写操作路由一律不要加 —— 加了就等于这项防护对它完全失效。
    """
    setattr(f, _EXEMPT_ATTR, True)
    return f


def is_exempt(view_func):
    """判断视图函数是否被豁免。"""
    if view_func is None:
        return False
    return getattr(view_func, _EXEMPT_ATTR, False) is True


# ============================================================
# 请求校验（由 app.py 的 before_request 调用）
# ============================================================

def _token_from_request():
    """从请求中取出令牌，按「表单字段 → JSON body → 请求头」顺序查找。

    三种来源都支持，是为了让表单提交和 fetch 请求都能用同一种机制，
    不必为 AJAX 单独开后门。
    """
    token = request.form.get(FIELD_NAME)
    if token:
        return token

    if request.is_json:
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            token = data.get(FIELD_NAME)
            if token:
                return token

    for name in HEADER_NAMES:
        token = request.headers.get(name)
        if token:
            return token
    return None


def _wants_json():
    """客户端是否期望 JSON 响应（AJAX 请求）。"""
    return (request.headers.get('X-Requested-With') is not None
            or request.path.startswith('/api/'))


def _error_response(reason):
    """构造校验失败的响应：AJAX 给 JSON，页面给 400 提示页。"""
    # 记日志但不让它影响响应：日志写不出去（磁盘满/只读）不该掩盖安全问题本身
    try:
        current_app.logger.warning(
            f'CSRF 校验失败: {reason} method={request.method} '
            f'path={request.path} ip={request.remote_addr} '
            f'ua={request.headers.get("User-Agent", "")[:80]}')
    except Exception:
        pass

    message = f'请求未通过安全校验（{reason}），请返回原页面刷新后重试。'
    if _wants_json():
        return jsonify({'success': False, 'message': message}), 400
    return render_template('errors/400.html', message=message), 400


def verify_csrf():
    """校验当前请求。由 app.py 的 before_request 钩子调用。

    Returns:
        None 表示放行；否则返回 (响应体, 状态码) 直接终止请求。
    """
    # 总开关：CSRF_ENABLED=False 时完全不校验（仅供排障/特殊部署，生产别关）
    if not config.CSRF_ENABLED:
        return None

    # 只读方法不校验
    if request.method in SAFE_METHODS:
        return None

    # 路由不存在时交给 404 处理器，不要抢先报安全错误
    endpoint = request.endpoint
    if not endpoint:
        return None

    if is_exempt(current_app.view_functions.get(endpoint)):
        return None

    token = _token_from_request()
    if not token:
        return _error_response('缺少安全令牌')
    if not validate_csrf_token(token):
        return _error_response('安全令牌无效或已过期')

    return None
