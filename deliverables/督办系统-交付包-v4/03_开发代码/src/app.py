"""app.py — Flask 应用工厂 + 启动主程序

职责：
1. 创建 Flask 应用，加载配置
2. 初始化数据库（建表 + 默认配置）
3. 注册所有蓝图（路由模块）
4. 注册错误处理器（403/404/500）
5. 注册 Jinja2 自定义过滤器
6. 注入全局模板上下文（current_user / unread_count）
7. 启动后台守护线程（逾期扫描 + 预警扫描）
8. 自动打开浏览器

启动方式：双击 start.bat 或命令行 python app.py
"""

import os
import sys
import logging
import webbrowser
import threading
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from flask import Flask, session, redirect, url_for, render_template

import config
import db
import models
import csrf
from routes import register_blueprints
import seed_demo_data as demo_seed


def setup_logging(app):
    """配置应用日志：文件（按大小轮转）+ 控制台。

    此前只输出到控制台，程序一关或窗口一闪就没了，线上出问题无从追查。
    现在同时写文件：
      - 开发时落在 项目根/logs/supervision.log
      - 打包后落在 exe 同级目录/logs/supervision.log（便于离线部署排查）

    两个防护点：
      1. 日志目录创建失败（例如部署在只读目录）时**静默降级**为仅控制台，
         绝不因为日志配置失败导致程序起不来。
      2. handler 只添加一次——测试套件会反复调用 create_app()，
         重复添加会让每条日志打印多遍。
    """
    level = getattr(logging, str(config.LOG_LEVEL).upper(), logging.INFO)
    app.logger.setLevel(level)

    fmt = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')

    # Flask 默认自带一个控制台 handler，统一套用我们的格式
    for h in app.logger.handlers:
        h.setFormatter(fmt)

    # 若没有任何 handler（被外部清空过），补一个控制台输出
    if not app.logger.handlers:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        app.logger.addHandler(console)

    # 文件 handler：只加一次，按大小轮转，避免日志无限增长撑爆磁盘
    if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        try:
            os.makedirs(config.LOG_DIR, exist_ok=True)
            file_handler = RotatingFileHandler(
                config.LOG_FILE,
                maxBytes=config.LOG_MAX_BYTES,
                backupCount=config.LOG_BACKUP_COUNT,
                encoding='utf-8',
                # delay=True：首次真正写日志时才打开文件。
                # 测试套件会反复 create_app()，延迟打开可避免堆出一堆文件句柄。
                delay=True)
            file_handler.setFormatter(fmt)
            app.logger.addHandler(file_handler)
        except OSError as e:
            # 只读目录等场景下写不了文件——降级为仅控制台，不阻断启动
            app.logger.warning(f'日志文件不可用，仅输出到控制台: {e}')


def create_app():
    """Flask 应用工厂：创建并配置 Flask 应用实例。"""
    # 显式指定模板和静态文件路径（兼容 PyInstaller 打包）
    app = Flask(__name__,
                template_folder=config.TEMPLATE_DIR,
                static_folder=config.STATIC_DIR)

    # 加载配置
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['PERMANENT_SESSION_LIFETIME'] = config.PERMANENT_SESSION_LIFETIME
    app.config['DEBUG'] = config.DEBUG
    app.config['TEMPLATES_AUTO_RELOAD'] = True

    # 会话 Cookie 安全属性（DEF-004 配套加固）
    # SAMESITE=Lax 让跨站 POST 不带会话 Cookie，是 CSRF 的第一道防线
    app.config['SESSION_COOKIE_HTTPONLY'] = config.SESSION_COOKIE_HTTPONLY
    app.config['SESSION_COOKIE_SAMESITE'] = config.SESSION_COOKIE_SAMESITE
    app.config['SESSION_COOKIE_SECURE'] = config.SESSION_COOKIE_SECURE

    # 配置日志（文件轮转 + 控制台）
    setup_logging(app)

    # --- 反向代理支持（默认关闭）---
    # 部署在 Nginx/Caddy 后面时，客户端 IP 会被记成代理服务器的地址。
    # 这会让 DEF-005 的登录限流「一人被锁、全员陪绑」，日志里的 IP 也全是错的。
    # 因此生产部署（尤其是 4.2 的 HTTPS 反向代理场景）需要开启 BEHIND_PROXY。
    #
    # 默认关闭是刻意的：开启后应用会**信任** X-Forwarded-* 请求头，
    # 若实际并没有代理在前面，攻击者可以自己伪造这些头来绕过限流。
    if config.BEHIND_PROXY:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=config.BEHIND_PROXY_TRUSTED_HOPS,
            x_proto=config.BEHIND_PROXY_TRUSTED_HOPS,
            x_host=config.BEHIND_PROXY_TRUSTED_HOPS,
        )
        app.logger.info(
            f'已启用反向代理模式：信任 {config.BEHIND_PROXY_TRUSTED_HOPS} 层代理的 '
            f'X-Forwarded-* 头（客户端 IP 将取真实来源）')

    # --- 初始化数据库 ---
    # 首次启动时自动建表 + 写入默认配置
    with app.app_context():
        models.init_db()

    # --- 注册蓝图 ---
    register_blueprints(app)

    # --- CSRF 防护（DEF-002）---
    register_csrf_protection(app)

    # --- 注册错误处理器 ---
    register_error_handlers(app)

    # --- 注册 Jinja2 过滤器 ---
    register_jinja_filters(app)

    # --- 注册上下文处理器 ---
    register_context_processors(app)

    return app


def register_csrf_protection(app):
    """注册 CSRF 防护钩子（DEF-002）。

    在**每个请求进入视图函数之前**校验写请求的 CSRF 令牌。
    放在 before_request 而不是给每个路由加装饰器，是为了不留遗漏——
    将来新写一条 POST 路由时，它默认就是受保护的，
    而不是依赖写代码的人记得加装饰器。

    必须放在 register_blueprints 之后：校验豁免要按 endpoint 查视图函数，
    而 endpoint 只有在蓝图注册后才存在。
    """

    @app.before_request
    def _check_csrf():
        result = csrf.verify_csrf()
        if result is not None:
            return result
        return None


def register_error_handlers(app):
    """注册全局错误处理器。"""

    @app.errorhandler(403)
    def forbidden(e):
        """权限不足时返回 403 页面。"""
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        """页面不存在时返回 404 页面。"""
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        """服务器内部错误时记录日志并返回 500 页面。"""
        app.logger.error(f'服务器错误: {e}')
        return render_template('errors/500.html'), 500


def register_jinja_filters(app):
    """注册 Jinja2 自定义过滤器（模板中可用）。"""

    @app.template_filter('format_date')
    def format_date(date_str):
        """格式化日期：'2025-08-25' -> '2025-08-25'。"""
        if not date_str:
            return '—'
        # 截取日期部分（兼容日期和日期时间字符串）
        return str(date_str)[:10]

    @app.template_filter('format_datetime')
    def format_datetime(dt_str):
        """格式化日期时间：'2025-08-25 14:30:00' -> '2025-08-25 14:30'。"""
        if not dt_str:
            return '—'
        return str(dt_str)[:16]

    @app.template_filter('time_ago')
    def time_ago(dt_str):
        """相对时间格式化：'2小时前' / '3天前' / '刚刚'。"""
        if not dt_str:
            return '—'
        try:
            dt = datetime.strptime(str(dt_str)[:19], '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return str(dt_str)
        now = datetime.now()
        diff = now - dt
        seconds = int(diff.total_seconds())

        if seconds < 60:
            return '刚刚'
        elif seconds < 3600:
            return f'{seconds // 60}分钟前'
        elif seconds < 86400:
            return f'{seconds // 3600}小时前'
        elif seconds < 2592000:
            return f'{seconds // 86400}天前'
        else:
            return str(dt_str)[:10]

    @app.template_filter('status_label')
    def status_label(status):
        """状态码转中文标签。"""
        from state_machine import STATUS_LABELS
        return STATUS_LABELS.get(status, status)

    @app.template_filter('status_color')
    def status_color(status):
        """状态码转颜色名。"""
        from state_machine import STATUS_COLORS
        return STATUS_COLORS.get(status, 'gray')

    @app.template_filter('priority_label')
    def priority_label(priority):
        """优先级码转中文标签。"""
        from state_machine import PRIORITY_LABELS
        return PRIORITY_LABELS.get(priority, priority)


def register_context_processors(app):
    """注册全局模板上下文处理器。

    每次模板渲染时自动注入以下变量，无需在每个路由中手动传递：
    - current_user: 当前登录用户对象（未登录为 None）
    - unread_count: 当前用户未读消息数
    - warning_due_days / warning_inactive_days: 当前预警配置
    - password_min_length: 密码最小长度（取自 config，避免前端把数字写死后
      与后端配置脱节——改了 PASSWORD_MIN_LENGTH，提示文案自动跟着变）
    - csrf_token: 当前会话的 CSRF 令牌，模板里塞进表单 hidden 字段
    """

    @app.context_processor
    def inject_globals():
        user_id = session.get('user_id')
        current_user = None
        unread_count = 0
        if user_id:
            current_user = models.get_user(user_id)
            if current_user:
                unread_count = models.get_unread_count(user_id)
            else:
                # 用户已被删除或停用，清除 session
                session.clear()

        # 顶栏日期副标题（如「8月28日 周五」）
        weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        now = datetime.now()
        now_str = f"{now.month}月{now.day}日 {weekdays[now.weekday()]}"

        return {
            'current_user': current_user,
            'unread_count': unread_count,
            'now_str': now_str,
            'warning_due_days': models.get_config('warning_due_days', str(config.DEFAULT_WARNING_DUE_DAYS)),
            'warning_inactive_days': models.get_config('warning_inactive_days', str(config.DEFAULT_WARNING_INACTIVE_DAYS)),
            'password_min_length': config.PASSWORD_MIN_LENGTH,
            # CSRF 令牌：关闭防护时给空串，模板里不会渲染出 hidden 字段
            'csrf_token': csrf.generate_csrf_token() if config.CSRF_ENABLED else '',
        }


# ============================================================
# 主程序入口
# ============================================================

def open_browser():
    """延迟 1.5 秒后自动打开浏览器（等 Flask 启动完成）。
    本机始终用 127.0.0.1 打开，即使 HOST 配置为 0.0.0.0。
    """
    threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{config.PORT}')).start()


def seed_demo_data():
    """（已废弃）完整扩充数据请改用 seed_demo_data.py:main()。"""
    import seed_demo_data as demo_seed
    return demo_seed.main()

    # ---- 以下为旧版精简种子实现，已废弃，不再执行 ----
    from werkzeug.security import generate_password_hash
    from state_machine import change_task_status

    models.init_db()

    # 如果已有数据，先清空
    if models.has_admin():
        print('[提示] 检测到已有数据，将清空后重新灌入演示数据...')
        conn = db.get_db()
        conn.executescript("""
            DELETE FROM messages;
            DELETE FROM progress_logs;
            DELETE FROM tasks;
            DELETE FROM users;
            DELETE FROM system_config;
        """)
        conn.commit()
        models.init_db()
        print('[完成] 旧数据已清空')

    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    today = now.strftime('%Y-%m-%d')
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    tomorrow = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    three_days_later = (now + timedelta(days=3)).strftime('%Y-%m-%d')
    five_days_later = (now + timedelta(days=5)).strftime('%Y-%m-%d')
    ten_days_ago = (now - timedelta(days=10)).strftime('%Y-%m-%d')
    eight_days_ago = (now - timedelta(days=8)).strftime('%Y-%m-%d')
    five_days_ago = (now - timedelta(days=5)).strftime('%Y-%m-%d')

    print('正在创建用户...')
    admin_id = models.create_user('admin', '管理员', generate_password_hash('Supv#Admin2026'), 'admin')
    zhang_id = models.create_user('zhangsan', '张三', generate_password_hash('Supv#Owner2026'), 'owner')
    li_id = models.create_user('lisi', '李四', generate_password_hash('Supv#Owner2026'), 'owner')
    wang_id = models.create_user('wangwu', '王五', generate_password_hash('Supv#Owner2026'), 'owner')
    zhao_id = models.create_user('zhaoliu', '赵六', generate_password_hash('Supv#Owner2026'), 'owner')
    print(f'  管理员 admin/Supv#Admin2026 + 4 个负责人（密码均为 Supv#Owner2026）')

    print('正在创建任务...')
    # 待启动 (3个)
    t1 = models.create_task('Q3季度总结报告撰写', '汇总Q3各项目进展、完成情况、问题与风险，形成PPT汇报材料。', admin_id, zhang_id, 'high', five_days_later)
    db.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (eight_days_ago + ' 09:00:00', t1))
    t2 = models.create_task('新员工培训计划制定', '制定下月新入职员工的培训计划，包含培训课程表、导师分配、考核标准。', admin_id, li_id, 'medium', ten_days_ago)
    db.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (five_days_ago + ' 10:00:00', t2))
    t3 = models.create_task('办公用品采购清单整理', '统计各部门办公用品需求，整理采购清单，提交审批。', zhang_id, zhang_id, 'low', three_days_later)

    # 进行中 (4个)
    t4 = models.create_task('客户满意度调研方案设计', '设计客户满意度调研问卷，覆盖产品体验、服务态度、响应速度三个维度。', admin_id, wang_id, 'urgent', tomorrow)
    change_task_status(t4, 'in_progress', admin_id, 'admin', '已安排王五负责，开始推进')
    t5 = models.create_task('服务器迁移方案评审', '评审新旧服务器迁移方案，确认迁移步骤、回滚策略、停机窗口。', admin_id, zhang_id, 'high', three_days_later)
    change_task_status(t5, 'in_progress', admin_id, 'admin', '方案初稿已完成，正在评审')
    t6 = models.create_task('部门周报模板优化', '优化部门周报模板，增加风险追踪、下周计划、资源需求三个板块。', li_id, li_id, 'medium', five_days_later)
    change_task_status(t6, 'in_progress', li_id, 'owner', '开始修改模板结构')
    t12 = models.create_task('今日紧急：月度经营数据分析', '今日下班前完成月度经营数据分析报告，提交给管理层审阅。', admin_id, zhang_id, 'urgent', today)
    change_task_status(t12, 'in_progress', admin_id, 'admin', '紧急任务，今日必须完成')

    # 已逾期 (2个)
    t7 = models.create_task('年度预算编制与审核', '编制下一年度部门预算，包含人力成本、设备采购、差旅费用、培训费用四大板块。', admin_id, zhao_id, 'urgent', yesterday)
    change_task_status(t7, 'in_progress', admin_id, 'admin', '赵六已开始编制')
    db.execute("UPDATE tasks SET status = 'overdue', is_overdue = 1, updated_at = ? WHERE task_id = ?", (now_str, t7))
    models.create_progress_log(t7, None, now_str, 'in_progress', 'overdue', '系统自动标记：任务超过截止日期')
    models.create_message(zhao_id, None, 'warning_overdue', f'任务「年度预算编制与审核」已逾期，请尽快处理或更新进度。', t7)
    models.create_message(admin_id, None, 'warning_overdue', f'任务「年度预算编制与审核」已逾期，负责人：赵六。', t7)

    t8 = models.create_task('供应商合同续签谈判', '与核心供应商洽谈年度合同续签，争取价格优惠5%，锁定交付周期。', admin_id, wang_id, 'high', five_days_ago)
    change_task_status(t8, 'in_progress', admin_id, 'admin', '王五已开始谈判')
    db.execute("UPDATE tasks SET status = 'overdue', is_overdue = 1, updated_at = ? WHERE task_id = ?", (now_str, t8))
    models.create_progress_log(t8, None, now_str, 'in_progress', 'overdue', '系统自动标记：任务超过截止日期')

    # 已闭环 (2个)
    t9 = models.create_task('Q2绩效考核完成', '完成Q2全员绩效考核，汇总评分结果，形成绩效报告。', admin_id, zhang_id, 'high', five_days_ago)
    change_task_status(t9, 'in_progress', admin_id, 'admin', '开始收集考核数据')
    change_task_status(t9, 'closed', zhang_id, 'owner', '考核数据已收集完毕，绩效报告已提交')
    t10 = models.create_task('办公网络升级实施', '升级办公网络带宽，更换核心交换机，优化WiFi覆盖。', admin_id, zhao_id, 'urgent', ten_days_ago)
    change_task_status(t10, 'in_progress', admin_id, 'admin', '设备已到货，开始施工')
    change_task_status(t10, 'closed', zhao_id, 'owner', '网络升级完成，测速达标，WiFi全覆盖')

    # 已撤销 (1个)
    t11 = models.create_task('团建活动策划（已取消）', '原计划组织部门团建活动，因预算调整取消。', admin_id, li_id, 'low', three_days_later)
    change_task_status(t11, 'cancelled', admin_id, 'admin', '因预算调整，本期取消团建计划')

    print('正在创建消息通知...')
    models.create_message(zhang_id, admin_id, 'assignment', '管理员给你指派了新任务「Q3季度总结报告撰写」', t1)
    models.create_message(wang_id, admin_id, 'assignment', '管理员给你指派了新任务「客户满意度调研方案设计」', t4)
    models.create_message(zhao_id, admin_id, 'assignment', '管理员给你指派了新任务「年度预算编制与审核」', t7)
    models.create_message(li_id, admin_id, 'assignment', '管理员给你指派了新任务「新员工培训计划制定」', t2)
    models.create_message(wang_id, None, 'warning_due', '任务「客户满意度调研方案设计」将在 1 天后到期，请及时跟进。', t4)
    models.create_message(zhang_id, None, 'warning_due', '任务「今日紧急：月度经营数据分析」将在今天到期，请尽快完成。', t12)
    models.create_message(zhang_id, None, 'warning_inactive', '任务「Q3季度总结报告撰写」创建 8 天仍未启动，请尽快处理。', t1)
    models.create_message(admin_id, None, 'warning_inactive', '任务「Q3季度总结报告撰写」创建 8 天仍未启动（负责人：张三）。', t1)
    models.create_message(zhang_id, admin_id, 'admin_directive', 'Q3报告请重点关注营收增长部分的同比分析，管理层很关注这个数据。', t1)
    models.create_message(zhao_id, admin_id, 'admin_directive', '预算编制请参考去年数据，人力成本板块需要细化到每个人。', t7)
    # 前3条标记已读
    msgs = db.query("SELECT message_id FROM messages ORDER BY message_id LIMIT 3")
    for msg in msgs:
        db.execute("UPDATE messages SET is_read = 1 WHERE message_id = ?", (msg['message_id'],))

    print()
    print('=' * 50)
    print('演示数据灌入完成！')
    print('=' * 50)
    print(f'  用户: 5 个（1 管理员 + 4 负责人）')
    print(f'  任务: 12 个（待启动3/进行中4/已逾期2/已闭环2/已撤销1）')
    print(f'  消息: 10 条（3 已读 + 7 未读）')
    print()
    print('登录账号：')
    print('  管理员: admin / Supv#Admin2026')
    print('  负责人: zhangsan / Supv#Owner2026')
    print('  负责人: lisi / Supv#Owner2026')
    print('  负责人: wangwu / Supv#Owner2026')
    print('  负责人: zhaoliu / Supv#Owner2026')


def clear_demo_data():
    """清除所有数据，恢复到初始状态（仅保留空表结构 + 默认配置）。"""
    print('正在清除所有数据...')
    conn = db.get_db()
    conn.executescript("""
        DELETE FROM messages;
        DELETE FROM progress_logs;
        DELETE FROM tasks;
        DELETE FROM users;
        DELETE FROM system_config;
    """)
    conn.commit()
    models.init_db()
    print()
    print('=' * 50)
    print('所有数据已清除，系统恢复到初始状态！')
    print('=' * 50)
    print('  下次启动将进入初始化向导，重新创建管理员账号。')


def main():
    """主程序入口。"""
    # 命令行参数处理：--seed-demo / --clear-demo
    if '--seed-demo' in sys.argv:
        demo_seed.main()
        return
    if '--clear-demo' in sys.argv:
        clear_demo_data()
        return

    app = create_app()

    # 启动后台守护线程（逾期扫描 + 预警扫描）
    # 仅在已有管理员时启动（首次启动需先完成初始化向导）
    if models.has_admin():
        try:
            import scheduler
            scheduler.start_background_tasks(app)
            app.logger.info('后台守护线程已启动（逾期扫描 + 预警扫描）')
        except Exception as e:
            app.logger.error(f'后台线程启动失败: {e}')
    else:
        app.logger.info('尚未创建管理员，后台线程将在初始化完成后重启生效')

    # 自动打开浏览器
    if not app.config['DEBUG']:
        open_browser()

    app.logger.info(f'督办系统启动: http://127.0.0.1:{config.PORT} (本机)')

    # 监听范围为「所有网卡」时提示局域网地址，让使用者清楚自己暴露到了哪里
    if config.HOST in ('0.0.0.0', '::'):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            lan_ip = s.getsockname()[0]
            s.close()
            app.logger.warning(
                f'已开放局域网访问: http://{lan_ip}:{config.PORT} '
                f'（HOST={config.HOST}）')
            print()
            print(f'  局域网其他设备请访问: http://{lan_ip}:{config.PORT}')
            print('  注意：同网段内任何设备都能打开本系统，确认网络环境可信。')
        except Exception:
            app.logger.info('无法获取局域网 IP 地址')
    else:
        app.logger.info(f'仅本机可访问（HOST={config.HOST}）；'
                        f'需要局域网访问请使用「局域网启动.bat」')

    if config.SERVER == 'waitress':
        _serve_waitress(app)
    else:
        if config.SERVER not in ('flask', 'werkzeug'):
            app.logger.warning(f'未知的 SERVER 取值 "{config.SERVER}"，回退到 Flask 开发服务器')
        app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, use_reloader=False)


def _serve_waitress(app):
    """用 Waitress（生产级 WSGI 服务器）承载应用。

    Waitress 是可选依赖：没装就退回 Flask 开发服务器并明确告警，
    绝不因为缺一个可选包就起不来服务。
    """
    try:
        from waitress import serve
    except ImportError:
        app.logger.error(
            'SERVER=waitress 但 waitress 未安装，已回退 Flask 开发服务器。'
            '生产部署请先执行: pip install waitress')
        app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, use_reloader=False)
        return

    app.logger.info(f'WSGI 服务器: waitress（监听 {config.HOST}:{config.PORT}）')
    serve(app, host=config.HOST, port=config.PORT)


if __name__ == '__main__':
    main()
