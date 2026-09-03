"""config.py — 督办系统配置项集中管理

所有全局配置集中在此文件，方便统一修改。
分为：路径配置、安全配置、分页配置、后台扫描配置、预警默认值。
"""

import os
import secrets
import sys

# ============================================================
# PyInstaller 冻结检测
# ============================================================
# 打包后 sys.frozen 为 True，sys.executable 指向 exe 所在路径
# 打包前（开发模式）正常运行，__file__ 指向源码文件
FROZEN = getattr(sys, 'frozen', False)

# ============================================================
# 路径配置
# ============================================================
# 目录约定（src 分层后）：
#   项目根/
#     ├─ src/    ← 本文件所在目录（应用源码、routes/templates/static）
#     ├─ data/   ← 数据库（BASE_DIR 指向项目根，与 src/ 同级）
#     └─ tests/ scripts/ docs/
#
# 运行目录：exe 所在目录（打包后）或项目根（开发时）
# 数据库文件存在这里，保证数据持久化
if FROZEN:
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # config.py 位于 src/ 下，向上退一级 = 项目根
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 资源目录：模板和静态文件所在位置
# 打包后资源在 sys._MEIPASS（PyInstaller 临时解压目录）
# 开发时在 src/ 目录（与 config.py 同级）
if FROZEN:
    BUNDLE_DIR = sys._MEIPASS
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))

# 模板和静态文件路径
TEMPLATE_DIR = os.path.join(BUNDLE_DIR, 'templates')
STATIC_DIR = os.path.join(BUNDLE_DIR, 'static')

# 静态资源缓存串（cache-busting）：改了 CSS/JS 之后改这里即可全局生效。
#
# 背景：模板里 url_for('static', ..., v='YYYYMMDDx') 靠这个版本号让浏览器
# 丢弃旧缓存。以前版本号写死在每个模板里，而 login.html / setup.html 是
# 独立页面（不继承 base.html），改样式时只 bump 了 base.html，导致登录页
# 和初始化向导页仍请求旧版本 → 拿到旧 CSS。
# 现在统一由 app.py 的 inject_globals() 注入 static_version，模板里一律
# 写 v=static_version，杜绝「改了样式忘了升某个页面」。
STATIC_VERSION = '20260903d'

# 数据库文件路径（运行时自动创建 data/ 目录）
# 数据库始终放在 BASE_DIR 下（exe 同级目录），不在临时解压目录
DATA_DIR = os.path.join(BASE_DIR, 'data')
DATABASE_PATH = os.path.join(DATA_DIR, 'supervision.db')

# ============================================================
# 环境变量覆盖（优先级：系统环境变量 > .env 文件 > 代码默认值）
# ============================================================
# 目的：让 SECRET_KEY 等敏感/环境相关配置不必写死在代码里，
# 也不需要改代码就能按部署环境调整。详见仓库根目录 .env.example。
#
# 设计约束：
#   1. 不引入 python-dotenv 依赖——新增依赖要重打包 exe，成本高；
#      这里用 20 行的极简 .env 解析替代。
#   2. 每一步都有原默认值兜底：打包后 .env 通常不存在、环境变量也没设，
#      此时行为必须与改动前**完全一致**，否则会破坏已发行的离线程序。


def _load_dotenv(path):
    """极简 .env 解析：逐行读 KEY=VALUE，忽略空行与 # 注释。

    只补齐 os.environ 里**不存在**的键——系统环境变量优先级更高。
    解析失败（文件损坏/权限问题）一律静默跳过，绝不让启动崩掉。
    """
    if not os.path.isfile(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_dotenv(os.path.join(BASE_DIR, '.env'))


def _env_str(key, default=None):
    v = os.environ.get(key)
    return default if v is None or v.strip() == '' else v.strip()


def _env_int(key, default):
    v = os.environ.get(key)
    if v is None or v.strip() == '':
        return default
    try:
        return int(v.strip())
    except ValueError:
        return default


def _env_bool(key, default):
    v = os.environ.get(key)
    if v is None or v.strip() == '':
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'on')


# ============================================================
# 安全配置
# ============================================================

# 密钥文件：存放本实例自动生成的会话签名密钥
SECRET_KEY_FILE = os.path.join(DATA_DIR, 'secret.key')


def _load_or_create_secret_key():
    """取得会话签名密钥：优先复用已落盘的，否则生成一个新的。

    解决了 DEF-001：此前密钥是写死在源码里的固定字符串，会随 exe/源码
    分发给所有部署方，任何人都能伪造管理员会话 Cookie。

    现在的取值顺序（由 SECRET_KEY 组装）：
        1. 环境变量 / .env 显式配置的 SECRET_KEY（运维主动指定时最高优先）
        2. data/secret.key 中已存在的密钥（首次启动生成后一直复用）
        3. 新生成并尝试落盘

    落盘失败（例如部署在只读目录）时不阻断启动：退回内存随机值，
    代价是重启后所有会话失效、需要重新登录——这仍远好过使用公开密钥。
    """
    # 已存在则直接复用，保证重启后旧会话仍然有效
    if os.path.isfile(SECRET_KEY_FILE):
        try:
            with open(SECRET_KEY_FILE, 'r', encoding='utf-8') as f:
                existing = f.read().strip()
            if existing:
                return existing
        except OSError:
            pass

    key = secrets.token_hex(32)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SECRET_KEY_FILE, 'w', encoding='utf-8') as f:
            f.write(key)
        try:
            # 尽力收紧权限（Windows 上 chmod 支持有限，失败可忽略）
            os.chmod(SECRET_KEY_FILE, 0o600)
        except OSError:
            pass
    except OSError:
        # 只读目录：用内存随机值继续运行，重启后会话失效
        pass
    return key


# Flask session 密钥（签名 cookie 用）
# 不再有任何写死在代码里的默认密钥：
#   - 显式配置（环境变量 / .env）优先；
#   - 否则首次启动自动生成随机密钥并写入 data/secret.key，之后一直复用。
# 因此**每个部署实例的密钥都不相同**，源码与打包物中不含可用密钥。
SECRET_KEY = _env_str('SECRET_KEY') or _load_or_create_secret_key()

# session 持久化时长（秒），默认 7 天
PERMANENT_SESSION_LIFETIME = 7 * 24 * 60 * 60

# ============================================================
# 分页配置（C1 确认：第一版就做分页）
# ============================================================
# 任务列表每页显示条数（需求：每页 10 条，使正常全屏下整页无滚动条）
TASKS_PER_PAGE = 10

# 消息列表每页显示条数
MESSAGES_PER_PAGE = 20

# ============================================================
# 后台扫描配置
# ============================================================
# 逾期扫描间隔（秒），默认 300 秒 = 5 分钟
OVERDUE_SCAN_INTERVAL = 300

# 预警扫描检查间隔（秒），每分钟检查一次是否到达扫描时间
WARNING_CHECK_INTERVAL = 60

# 预警每日扫描时间（HH:MM 格式），默认 09:00
WARNING_SCAN_TIME = '09:00'

# ============================================================
# 预警默认值（可被数据库 system_config 表覆盖）
# ============================================================
# 即将到期预警天数（默认 3 天）
DEFAULT_WARNING_DUE_DAYS = 3

# 长期待激活预警天数（默认 7 天）
DEFAULT_WARNING_INACTIVE_DAYS = 7

# ============================================================
# 服务器配置
# ============================================================
# 监听地址（可用环境变量 HOST 覆盖）
# '127.0.0.1' = 仅本机可访问 —— **默认值**，DEF-004 修复后不再对外暴露
# '0.0.0.0'   = 监听所有网卡，局域网内其他设备也可访问
#
# 需要局域网访问时用「局域网启动.bat」（它会设置 HOST=0.0.0.0 后启动），
# 不要把这个默认值改回 0.0.0.0 —— 那会让每一台部署机器默认对整个局域网开放。
HOST = _env_str('HOST', '127.0.0.1')

# 监听端口（可用环境变量 PORT 覆盖）
PORT = _env_int('PORT', 5000)

# 是否开启调试模式（可用环境变量 DEBUG 覆盖）
# 本地开发可设 True，打包发布**必须**为 False
DEBUG = _env_bool('DEBUG', False)

# 运行载体（可用环境变量 SERVER 覆盖）
# 'flask'    = Werkzeug 开发服务器（默认；仅适合本机/内网小规模使用场景）
# 'waitress' = 生产级 WSGI 服务器（需先 pip install waitress；未安装则自动回退）
# 生产部署建议设为 waitress，详见 docs/生产部署指南.md
SERVER = _env_str('SERVER', 'flask').lower()

# ============================================================
# CSRF 防护配置（DEF-002：全站跨站请求伪造防护）
# ============================================================
# 是否校验写请求的 CSRF 令牌。默认开启。
#
# 关掉意味着任何外部页面都能以已登录用户的身份提交表单
# （删任务、改状态、建管理员账号），**仅排障时临时关闭**，生产环境务必保持开启。
CSRF_ENABLED = _env_bool('CSRF_ENABLED', True)

# 令牌有效期（秒），默认 24 小时。
# 页面停留超过这个时长后再提交会提示刷新——这是「令牌带过期时间」方案的固有代价，
# 换来的是多标签页各自渲染的令牌互不干扰。调大可降低打扰，代价是令牌泄露后的窗口变长。
CSRF_TOKEN_MAX_AGE = _env_int('CSRF_TOKEN_MAX_AGE', 24 * 60 * 60)

# ============================================================
# 会话 Cookie 安全属性（可用环境变量覆盖）
# ============================================================
# 禁止 JS 读取会话 Cookie，缓解 XSS 后的会话窃取
SESSION_COOKIE_HTTPONLY = _env_bool('SESSION_COOKIE_HTTPONLY', True)

# 跨站请求时不发送会话 Cookie（Lax 允许正常的顶级导航跳转）
# 这是 CSRF 的第一道防线：跨站发起的 POST 不会带上会话
SESSION_COOKIE_SAMESITE = _env_str('SESSION_COOKIE_SAMESITE', 'Lax')

# 仅通过 HTTPS 传输会话 Cookie。
# 启用 HTTPS 后**必须**设为 True，否则会话 Cookie 会以明文在网上传输。
# 注意：在纯 HTTP 的内网环境设为 True 会导致无法登录（浏览器不会回传 Cookie）。
SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', False)

# ============================================================
# 登录安全配置（DEF-005：登录限流 + 弱口令拦截）
# ============================================================
# 同一个「客户端 IP + 用户名」组合，连续失败多少次后临时锁定
LOGIN_MAX_ATTEMPTS = _env_int('LOGIN_MAX_ATTEMPTS', 5)

# 锁定持续时长（分钟）。从**最后一次失败**起算，期间即使密码正确也拒绝登录。
# 设为 0 表示不锁定（只计数不拦截），仅用于排障。
LOGIN_LOCKOUT_MINUTES = _env_int('LOGIN_LOCKOUT_MINUTES', 15)

# 密码最小长度（新建账号 / 改密码 / 重置密码时校验）
# 注意：这是**前瞻性**约束，不会追溯已有账号——
# 早期创建的 6 位密码账号仍可正常登录，只在下次改密码时才要求达到新长度。
PASSWORD_MIN_LENGTH = _env_int('PASSWORD_MIN_LENGTH', 8)

# 是否启用弱口令拦截（长度、纯数字、常见弱口令、与用户名相同）
# 关掉后只保留最小长度校验，用于对接外部账号体系等特殊场景
PASSWORD_REQUIRE_STRENGTH = _env_bool('PASSWORD_REQUIRE_STRENGTH', True)

# ------------------------------------------------------------
# 反向代理支持（影响登录限流取到的客户端 IP）
# ------------------------------------------------------------
# 部署在 Nginx / Caddy 等反向代理后面时，应用看到的来源 IP 全是代理服务器的地址，
# 会让登录限流变成「一人被锁、全员陪绑」，审计日志里的 IP 也失去意义。
# 设为 true 后，应用会按 X-Forwarded-For 取真实客户端 IP。
#
# ⚠️ 只有在**确实**有反向代理在前面时才开启：
#    开启意味着信任 X-Forwarded-* 请求头，若实际没有代理，
#    攻击者可以自己伪造这个头，从而绕过登录限流。
BEHIND_PROXY = _env_bool('BEHIND_PROXY', False)

# 信任几层代理（对应 ProxyFix 的 x_for 参数）。
# 数字必须**等于**实际的代理层数：写大了会让攻击者有机会伪造更靠前的 IP 绕过限流。
#   1 层 = 只有 Nginx/Caddy（最常见）
#   2 层 = CDN + Nginx
BEHIND_PROXY_TRUSTED_HOPS = _env_int('BEHIND_PROXY_TRUSTED_HOPS', 1)

# ============================================================
# 日志配置（可用环境变量覆盖）
# ============================================================
# 日志目录：落在 BASE_DIR 下（exe 同级目录），便于离线部署时排查
LOG_DIR = os.path.join(BASE_DIR, 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'supervision.log')

# 日志级别：DEBUG / INFO / WARNING / ERROR
LOG_LEVEL = _env_str('LOG_LEVEL', 'INFO')

# 单个日志文件上限（字节），超过后自动轮转；默认 2 MB
LOG_MAX_BYTES = _env_int('LOG_MAX_BYTES', 2 * 1024 * 1024)

# 轮转保留的历史文件个数
LOG_BACKUP_COUNT = _env_int('LOG_BACKUP_COUNT', 5)

# ============================================================
# 消息轮询配置（C2 确认：每 30 秒轮询）
# ============================================================
# 前端消息红点轮询间隔（毫秒）
UNREAD_POLL_INTERVAL_MS = 30000

# ============================================================
# 邮件通知配置（V4 迭代：发送邮件功能）
# ============================================================
# 取值优先级：系统环境变量 / .env  >  数据库（设置页填写，密码加密存储）  >  此处默认值。
# 数据库这一层由 models.get_mail_config() 合并，不在此处读取。
#
# ⚠️ 铁律复核：所有默认值必须让「不配置 = 行为不变」成立。
#    MAIL_ENABLED 默认 False 且 host 默认为空，因此 exe 分发到目标机器时，
#    即使没有 .env、设置页也没填过，邮件功能完全不激活，行为与 V3 一致。
# ------------------------------------------------------------

# 邮件功能总开关。False 时队列不再扫描发送，页面也不显示邮件入口。
MAIL_ENABLED = _env_bool('MAIL_ENABLED', False)

# SMTP 服务器地址（如 smtp.qq.com）。为空即视为未配置。
MAIL_SMTP_HOST = _env_str('MAIL_SMTP_HOST', '')

# SMTP 端口：465 走 SSL 直连，587 走 STARTTLS
MAIL_SMTP_PORT = _env_int('MAIL_SMTP_PORT', 465)

# SMTP 账号（通常是完整邮箱地址）
MAIL_SMTP_USERNAME = _env_str('MAIL_SMTP_USERNAME', '')

# SSL 直连（465 端口用）。与 MAIL_USE_TLS 二选一，都填 True 时以 SSL 优先。
MAIL_USE_SSL = _env_bool('MAIL_USE_SSL', True)

# STARTTLS（587 端口用）
MAIL_USE_TLS = _env_bool('MAIL_USE_TLS', False)

# 发件箱地址（B2-③：全员共用同一个发件箱，Reply-To 才指向具体操作人）
MAIL_FROM_ADDR = _env_str('MAIL_FROM_ADDR', '')

# 发件人显示名
MAIL_FROM_NAME = _env_str('MAIL_FROM_NAME', '督办系统')

# 邮件落款（E5-①：做成可配项，不同单位可改成自己的署名）
MAIL_FOOTER = _env_str('MAIL_FOOTER', '本邮件由督办系统自动发送，请勿直接回复。')

# 每轮扫描最多发送几封物理邮件（F3-②：防止瞬间批量外发触发服务商风控）
MAIL_BATCH_LIMIT = _env_int('MAIL_BATCH_LIMIT', 20)

# 单封邮件最多重试几次（G1-①：超过后标记永久失败）
MAIL_RETRY_MAX = _env_int('MAIL_RETRY_MAX', 3)

# 重试间隔（分钟），长度应等于 MAIL_RETRY_MAX；不够时用最后一项兜底
# 默认 5 / 15 / 30 分钟递增
MAIL_RETRY_BACKOFF = _env_str('MAIL_RETRY_BACKOFF', '5,15,30')

# 手动发送冷却秒数（F4-②：同一任务 + 同一操作人 5 分钟内只能发一次）
MAIL_MANUAL_COOLDOWN = _env_int('MAIL_MANUAL_COOLDOWN', 300)

# 标题脱敏开关（H5-②：开启后邮件正文不显示完整任务标题，只显示「任务 #123」）
MAIL_MASK_TITLE = _env_bool('MAIL_MASK_TITLE', False)

# 发送记录保留天数（I2-②：超期自动清理，避免库文件无限膨胀）
MAIL_LOG_RETENTION_DAYS = _env_int('MAIL_LOG_RETENTION_DAYS', 90)

# 连续失败多少次触发通用熔断（G4-②），熔断后暂停 60 分钟再自动试探
MAIL_CIRCUIT_FAIL_THRESHOLD = _env_int('MAIL_CIRCUIT_FAIL_THRESHOLD', 10)

# 通用熔断的暂停时长（分钟）
MAIL_CIRCUIT_PAUSE_MINUTES = _env_int('MAIL_CIRCUIT_PAUSE_MINUTES', 60)

# 注：MAIL_SMTP_PASSWORD 不在此处读取。
#     它只有两处来源：环境变量 / .env（明文）、数据库（加密，见 crypto_util.py）。
#     放在 config 里会被模块级常量固化，既不利于设置页覆盖，也增加泄露面。

# ============================================================
# AI 能力配置（V5 迭代：AI 辅助生成）
# ============================================================
# 取值优先级：系统环境变量 / .env > 代码默认值。
# ⚠️ 铁律复核：所有默认值必须让「不配置 = 行为不变」成立。
#    AI_ENABLED 默认 False，因此未配置时 AI 功能完全不激活，行为与 V4 完全一致。
# ------------------------------------------------------------

# AI 功能总开关。False 时队列不再扫描生成，页面仅只读展示。
AI_ENABLED = _env_bool('AI_ENABLED', False)

# 模型提供方：'local'（Ollama 本地，零数据出网）/ 'cloud'（OpenAI 兼容云端）
AI_PROVIDER = _env_str('AI_PROVIDER', 'local')

# 本地模型接口地址（Ollama 默认端口 11434）
AI_API_BASE_URL = _env_str('AI_API_BASE_URL', 'http://127.0.0.1:11434')

# 模型名（本地填 Ollama 模型名；云端填 OpenAI 兼容模型名）
AI_MODEL_NAME = _env_str('AI_MODEL_NAME', 'qwen2.5:7b')

# 单次模型调用超时（秒）
AI_TIMEOUT = _env_int('AI_TIMEOUT', 30)

# 送模型前是否脱敏（手机号 / 邮箱 / 长数字证件号）
AI_MASK_DATA = _env_bool('AI_MASK_DATA', True)

# 每轮扫描最多处理几个 AI 任务（限流，避免瞬间打满本机 GPU / API 配额）
AI_BATCH_LIMIT = _env_int('AI_BATCH_LIMIT', 5)

# 单任务最多重试几次（超过后标记永久失败归档）
AI_RETRY_MAX = _env_int('AI_RETRY_MAX', 3)

# 重试间隔（分钟），长度应等于 AI_RETRY_MAX；不够时取最后一项兜底
AI_RETRY_BACKOFF = _env_str('AI_RETRY_BACKOFF', '1,5,15')

# 连续失败多少次触发通用熔断，熔断后暂停 N 分钟再自动试探
AI_CIRCUIT_FAIL_THRESHOLD = _env_int('AI_CIRCUIT_FAIL_THRESHOLD', 10)

# 通用熔断的暂停时长（分钟）
AI_CIRCUIT_PAUSE_MINUTES = _env_int('AI_CIRCUIT_PAUSE_MINUTES', 60)

# 注：AI_API_KEY 不在此处读取。
#     它只有一处来源：环境变量 / .env（明文，由 ai_service 直接读取）。
#     刻意不进 config 默认值，避免密钥被模块级常量固化或误打印。
