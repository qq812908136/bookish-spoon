"""ai_templates.py — AI 提示词构建与脱敏（V5 迭代「AI 辅助生成」，Phase 0）

职责边界（对齐邮件子系统 ai_templates 的定位）：
- 仅为不同 job_type 构建送往模型的提示词
- 送模型前按配置脱敏（AI_MASK_DATA）敏感信息（手机号 / 邮箱 / 长数字证件号）
- 本模块不调用模型、不碰数据库、不做业务落库

⚠️ 提示词注入护栏：这里只做「基础脱敏」，不解析模型返回内容里的指令。
   模型返回内容在 ai_dispatcher 落库前不做二次执行，且必须经管理员人工确认
   （adopt / 确认建任务）才会真正生效——这是 SPEC v1.0 明确的「人工确认闸」。
"""

import json
import re

import config


# 脱敏正则
_PHONE_RE = re.compile(r'(?<!\d)(1[3-9]\d{9})(?!\d)')          # 手机号
_EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')  # 邮箱
_ID_RE = re.compile(r'(?<!\d)(\d{11,})(?!\d)')                 # 11 位以上疑似证件号


def mask_text(text):
    """对送往模型的文本做基础脱敏。

    仅在 AI_MASK_DATA=True 时由调用方触发；脱敏后无法还原，
    因此只用于「模型输入」，绝不用于「展示给用户的原文」。
    """
    if not text:
        return text
    text = _PHONE_RE.sub(lambda m: m.group(1)[:3] + '****' + m.group(1)[-4:], text)
    text = _EMAIL_RE.sub(lambda m: m.group(0)[0] + '***@***', text)
    text = _ID_RE.sub(lambda m: m.group(1)[:3] + '*********', text)
    return text


def _mask_if_needed(text):
    return mask_text(text) if config.AI_MASK_DATA else text


def build_reminder_prompt(task, owner_name='负责人'):
    """催办话术（PR-1 首选场景）。

    Args:
        task: tasks 行（sqlite3.Row 或 dict，统一按下标访问）
        owner_name: 负责人显示名（当前未直接用到，保留扩展位）
    Returns:
        str: 发送给本地模型的提示词
    """
    title = task['title'] or ''
    due = task['due_date'] or ''
    status = task['status'] or ''
    desc = task['description'] or ''
    masked_desc = _mask_if_needed(desc)
    return (
        "你是单位内部的督办助手。请用正式、简洁、得体的中文，"
        "起草一条发给任务负责人的催办提醒（不超过 120 字）。\n"
        f"任务标题：{title}\n"
        f"截止日期：{due}\n"
        f"当前状态：{status}\n"
        f"任务说明：{masked_desc}\n"
        "要求：只输出提醒正文，不要解释、不要加引号、不要使用 Markdown。"
    )


def build_summary_prompt(task):
    """任务综述（PR-2）：把任务信息浓缩成一段可归档的摘要。"""
    title = task['title'] or ''
    due = task['due_date'] or ''
    status = task['status'] or ''
    desc = task['description'] or ''
    masked_desc = _mask_if_needed(desc)
    return (
        "请用 2-3 句话客观概括以下督办任务，语气中立、可用于归档。\n"
        f"任务标题：{title}\n"
        f"截止日期：{due}\n"
        f"当前状态：{status}\n"
        f"任务说明：{masked_desc}\n"
        "要求：只输出摘要正文，不要解释、不要加引号、不要使用 Markdown。"
    )


# PR-2：任务描述结构化抽取的目标字段与归一化映射
_DRAFT_PRIORITY_MAP = {
    '高': 'high', '中': 'medium', '低': 'low',
    '紧急': 'urgent', '特急': 'urgent', '急': 'urgent',
    'high': 'high', 'medium': 'medium', 'low': 'low', 'urgent': 'urgent',
}


def build_structured_task_prompt(text):
    """任务描述结构化抽取（PR-2）：把一段自由文本整理成一则任务草稿的字段。

    Args:
        text: 用户粘贴的原始需求 / 会议纪要等自由文本
    Returns:
        str: 发送给本地模型的提示词（要求输出 JSON）
    """
    cleaned = (text or '').strip()
    return (
        "你是单位内部的督办助手。请把下面这段自由文本整理成一则督办任务的草稿，"
        "提取关键字段并以 JSON 输出（不要输出 JSON 以外的任何解释或 Markdown 代码块标记）。\n"
        "JSON 字段约定：\n"
        "  title: 任务标题（必填，简洁，≤30 字）\n"
        "  priority: 优先级，取值仅限 \"high\" / \"medium\" / \"low\"（高/中/低）\n"
        "  due_date: 截止日期，格式 \"YYYY-MM-DD\"；无法推断则填空字符串\n"
        "  risk_note: 风险点说明（≤100 字），没有则填空字符串\n"
        "  collaborators: 协同方（≤100 字），没有则填空字符串\n"
        "  description: 任务说明（整合原文要点，≤300 字）\n"
        "注意：不要臆造负责人（assignee 由人工在系统里选择，不要出现在 JSON 里）。\n"
        f"原始文本：\n{cleaned}\n"
    )


def parse_structured_task(text):
    """解析模型返回的 JSON 草稿，归一化为表单字段 dict。

    容错：支持 ```json 围栏、前后多余文字、以及非严格 JSON。
    解析失败返回 None，由调用方退化为「原文放进 description」的人工录入。

    Returns:
        dict|None: {title, priority, due_date, risk_note, collaborators, description}
    """
    if not text:
        return None
    raw = text.strip()
    # 去 ```json ... ``` 围栏
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw.strip())
    # 截取首个 {...} 块，容忍前后解释文字
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    pri = str(data.get('priority', '') or '').strip().lower()
    priority = _DRAFT_PRIORITY_MAP.get(pri, 'medium')
    due = str(data.get('due_date', '') or '').strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', due):
        due = ''
    return {
        'title': str(data.get('title', '') or '').strip(),
        'priority': priority,
        'due_date': due,
        'risk_note': str(data.get('risk_note', '') or '').strip(),
        'collaborators': str(data.get('collaborators', '') or '').strip(),
        'description': str(data.get('description', '') or '').strip(),
    }


# PR-3：督办简报 / 周报（管理员）


def _fmt_task_lines(items, fields):
    """把任务清单格式化成可读文本行（供提示词拼接）。"""
    lines = []
    for it in items:
        parts = [str(it.get(f) or '') for f in fields]
        parts = [p for p in parts if p]
        lines.append('- ' + ' | '.join(parts))
    return '\n'.join(lines) if lines else '（无）'


def build_daily_brief_prompt(context):
    """每日督办简报（PR-3）：把当日预警数据整理成一段可转发的管理简报。

    Args:
        context: models.get_brief_context('daily') 返回的 dict
    Returns:
        str: 发送给本地模型的提示词（要求输出简报正文）
    """
    lines = [
        "你是单位内部的督办助手。下面是一份当日督办态势数据，"
        "请据此写一段面向管理层的「每日督办简报」（中文，不超过 280 字）。",
        "要求：先一句话总览，再按紧急度列出最该关注的事项（逾期 > 即将到期 > 长期待激活），"
        "最后给 1-2 条处置建议。只输出简报正文，不要解释、不要加引号、不要使用 Markdown。",
        "",
        f"日期：{context.get('today', '')}",
        f"进行中任务数：{context.get('in_progress', 0)}",
        f"逾期任务数：{context.get('overdue_count', 0)}",
        f"即将到期（3 天内）任务数：{context.get('due_soon_count', 0)}",
        f"长期待激活（≥7 天未启动）任务数：{context.get('long_inactive_count', 0)}",
        "",
        "【逾期任务】",
        _fmt_task_lines(context.get('overdue', []),
                        ['title', 'assignee_name', 'due_date', 'priority']),
        "",
        "【即将到期】",
        _fmt_task_lines(context.get('due_soon', []),
                        ['title', 'assignee_name', 'due_date', 'priority']),
        "",
        "【长期待激活】",
        _fmt_task_lines(context.get('long_inactive', []),
                        ['title', 'assignee_name', 'created_at']),
    ]
    return '\n'.join(lines)


def build_weekly_report_prompt(context):
    """每周督办周报（PR-3）：把本周聚合数据整理成周报。

    Args:
        context: models.get_brief_context('weekly') 返回的 dict
    Returns:
        str: 发送给本地模型的提示词（要求输出周报正文）
    """
    lines = [
        "你是单位内部的督办助手。下面是一份本周督办态势数据，"
        "请据此写一份面向管理层的「每周督办周报」（中文，不超过 400 字）。",
        "要求：含「本周概览」（新建/闭环/当前逾期）、「风险与停滞提示」、"
        "「下周建议」三段，语气客观。只输出周报正文，不要解释、不要加引号、不要使用 Markdown。",
        "",
        f"统计区间：{context.get('week_start', '')} 至 {context.get('today', '')}",
        f"本周新建任务：{context.get('new_this_week', 0)} 项",
        f"本周闭环任务：{context.get('closed_this_week', 0)} 项",
        f"当前逾期任务：{context.get('overdue', 0)} 项",
        f"进行中任务：{context.get('in_progress', 0)} 项",
        f"待启动任务：{context.get('pending', 0)} 项",
        f"存在风险点任务：{context.get('risk_count', 0)} 项",
        f"停滞任务（进行中但进度为 0）：{context.get('stalled_count', 0)} 项",
        "",
        "【当前逾期清单】",
        _fmt_task_lines(context.get('overdue_list', []),
                        ['title', 'assignee_name', 'due_date', 'priority']),
    ]
    return '\n'.join(lines)
