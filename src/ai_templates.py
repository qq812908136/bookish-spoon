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
