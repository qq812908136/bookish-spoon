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

import os
from datetime import datetime

import config
import db

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
