"""ai_templates.py — AI 提示词构建与脱敏（V5 迭代「AI 辅助生成」，Phase 0）

职责边界（对齐邮件子系统 ai_templates 的定位）：
- 仅为不同 job_type 构建送往模型的提示词
- 送模型前按配置脱敏（AI_MASK_DATA）敏感信息（手机号 / 邮箱 / 长数字证件号）
- 本模块不调用模型、不碰数据库、不做业务落库

⚠️ 提示词注入护栏：这里只做「基础脱敏」，不解析模型返回内容里的指令。
   模型返回内容在 ai_dispatcher 落库前不做二次执行，且必须经管理员人工确认
   （adopt）才会作为站内信发出——这是 SPEC v1.0 明确的「人工确认闸」。
"""

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
