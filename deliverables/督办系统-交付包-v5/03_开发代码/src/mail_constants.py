"""mail_constants.py — 邮件功能常量定义（V4 迭代）

单独成文件是为了避免循环依赖：
mail_templates / mail_service / mail_dispatcher / models 都要引用这些常量，
如果放在 models 里，models 又要在运行时 import mail_templates（重发时渲染正文），
就会形成 models → mail_templates → models 的环。
"""

# ============================================================
# 邮件类型（email_queue.mail_type / email_log.mail_type）
# ============================================================
MAIL_TYPE_OVERDUE = 'overdue'              # 逾期提醒（发给负责人，可能合并多条）
MAIL_TYPE_DUE_SOON = 'due_soon'            # 即将到期提醒（订阅等级升级后才有）
MAIL_TYPE_INACTIVE = 'inactive'            # 长期待激活提醒（订阅等级升级后才有）
MAIL_TYPE_ASSIGN = 'assign'                # 任务分配 / 改派通知
MAIL_TYPE_DAILY_REPORT = 'daily_report'    # 管理员日报
MAIL_TYPE_MANUAL = 'manual'                # 手动发送（任务详情页按钮）
MAIL_TYPE_TEST = 'test'                    # 设置页测试邮件
MAIL_TYPE_AI_BRIEF = 'ai_brief'            # AI 督办简报 / 周报（PR-3）

MAIL_TYPE_LABELS = {
    MAIL_TYPE_OVERDUE:      '逾期提醒',
    MAIL_TYPE_DUE_SOON:     '即将到期提醒',
    MAIL_TYPE_INACTIVE:     '待激活提醒',
    MAIL_TYPE_ASSIGN:       '任务分配通知',
    MAIL_TYPE_DAILY_REPORT: '管理员日报',
    MAIL_TYPE_MANUAL:       '手动提醒',
    MAIL_TYPE_TEST:         '测试邮件',
    MAIL_TYPE_AI_BRIEF:     'AI 督办简报',
}

# ============================================================
# 用户订阅等级（users.mail_notify_level，D6-②）
# ============================================================
LEVEL_OFF = 'off'                    # 不收任何邮件（仍收站内信）
LEVEL_OVERDUE = 'overdue'            # 仅逾期（默认）
LEVEL_OVERDUE_DUE = 'overdue_due'    # 逾期 + 即将到期
LEVEL_ALL = 'all'                    # 全部预警

NOTIFY_LEVELS = (LEVEL_OFF, LEVEL_OVERDUE, LEVEL_OVERDUE_DUE, LEVEL_ALL)

NOTIFY_LEVEL_LABELS = {
    LEVEL_OFF:         '不接收邮件提醒',
    LEVEL_OVERDUE:     '仅逾期（推荐）',
    LEVEL_OVERDUE_DUE: '逾期 + 即将到期',
    LEVEL_ALL:         '全部预警',
}

# 每个等级允许接收的邮件类型（C1-③④）
LEVEL_ALLOWED_TYPES = {
    LEVEL_OFF:         (),
    LEVEL_OVERDUE:     (MAIL_TYPE_OVERDUE, MAIL_TYPE_ASSIGN),
    LEVEL_OVERDUE_DUE: (MAIL_TYPE_OVERDUE, MAIL_TYPE_DUE_SOON, MAIL_TYPE_ASSIGN),
    LEVEL_ALL:         (MAIL_TYPE_OVERDUE, MAIL_TYPE_DUE_SOON,
                        MAIL_TYPE_INACTIVE, MAIL_TYPE_ASSIGN),
}

# ============================================================
# 队列状态（email_queue.status）
# ============================================================
STATUS_PENDING = 'pending'    # 待发送（含等待重试）
STATUS_SENDING = 'sending'    # 发送中
STATUS_SENT = 'sent'          # 已发送（随后会转入 email_log）
STATUS_FAILED = 'failed'      # 永久失败（随后会转入 email_log）

# ============================================================
# 熔断状态（G3-③ 认证失败立即熔断 / G4-② 连续失败通用熔断）
# ============================================================
CIRCUIT_CLOSED = 'closed'     # 正常，允许发送
CIRCUIT_OPEN = 'open'         # 已熔断，停止发送

# 永久性错误：不重试，直接熔断并告警（G2 确认）
PERMANENT_ERROR_AUTH = 'auth'          # 535 认证失败
PERMANENT_ERROR_REJECTED = 'rejected'  # 550 收件人不存在 / 被拒
PERMANENT_ERROR_SPAM = 'spam'          # 被判定为垃圾邮件

# 需要「延迟较久再重试」的错误：服务商限流（G2 的 452/454）
THROTTLED_ERROR = 'throttled'

# ============================================================
# 逾期提醒降频规则（F1-②）
# ============================================================
# 逾期第 1/2/3 天每天提醒；之后每 3 天提醒一次（第 6/9/12… 天）
OVERDUE_DAILY_DAYS = 3
OVERDUE_INTERVAL_DAYS = 3


def should_remind_overdue(overdue_days):
    """判断逾期第 N 天该不该发提醒邮件（F1-②）。

    Args:
        overdue_days: 已逾期天数（1 表示刚逾期）

    Returns:
        bool

    序列：1,2,3,6,9,12,15...
    """
    if overdue_days is None or overdue_days < 1:
        return False
    if overdue_days <= OVERDUE_DAILY_DAYS:
        return True
    return (overdue_days - OVERDUE_DAILY_DAYS) % OVERDUE_INTERVAL_DAYS == 0
