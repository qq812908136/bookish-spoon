"""routes/mail_routes.py — 邮件功能路由（V4 迭代）

包含：
- GET  /mail                      邮件状态页（管理员，I1-①②③④）
- POST /mail/config               保存邮件配置
- POST /mail/test                 发送测试邮件（I1-④）
- POST /mail/scan                 立即扫描发送队列（不等 5 分钟）
- POST /mail/circuit/resume       手动恢复熔断（G3-③）
- POST /mail/log/<id>/requeue     失败邮件一键重发（G7-①）
- POST /mail/users/<id>/email     管理员代填用户邮箱（D4-② 补数据）
- GET  /mail/my                   「发给我的」邮件记录（H2-①，普通用户）

设计要点：
1. 状态页是管理员排障的主入口，所有异常（未配置 / 已熔断 / 有失败件 / 有人没填邮箱）
   都在这里**一次看完**，不需要翻日志。
2. 所有写操作走 POST + flash 重定向，与既有 settings/user 路由保持同一套交互习惯。
3. 环境变量锁定的配置项在页面上会明确标注「由 .env 锁定，页面修改不生效」——
   否则管理员会遇到「明明保存了却没变化」的假故障。
"""

import os

from flask import Blueprint, render_template, request, redirect, url_for, flash

import models
import mail_constants
import mail_dispatcher
from auth import login_required, admin_required, get_current_user

mail_bp = Blueprint('mail', __name__)

LOGS_PER_PAGE = 20


# ============================================================
# 工具函数
# ============================================================

def _env_locked_keys():
    """返回被环境变量/.env 锁定的配置项键名集合。

    get_mail_config() 的优先级是 env > db > config，
    被 env 占住的键即使页面保存成功也不会生效。
    这里提前算出来交给模板做标注，避免「保存了没变化」的困惑。
    """
    locked = set()
    for key, env_key, _attr, _typ in models.MAIL_SETTING_SCHEMA:
        raw = os.environ.get(env_key)
        if raw is not None and str(raw).strip() != '':
            locked.add(key)
    if os.environ.get('MAIL_SMTP_PASSWORD'):
        locked.add('smtp_password')
    return locked


def _redirect_to_status():
    """重定向回状态页，并保留当前的分页与筛选条件。

    只放行白名单里的键：request.args 是外部可控的，
    直接 **request.args 展开既可能带重复键（值变成列表），
    也可能被人塞进奇怪的参数拼进 URL。
    """
    keep = {}
    for key in ('status', 'mail_type', 'keyword', 'page'):
        val = request.args.get(key)
        if val:
            keep[key] = val
    return redirect(url_for('mail.status', **keep))


# ============================================================
# 一、状态页（I1-①②③④）
# ============================================================

@mail_bp.route('/mail')
@admin_required
def status():
    """邮件状态页：状态概览 + 配置表单 + 发送记录 + 失败清单 + 未填邮箱名单。"""
    user = get_current_user()

    cfg, pwd_masked, pwd_settable = models.get_mail_config_for_display()

    # --- I1-① 状态概览 ---
    today_stat = models.count_emails_today()
    overview = {
        'enabled': bool(cfg.get('enabled')),
        'configured': models.is_mail_configured(cfg),
        'reason': models.mail_unconfigured_reason(cfg),
        'circuit': models.get_circuit_state(),
        'today_success': today_stat['success'],
        'today_failed': today_stat['failed'],
        'pending': models.count_pending_emails(),
        'last_sent_at': models.get_last_sent_at(),
        'retention_days': cfg.get('retention_days'),
        'circuit_threshold': cfg.get('circuit_threshold'),
        'circuit_pause_minutes': cfg.get('circuit_pause_minutes'),
        'retry_backoff': ','.join(str(x) for x in cfg.get('retry_backoff') or []),
    }

    # --- I1-② 发送记录（带筛选与分页）---
    filters = {
        'status': request.args.get('status', ''),
        'mail_type': request.args.get('mail_type', ''),
        'keyword': request.args.get('keyword', '').strip(),
    }
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1

    logs, total, total_pages, page = models.get_email_logs(
        filters, page=page, per_page=LOGS_PER_PAGE)

    # --- I1-③ 失败清单 + 未填邮箱名单 ---
    failed_logs = models.get_failed_email_logs(limit=50)
    no_email_users = models.get_users_without_email()

    # --- I1-④ 测试邮件收件人候选（仅已填邮箱的启用用户）---
    candidates = list(models.get_mail_subscribers())
    candidate_ids = {u['user_id'] for u in candidates}
    if user['user_id'] not in candidate_ids:
        candidates.insert(0, {
            'user_id': user['user_id'],
            'display_name': user['display_name'],
            'email': (user['email'] if 'email' in user.keys() else '') or '',
        })

    return render_template(
        'mail/status.html',
        current_user=user,
        cfg=cfg,
        pwd_masked=pwd_masked,
        pwd_settable=pwd_settable,
        env_locked=_env_locked_keys(),
        overview=overview,
        logs=logs,
        total=total,
        total_pages=total_pages,
        page=page,
        filters=filters,
        failed_logs=failed_logs,
        no_email_users=no_email_users,
        candidates=candidates,
        mail_type_labels=mail_constants.MAIL_TYPE_LABELS,
        mail_types=mail_constants.MAIL_TYPE_LABELS.keys(),
    )


# ============================================================
# 二、配置保存
# ============================================================

@mail_bp.route('/mail/config', methods=['POST'])
@admin_required
def save_config():
    """保存邮件配置。

    复选框未勾选时不会出现在 form 里，因此这里**显式组装**全部布尔键，
    否则「取消勾选」会因为键缺失而保存不进去（值停留在旧的 1）。
    """
    form = request.form
    new_pwd = (form.get('smtp_password') or '').strip()

    data = {
        # 布尔型：显式取值，未勾选记 0
        'enabled':    'enabled' in form,
        'use_ssl':    'use_ssl' in form,
        'use_tls':    'use_tls' in form,
        'mask_title': 'mask_title' in form,
        # 文本 / 数值型
        'smtp_host':     form.get('smtp_host', ''),
        'smtp_port':     form.get('smtp_port', ''),
        'smtp_username': form.get('smtp_username', ''),
        'from_addr':     form.get('from_addr', ''),
        'from_name':     form.get('from_name', ''),
        'footer':        form.get('footer', ''),
        'batch_limit':   form.get('batch_limit', ''),
        'retry_max':     form.get('retry_max', ''),
        'manual_cooldown': form.get('manual_cooldown', ''),
        # 密码不在 MAIL_SETTING_SCHEMA 里，单独传；留空时由下面的 save_password=False 跳过
        'smtp_password': new_pwd,
    }

    errors = []

    # --- SSL / TLS 互斥 ---
    if data['use_ssl'] and data['use_tls']:
        errors.append('SSL 与 STARTTLS 只能选一种（国内邮箱服务一般用 465 端口 + SSL）')

    # --- 端口范围 ---
    try:
        port = int(str(data['smtp_port']).strip())
        if not (1 <= port <= 65535):
            errors.append('SMTP 端口应在 1-65535 之间')
    except ValueError:
        errors.append('SMTP 端口必须是整数')

    # --- 发件箱格式（只做最基本的 @ 检查，不追求 RFC 完备）---
    from_addr = str(data['from_addr']).strip()
    if from_addr and '@' not in from_addr:
        errors.append('发件箱地址格式不正确（需包含 @）')

    # --- 数值型范围 ---
    try:
        if not (1 <= int(str(data['batch_limit']).strip()) <= 200):
            errors.append('单轮发送上限应在 1-200 之间')
    except ValueError:
        errors.append('单轮发送上限必须是整数')

    try:
        if not (0 <= int(str(data['retry_max']).strip()) <= 5):
            errors.append('重试次数应在 0-5 之间')
    except ValueError:
        errors.append('重试次数必须是整数')

    try:
        if not (0 <= int(str(data['manual_cooldown']).strip()) <= 3600):
            errors.append('手动发送冷却应在 0-3600 秒之间')
    except ValueError:
        errors.append('手动发送冷却必须是整数')

    if errors:
        for err in errors:
            flash(err, 'error')
        return redirect(url_for('mail.status'))

    # --- 密码：留空表示不修改（save_password=False 时保留库中原有密文）---
    errs, saved = models.set_mail_config(data, save_password=bool(new_pwd))
    for err in errs:
        flash(err, 'error')

    if not errs:
        # 配置变更后重置连续失败计数：旧密码导致的失败不该累加到新配置上
        models.reset_fail_streak()
        flash(f'邮件配置已保存（{saved} 项）', 'success')

        locked = _env_locked_keys()
        if locked:
            flash(f'注意：{len(locked)} 项配置被 .env / 系统环境变量锁定，页面修改不会生效', 'error')

    return redirect(url_for('mail.status'))


# ============================================================
# 三、操作类
# ============================================================

@mail_bp.route('/mail/test', methods=['POST'])
@admin_required
def send_test():
    """发送测试邮件（I1-④）。"""
    try:
        recipient_id = int(request.form.get('recipient_id', 0))
    except ValueError:
        recipient_id = 0

    if not recipient_id:
        recipient_id = get_current_user()['user_id']

    result = mail_dispatcher.send_test_mail(recipient_id)
    flash(result['message'], 'success' if result['success'] else 'error')
    return _redirect_to_status()


@mail_bp.route('/mail/scan', methods=['POST'])
@admin_required
def scan_now():
    """立即扫描并发送队列（不必等下一个 5 分钟周期）。"""
    stat = mail_dispatcher.scan_and_send()

    if stat['skipped'] == 'not_configured':
        flash('邮件功能未启用或未完成配置，未执行发送', 'error')
    elif stat['skipped'] == 'circuit_open':
        flash('邮件发送已熔断，请先排查原因并点击「恢复发送」', 'error')
    elif stat['skipped']:
        flash('读取邮件队列失败，请查看运行日志', 'error')
    elif stat['sent'] or stat['failed']:
        flash(f"本轮发送完成：成功 {stat['sent']} 封，失败 {stat['failed']} 封", 'success')
    else:
        flash('队列中没有待发送的邮件', 'success')

    return _redirect_to_status()


@mail_bp.route('/mail/circuit/resume', methods=['POST'])
@admin_required
def circuit_resume():
    """手动恢复熔断（G3-③：认证失败需人工确认后才能恢复）。"""
    flash(mail_dispatcher.resume_circuit(), 'success')
    return _redirect_to_status()


@mail_bp.route('/mail/log/<int:log_id>/requeue', methods=['POST'])
@admin_required
def requeue(log_id):
    """失败邮件一键重发（G7-①）。"""
    ok, msg = models.requeue_failed_email(log_id)
    flash(msg, 'success' if ok else 'error')
    return _redirect_to_status()


@mail_bp.route('/mail/users/<int:user_id>/email', methods=['POST'])
@admin_required
def set_user_email(user_id):
    """管理员代填用户邮箱（D4-② 补齐漏填数据）。

    邮箱属于个人信息，写入前做最基本的格式校验，
    但不做可达性验证——发不出去会在发送记录里暴露出来，由失败清单兜底。
    """
    email = (request.form.get('email') or '').strip()

    if email and '@' not in email:
        flash('邮箱地址格式不正确（需包含 @）', 'error')
        return _redirect_to_status()

    target = models.get_user(user_id)
    if not target:
        flash('用户不存在', 'error')
        return _redirect_to_status()

    models.update_user_email(user_id, email)
    flash(f"已{'更新' if email else '清空'}用户「{target['display_name']}」的邮箱", 'success')
    return _redirect_to_status()


# ============================================================
# 四、普通用户：发给我的邮件（H2-①）
# ============================================================

@mail_bp.route('/mail/my')
@login_required
def my_mails():
    """「发给我的」邮件记录。管理员看全部时会走 /mail，这里只暴露自己的。"""
    user = get_current_user()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1

    logs, total, total_pages, page = models.get_my_email_logs(
        user['user_id'], page=page, per_page=LOGS_PER_PAGE)

    return render_template(
        'mail/my.html',
        current_user=user,
        logs=logs,
        total=total,
        total_pages=total_pages,
        page=page,
        mail_type_labels=mail_constants.MAIL_TYPE_LABELS,
        notify_level_labels=mail_constants.NOTIFY_LEVEL_LABELS,
    )
