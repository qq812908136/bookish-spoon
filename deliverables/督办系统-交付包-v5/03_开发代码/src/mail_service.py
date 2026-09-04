"""mail_service.py — SMTP 发送封装与错误分类（V4 迭代）

职责边界：
    本模块只做一件事——**把一封已经渲染好的邮件发出去，并说清楚结果**。
    队列、重试、熔断、合并都不归它管（那些在 mail_dispatcher.py）。

    这样切分的原因：发送是最容易出各种异常的环节（网络、认证、限流、
    被拒收……），把它单独隔离出来，单元测试可以用假 SMTP 对象覆盖，
    不必牵扯调度逻辑。

错误分类（G2 确认的规则）：
    auth       认证失败（535）        → 永久错误，立即熔断
    rejected   收件人不存在（550）    → 永久错误，不重试
    spam       被判定为垃圾邮件       → 永久错误 + 告警
    throttled  超出发信限额（452/454）→ 延迟较久后重试
    transient  超时/断连等临时故障    → 正常重试

安全硬约束（P-7）：
    SMTP 密码在任何情况下都不写进日志，包括异常信息。
    本模块的 _sanitize() 会在返回前把密码从错误文本里抹掉——
    smtplib 的异常理论上不含密码，但这条防线必须显式存在，
    因为"理论上"三个字在安全领域不算数。
"""

import smtplib
import socket
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate

import mail_constants

# SMTP 连接/读写的超时秒数。
# 太短会在慢网络下误判为失败，太长会拖住整个 5 分钟扫描循环；
# 30 秒是个折中，且 dispatcher 每轮只发有限封数，最坏情况可控。
SMTP_TIMEOUT = 30


def _sanitize(text, secrets=None):
    """把敏感串从文本中抹掉（用于错误信息与日志）。

    Args:
        text: 原始文本
        secrets: 需要遮蔽的敏感串列表（通常传 SMTP 密码）

    Returns:
        str: 已遮蔽的文本
    """
    if not text:
        return ''
    result = str(text)
    for secret in (secrets or []):
        if secret and len(str(secret)) >= 3:
            result = result.replace(str(secret), '******')
    return result


def _classify(exc, code=None):
    """把 smtplib 异常归类为 mail_constants 中的错误类型。

    Returns:
        tuple: (错误类型, SMTP 响应码或 None)
    """
    # 认证类：535 密码错误、530 需要认证、发件人被拒（通常是账号配置错）
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return mail_constants.PERMANENT_ERROR_AUTH, getattr(exc, 'smtp_code', None)
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return mail_constants.PERMANENT_ERROR_AUTH, getattr(exc, 'smtp_code', None)
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return mail_constants.PERMANENT_ERROR_REJECTED, 550

    resp_code = code or getattr(exc, 'smtp_code', None)

    if isinstance(exc, smtplib.SMTPDataError):
        # 552 = 超配额 / 内容被拒；554 = 事务失败（常见的垃圾邮件判定）
        if resp_code in (552, 554):
            return mail_constants.PERMANENT_ERROR_SPAM, resp_code
        if resp_code in (550, 553):
            return mail_constants.PERMANENT_ERROR_REJECTED, resp_code
        if resp_code in (452, 454):
            return mail_constants.THROTTLED_ERROR, resp_code
        return 'transient', resp_code

    if isinstance(exc, smtplib.SMTPResponseException):
        if resp_code in (452, 454):
            return mail_constants.THROTTLED_ERROR, resp_code
        if resp_code in (550, 553):
            return mail_constants.PERMANENT_ERROR_REJECTED, resp_code
        if resp_code in (552, 554):
            return mail_constants.PERMANENT_ERROR_SPAM, resp_code
        if resp_code is not None and 500 <= resp_code < 600:
            return 'transient', resp_code
        return 'transient', resp_code

    # 连接层故障：断连、连不上、超时、DNS 失败——一律视为临时故障
    if isinstance(exc, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected,
                        socket.timeout, socket.gaierror, OSError, ConnectionError)):
        return 'transient', resp_code

    return 'transient', resp_code


def build_message(cfg, recipient_email, subject, body, reply_to=None):
    """构造 MIME 邮件对象（纯文本 UTF-8，N-4）。

    Args:
        cfg: 邮件配置 dict
        recipient_email: 收件地址
        subject / body: 主题与正文
        reply_to: 回复地址（B2-③：指向具体操作人，收件人点"回复"回到真人）

    Returns:
        tuple: (MIMEText 对象, 实际使用的发件地址)
    """
    from_addr = (cfg.get('from_addr') or '').strip()
    from_name = (cfg.get('from_name') or '督办系统').strip()

    msg = MIMEText(body, 'plain', 'utf-8')
    # 中文主题必须走 Header 编码，否则部分客户端会显示乱码
    msg['Subject'] = Header(subject or '(无主题)', 'utf-8')
    msg['From'] = formataddr((str(Header(from_name, 'utf-8')), from_addr))
    msg['To'] = recipient_email
    msg['Date'] = formatdate(localtime=True)
    if reply_to:
        msg['Reply-To'] = reply_to

    # 抑制"自动发送"类的自动回复，减少无效回信（E5-① 的精神）
    msg['Auto-Submitted'] = 'auto-generated'
    return msg, from_addr


def send_email(cfg, recipient_email, subject, body, reply_to=None):
    """发送一封邮件。

    Args:
        cfg: models.get_mail_config() 的结果
        recipient_email: 收件地址
        subject / body: 主题与正文（已渲染好）
        reply_to: 回复地址

    Returns:
        dict: {
            'success': bool,
            'error_type': None | 'auth' | 'rejected' | 'spam' | 'throttled' | 'transient',
            'error_code': SMTP 响应码或 None,
            'error_message': 已脱敏的错误描述（成功时为 ''）
        }
    """
    password = cfg.get('smtp_password') or ''
    secrets = [password] if password else []

    try:
        msg, from_addr = build_message(cfg, recipient_email, subject, body, reply_to)

        host = (cfg.get('smtp_host') or '').strip()
        port = int(cfg.get('smtp_port') or 465)

        # --- 建立连接 ---
        # SSL 直连（465）优先于 STARTTLS（587）；两者都开时以 SSL 为准，
        # 因为这是最常见的"填错了但还能连上"的组合。
        if cfg.get('use_ssl'):
            server = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT)
        else:
            server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT)
            if cfg.get('use_tls'):
                server.starttls()

        try:
            username = (cfg.get('smtp_username') or '').strip()
            if username:
                server.login(username, password)
            server.sendmail(from_addr, [recipient_email], msg.as_string())
        finally:
            # 退出失败不影响发送结果（消息已经投递），只吞掉异常
            try:
                server.quit()
            except Exception:
                pass

        return {'success': True, 'error_type': None, 'error_code': None, 'error_message': ''}

    except Exception as e:
        error_type, error_code = _classify(e)
        raw = f'{type(e).__name__}: {e}'
        return {
            'success': False,
            'error_type': error_type,
            'error_code': error_code,
            # 脱敏后再返回：这串文本最终会进数据库和日志
            'error_message': _sanitize(raw, secrets)[:500],
        }


def send_test_email(cfg, recipient_email, recipient_name=''):
    """发送一封测试邮件（I1-④ 设置页「发送测试邮件」按钮）。

    内容与正式邮件区分开，便于管理员确认"这封是我刚点的测试"。

    Returns:
        dict: 同 send_email()
    """
    subject = '[督办系统] 测试邮件：配置验证'
    body = (
        f'您好，{recipient_name}：\n\n'
        '这是一封测试邮件，用于验证督办系统的邮件配置是否正确。\n'
        '收到本邮件说明 SMTP 配置可用，系统可以正常发送督办提醒。\n\n'
        '如果这不是您本人触发的操作，请忽略本邮件。\n\n'
        f'—— {cfg.get("footer") or "本邮件由督办系统自动发送，请勿直接回复。"}'
    )
    return send_email(cfg, recipient_email, subject, body)
