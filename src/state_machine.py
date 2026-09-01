"""state_machine.py — 任务状态机

包含：
1. 状态枚举（TaskStatus）+ 中文/颜色映射
2. 优先级枚举（TaskPriority）+ 中文映射
3. 状态转换矩阵（TRANSITIONS + ADMIN_ONLY_TRANSITIONS）
4. 转换校验函数（validate_transition）
5. 获取允许转换列表（get_allowed_transitions）
6. 状态变更完整流程（change_task_status，含副作用）

状态流转规则（5 态状态机）：
- pending（待启动）→ in_progress / closed / cancelled + 自动转 overdue
- in_progress（进行中）→ closed / cancelled + 自动转 overdue
- overdue（已逾期）→ in_progress / closed / cancelled
- closed（已闭环）→ in_progress（仅管理员重新打开）
- cancelled（已撤销）→ pending（仅管理员重新激活）
"""

from datetime import datetime

import db
import models


# ============================================================
# 状态枚举与映射
# ============================================================

class TaskStatus:
    """任务状态枚举（值与数据库 status 字段一致）。"""
    PENDING     = 'pending'       # 待启动
    IN_PROGRESS = 'in_progress'   # 进行中
    OVERDUE     = 'overdue'       # 已逾期
    CLOSED      = 'closed'        # 已闭环
    CANCELLED   = 'cancelled'     # 已撤销


# 状态中文映射（模板渲染用）
STATUS_LABELS = {
    'pending':     '待启动',
    'in_progress': '进行中',
    'overdue':     '已逾期',
    'closed':      '已闭环',
    'cancelled':   '已撤销',
}

# 状态颜色映射（前端样式用）
STATUS_COLORS = {
    'pending':     'gray',      # 灰色
    'in_progress': 'blue',      # 蓝色
    'overdue':     'red',       # 红色
    'closed':      'green',     # 绿色
    'cancelled':   'darkgray',  # 深灰色
}

# 所有状态列表（按业务顺序排列）
ALL_STATUSES = ['pending', 'in_progress', 'overdue', 'closed', 'cancelled']


# ============================================================
# 优先级枚举与映射
# ============================================================

class TaskPriority:
    """任务优先级枚举。"""
    URGENT = 'urgent'
    HIGH   = 'high'
    MEDIUM = 'medium'
    LOW    = 'low'


PRIORITY_LABELS = {
    'urgent': '紧急',
    'high':   '高',
    'medium': '中',
    'low':    '低',
}

# 优先级顺序（用于排序和下拉选项）
ALL_PRIORITIES = ['urgent', 'high', 'medium', 'low']


# ============================================================
# 状态转换矩阵
# ============================================================

# 转换矩阵：key=当前状态，value=允许手动转到的目标状态集合
# 注意：自动逾期（→ overdue）不在此矩阵中，由后台扫描强制触发
TRANSITIONS = {
    'pending':     {'in_progress', 'closed', 'cancelled'},
    'in_progress': {'closed', 'cancelled'},
    'overdue':     {'in_progress', 'closed', 'cancelled'},
    'closed':      {'in_progress'},        # 仅管理员，需角色校验
    'cancelled':   {'pending'},            # 仅管理员，需角色校验
}

# 需要管理员角色的转换（角色级权限，额外校验）
ADMIN_ONLY_TRANSITIONS = {
    ('closed', 'in_progress'),     # 重新打开已闭环任务
    ('cancelled', 'pending'),      # 重新激活已撤销任务
}


# ============================================================
# 转换校验函数
# ============================================================

def validate_transition(current_status, target_status, user_role):
    """校验状态转换是否合法。

    校验顺序：
    1. 状态是否相同（相同不允许）
    2. 转换矩阵是否允许（当前状态能否转到目标状态）
    3. 是否需要管理员权限（重新打开/重新激活）

    Args:
        current_status: 当前状态
        target_status:  目标状态
        user_role:      操作者角色 ('admin' / 'owner')

    Returns:
        tuple: (是否允许: bool, 不允许时的错误原因: str)
    """
    # 相同状态不允许转换
    if current_status == target_status:
        return False, '状态未发生变化'

    # 查转换矩阵：当前状态允许转到的目标状态集合
    allowed = TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        return False, f'不允许从「{STATUS_LABELS.get(current_status, current_status)}」转换到「{STATUS_LABELS.get(target_status, target_status)}」'

    # 检查是否需要管理员权限
    if (current_status, target_status) in ADMIN_ONLY_TRANSITIONS:
        if user_role != 'admin':
            return False, '此操作仅管理员可执行'

    return True, ''


def get_allowed_transitions(current_status, user_role):
    """获取当前状态下允许转换的目标状态列表（供详情页下拉选项用）。

    Args:
        current_status: 当前状态
        user_role: 操作者角色

    Returns:
        list[dict]: 可转换的状态列表，每项含 status / label / color
    """
    allowed_set = TRANSITIONS.get(current_status, set())
    result = []
    for status in allowed_set:
        # 检查该转换是否需要管理员权限
        if (current_status, status) in ADMIN_ONLY_TRANSITIONS:
            if user_role != 'admin':
                continue  # 非管理员无权此转换，不显示
        result.append({
            'status': status,
            'label': STATUS_LABELS[status],
            'color': STATUS_COLORS[status],
        })
    return result


# ============================================================
# 状态变更完整流程（含副作用）
# ============================================================

def change_task_status(task_id, target_status, operator_id, operator_role, progress_note=''):
    """执行状态变更的完整流程（事务性操作）。

    流程：
    1. 查询任务，校验任务存在
    2. 校验状态转换合法性
    3. 准备副作用数据（闭环时间等）
    4. 事务执行：更新任务状态 + 写进度日志 + 生成状态变更消息

    Args:
        task_id: 任务ID
        target_status: 目标状态
        operator_id: 操作人 user_id（系统操作为 None）
        operator_role: 操作人角色 ('admin' / 'owner')
        progress_note: 进度备注（可选）

    Returns:
        tuple: (是否成功: bool, 错误原因或空: str)
    """
    task = models.get_task(task_id)
    if not task:
        return False, '任务不存在'

    current_status = task['status']

    # 1. 校验转换合法性
    ok, reason = validate_transition(current_status, target_status, operator_role)
    if not ok:
        return False, reason

    # 2. 准备副作用数据
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    extra_updates = {'updated_at': now}

    # 转为"已闭环"时记录闭环时间
    if target_status == TaskStatus.CLOSED:
        extra_updates['closed_at'] = now

    # 从"已闭环"重新打开时清空闭环时间
    if current_status == TaskStatus.CLOSED and target_status == TaskStatus.IN_PROGRESS:
        extra_updates['closed_at'] = None

    # 转为"已逾期"时设置 is_overdue 标记
    if target_status == TaskStatus.OVERDUE:
        extra_updates['is_overdue'] = 1

    # 从"已逾期"恢复时清除标记
    if current_status == TaskStatus.OVERDUE and target_status != TaskStatus.OVERDUE:
        extra_updates['is_overdue'] = 0

    # 3. 事务执行：更新状态 + 写日志 + 发消息
    with db.transaction() as conn:
        # 更新任务状态
        set_clause = ', '.join([f"{k} = ?" for k in extra_updates])
        params = list(extra_updates.values())
        params.append(target_status)
        params.append(task_id)
        conn.execute(
            f"UPDATE tasks SET {set_clause}, status = ? WHERE task_id = ?",
            tuple(params)
        )

        # 写进度日志（记录状态变更轨迹）
        conn.execute(
            "INSERT INTO progress_logs (task_id, operator, operated_at, status_from, status_to, progress_note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, operator_id, now, current_status, target_status, progress_note)
        )

        # 生成状态变更消息（通知任务的另一相关方）
        # owner 操作 → 通知 admin（创建人）；admin 操作 → 通知 owner（负责人）
        if operator_id is not None:
            notify_target = task['created_by'] if operator_role == 'owner' else task['assignee']
            # 不给自己发消息
            if notify_target != operator_id:
                content = f'任务「{task["title"]}」状态变更为「{STATUS_LABELS[target_status]}」'
                if progress_note:
                    content += f'，备注：{progress_note}'
                conn.execute(
                    "INSERT INTO messages (recipient, sender, type, content, task_id, is_read, created_at) "
                    "VALUES (?, ?, 'status_change', ?, ?, 0, ?)",
                    (notify_target, operator_id, content, task_id, now)
                )

    return True, ''
