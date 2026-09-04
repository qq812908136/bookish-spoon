"""crypto_util.py — 零依赖对称加密（SMTP 凭据存储用）

背景（V4 迭代「发送邮件」功能 B4 决策）：
    设置页允许管理员填写 SMTP 密码，需要加密后存进数据库。
    引入 cryptography 等专业库是最规范的做法，但那意味着
    requirements.txt + .spec hiddenimports + 托管解释器 + 重新打包 exe
    一整串流程（本项目踩过这个坑）。

    因此这里用**纯标准库**实现：
        hashlib.pbkdf2_hmac  —— 从 data/secret.key 派生 32 字节主密钥
        hashlib.shake_256    —— 由主密钥 + 随机 nonce 生成密钥流（XOR 流密码）

安全边界（必须如实告知使用者）：
    1. 这不是工业标准算法（不是 AES-GCM）。它足以抵御
       「用文本编辑器打开数据库文件瞄一眼」这个级别，
       但若要过正式的等保 / 安全审计，仍需换成 cryptography 的 AES。
    2. 安全性完全依赖 data/secret.key。该文件一旦丢失或被替换，
       已存的密文就解不开了 —— 代码会返回 None 而不是报错崩溃，
       上层据此提示「请重新填写密码」。
    3. 不提供完整性校验（无 MAC）。篡改密文会得到乱码而非明确报错，
       对本场景（本地 SQLite、同机读写）不构成实际威胁。
"""

import base64
import hashlib
import os

import config

# 派生密钥用的盐。是常量而非随机值——真正的秘密是 secret.key 本身，
# 盐的作用是让「邮件凭据」与其它用途派生出互不相干的密钥。
_PBKDF2_SALT = b'supervision-mail-credential-v1'

# PBKDF2 迭代次数。20 万次在普通机器上约 0.1 秒，
# 对「保存/读取配置」这种低频操作完全无感，但能挡住暴力枚举。
_PBKDF2_ITERATIONS = 200_000

# 密文前缀魔数，用于识别「密钥不对」的情形（解密后校验）
_MAGIC = b'DBXT'

# nonce 长度（字节）。每次加密随机生成，保证同一明文两次加密结果不同。
_NONCE_LEN = 12


def _derive_master_key():
    """从 data/secret.key 派生 32 字节主密钥。

    Returns:
        bytes: 32 字节主密钥；secret.key 不可读时返回 None。
    """
    try:
        with open(config.SECRET_KEY_FILE, 'r', encoding='utf-8') as f:
            secret = f.read().strip()
    except OSError:
        return None

    if not secret:
        return None

    return hashlib.pbkdf2_hmac(
        'sha256',
        secret.encode('utf-8'),
        _PBKDF2_SALT,
        _PBKDF2_ITERATIONS,
        32,
    )


def encrypt(plaintext):
    """加密字符串。

    Args:
        plaintext: 明文（str 或 None）。None / 空串原样返回。

    Returns:
        str: base64 编码的密文；密钥不可用时返回 None。
    """
    if not plaintext:
        return None

    master_key = _derive_master_key()
    if master_key is None:
        return None

    nonce = os.urandom(_NONCE_LEN)
    payload = _MAGIC + plaintext.encode('utf-8')

    # shake_256 可输出任意长度，正好用作流密码的密钥流
    keystream = hashlib.shake_256(master_key + nonce).digest(len(payload))
    cipher = bytes(a ^ b for a, b in zip(payload, keystream))

    return base64.b64encode(nonce + cipher).decode('ascii')


def decrypt(ciphertext_b64):
    """解密字符串。

    Args:
        ciphertext_b64: base64 编码的密文（str 或 None）

    Returns:
        str: 明文；密文为空 / 密钥不对 / 格式损坏时返回 None。

    说明：
        返回 None 而非抛异常，是因为本函数最常见的失败原因
        是「secret.key 丢了或被换过」——这是可恢复的运维事件，
        上层只需提示管理员重新填写，不该让整个请求 500。
    """
    if not ciphertext_b64:
        return None

    master_key = _derive_master_key()
    if master_key is None:
        return None

    try:
        raw = base64.b64decode(ciphertext_b64.encode('ascii'))
    except Exception:
        return None

    if len(raw) <= _NONCE_LEN:
        return None

    nonce = raw[:_NONCE_LEN]
    cipher = raw[_NONCE_LEN:]

    keystream = hashlib.shake_256(master_key + nonce).digest(len(cipher))
    payload = bytes(a ^ b for a, b in zip(cipher, keystream))

    # 魔数校验：解出来的东西不带魔数，说明密钥不对或密文被破坏
    if not payload.startswith(_MAGIC):
        return None

    try:
        return payload[len(_MAGIC):].decode('utf-8')
    except UnicodeDecodeError:
        return None


def is_available():
    """加密能力是否可用（secret.key 可读）。

    设置页据此决定是否允许填写 SMTP 密码——不可用时给出明确提示，
    而不是让用户填完了才发现存不进去。
    """
    return _derive_master_key() is not None
