"""ai_service.py — AI 模型调用（V5 迭代「AI 辅助生成」，Phase 0）

设计要点（对齐 V4 邮件子系统铁律）：
- 零新增第三方依赖：用标准库 urllib 发 HTTP，避免改 requirements.txt / .spec / 重新打包 exe
- 失败必须静默降级：调用方（ai_dispatcher）保证不影响主流程
- 错误信息里绝不出现 API Key / Token
- Phase 0 实现 local（Ollama）通道；cloud（OpenAI 兼容）通道预留接口

⚠️ local 通道默认走 http://127.0.0.1:11434，数据不出本机，满足内网 / 离线部署合规要求。
"""

import json
import os
import re
import urllib.request
import urllib.error

import config


def call_model(prompt):
    """调用配置的 AI 模型。

    Args:
        prompt: 拼接好的提示词（str）

    Returns:
        dict: {'success': bool, 'text': str|None, 'error': str|None}
        - 成功：success=True, text=模型输出文本（已 strip）
        - 失败：success=False, text=None, error=脱敏后的错误说明
    """
    if not config.AI_ENABLED:
        return {'success': False, 'text': None, 'error': 'AI 功能未启用'}

    provider = (config.AI_PROVIDER or 'local').lower()
    try:
        if provider == 'cloud':
            return _call_cloud(prompt)
        return _call_local(prompt)
    except urllib.error.URLError as e:
        return {'success': False, 'text': None, 'error': _sanitize(str(e))}
    except Exception as e:  # pragma: no cover - 兜底，绝不向外抛出
        return {'success': False, 'text': None, 'error': _sanitize(repr(e))}


def _call_local(prompt):
    """Ollama 本地通道：POST {base}/api/generate。"""
    base = (config.AI_API_BASE_URL or 'http://127.0.0.1:11434').rstrip('/')
    model = config.AI_MODEL_NAME or 'qwen2.5:7b'
    url = base + '/api/generate'
    payload = json.dumps({
        'model': model,
        'prompt': prompt,
        'stream': False,
    }).encode('utf-8')
    req = urllib.request.Request(
        url, data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST')
    with urllib.request.urlopen(req, timeout=config.AI_TIMEOUT) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    text = (data.get('response') or '').strip()
    if not text:
        return {'success': False, 'text': None, 'error': '模型返回为空'}
    return {'success': True, 'text': text, 'error': None}


def _call_cloud(prompt):
    """云端通道（OpenAI 兼容 /chat/completions）。

    API Key 仅来自环境变量 / .env（AI_API_KEY），不进代码默认值、不进数据库明文。
    """
    base = (config.AI_API_BASE_URL or '').rstrip('/')
    model = config.AI_MODEL_NAME or ''
    api_key = os.environ.get('AI_API_KEY') or ''
    if not base or not model or not api_key:
        return {'success': False, 'text': None,
                'error': '云端通道配置不完整（缺少 base / model / key）'}
    url = base + '/chat/completions'
    payload = json.dumps({
        'model': model,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.3,
    }).encode('utf-8')
    req = urllib.request.Request(
        url, data=payload,
        headers={'Content-Type': 'application/json',
                 'Authorization': 'Bearer ' + api_key},
        method='POST')
    with urllib.request.urlopen(req, timeout=config.AI_TIMEOUT) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    text = (data.get('choices', [{}])[0]
            .get('message', {}).get('content', '') or '').strip()
    if not text:
        return {'success': False, 'text': None, 'error': '模型返回为空'}
    return {'success': True, 'text': text, 'error': None}


def _sanitize(error_text):
    """清洗错误信息，绝不包含 API Key / Token 等凭据。"""
    error_text = re.sub(r'Bearer\s+\S+', 'Bearer ***', error_text, flags=re.I)
    error_text = re.sub(r'Authorization[=:]\s*\S+', 'Authorization=***',
                        error_text, flags=re.I)
    if len(error_text) > 200:
        error_text = error_text[:200] + '…'
    return error_text
