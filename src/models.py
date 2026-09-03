"""models.py — 数据访问层：建表 SQL + 全部 CRUD 封装函数

本文件包含：
1. init_db()：首次启动建表 + 创建索引 + 写入默认配置 + V2 迁移
2. 用户 CRUD 函数
3. 任务 CRUD 函数（含分页、筛选、排序）
4. 进度记录 CRUD 函数
5. 消息 CRUD 函数
6. 系统配置 CRUD 函数
7. 仪表盘统计函数
8. V2 增补：证据 / 阻塞 CRUD + 仪表盘统计 v2（6 卡 / 焦点 / 闭环矩阵）

所有函数返回 sqlite3.Row 对象（字典式访问）或普通 Python 类型。
"""

import json
import os
from datetime import datetime, timedelta

import config
import crypto_util
import db
import mail_constants

# ============================================================
# 一、数据库初始化
# ============================================================

def init_db():
    """初始化数据库：创建目录、建表、建索引、写入默认配置。

    首次启动时由 app.py 调用。使用 CREATE TABLE IF NOT EXISTS，
    重复调用不会破坏已有数据。
    """
    # 确保数据目录存在
    os.makedirs(config.DATA_DIR, exist_ok=True)

    conn = db.get_db()

    # --- 建表 ---
    conn.executescript("""
    -- 1. 用户表
    CREATE TABLE IF NOT EXISTS users (
        user_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        username       TEXT    NOT NULL UNIQUE,
        display_name   TEXT    NOT NULL,
        password_hash  TEXT    NOT NULL,
        role           TEXT    NOT NULL DEFAULT 'owner',
        is_active      INTEGER NOT NULL DEFAULT 1,
        created_at     TEXT    NOT NULL
    );

    -- 2. 任务表
    CREATE TABLE IF NOT EXISTS tasks (
        task_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title            TEXT    NOT NULL,
        description      TEXT,
        created_by       INTEGER NOT NULL,
        assignee         INTEGER NOT NULL,
        status           TEXT    NOT NULL DEFAULT 'pending',
        priority         TEXT    NOT NULL DEFAULT 'medium',
        due_date         TEXT    NOT NULL,
        created_at       TEXT    NOT NULL,
        updated_at       TEXT    NOT NULL,
        closed_at        TEXT,
        completion_note  TEXT,
        is_overdue       INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (created_by) REFERENCES users(user_id),
        FOREIGN KEY (assignee)    REFERENCES users(user_id)
    );

    -- 3. 进度更新记录表
    CREATE TABLE IF NOT EXISTS progress_logs (
        log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id        INTEGER NOT NULL,
        operator       INTEGER,
        operated_at    TEXT    NOT NULL,
        status_from    TEXT,
        status_to      TEXT,
        progress_note  TEXT,
        FOREIGN KEY (task_id)  REFERENCES tasks(task_id) ON DELETE CASCADE,
        FOREIGN KEY (operator) REFERENCES users(user_id)
    );

    -- 4. 站内消息表
    CREATE TABLE IF NOT EXISTS messages (
        message_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        recipient    INTEGER NOT NULL,
        sender       INTEGER,
        type         TEXT    NOT NULL,
        content      TEXT    NOT NULL,
        task_id      INTEGER,
        is_read      INTEGER NOT NULL DEFAULT 0,
        created_at   TEXT    NOT NULL,
        FOREIGN KEY (recipient) REFERENCES users(user_id),
        FOREIGN KEY (sender)   REFERENCES users(user_id),
        FOREIGN KEY (task_id)  REFERENCES tasks(task_id) ON DELETE SET NULL
    );

    -- 5. 系统配置表
    CREATE TABLE IF NOT EXISTS system_config (
        config_key    TEXT    PRIMARY KEY,
        config_value  TEXT    NOT NULL,
        updated_at    TEXT    NOT NULL
    );
    """)

    # --- 建索引 ---
    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_tasks_status      ON tasks(status);
    CREATE INDEX IF NOT EXISTS idx_tasks_assignee    ON tasks(assignee);
    CREATE INDEX IF NOT EXISTS idx_tasks_due_date    ON tasks(due_date);
    CREATE INDEX IF NOT EXISTS idx_tasks_is_overdue  ON tasks(is_overdue);
    CREATE INDEX IF NOT EXISTS idx_tasks_created_by  ON tasks(created_by);
    CREATE INDEX IF NOT EXISTS idx_logs_task_id      ON progress_logs(task_id);
    CREATE INDEX IF NOT EXISTS idx_logs_operated_at  ON progress_logs(operated_at);
    CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient);
    CREATE INDEX IF NOT EXISTS idx_messages_is_read   ON messages(is_read);
    CREATE INDEX IF NOT EXISTS idx_messages_created   ON messages(created_at);
    """)

    # --- 写入默认配置（INSERT OR IGNORE 保证不重复插入）---
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.executemany(
        "INSERT OR IGNORE INTO system_config (config_key, config_value, updated_at) VALUES (?, ?, ?)",
        [
            ('warning_due_days',      str(config.DEFAULT_WARNING_DUE_DAYS),      now),
            ('warning_inactive_days', str(config.DEFAULT_WARNING_INACTIVE_DAYS), now),
            ('scan_interval_seconds', str(config.OVERDUE_SCAN_INTERVAL),         now),
            ('warning_scan_time',     config.WARNING_SCAN_TIME,                  now),
        ]
    )
    conn.commit()

    # V2 迁移：tasks 加 3 列 + evidence/blockers 两张新表（幂等，老库自动升级）
    _migrate_v2()

    # V3 迁移：邮件功能——users 加 2 列 + email_queue/email_log 两张新表
    _migrate_v3()

    # V4 迁移：AI 辅助生成——ai_queue / ai_log 两张新表（Phase 0）
    _migrate_v4()


def _migrate_v2():
    """V2 数据库迁移（幂等，可重复调用）。

    内容：
    1. 新建 evidence（过程证据）/ blockers（阻塞记录）两张表 + 索引
    2. tasks 表补 3 列：progress_percent / risk_note / collaborators
       （先用 PRAGMA table_info 检查列是否存在，不存在才 ALTER）

    老数据库升级时数据不丢；异常时打印日志但不中断启动。
    """
    conn = db.get_db()
    try:
        # --- 1. 新表（CREATE IF NOT EXISTS 天然幂等） ---
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id      INTEGER NOT NULL,
            etype        TEXT    NOT NULL,
            content      TEXT    NOT NULL,
            created_by   INTEGER,
            created_at   TEXT    NOT NULL,
            FOREIGN KEY (task_id)    REFERENCES tasks(task_id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS blockers (
            blocker_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id      INTEGER NOT NULL,
            content      TEXT    NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'open',
            created_by   INTEGER,
            created_at   TEXT    NOT NULL,
            resolved_at  TEXT,
            resolved_by  INTEGER,
            FOREIGN KEY (task_id)    REFERENCES tasks(task_id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_task ON evidence(task_id);
        CREATE INDEX IF NOT EXISTS idx_blockers_task ON blockers(task_id);
        """)
        conn.commit()

        # --- 2. tasks 补列（逐列检查，存在则跳过） ---
        existing_cols = {
            row['name'] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        new_cols = [
            ("progress_percent", "INTEGER NOT NULL DEFAULT 0"),
            ("risk_note",        "TEXT"),
            ("collaborators",    "TEXT"),
        ]
        migrated = []
        for col_name, col_def in new_cols:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_def}")
                migrated.append(col_name)
        if migrated:
            conn.commit()
            print(f"[migrate_v2] tasks 表已新增列: {', '.join(migrated)}")
    except Exception as e:  # pragma: no cover - 迁移失败不阻断启动
        print(f"[migrate_v2] 迁移异常（不影响启动）: {e}")


def _migrate_v3():
    """V3 数据库迁移：邮件通知功能（幂等，可重复调用）。

    内容：
    1. 新建 email_queue（待发队列）/ email_log（发送历史）两张表 + 索引
    2. users 表补 2 列：
       - email             TEXT  选填；未填则降级为只走站内信（A5-②/D4）
       - mail_notify_level TEXT  订阅等级，默认 'overdue'（D6-②）

    与 _migrate_v2 同一套路子：PRAGMA table_info 检查列存在性，
    老库升级数据不丢，异常只打印不阻断启动。
    """
    conn = db.get_db()
    try:
        # --- 1. 新表（CREATE IF NOT EXISTS 天然幂等） ---
        conn.executescript("""
        -- 邮件发送队列：所有待发邮件先落这里，由调度器每 5 分钟扫描发送（B6-③）
        CREATE TABLE IF NOT EXISTS email_queue (
            queue_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_id     INTEGER NOT NULL,
            recipient_email  TEXT    NOT NULL,
            task_id          INTEGER,
            mail_type        TEXT    NOT NULL,
            subject          TEXT    NOT NULL,
            body             TEXT    NOT NULL,
            reply_to         TEXT,
            operator_id      INTEGER,
            dedup_key        TEXT    NOT NULL,
            status           TEXT    NOT NULL DEFAULT 'pending',
            retry_count      INTEGER NOT NULL DEFAULT 0,
            next_attempt_at  TEXT    NOT NULL,
            last_error       TEXT,
            created_at       TEXT    NOT NULL,
            sent_at          TEXT,
            FOREIGN KEY (recipient_id) REFERENCES users(user_id),
            FOREIGN KEY (task_id)      REFERENCES tasks(task_id) ON DELETE CASCADE,
            FOREIGN KEY (operator_id)  REFERENCES users(user_id)
        );

        -- 邮件发送历史：发送成功/永久失败后从队列转入此表，保留 90 天（I2-②）
        CREATE TABLE IF NOT EXISTS email_log (
            log_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_id     INTEGER,
            recipient_email  TEXT    NOT NULL,
            task_id          INTEGER,
            mail_type        TEXT    NOT NULL,
            subject          TEXT    NOT NULL,
            operator_id      INTEGER,
            success          INTEGER NOT NULL,
            error_message    TEXT,
            attempts         INTEGER NOT NULL DEFAULT 1,
            created_at       TEXT    NOT NULL,
            finished_at      TEXT    NOT NULL,
            FOREIGN KEY (recipient_id) REFERENCES users(user_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_email_queue_dedup
            ON email_queue(dedup_key);
        CREATE INDEX IF NOT EXISTS idx_email_queue_status
            ON email_queue(status, next_attempt_at);
        CREATE INDEX IF NOT EXISTS idx_email_queue_recipient
            ON email_queue(recipient_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_email_log_created
            ON email_log(created_at);
        CREATE INDEX IF NOT EXISTS idx_email_log_recipient
            ON email_log(recipient_id, created_at);
        """)
        conn.commit()

        # --- 2. users 补列（逐列检查，存在则跳过） ---
        existing_cols = {
            row['name'] for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        new_cols = [
            ("email",             "TEXT"),
            ("mail_notify_level", "TEXT NOT NULL DEFAULT 'overdue'"),
        ]
        migrated = []
        for col_name, col_def in new_cols:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
                migrated.append(col_name)
        if migrated:
            conn.commit()
            print(f"[migrate_v3] users 表已新增列: {', '.join(migrated)}")
    except Exception as e:  # pragma: no cover - 迁移失败不阻断启动
        print(f"[migrate_v3] 迁移异常（不影响启动）: {e}")


# ============================================================
# 二、用户 CRUD
# ============================================================

def get_user(user_id):
    """根据 user_id 查询用户。"""
    return db.query_one("SELECT * FROM users WHERE user_id = ?", (user_id,))


def get_user_by_username(username):
    """根据用户名查询用户（登录用）。"""
    return db.query_one("SELECT * FROM users WHERE username = ?", (username,))


def create_user(username, display_name, password_hash, role='owner'):
    """创建新用户。

    Args:
        username: 登录账号（唯一）
        display_name: 显示姓名
        password_hash: 已哈希的密码
        role: 角色 'admin' / 'owner'

    Returns:
        int: 新用户的 user_id
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return db.execute(
        "INSERT INTO users (username, display_name, password_hash, role, is_active, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (username, display_name, password_hash, role, now)
    )


def get_all_users():
    """获取所有用户列表（按创建时间排序）。"""
    return db.query("SELECT * FROM users ORDER BY created_at ASC")


def get_all_active_users():
    """获取所有启用的用户（用于负责人下拉选项）。"""
    return db.query("SELECT * FROM users WHERE is_active = 1 ORDER BY display_name ASC")


def toggle_user_active(user_id):
    """切换用户启用/停用状态。"""
    user = get_user(user_id)
    if user:
        new_status = 0 if user['is_active'] else 1
        db.execute("UPDATE users SET is_active = ? WHERE user_id = ?", (new_status, user_id))


def update_password(user_id, password_hash):
    """更新用户密码哈希。"""
    db.execute("UPDATE users SET password_hash = ? WHERE user_id = ?", (password_hash, user_id))


def update_display_name(user_id, display_name):
    """更新用户显示名。"""
    db.execute("UPDATE users SET display_name = ? WHERE user_id = ?", (display_name, user_id))


def get_admin_user_ids():
    """获取所有管理员的 user_id 列表（预警抄送用）。"""
    rows = db.query("SELECT user_id FROM users WHERE role = 'admin' AND is_active = 1")
    return [row['user_id'] for row in rows]


def has_admin():
    """检查系统中是否已存在管理员账号（初始化向导用）。"""
    row = db.query_one("SELECT COUNT(*) as cnt FROM users WHERE role = 'admin'")
    return row['cnt'] > 0


def count_users():
    """统计用户总数。"""
    row = db.query_one("SELECT COUNT(*) as cnt FROM users")
    return row['cnt']


# ============================================================
# 三、任务 CRUD
# ============================================================

def get_tasks(filters=None, page=1, per_page=None):
    """根据筛选条件查询任务列表（含分页）。

    Args:
        filters: dict，支持的键：
            - status:    状态筛选（可选）
            - priority:  优先级筛选（可选）
            - assignee:  负责人ID筛选（可选）
            - keyword:   标题模糊搜索（可选）
            - sort:      排序方式，默认 due_date_asc
        page: 页码（从 1 开始）
        per_page: 每页条数，默认取 config.TASKS_PER_PAGE

    Returns:
        tuple: (任务列表 list[Row], 总条数 int)

    Note:
        本函数不做权限过滤（PRD Q4-B：owner 可看全部任务，只读）。
        权限过滤在模板层通过 can_edit_task 判断。
    """
    if filters is None:
        filters = {}
    if per_page is None:
        per_page = config.TASKS_PER_PAGE

    # 构造 WHERE 条件
    where_clauses = []
    params = []

    if filters.get('status'):
        where_clauses.append("t.status = ?")
        params.append(filters['status'])

    if filters.get('priority'):
        where_clauses.append("t.priority = ?")
        params.append(filters['priority'])

    if filters.get('assignee'):
        where_clauses.append("t.assignee = ?")
        params.append(filters['assignee'])

    if filters.get('keyword'):
        where_clauses.append("t.title LIKE ?")
        params.append(f"%{filters['keyword']}%")

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # 构造 ORDER BY
    sort = filters.get('sort', 'due_date_asc')
    order_map = {
        'due_date_asc':  't.due_date ASC',
        'due_date_desc': 't.due_date DESC',
        'priority_asc':  "CASE t.priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 END ASC",
        'priority_desc': "CASE t.priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 END DESC",
        'updated_desc':  't.updated_at DESC',
        'updated_asc':   't.updated_at ASC',
    }
    order_sql = " ORDER BY " + order_map.get(sort, order_map['due_date_asc'])

    # 查询总数
    count_sql = f"SELECT COUNT(*) as cnt FROM tasks t{where_sql}"
    total = db.query_one(count_sql, tuple(params))['cnt']

    # 分页查询（关联用户表获取负责人/创建人姓名）
    offset = (page - 1) * per_page
    list_sql = (
        "SELECT t.*, "
        "u_assignee.display_name AS assignee_name, "
        "u_creator.display_name AS creator_name "
        "FROM tasks t "
        "LEFT JOIN users u_assignee ON t.assignee = u_assignee.user_id "
        "LEFT JOIN users u_creator ON t.created_by = u_creator.user_id "
        + where_sql + order_sql + " LIMIT ? OFFSET ?"
    )
    params.extend([per_page, offset])
    tasks = db.query(list_sql, tuple(params))

    return tasks, total


def get_task(task_id):
    """查询单个任务详情（含负责人/创建人姓名）。"""
    return db.query_one(
        "SELECT t.*, "
        "u_assignee.display_name AS assignee_name, "
        "u_creator.display_name AS creator_name "
        "FROM tasks t "
        "LEFT JOIN users u_assignee ON t.assignee = u_assignee.user_id "
        "LEFT JOIN users u_creator ON t.created_by = u_creator.user_id "
        "WHERE t.task_id = ?",
        (task_id,)
    )


def create_task(title, description, created_by, assignee, priority, due_date):
    """创建新任务。

    Args:
        title: 任务标题
        description: 工作要求/描述
        created_by: 创建人 user_id
        assignee: 负责人 user_id
        priority: 优先级 urgent/high/medium/low
        due_date: 截止日期 YYYY-MM-DD

    Returns:
        int: 新任务 task_id
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return db.execute(
        "INSERT INTO tasks (title, description, created_by, assignee, status, priority, "
        "due_date, created_at, updated_at, is_overdue) "
        "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, 0)",
        (title, description, created_by, assignee, priority, due_date, now, now)
    )


def update_task(task_id, **fields):
    """更新任务字段（动态构造 SET 语句）。

    Args:
        task_id: 任务ID
        **fields: 要更新的字段，如 status='in_progress', updated_at='...'

    Note:
        此函数不加事务锁，调用方如需原子性请用 db.transaction()。
    """
    if not fields:
        return
    set_clauses = [f"{key} = ?" for key in fields]
    params = list(fields.values())
    params.append(task_id)
    sql = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE task_id = ?"
    db.execute(sql, tuple(params))


def delete_task(task_id):
    """物理删除任务（仅允许删除已撤销任务，由路由层校验）。

    级联删除关联的进度日志（ON DELETE CASCADE）。
    消息的 task_id 置为 NULL（ON DELETE SET NULL，保留历史消息）。
    """
    db.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))


def get_tasks_for_overdue_check(now_date):
    """查询所有超期未闭环的任务（逾期扫描用）。

    条件：状态为 pending 或 in_progress，且 due_date < 今天。

    Args:
        now_date: 今天的日期字符串 YYYY-MM-DD

    Returns:
        list[Row]: 超期任务列表
    """
    return db.query(
        "SELECT * FROM tasks WHERE status IN ('pending', 'in_progress') AND due_date < ?",
        (now_date,)
    )


def get_active_tasks_for_warning():
    """查询所有活跃任务（预警扫描用，排除终态 closed/cancelled）。"""
    return db.query(
        "SELECT * FROM tasks WHERE status IN ('pending', 'in_progress', 'overdue')"
    )


# ============================================================
# 四、进度记录 CRUD
# ============================================================

def create_progress_log(task_id, operator, operated_at, status_from, status_to, progress_note):
    """创建一条进度更新记录。

    Args:
        task_id: 关联任务ID
        operator: 操作人 user_id（系统自动操作时为 None）
        operated_at: 操作时间
        status_from: 变更前状态（首次创建为 None）
        status_to: 变更后状态
        progress_note: 进度备注
    """
    db.execute(
        "INSERT INTO progress_logs (task_id, operator, operated_at, status_from, status_to, progress_note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (task_id, operator, operated_at, status_from, status_to, progress_note)
    )


def get_progress_logs(task_id):
    """查询任务的进度记录时间线（按时间倒序）。"""
    return db.query(
        "SELECT pl.*, u.display_name AS operator_name "
        "FROM progress_logs pl "
        "LEFT JOIN users u ON pl.operator = u.user_id "
        "WHERE pl.task_id = ? ORDER BY pl.operated_at DESC",
        (task_id,)
    )


# ============================================================
# 五、消息 CRUD
# ============================================================

def create_message(recipient, sender, msg_type, content, task_id=None):
    """创建一条站内消息。

    Args:
        recipient: 接收人 user_id
        sender: 发送人 user_id（系统消息为 None）
        msg_type: 消息类型 assignment/status_change/warning_due/warning_overdue/warning_inactive/admin_directive
        content: 消息正文
        task_id: 关联任务ID（可选，用于点击跳转）
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db.execute(
        "INSERT INTO messages (recipient, sender, type, content, task_id, is_read, created_at) "
        "VALUES (?, ?, ?, ?, ?, 0, ?)",
        (recipient, sender, msg_type, content, task_id, now)
    )


def get_messages(user_id, filters=None):
    """查询用户的消息列表（按时间倒序）。

    Args:
        user_id: 接收人 user_id
        filters: dict，支持 type / is_read 筛选

    Returns:
        list[Row]: 消息列表
    """
    if filters is None:
        filters = {}

    where_clauses = ["m.recipient = ?"]
    params = [user_id]

    if filters.get('type'):
        where_clauses.append("m.type = ?")
        params.append(filters['type'])

    if filters.get('is_read') is not None:
        where_clauses.append("m.is_read = ?")
        params.append(filters['is_read'])

    where_sql = " WHERE " + " AND ".join(where_clauses)
    sql = (
        "SELECT m.*, u.display_name AS sender_name, t.title AS task_title "
        "FROM messages m "
        "LEFT JOIN users u ON m.sender = u.user_id "
        "LEFT JOIN tasks t ON m.task_id = t.task_id "
        + where_sql + " ORDER BY m.created_at DESC"
    )
    return db.query(sql, tuple(params))


def mark_message_read(message_id, user_id):
    """标记单条消息为已读（校验消息属于该用户）。"""
    db.execute(
        "UPDATE messages SET is_read = 1 WHERE message_id = ? AND recipient = ?",
        (message_id, user_id)
    )


def mark_all_read(user_id):
    """标记用户所有未读消息为已读。

    Returns:
        int: 标记的条数
    """
    conn = db.get_db()
    cursor = conn.execute(
        "UPDATE messages SET is_read = 1 WHERE recipient = ? AND is_read = 0",
        (user_id,)
    )
    conn.commit()
    return cursor.rowcount


def get_unread_count(user_id):
    """获取用户未读消息数（导航栏红点轮询用）。"""
    row = db.query_one(
        "SELECT COUNT(*) as cnt FROM messages WHERE recipient = ? AND is_read = 0",
        (user_id,)
    )
    return row['cnt']


def has_warning_today(task_id, recipient_id, msg_type, today):
    """检查今天是否已对该任务、该接收人发过同类型预警（去重用）。

    Args:
        task_id: 任务ID
        recipient_id: 接收人ID
        msg_type: 预警消息类型
        today: 今天的日期 YYYY-MM-DD

    Returns:
        bool: True 表示今天已发过，无需再发
    """
    row = db.query_one(
        "SELECT COUNT(*) as cnt FROM messages "
        "WHERE task_id = ? AND recipient = ? AND type = ? AND created_at LIKE ?",
        (task_id, recipient_id, msg_type, f"{today}%")
    )
    return row['cnt'] > 0


# ============================================================
# 六、系统配置 CRUD
# ============================================================

def get_config(key, default=None):
    """获取配置值。

    Args:
        key: 配置键
        default: 键不存在时的默认值

    Returns:
        str: 配置值
    """
    row = db.query_one("SELECT config_value FROM system_config WHERE config_key = ?", (key,))
    if row:
        return row['config_value']
    return default


def set_config(key, value):
    """设置配置值（存在则更新，不存在则插入）。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db.execute(
        "INSERT INTO system_config (config_key, config_value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(config_key) DO UPDATE SET config_value = ?, updated_at = ?",
        (key, value, now, value, now)
    )


def get_all_config():
    """获取所有配置项（字典形式）。"""
    rows = db.query("SELECT config_key, config_value FROM system_config")
    return {row['config_key']: row['config_value'] for row in rows}


# ============================================================
# 七、仪表盘统计
# ============================================================

def get_dashboard_stats(user_id=None):
    """获取仪表盘统计数据。

    Args:
        user_id: 当前用户ID（用于"我的待办"统计）

    Returns:
        dict: 统计数据
    """
    today = datetime.now().strftime('%Y-%m-%d')
    # 本周最后一天（7天后）
    from datetime import timedelta
    week_end = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')

    # 总任务数
    total = db.query_one("SELECT COUNT(*) as cnt FROM tasks WHERE status != 'cancelled'")['cnt']

    # 各状态数量
    status_counts = {}
    for row in db.query("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"):
        status_counts[row['status']] = row['cnt']

    # 已逾期数
    overdue_count = status_counts.get('overdue', 0)

    # 本周到期数（非终态，截止日期在今天到7天内）
    week_due = db.query_one(
        "SELECT COUNT(*) as cnt FROM tasks "
        "WHERE status IN ('pending', 'in_progress') AND due_date >= ? AND due_date <= ?",
        (today, week_end)
    )['cnt']

    # 我的待办数（分配给当前用户的非终态任务）
    my_pending = 0
    if user_id:
        my_pending = db.query_one(
            "SELECT COUNT(*) as cnt FROM tasks "
            "WHERE assignee = ? AND status IN ('pending', 'in_progress', 'overdue')",
            (user_id,)
        )['cnt']

    # 我的紧急任务数
    my_urgent = 0
    if user_id:
        my_urgent = db.query_one(
            "SELECT COUNT(*) as cnt FROM tasks "
            "WHERE assignee = ? AND priority = 'urgent' AND status IN ('pending', 'in_progress', 'overdue')",
            (user_id,)
        )['cnt']

    return {
        'total': total,
        'pending': status_counts.get('pending', 0),
        'in_progress': status_counts.get('in_progress', 0),
        'overdue': overdue_count,
        'closed': status_counts.get('closed', 0),
        'cancelled': status_counts.get('cancelled', 0),
        'week_due': week_due,
        'my_pending': my_pending,
        'my_urgent': my_urgent,
        'today': today,
    }


# ============================================================
# 八、V2 增补：证据 / 阻塞 CRUD
# ============================================================

EVIDENCE_TYPES = ('text', 'link', 'file')      # 证据三类型
EVIDENCE_TYPE_LABELS = {'text': '文字', 'link': '链接', 'file': '文件'}
BLOCKER_STATUSES = ('open', 'resolved')         # 阻塞两态
BLOCKER_STATUS_LABELS = {'open': '待解决', 'resolved': '已解决'}


def add_evidence(task_id, etype, content, created_by):
    """添加一条过程证据。

    Args:
        task_id: 关联任务ID
        etype: 证据类型 'text' / 'link' / 'file'
        content: 文字内容 / URL / 文件名（file 类不真正上传文件）
        created_by: 创建人 user_id

    Returns:
        int: 新证据 evidence_id
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return db.execute(
        "INSERT INTO evidence (task_id, etype, content, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (task_id, etype, content, created_by, now)
    )


def get_evidence_list(task_id):
    """查询任务的过程证据列表（按时间倒序，含创建人姓名）。"""
    return db.query(
        "SELECT e.*, u.display_name AS creator_name "
        "FROM evidence e "
        "LEFT JOIN users u ON e.created_by = u.user_id "
        "WHERE e.task_id = ? ORDER BY e.created_at DESC",
        (task_id,)
    )


def add_blocker(task_id, content, created_by):
    """添加一条阻塞记录（初始状态 open）。

    Returns:
        int: 新阻塞 blocker_id
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return db.execute(
        "INSERT INTO blockers (task_id, content, status, created_by, created_at) "
        "VALUES (?, ?, 'open', ?, ?)",
        (task_id, content, created_by, now)
    )


def get_blockers(task_id):
    """查询任务的阻塞记录（open 在前、resolved 在后，各按时间倒序）。"""
    return db.query(
        "SELECT b.*, "
        "u_creator.display_name AS creator_name, "
        "u_resolver.display_name AS resolver_name "
        "FROM blockers b "
        "LEFT JOIN users u_creator  ON b.created_by  = u_creator.user_id "
        "LEFT JOIN users u_resolver ON b.resolved_by = u_resolver.user_id "
        "WHERE b.task_id = ? "
        "ORDER BY CASE b.status WHEN 'open' THEN 0 ELSE 1 END, b.created_at DESC",
        (task_id,)
    )


def delete_evidence(evidence_id):
    """删除一条过程证据（仅管理员，权限由路由层校验）。

    Args:
        evidence_id: 证据ID

    Returns:
        bool: True 表示删除成功；False 表示记录不存在
    """
    row = db.query_one(
        "SELECT evidence_id FROM evidence WHERE evidence_id = ?", (evidence_id,)
    )
    if not row:
        return False
    db.execute("DELETE FROM evidence WHERE evidence_id = ?", (evidence_id,))
    return True


def delete_blocker(blocker_id):
    """删除一条阻塞记录（仅管理员，权限由路由层校验）。

    Args:
        blocker_id: 阻塞记录ID

    Returns:
        bool: True 表示删除成功；False 表示记录不存在
    """
    row = db.query_one(
        "SELECT blocker_id FROM blockers WHERE blocker_id = ?", (blocker_id,)
    )
    if not row:
        return False
    db.execute("DELETE FROM blockers WHERE blocker_id = ?", (blocker_id,))
    return True


def resolve_blocker(blocker_id, resolved_by):
    """标记一条阻塞为已解决。

    Args:
        blocker_id: 阻塞记录ID
        resolved_by: 操作人 user_id（路由层校验权限：admin 或创建者本人）

    Returns:
        bool: True 表示成功；False 表示记录不存在或已是 resolved
    """
    blocker = db.query_one(
        "SELECT * FROM blockers WHERE blocker_id = ?", (blocker_id,)
    )
    if not blocker or blocker['status'] == 'resolved':
        return False
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db.execute(
        "UPDATE blockers SET status = 'resolved', resolved_at = ?, resolved_by = ? "
        "WHERE blocker_id = ?",
        (now, resolved_by, blocker_id)
    )
    return True


# ============================================================
# 九、V2 增补：仪表盘统计（6 卡 / 焦点列表 / 闭环矩阵）
# ============================================================

# 支持的时间范围：全部 / 本年 / 本季 / 本月 / 本周
RANGE_KEYS = ('all', 'year', 'quarter', 'month', 'week')
RANGE_LABELS = {
    'all':      '全部',
    'year':     '本年',
    'quarter':  '本季',
    'month':    '本月',
    'week':     '本周',
}


def _range_start(range_key):
    """把时间范围键换算成起始日期（YYYY-MM-DD），'all' 返回 None。

    口径：按任务 created_at（创建时间）过滤。
    - year:     当年 1 月 1 日
    - quarter:  当季度首日（Q1=1月 / Q2=4月 / Q3=7月 / Q4=10月）
    - month:    当月 1 号
    - week:     本周一
    """
    today = datetime.now()
    if range_key == 'year':
        return today.replace(month=1, day=1).strftime('%Y-%m-%d')
    if range_key == 'quarter':
        quarter_first_month = ((today.month - 1) // 3) * 3 + 1
        return today.replace(month=quarter_first_month, day=1).strftime('%Y-%m-%d')
    if range_key == 'month':
        return today.replace(day=1).strftime('%Y-%m-%d')
    if range_key == 'week':
        from datetime import timedelta
        monday = today - timedelta(days=today.weekday())
        return monday.strftime('%Y-%m-%d')
    return None  # all / 未知值 → 不过滤


def _range_where(range_key, alias='t'):
    """构造时间范围 WHERE 片段。返回 (sql片段, params)。

    created_at 存的是 'YYYY-MM-DD HH:MM:SS'，用字符串前缀比较即可
    （'2026-08-25 10:00' >= '2026-08-01' 成立）。
    """
    start = _range_start(range_key)
    if start is None:
        return "", []
    return f" AND {alias}.created_at >= ?", [start]


def get_dashboard_stats_v2(range_key='all'):
    """V2 仪表盘 6 卡统计（按任务创建时间过滤）。

    卡片：任务总数 / 待启动 / 进行中 / 已逾期 / 已闭环 / 闭环率

    口径（已确认 Q9）：
    - 任务总数 = 非撤销任务数（total − cancelled）
    - 闭环率 = closed ÷ (total − cancelled)，分母为 0 时为 None（模板显示 —）

    Returns:
        dict: total/pending/in_progress/overdue/closed/cancelled/closure_rate
    """
    range_sql, range_params = _range_where(range_key)

    # 各状态计数（含撤销，供闭环率分母与详情使用）
    status_counts = {}
    for row in db.query(
        f"SELECT status, COUNT(*) as cnt FROM tasks t "
        f"WHERE 1=1{range_sql} GROUP BY status",
        tuple(range_params)
    ):
        status_counts[row['status']] = row['cnt']

    cancelled = status_counts.get('cancelled', 0)
    total = sum(status_counts.values()) - cancelled   # 任务总数（非撤销）
    closed = status_counts.get('closed', 0)

    # 闭环率：closed ÷ (总数 − 已撤销)；分母 0 → None
    closure_rate = round(closed / total, 4) if total > 0 else None

    return {
        'total': total,
        'pending': status_counts.get('pending', 0),
        'in_progress': status_counts.get('in_progress', 0),
        'overdue': status_counts.get('overdue', 0),
        'closed': closed,
        'cancelled': cancelled,
        'closure_rate': closure_rate,
        'today': datetime.now().strftime('%Y-%m-%d'),
    }


def get_today_focus(range_key='all', user_id=None, limit=20):
    """V2 今日督办焦点列表。

    规则（设计文档 §3.2）：
    - 取非终态任务（待启动/进行中/已逾期）
    - 排序：已逾期 > 进行中 > 待启动，同状态内按到期日升序
    - 最多 limit 条（默认 20）
    - 当前用户负责的任务标记 is_mine（模板显示"我的"小标记）

    Returns:
        list[dict]: 任务行（含 assignee_name / is_mine）
    """
    range_sql, range_params = _range_where(range_key)
    sql = (
        "SELECT t.task_id, t.title, t.status, t.priority, t.due_date, "
        "t.progress_percent, t.assignee, "
        "u.display_name AS assignee_name "
        "FROM tasks t "
        "LEFT JOIN users u ON t.assignee = u.user_id "
        f"WHERE t.status IN ('pending', 'in_progress', 'overdue'){range_sql} "
        "ORDER BY CASE t.status "
        "    WHEN 'overdue' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, "
        "    t.due_date ASC "
        "LIMIT ?"
    )
    rows = db.query(sql, tuple(range_params + [limit]))

    # Row 不可写，转 dict 并补 is_mine 标记
    result = []
    for row in rows:
        item = dict(row)
        item['is_mine'] = bool(user_id and row['assignee'] == user_id)
        result.append(item)
    return result


def get_closure_matrix(range_key='all', page=1, per_page=6):
    """V2 任务闭环矩阵（按负责人聚合）。

    每行：负责人 | 任务数 | 待启动 | 进行中 | 已逾期 | 已闭环 | 已撤销 | 闭环率
    - 任务数 = 非撤销任务数；闭环率 = 闭环 ÷ 任务数（分母 0 → None）
    - 按任务数降序排列，每页 per_page 人（默认 6）

    Returns:
        tuple: (矩阵行列表, 负责人总数, 总页数, 当前页)
    """
    range_sql, range_params = _range_where(range_key)
    params = tuple(range_params)

    # 负责人总数（用于分页）
    total = db.query_one(
        f"SELECT COUNT(DISTINCT t.assignee) as cnt FROM tasks t WHERE 1=1{range_sql}",
        params
    )['cnt']
    total_pages = max(1, -(-total // per_page))   # 向上取整
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page

    rows = db.query(
        "SELECT u.user_id, u.display_name, "
        "SUM(CASE WHEN t.status != 'cancelled' THEN 1 ELSE 0 END) as total, "
        "SUM(CASE WHEN t.status =  'pending'     THEN 1 ELSE 0 END) as pending, "
        "SUM(CASE WHEN t.status =  'in_progress' THEN 1 ELSE 0 END) as in_progress, "
        "SUM(CASE WHEN t.status =  'overdue'     THEN 1 ELSE 0 END) as overdue, "
        "SUM(CASE WHEN t.status =  'closed'      THEN 1 ELSE 0 END) as closed, "
        "SUM(CASE WHEN t.status =  'cancelled'   THEN 1 ELSE 0 END) as cancelled "
        "FROM tasks t "
        "LEFT JOIN users u ON t.assignee = u.user_id "
        f"WHERE 1=1{range_sql} "
        "GROUP BY t.assignee "
        "ORDER BY total DESC, u.display_name ASC "
        "LIMIT ? OFFSET ?",
        params + (per_page, offset)
    )

    # Row → dict，补闭环率
    matrix = []
    for row in rows:
        item = dict(row)
        item['total'] = item['total'] or 0
        closure = item['closed'] or 0
        item['closure_rate'] = round(closure / item['total'], 4) if item['total'] > 0 else None
        matrix.append(item)
    return matrix, total, total_pages, page


# ============================================================
# 十一、邮件通知（V4 迭代）
# ============================================================
# 分四块：
#   A. 邮件配置读写（三级优先级 + 密码加密）
#   B. 用户邮箱与订阅等级
#   C. 发送队列 CRUD
#   D. 发送历史（email_log）与统计
#
# 设计要点见 docs/督办系统-V4邮件功能需求清单.md。


# --- A. 邮件配置读写 -------------------------------------------------------

# 配置项的「键名 → 环境变量名 → config 属性 → 类型」映射表。
# 读取优先级：系统环境变量/.env  >  数据库（设置页填写）  >  config.py 默认值。
#
# 注意：这里必须直接读 os.environ，不能用 config.MAIL_* 判断「环境变量有没有配」——
# config 里的值已是「env 或默认值」的合并结果，无法反推来源。
MAIL_SETTING_SCHEMA = [
    ('enabled',         'MAIL_ENABLED',         'MAIL_ENABLED',         'bool'),
    ('smtp_host',       'MAIL_SMTP_HOST',       'MAIL_SMTP_HOST',       'str'),
    ('smtp_port',       'MAIL_SMTP_PORT',       'MAIL_SMTP_PORT',       'int'),
    ('smtp_username',   'MAIL_SMTP_USERNAME',   'MAIL_SMTP_USERNAME',   'str'),
    ('use_ssl',         'MAIL_USE_SSL',         'MAIL_USE_SSL',         'bool'),
    ('use_tls',         'MAIL_USE_TLS',         'MAIL_USE_TLS',         'bool'),
    ('from_addr',       'MAIL_FROM_ADDR',       'MAIL_FROM_ADDR',       'str'),
    ('from_name',       'MAIL_FROM_NAME',       'MAIL_FROM_NAME',       'str'),
    ('footer',          'MAIL_FOOTER',          'MAIL_FOOTER',          'str'),
    ('batch_limit',     'MAIL_BATCH_LIMIT',     'MAIL_BATCH_LIMIT',     'int'),
    ('retry_max',       'MAIL_RETRY_MAX',       'MAIL_RETRY_MAX',       'int'),
    ('manual_cooldown', 'MAIL_MANUAL_COOLDOWN', 'MAIL_MANUAL_COOLDOWN', 'int'),
    ('mask_title',      'MAIL_MASK_TITLE',      'MAIL_MASK_TITLE',      'bool'),
]


def _cast_setting(raw, typ):
    """把配置字符串转成目标类型，转换失败时回退到 config 默认值。"""
    try:
        if typ == 'bool':
            return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')
        if typ == 'int':
            return int(str(raw).strip())
        return str(raw)
    except (ValueError, AttributeError):
        return None


def get_mail_config():
    """取得完整邮件配置（已合并三级优先级）。

    Returns:
        dict: 含 schema 中全部键，外加：
            - smtp_password  str/None  已解密的密码（无配置时为 None）
            - password_source str      'env' / 'db' / 'none'，页面展示用
            - 若干只读运维参数（retry_backoff / retention_days 等）
    """
    # 一次性读出全部配置再在内存里比对：get_config 每次一条 SQL，
    # 而这里要查 14 个键，抽屉每打开一次就要付 14 次查询的代价。
    all_cfg = get_all_config()

    cfg = {}
    for key, env_key, cfg_attr, typ in MAIL_SETTING_SCHEMA:
        # 1) 环境变量 / .env 优先
        env_raw = os.environ.get(env_key)
        if env_raw is not None and str(env_raw).strip() != '':
            val = _cast_setting(env_raw, typ)
            if val is not None:
                cfg[key] = val
                continue
        # 2) 数据库（设置页填写）
        db_raw = all_cfg.get('mail_' + key)
        if db_raw is not None and str(db_raw).strip() != '':
            val = _cast_setting(db_raw, typ)
            if val is not None:
                cfg[key] = val
                continue
        # 3) config.py 默认值
        cfg[key] = getattr(config, cfg_attr)

    # --- 密码单独处理：环境变量明文 / 数据库密文 ---
    env_pwd = os.environ.get('MAIL_SMTP_PASSWORD')
    if env_pwd is not None and env_pwd.strip() != '':
        cfg['smtp_password'] = env_pwd.strip()
        cfg['password_source'] = 'env'
    else:
        stored = all_cfg.get('mail_smtp_password')
        decrypted = crypto_util.decrypt(stored) if stored else None
        cfg['smtp_password'] = decrypted
        cfg['password_source'] = 'db' if decrypted else 'none'

    # --- 只读运维参数：不入库，只从 env / config 读 ---
    cfg['retry_backoff'] = _parse_backoff(
        os.environ.get('MAIL_RETRY_BACKOFF') or config.MAIL_RETRY_BACKOFF)
    cfg['retention_days'] = _env_int_or('MAIL_LOG_RETENTION_DAYS', config.MAIL_LOG_RETENTION_DAYS)
    cfg['circuit_threshold'] = _env_int_or(
        'MAIL_CIRCUIT_FAIL_THRESHOLD', config.MAIL_CIRCUIT_FAIL_THRESHOLD)
    cfg['circuit_pause_minutes'] = _env_int_or(
        'MAIL_CIRCUIT_PAUSE_MINUTES', config.MAIL_CIRCUIT_PAUSE_MINUTES)

    return cfg


def _parse_backoff(raw):
    """解析重试间隔串（如 '5,15,30'）为整数分钟列表。"""
    parts = []
    for chunk in str(raw).split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            val = int(chunk)
        except ValueError:
            continue
        if val > 0:
            parts.append(val)
    return parts or [5, 15, 30]


def _env_int_or(env_key, default):
    """读环境变量整数，缺失或非法时返回默认值。"""
    raw = os.environ.get(env_key)
    if raw is None or str(raw).strip() == '':
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def is_mail_configured(cfg=None):
    """邮件功能是否「可用」：开关打开且关键字段齐全。

    注意与 get_mail_config()['enabled'] 的区别——开关开了但没填服务器，
    仍然发不出去。函数用于决定要不要真的去连 SMTP。
    """
    if cfg is None:
        cfg = get_mail_config()
    return bool(
        cfg.get('enabled')
        and (cfg.get('smtp_host') or '').strip()
        and (cfg.get('from_addr') or '').strip()
    )


def mail_unconfigured_reason(cfg=None):
    """返回邮件不可用的原因文案（用于设置页红条），可用时返回 None。"""
    if cfg is None:
        cfg = get_mail_config()
    if not cfg.get('enabled'):
        return '邮件功能未启用（MAIL_ENABLED 为关闭状态）'
    if not (cfg.get('smtp_host') or '').strip():
        return '未配置 SMTP 服务器地址'
    if not (cfg.get('from_addr') or '').strip():
        return '未配置发件箱地址'
    return None


def set_mail_config(form_data, save_password=True):
    """保存设置页提交的邮件配置。

    Args:
        form_data: dict，键名与 MAIL_SETTING_SCHEMA 的第一列一致
                   （另可含 smtp_password）
        save_password: 是否保存密码。置 False 时保留库中原有密码，
                       用于「密码框留空 = 不修改」的场景。

    Returns:
        tuple: (错误列表 list[str], 已保存键数 int)
    """
    errors = []
    saved = 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for key, _env_key, _cfg_attr, typ in MAIL_SETTING_SCHEMA:
        if key not in form_data:
            continue
        raw = form_data[key]

        # 布尔型来自复选框：有值即为真
        if typ == 'bool':
            value = '1' if raw in (True, '1', 'true', 'on', 1) else '0'
        elif typ == 'int':
            try:
                value = str(int(str(raw).strip()))
            except (ValueError, AttributeError):
                errors.append(f'配置项 {key} 必须是整数')
                continue
        else:
            value = str(raw).strip()

        set_config('mail_' + key, value)
        saved += 1

    # --- 密码：加密后入库 ---
    if save_password:
        pwd = (form_data.get('smtp_password') or '').strip()
        if pwd:
            encrypted = crypto_util.encrypt(pwd)
            if encrypted is None:
                errors.append('SMTP 密码保存失败：加密不可用（data/secret.key 不可读），请检查文件权限')
            else:
                set_config('mail_smtp_password', encrypted)
                saved += 1

    return errors, saved


def get_mail_config_for_display():
    """取得用于页面展示的配置（密码打码）。

    Returns:
        tuple: (config dict, password_masked str, password_settable bool)
    """
    cfg = get_mail_config()

    # 密码一律不出现在页面上，只告诉前端「有没有配」
    if cfg.get('password_source') == 'env':
        masked = '······（由 .env 提供，如需修改请编辑 .env 文件）'
    elif cfg.get('password_source') == 'db':
        masked = '······（已保存，留空表示不修改）'
    else:
        masked = ''

    return cfg, masked, crypto_util.is_available()


# --- 熔断状态 -------------------------------------------------------------

def get_circuit_state():
    """读取邮件熔断状态。

    Returns:
        dict: {'state': 'closed'|'open', 'reason': str,
               'opened_at': str|None, 'resume_at': str|None, 'fail_streak': int}
    """
    raw = get_config('mail_circuit_state')
    default = {'state': 'closed', 'reason': '', 'opened_at': None,
               'resume_at': None, 'fail_streak': 0}
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            default.update(parsed)
    except (ValueError, TypeError):
        pass
    return default


def set_circuit_state(state, reason='', resume_at=None, fail_streak=0, opened_at=None):
    """写入熔断状态。

    Args:
        state: 'closed'（正常） / 'open'（已熔断，停止发送）
        reason: 熔断原因文案，展示给管理员
        resume_at: 自动恢复时间 YYYY-MM-DD HH:MM:SS（通用熔断用）
        fail_streak: 当前连续失败次数
        opened_at: 熔断发生时间；state='open' 且未传时自动取当前时间
    """
    if state == 'open' and not opened_at:
        opened_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if state == 'closed':
        opened_at = None
        resume_at = None
        reason = ''
        fail_streak = 0

    set_config('mail_circuit_state', json.dumps({
        'state': state,
        'reason': reason,
        'opened_at': opened_at,
        'resume_at': resume_at,
        'fail_streak': fail_streak,
    }, ensure_ascii=False))


def bump_fail_streak():
    """连续失败计数 +1，返回新值。"""
    state = get_circuit_state()
    state['fail_streak'] = int(state.get('fail_streak') or 0) + 1
    set_config('mail_circuit_state', json.dumps(state, ensure_ascii=False))
    return state['fail_streak']


def reset_fail_streak():
    """发送成功后清零连续失败计数。"""
    state = get_circuit_state()
    if state.get('fail_streak'):
        state['fail_streak'] = 0
        set_config('mail_circuit_state', json.dumps(state, ensure_ascii=False))


# --- C. AI 能力（V5 迭代「AI 辅助生成」，Phase 0） -------------------------

def _migrate_v4():
    """V4 数据库迁移：AI 辅助生成（幂等，可重复调用）。

    内容：
    1. 新建 ai_queue（生成任务队列）/ ai_log（生成历史）两张表 + 索引
    2. AI 熔断状态复用 system_config 的 'ai_circuit_state' 键（无需新表）

    与 _migrate_v2/_migrate_v3 同一套路：CREATE IF NOT EXISTS 天然幂等，
    异常只打印不阻断启动。
    """
    conn = db.get_db()
    try:
        conn.executescript("""
        -- AI 生成任务队列：先落这里，由调度器每 5 分钟扫描执行（V5）
        CREATE TABLE IF NOT EXISTS ai_queue (
            queue_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id         INTEGER,
            job_type        TEXT    NOT NULL,
            prompt          TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'pending',
            retry_count     INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT    NOT NULL,
            last_error      TEXT,
            created_at      TEXT    NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );

        -- AI 生成历史：成功/失败后从队列转入此表
        CREATE TABLE IF NOT EXISTS ai_log (
            log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id        INTEGER,
            job_type       TEXT    NOT NULL,
            success        INTEGER NOT NULL,
            result_text    TEXT,
            error_message  TEXT,
            attempts       INTEGER NOT NULL DEFAULT 1,
            adopted        INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT    NOT NULL,
            finished_at    TEXT    NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ai_queue_status
            ON ai_queue(status, next_attempt_at);
        CREATE INDEX IF NOT EXISTS idx_ai_queue_task
            ON ai_queue(task_id);
        CREATE INDEX IF NOT EXISTS idx_ai_log_created
            ON ai_log(created_at);
        """)
        conn.commit()
    except Exception as e:  # pragma: no cover - 迁移失败不阻断启动
        print(f"[migrate_v4] 迁移异常（不影响启动）: {e}")


def enqueue_ai_job(task_id, job_type, prompt):
    """把一个 AI 生成任务放入队列（task_id 可空，如通用任务）。

    Returns:
        int: 新记录 queue_id；异常时返回 None
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        return db.execute(
            "INSERT INTO ai_queue "
            "(task_id, job_type, prompt, status, retry_count, next_attempt_at, created_at) "
            "VALUES (?, ?, ?, 'pending', 0, ?, ?)",
            (task_id, job_type, prompt, now, now)
        )
    except Exception:
        return None


def fetch_due_ai_jobs(limit):
    """取出到期待处理 AI 任务（按创建时间升序）。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return db.query(
        "SELECT * FROM ai_queue "
        "WHERE status = 'pending' AND next_attempt_at <= ? "
        "ORDER BY created_at ASC LIMIT ?",
        (now, limit)
    )


def mark_ai_jobs_sending(queue_ids):
    """批量标记为生成中。"""
    if not queue_ids:
        return
    placeholders = ','.join('?' * len(queue_ids))
    conn = db.get_db()
    conn.execute(
        f"UPDATE ai_queue SET status = 'sending' WHERE queue_id IN ({placeholders})",
        tuple(queue_ids))
    conn.commit()


def mark_ai_job_done(queue_id, result_text, task_id, job_type):
    """标记生成成功：写入历史表并从队列移除。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    row = db.query_one("SELECT * FROM ai_queue WHERE queue_id = ?", (queue_id,))
    if not row:
        return
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO ai_log "
            "(task_id, job_type, success, result_text, attempts, created_at, finished_at) "
            "VALUES (?, ?, 1, ?, 1, ?, ?)",
            (task_id, job_type, result_text, row['created_at'], now))
        conn.execute("DELETE FROM ai_queue WHERE queue_id = ?", (queue_id,))


def mark_ai_job_failed(queue_id, error_message, retry_max=3, backoff=None):
    """标记生成失败：可重试排到下次，超过 retry_max 则归档到历史表。

    Returns:
        str: 'retrying' / 'failed'
    """
    backoff = backoff or [1, 5, 15]
    now_dt = datetime.now()
    now = now_dt.strftime('%Y-%m-%d %H:%M:%S')
    row = db.query_one("SELECT * FROM ai_queue WHERE queue_id = ?", (queue_id,))
    if not row:
        return 'failed'

    retry_count = int(row['retry_count'] or 0) + 1
    if retry_count > retry_max:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO ai_log "
                "(task_id, job_type, success, error_message, attempts, created_at, finished_at) "
                "VALUES (?, ?, 0, ?, ?, ?, ?)",
                (row['task_id'], row['job_type'], error_message, retry_count,
                 row['created_at'], now))
            conn.execute("DELETE FROM ai_queue WHERE queue_id = ?", (queue_id,))
        return 'failed'

    idx = min(retry_count - 1, len(backoff) - 1)
    next_at = (now_dt + timedelta(minutes=backoff[idx])).strftime('%Y-%m-%d %H:%M:%S')
    db.execute(
        "UPDATE ai_queue SET status = 'pending', retry_count = ?, "
        "next_attempt_at = ?, last_error = ? WHERE queue_id = ?",
        (retry_count, next_at, error_message, queue_id))
    return 'retrying'


def reset_stuck_ai_jobs():
    """把卡在 sending 的记录重置为 pending（程序被强杀后的恢复）。"""
    conn = db.get_db()
    cursor = conn.execute(
        "UPDATE ai_queue SET status = 'pending' WHERE status = 'sending'")
    conn.commit()
    return cursor.rowcount


def get_ai_circuit_state():
    """读取 AI 熔断状态。

    Returns:
        dict: {'state': 'closed'|'open', 'reason': str,
               'opened_at': str|None, 'resume_at': str|None, 'fail_streak': int}
    """
    raw = get_config('ai_circuit_state')
    default = {'state': 'closed', 'reason': '', 'opened_at': None,
               'resume_at': None, 'fail_streak': 0}
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            default.update(parsed)
    except (ValueError, TypeError):
        pass
    return default


def set_ai_circuit_state(state, reason='', resume_at=None, fail_streak=0, opened_at=None):
    """写入 AI 熔断状态（state='open' 且未传 opened_at 时自动取当前时间）。"""
    if state == 'open' and not opened_at:
        opened_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if state == 'closed':
        opened_at = None
        resume_at = None
        reason = ''
        fail_streak = 0
    set_config('ai_circuit_state', json.dumps({
        'state': state,
        'reason': reason,
        'opened_at': opened_at,
        'resume_at': resume_at,
        'fail_streak': fail_streak,
    }, ensure_ascii=False))


def bump_ai_fail_streak():
    """连续失败计数 +1，返回新值。"""
    state = get_ai_circuit_state()
    state['fail_streak'] = int(state.get('fail_streak') or 0) + 1
    set_config('ai_circuit_state', json.dumps(state, ensure_ascii=False))
    return state['fail_streak']


def reset_ai_fail_streak():
    """生成成功后清零连续失败计数。"""
    state = get_ai_circuit_state()
    if state.get('fail_streak'):
        state['fail_streak'] = 0
        set_config('ai_circuit_state', json.dumps(state, ensure_ascii=False))


def get_ai_log(log_id):
    """读取单条 AI 生成历史。"""
    return db.query_one("SELECT * FROM ai_log WHERE log_id = ?", (log_id,))


def list_ai_logs(limit=50):
    """近期 AI 生成历史（按创建时间倒序）。"""
    return db.query(
        "SELECT * FROM ai_log ORDER BY created_at DESC LIMIT ?", (limit,))


def mark_ai_log_adopted(log_id):
    """标记某条 AI 生成结果已被采纳（发出站内信）。"""
    db.execute("UPDATE ai_log SET adopted = 1 WHERE log_id = ?", (log_id,))


# --- B. 用户邮箱与订阅等级 -------------------------------------------------

def update_user_email(user_id, email):
    """更新用户邮箱（空串存 NULL）。"""
    email = (email or '').strip()
    db.execute(
        "UPDATE users SET email = ? WHERE user_id = ?",
        (email or None, user_id)
    )


def update_mail_notify_level(user_id, level):
    """更新用户邮件订阅等级（非法值忽略）。"""
    if level not in mail_constants.NOTIFY_LEVELS:
        return False
    db.execute(
        "UPDATE users SET mail_notify_level = ? WHERE user_id = ?",
        (level, user_id)
    )
    return True


def get_mail_recipient(user_id):
    """取一个可发邮件的用户（需启用且填了邮箱），否则返回 None。

    D4-②：无邮箱 / 已停用的用户一律静默跳过，由状态页统一提示管理员。
    """
    if not user_id:
        return None
    row = db.query_one(
        "SELECT user_id, display_name, email, mail_notify_level "
        "FROM users WHERE user_id = ? AND is_active = 1",
        (user_id,)
    )
    if not row or not (row['email'] or '').strip():
        return None
    return row


def get_users_without_email():
    """列出未填邮箱的启用用户（D4-②：状态页展示，供管理员补数据）。"""
    return db.query(
        "SELECT user_id, username, display_name, role FROM users "
        "WHERE is_active = 1 AND (email IS NULL OR TRIM(email) = '') "
        "ORDER BY display_name ASC"
    )


def user_wants_mail(user, mail_type):
    """按订阅等级判断该用户是否接收这类邮件（C1-③④ + D6-②）。

    Args:
        user: 含 mail_notify_level 的用户行
        mail_type: mail_constants 中的邮件类型

    Returns:
        bool
    """
    level = (user['mail_notify_level'] if 'mail_notify_level' in user.keys() else None) \
        or mail_constants.LEVEL_OVERDUE
    allowed = mail_constants.LEVEL_ALLOWED_TYPES.get(level, ())
    return mail_type in allowed


def get_mail_subscribers(role_filter=None):
    """取得需要接收邮件的用户（启用 + 已填邮箱）。

    Args:
        role_filter: 'admin' 只取管理员，None 取全部
    """
    sql = ("SELECT user_id, display_name, email, mail_notify_level, role FROM users "
           "WHERE is_active = 1 AND email IS NOT NULL AND TRIM(email) != ''")
    params = ()
    if role_filter:
        sql += " AND role = ?"
        params = (role_filter,)
    sql += " ORDER BY user_id ASC"
    return db.query(sql, params)


# --- C. 发送队列 CRUD ------------------------------------------------------

def enqueue_email(recipient_id, recipient_email, mail_type, subject, body,
                  dedup_key, task_id=None, reply_to=None, operator_id=None,
                  next_attempt_at=None):
    """把一封邮件放进待发队列（已存在相同去重键则忽略）。

    Args:
        recipient_id: 收件人 user_id
        recipient_email: 收件地址（发送时快照，避免事后改邮箱导致记录失真）
        mail_type: mail_constants.MAIL_TYPE_*
        subject / body: 邮件主题与正文
        dedup_key: 去重键；相同键视为同一封，直接跳过（C6-②：独立于站内信）
        task_id: 关联任务（日报为 None）
        reply_to: 回复地址（B2-③：指向具体操作人）
        operator_id: 操作人（H6-①：手动发送时记录，自动发送为 None）
        next_attempt_at: 最早发送时间，默认立即

    Returns:
        int: 新记录的 queue_id；被去重键挡下时返回 None
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        return db.execute(
            "INSERT INTO email_queue "
            "(recipient_id, recipient_email, task_id, mail_type, subject, body, "
            " reply_to, operator_id, dedup_key, status, retry_count, next_attempt_at, "
            " created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)",
            (recipient_id, recipient_email, task_id, mail_type, subject, body,
             reply_to, operator_id, dedup_key,
             next_attempt_at or now, now)
        )
    except Exception:
        # UNIQUE 约束冲突 = 今天已经排过同一封，静默忽略即可
        return None


def has_dedup_key(dedup_key):
    """判断去重键是否已存在（入队前预检，便于调用方直接跳过渲染开销）。"""
    row = db.query_one(
        "SELECT COUNT(*) as cnt FROM email_queue WHERE dedup_key = ?", (dedup_key,))
    return row['cnt'] > 0


def reset_stuck_emails():
    """把卡在 sending 的记录重置为 pending（G5-①）。

    程序被强杀时可能有记录停留在 sending。宁可重复发送、不可丢失邮件——
    这是已确认的取舍：重复代价是收件人可能多收一封提醒，
    丢失代价是管理员以为通知到位了而实际没有。
    """
    conn = db.get_db()
    cursor = conn.execute(
        "UPDATE email_queue SET status = 'pending' WHERE status = 'sending'")
    conn.commit()
    return cursor.rowcount


def fetch_due_emails(limit):
    """取出到期待发邮件（按收件人聚合的前提数据）。

    Args:
        limit: 最多取多少条记录（注意这是记录数，不是最终邮件数）

    Returns:
        list[Row]: 按创建时间升序的队列记录
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return db.query(
        "SELECT * FROM email_queue "
        "WHERE status = 'pending' AND next_attempt_at <= ? "
        "ORDER BY created_at ASC LIMIT ?",
        (now, limit)
    )


def mark_emails_sending(queue_ids):
    """批量标记为发送中。"""
    if not queue_ids:
        return
    placeholders = ','.join('?' * len(queue_ids))
    conn = db.get_db()
    conn.execute(
        f"UPDATE email_queue SET status = 'sending' WHERE queue_id IN ({placeholders})",
        tuple(queue_ids))
    conn.commit()


def mark_email_sent(queue_id, attempts=1):
    """标记发送成功：写入历史表并从队列移除。

    成功后直接从队列删除，让 email_queue 只保留 pending / sending 两种状态——
    否则队列会无限堆积已完成的记录，拖慢扫描与备份。
    历史查询一律走 email_log（I2-② 保留 90 天）。

    注意：删除队列记录不影响手动发送冷却（F4-②），
    因为 has_recent_manual_mail 同时查 email_queue 与 email_log。
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    row = db.query_one("SELECT * FROM email_queue WHERE queue_id = ?", (queue_id,))
    if not row:
        return
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO email_log "
            "(recipient_id, recipient_email, task_id, mail_type, subject, operator_id, "
            " success, error_message, attempts, created_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, NULL, ?, ?, ?)",
            (row['recipient_id'], row['recipient_email'], row['task_id'],
             row['mail_type'], row['subject'], row['operator_id'],
             attempts, row['created_at'], now))
        conn.execute("DELETE FROM email_queue WHERE queue_id = ?", (queue_id,))


def mark_email_failed(queue_id, error_message, retry_max, backoff, permanent=False):
    """标记发送失败：可重试的排到下次，重试耗尽或永久错误则转历史表。

    Args:
        queue_id: 队列记录 ID
        error_message: 错误信息（绝不含密码）
        retry_max: 最大重试次数
        backoff: 重试间隔分钟列表
        permanent: True 表示永久性错误（如认证失败），不重试直接归档

    Returns:
        str: 'retrying' / 'failed'
    """
    now_dt = datetime.now()
    now = now_dt.strftime('%Y-%m-%d %H:%M:%S')
    row = db.query_one("SELECT * FROM email_queue WHERE queue_id = ?", (queue_id,))
    if not row:
        return 'failed'

    # 注意这里是「>」而不是「>=」：
    # retry_count 表示**已重试的次数**，不含首次发送。
    # retry_max=3 的含义是「首次失败后再重试 3 次」，总共尝试 4 次。
    # 用 >= 会变成只重试 2 次，与配置项的字面意思不符。
    retry_count = int(row['retry_count'] or 0) + 1

    if permanent or retry_count > retry_max:
        # 归档到历史表并删除队列记录（避免队列无限膨胀）
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO email_log "
                "(recipient_id, recipient_email, task_id, mail_type, subject, operator_id, "
                " success, error_message, attempts, created_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                (row['recipient_id'], row['recipient_email'], row['task_id'],
                 row['mail_type'], row['subject'], row['operator_id'],
                 error_message, retry_count, row['created_at'], now))
            conn.execute("DELETE FROM email_queue WHERE queue_id = ?", (queue_id,))
        return 'failed'

    # 排到下一轮：间隔按重试次数递增，超出列表长度时用最后一项兜底
    idx = min(retry_count - 1, len(backoff) - 1)
    next_at = (now_dt + timedelta(minutes=backoff[idx])).strftime('%Y-%m-%d %H:%M:%S')
    db.execute(
        "UPDATE email_queue SET status = 'pending', retry_count = ?, "
        "next_attempt_at = ?, last_error = ? WHERE queue_id = ?",
        (retry_count, next_at, error_message, queue_id))
    return 'retrying'


def requeue_failed_email(log_id):
    """把一条永久失败的历史邮件重新放回队列（G7-① 一键重发）。

    Returns:
        tuple: (成功与否 bool, 提示文案 str)
    """
    row = db.query_one("SELECT * FROM email_log WHERE log_id = ?", (log_id,))
    if not row:
        return False, '记录不存在'
    if row['success']:
        return False, '该邮件已发送成功，无需重发'

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # 去重键加时间戳后缀，避免与历史记录冲突导致插不进去
    new_key = f"retry:{log_id}:{now}"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO email_queue "
            "(recipient_id, recipient_email, task_id, mail_type, subject, body, "
            " reply_to, operator_id, dedup_key, status, retry_count, next_attempt_at, "
            " created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)",
            (row['recipient_id'], row['recipient_email'], row['task_id'],
             row['mail_type'], row['subject'],
             _rebuild_body_for_retry(row), None, row['operator_id'],
             new_key, now, now))
        conn.execute("DELETE FROM email_log WHERE log_id = ?", (log_id,))
    return True, '已重新加入发送队列'


def _rebuild_body_for_retry(log_row):
    """重发时还原邮件正文。

    历史表只存 subject 不存 body（省空间），因此重发时按类型重新渲染。
    渲染失败则退化为含主题与提示的占位正文——重发是补救动作，
    宁可内容简略也不能卡住。
    """
    try:
        import mail_templates
        if log_row['mail_type'] == mail_constants.MAIL_TYPE_DAILY_REPORT:
            return mail_templates.render_daily_report_for_user(log_row['recipient_id'])
        if log_row['task_id']:
            task = get_task(log_row['task_id'])
            if task:
                return mail_templates.render_overdue_grouped(
                    log_row['recipient_id'], [task], mask_title=False)
    except Exception:
        pass
    return f"（原邮件正文未保留，此为重发）\n\n主题：{log_row['subject']}\n请登录督办系统查看详情。"


# --- D. 发送历史与统计 -----------------------------------------------------

def get_email_logs(filters=None, page=1, per_page=20):
    """查询发送历史（管理员看全部）。

    Args:
        filters: dict，支持 status('success'/'failed') / recipient_id / mail_type / keyword
        page / per_page: 分页

    Returns:
        tuple: (记录列表, 总条数, 总页数, 当前页)
    """
    if filters is None:
        filters = {}

    where = ['1=1']
    params = []

    status = filters.get('status')
    if status == 'success':
        where.append('l.success = 1')
    elif status == 'failed':
        where.append('l.success = 0')

    if filters.get('recipient_id'):
        where.append('l.recipient_id = ?')
        params.append(filters['recipient_id'])

    if filters.get('mail_type'):
        where.append('l.mail_type = ?')
        params.append(filters['mail_type'])

    if filters.get('keyword'):
        where.append('(l.subject LIKE ? OR l.recipient_email LIKE ?)')
        kw = f"%{filters['keyword']}%"
        params.extend([kw, kw])

    where_sql = ' WHERE ' + ' AND '.join(where)

    total = db.query_one(
        f"SELECT COUNT(*) as cnt FROM email_log l{where_sql}", tuple(params))['cnt']
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    offset = (page - 1) * per_page
    rows = db.query(
        "SELECT l.*, u.display_name AS recipient_name, t.title AS task_title "
        "FROM email_log l "
        "LEFT JOIN users u ON l.recipient_id = u.user_id "
        "LEFT JOIN tasks t ON l.task_id = t.task_id "
        f"{where_sql} ORDER BY l.finished_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (per_page, offset)
    )
    return rows, total, total_pages, page


def get_my_email_logs(user_id, page=1, per_page=20):
    """查询「发给我的」邮件记录（H2-①：普通用户只能看自己的）。"""
    return get_email_logs({'recipient_id': user_id}, page=page, per_page=per_page)


def get_failed_email_logs(limit=50):
    """取得最近永久失败的邮件（G7-①：状态页失败清单 + 一键重发）。"""
    return db.query(
        "SELECT l.*, u.display_name AS recipient_name, t.title AS task_title "
        "FROM email_log l "
        "LEFT JOIN users u ON l.recipient_id = u.user_id "
        "LEFT JOIN tasks t ON l.task_id = t.task_id "
        "WHERE l.success = 0 ORDER BY l.finished_at DESC LIMIT ?",
        (limit,)
    )


def count_emails_today():
    """统计今日发送成功 / 失败数（I1-①：状态页概览）。"""
    today = datetime.now().strftime('%Y-%m-%d')
    row = db.query_one(
        "SELECT "
        "  SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS ok, "
        "  SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS bad "
        "FROM email_log WHERE finished_at LIKE ?",
        (f"{today}%",)
    )
    return {'success': row['ok'] or 0, 'failed': row['bad'] or 0}


def count_pending_emails():
    """统计队列中待发 / 重试中的邮件数。"""
    row = db.query_one(
        "SELECT COUNT(*) as cnt FROM email_queue WHERE status IN ('pending', 'sending')")
    return row['cnt'] or 0


def get_last_sent_at():
    """最近一次成功发送的时间（状态页展示）。"""
    row = db.query_one(
        "SELECT MAX(finished_at) AS last_at FROM email_log WHERE success = 1")
    return row['last_at'] if row else None


def cleanup_email_logs(retention_days=None):
    """清理过期的发送历史（I2-②：默认保留 90 天）。

    由调度器每日调用一次，避免 email_log 无限膨胀拖慢备份与拷贝。
    """
    if retention_days is None:
        retention_days = config.MAIL_LOG_RETENTION_DAYS
    if retention_days <= 0:
        return 0

    cutoff = (datetime.now() - timedelta(days=int(retention_days))).strftime('%Y-%m-%d %H:%M:%S')
    conn = db.get_db()
    cursor = conn.execute("DELETE FROM email_log WHERE created_at < ?", (cutoff,))
    conn.commit()
    return cursor.rowcount


def get_overdue_tasks_with_names():
    """取得全部逾期任务（附带负责人/创建人显示名），供邮件日报与提醒使用。

    按负责人姓名、截止日期排序——日报要按负责人分组，
    排序交给 SQL 做比在 Python 里二次排序更省事。
    """
    return db.query(
        "SELECT t.*, "
        "  u.display_name AS assignee_name, "
        "  c.display_name AS creator_name "
        "FROM tasks t "
        "LEFT JOIN users u ON t.assignee = u.user_id "
        "LEFT JOIN users c ON t.created_by = c.user_id "
        "WHERE t.status = 'overdue' "
        "ORDER BY u.display_name ASC, t.due_date ASC"
    )


def get_overdue_tasks_by_assignee():
    """取得逾期任务并按负责人归组。

    Returns:
        dict: {assignee_user_id: [task, ...]}
    """
    grouped = {}
    for task in get_overdue_tasks_with_names():
        grouped.setdefault(task['assignee'], []).append(task)
    return grouped


def has_recent_manual_mail(task_id, operator_id, cooldown_seconds):
    """手动发送冷却检查（F4-②）。

    判定依据：在冷却窗口内，该任务 + 该操作人是否已经发过（含待发队列与历史）。
    """
    if not cooldown_seconds or cooldown_seconds <= 0:
        return False

    since = (datetime.now() - timedelta(seconds=int(cooldown_seconds))).strftime('%Y-%m-%d %H:%M:%S')

    row = db.query_one(
        "SELECT COUNT(*) as cnt FROM email_queue "
        "WHERE mail_type = ? AND task_id = ? AND operator_id = ? AND created_at >= ?",
        (mail_constants.MAIL_TYPE_MANUAL, task_id, operator_id, since))
    if row['cnt'] > 0:
        return True

    row = db.query_one(
        "SELECT COUNT(*) as cnt FROM email_log "
        "WHERE mail_type = ? AND task_id = ? AND operator_id = ? AND created_at >= ?",
        (mail_constants.MAIL_TYPE_MANUAL, task_id, operator_id, since))
    return row['cnt'] > 0
