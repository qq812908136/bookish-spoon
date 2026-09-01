"""routes/__init__.py — 蓝图注册汇总

供 app.py 调用，统一注册所有功能模块的 Flask Blueprint。
"""

from flask import Flask


def register_blueprints(app: Flask):
    """注册所有路由蓝图到 Flask 应用。

    每个蓝图对应一个功能模块：
    - auth:      登录、登出、初始化向导
    - task:      任务 CRUD、状态变更、删除
    - progress:  进度记录提交与查看
    - message:   消息通知、标记已读、发消息
    - user:      用户管理（管理员）
    - settings:  个人设置、系统设置
    - dashboard: 仪表盘概览
    """
    # 延迟导入避免循环依赖
    from routes.auth_routes import auth_bp
    from routes.task_routes import task_bp
    from routes.progress_routes import progress_bp
    from routes.message_routes import message_bp
    from routes.user_routes import user_bp
    from routes.settings_routes import settings_bp
    from routes.dashboard_routes import dashboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(task_bp)
    app.register_blueprint(progress_bp)
    app.register_blueprint(message_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(dashboard_bp)
