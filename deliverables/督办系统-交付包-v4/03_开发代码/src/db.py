"""db.py — SQLite 连接管理（线程安全）

提供应用级的线程安全数据库连接管理：
- 每个线程拥有独立的 SQLite 连接（threading.local）
- 全局锁保证写操作（事务）的原子性
- 统一的 query / execute 快捷方法

使用方式：
    from db import query, execute, transaction
    rows = query("SELECT * FROM users WHERE user_id = ?", (1,))
    execute("INSERT INTO users (...) VALUES (...)", params)
    with transaction() as conn:
        conn.execute(...)
        conn.execute(...)
"""

import sqlite3
import threading
from contextlib import contextmanager

import config

# ============================================================
# 线程安全基础设施
# ============================================================
# 全局写锁：保证事务的原子性（多线程并发写时串行化）
_lock = threading.Lock()

# 线程局部存储：每个线程持有独立的数据库连接
_local = threading.local()


def get_db():
    """获取当前线程的数据库连接（线程安全）。

    每个线程首次调用时创建连接并缓存，后续直接复用。
    连接配置：
    - row_factory=sqlite3.Row：返回字典式 Row 对象，方便按字段名访问
    - check_same_thread=False：允许跨线程使用（配合线程局部存储）
    - 启用外键约束：PRAGMA foreign_keys = ON

    Returns:
        sqlite3.Connection: 当前线程的数据库连接
    """
    if not hasattr(_local, 'connection'):
        conn = sqlite3.connect(
            config.DATABASE_PATH,
            check_same_thread=False     # 允许在守护线程中使用
        )
        conn.row_factory = sqlite3.Row  # 返回 Row 对象，支持 row['field'] 访问
        conn.execute('PRAGMA foreign_keys = ON')  # 启用外键约束
        _local.connection = conn
    return _local.connection


@contextmanager
def transaction():
    """事务上下文管理器。

    用法：
        with transaction() as conn:
            conn.execute("UPDATE ...")
            conn.execute("INSERT ...")

    特性：
    - 自动提交（无异常时）或回滚（有异常时）
    - 加全局锁保证并发安全（多线程同时写不会冲突）
    - 上下文内可执行多条 SQL，作为一个原子事务

    Yields:
        sqlite3.Connection: 事务内的数据库连接
    """
    with _lock:
        conn = get_db()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def query(sql, params=()):
    """查询快捷方法（SELECT）。

    Args:
        sql: SQL 查询语句，使用 ? 占位符
        params: 参数元组，与占位符一一对应

    Returns:
        list[sqlite3.Row]: 查询结果行列表，空结果返回 []
    """
    return get_db().execute(sql, params).fetchall()


def query_one(sql, params=()):
    """查询单条记录快捷方法。

    Args:
        sql: SQL 查询语句
        params: 参数元组

    Returns:
        sqlite3.Row 或 None: 单条结果行，无结果时返回 None
    """
    return get_db().execute(sql, params).fetchone()


def execute(sql, params=()):
    """执行快捷方法（INSERT / UPDATE / DELETE）。

    自动提交，适合单条写操作。多条原子操作请用 transaction()。

    Args:
        sql: SQL 执行语句
        params: 参数元组

    Returns:
        int: 最后插入行的 rowid（INSERT 时为新记录 ID）
    """
    conn = get_db()
    cursor = conn.execute(sql, params)
    conn.commit()
    return cursor.lastrowid


def close_db():
    """关闭当前线程的数据库连接。

    通常在应用关闭时调用，清理资源。
    """
    if hasattr(_local, 'connection'):
        _local.connection.close()
        del _local.connection
