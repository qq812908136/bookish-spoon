# DEF-002 整改记录：全站 CSRF 防护

> 日期：2026-09-01 ｜ 关联缺陷：DEF-002（一般 / 安全）｜ 状态：✅ 已修复
>
> 相关文档：`docs/上线前待办.md`（DEF-002 章节）、`docs/缺陷清单-2026-08-31.md`、`docs/生产部署指南.md`

---

## 一、问题

所有写操作路由都没有 CSRF 防护。攻击者可以在自己的页面里放一个自动提交的表单，指向已登录用户的督办系统 —— 浏览器会**自动带上**受害者的会话 Cookie，于是删任务、改状态、建管理员账号这些操作会以受害者身份静默执行。

改动前的实际情况：

| 项目 | 数量 |
|---|---|
| 写操作路由（POST/PUT/DELETE） | 23 条，分布在 7 个蓝图 |
| `method="POST"` 表单 | 21 个，跨 10 个模板 |
| `main.js` 中的 AJAX 写请求 | 8 处 |
| 测试中的 `.post()` 调用 | 103 处 |

DEF-004 顺带加的 `SameSite=Lax` 能挡住最常见的跨站表单提交，但它是**依赖浏览器的被动防线**：同源场景下的伪造、以及 `fetch`/XHR 发起的跨站写请求都挡不住，服务端也无法主动拒绝可疑请求。

---

## 二、修复方案

### 2.1 为什么自研而不引入 Flask-WTF

第一反应是用 `Flask-WTF` 的 `CSRFProtect`，但放弃了这个方案。原因是**新增 Python 依赖在这个项目里成本很高**，需要同时改动四处：

1. `requirements.txt`
2. PyInstaller spec 的 `hiddenimports`
3. 托管解释器里 `pip install`
4. 重新打包 exe（并同步到两个离线目录、重打发行 zip）

而 CSRF 真正需要的只是「生成令牌 + 校验令牌」这一小块能力，用标准库 `hmac` + `hashlib` 实现不到 150 行，完全可控，也不给离线程序增加体积。同样的取舍在 DEF-005 时也做过一次（不引入 `python-dotenv`，改用内置 20 行 `.env` 解析）。

### 2.2 令牌形态：带过期时间的签名令牌

这是本次设计里最值得说的一个决定。

**朴素做法**是：会话里存一个随机令牌，表单里放这个令牌，提交时比对字符串是否相等。它有个很烦人的毛病 —— 一次只能有一个有效值。用户开了两个标签页，在 B 标签页重新登录之后，A 标签页的令牌就作废了，提交时莫名其妙报安全错误。

**采用的做法**是把过期时间签进令牌里：

```
会话里存：随机密钥 raw（只有服务端签名 Cookie 里有，攻击者读不到）
令牌     ：f"{过期时间戳}.{HMAC-SHA256(SECRET_KEY, f'{raw}.{过期时间戳}')}"
校验     ：解析出时间戳 → 用当前会话的 raw 重算签名 → 常量时间比对 → 检查是否过期
```

关键在于**校验是现算的，不是比对现值**。于是同一会话下多个令牌可以同时有效，只要都还在有效期内。这是 Flask-WTF 的做法，这里用标准库实现了一遍。

代价是页面停留超过 `CSRF_TOKEN_MAX_AGE` 后提交会提示刷新 —— 换来的是多标签页互不干扰。

### 2.3 接入方式：全局钩子，不是逐路由装饰器

```python
@app.before_request
def _check_csrf():
    result = csrf.verify_csrf()
    if result is not None:
        return result
```

放在 `before_request` 而不是给每个路由加装饰器，**是为了不留遗漏**：将来新写一条 POST 路由时，它默认就是受保护的，而不是依赖写代码的人记得加装饰器。

必须放在 `register_blueprints` 之后 —— 豁免判断要按 endpoint 查视图函数，而 endpoint 只有蓝图注册后才存在。

配套提供了 `csrf_exempt` 装饰器给确实无副作用的内部接口，并专门写了一条防回归用例遍历 `url_map`，确保豁免清单不会悄悄变长。

### 2.4 三处令牌来源

| 方式 | 适用场景 | 实现位置 |
|---|---|---|
| 表单字段 `csrf_token` | 普通表单提交 | 21 个模板的 hidden 字段 |
| 请求头 `X-CSRF-Token` / `X-CSRFToken` | fetch / XHR | `main.js` 的 `csrfHeaders()` |
| JSON body 的 `csrf_token` 键 | JSON 接口（如行内编辑） | 服务端 `request.get_json()` |

三种都支持，是为了让表单提交和 AJAX 走同一套机制，不必为 AJAX 单独开后门。

---

## 三、踩过的坑

### 3.1 测试用例「两次渲染令牌相同」是假失败

第一轮冒烟时写了一条用例：连续两次 `GET /login`，断言两个令牌不同，结果失败。

**原因不是 bug**：`generate_csrf_token()` 的过期时间是 `int(time.time()) + 86400`，两次调用发生在同一秒内，自然得到完全相同的字符串。真正要验证的属性是「一小时前渲染的页面，其令牌现在还有效」，不是「两次渲染的字符串不同」。

改成用 monkeypatch 把 `csrf.time.time` 往前拨一小时再生成，两个令牌就不同且都有效了。

> **教训**：验证时间相关的逻辑时，别指望靠调用间隔制造时间差。直接拨表。

### 3.2 探针路由自己被 CSRF 拦截

调试「JSON body 能否取到令牌」时，临时注册了一个 `/probe` 路由返回请求详情，结果拿回的是 400 页面 —— 探针自己被 CSRF 拦了。

这其实**反过来证明了钩子生效**，但调试时容易被绕进去。后来给探针加了 `@csrf.csrf_exempt`。

### 3.3 Flask 应用处理过第一个请求后不能再注册路由

调试脚本里想在跑过几个请求之后再 `@app.route` 加一个豁免路由，直接抛 `AssertionError: The setup method 'route' can no longer be called`。

写测试时要把所有探针路由在 `setUp` 里一次性注册完（`setUp` 每次都重建 app，所以是可行的）。

### 3.4 `/login` 的 JSON 请求返回 400，但不是 CSRF 拦的

验证「JSON body 携带令牌」时，往 `/login` 发 JSON 拿到 400，一度以为 JSON 通道有问题。

实际是 `/login` 路由本身只读 `request.form.get('username')`，JSON 传的用户名取不到，走的是「用户名为空」的 400 分支。**选错了验证用的路由**。换成一个专门的非豁免探针路由后立刻通过。

> **教训**：验证横切机制时，要用一个**行为最单纯**的探针路由，别挑一个本身就有多重校验的业务路由 —— 否则分不清 400 到底来自哪里。

### 3.5 测试客户端漏了 `json=` 形态，5 个用例挂了

`CsrfClient._prepare` 最初只处理两种形态：dict 表单数据 → 塞字段；既无 data 又无 json → 塞请求头。

结果 `TestInlineFieldEdit` 的 5 个用例全挂 —— 它们用的是 `self.client.post(url, json={...})`，两个分支都不进，令牌压根没带上。全量跑完才发现（单跑 `TestCSRF` 时看不到，因为失败的是**别的**类）。

补上「dict 型 json → 塞进 JSON body」这一支后全部通过。

> **教训**：写通用包装器时，先把调用点的参数形态**统计一遍**再动手。当时统计了「有没有 `json=`」卻只看了 `.post(` 的字面形态，没注意 `json=` 会被既有的 `data is None` 判断挡在外面。这类问题只在全量回归里暴露，所以改动横切机制后**必须跑全量**。

### 3.6 测试套件主入口不接受类名参数

`python test_suite.py TestCSRF` 会跑**全量**套件（参数被忽略），在 120 秒超时里被杀掉。要用 `python -m unittest test_suite.TestCSRF` 才按类跑。

---

## 四、测试改造

103 处 `.post()` 不可能逐个加参数。做法是包一层自动注入令牌的测试客户端，只改 18 处 `test_client()` 调用点：

```python
class CsrfClient:
    def __init__(self, client):
        self._client = client

    def _token(self):
        """读出**当前**会话的密钥，现算一个有效令牌。"""
        with self._client.session_transaction() as sess:
            if not sess.get(csrf.SESSION_KEY):
                sess[csrf.SESSION_KEY] = secrets.token_urlsafe(32)
            secret = sess[csrf.SESSION_KEY]
        expires_at = int(time.time()) + 3600
        return f'{expires_at}.{csrf._sign(f"{secret}.{expires_at}")}'

    def _prepare(self, kwargs):
        data = kwargs.get('data')
        if isinstance(data, dict) and csrf.FIELD_NAME not in data:
            data = dict(data)
            data[csrf.FIELD_NAME] = self._token()   # 走表单字段，贴近真实浏览器
            kwargs['data'] = data
            return kwargs

        payload = kwargs.get('json')
        if isinstance(payload, dict) and csrf.FIELD_NAME not in payload:
            payload = dict(payload)
            payload[csrf.FIELD_NAME] = self._token()  # 走 JSON body
            kwargs['json'] = payload
            return kwargs

        if data is None and payload is None:
            headers = dict(kwargs.get('headers') or {})
            headers.setdefault('X-CSRF-Token', self._token())  # 兜底走请求头
            kwargs['headers'] = headers
        return kwargs

    def post(self, *args, **kwargs):
        return self._client.post(*args, **self._prepare(kwargs))
    # put / patch / delete 同理，其余方法走 __getattr__ 透传
```

**「现算」这一步是必须的**：`do_login` 成功时会调用 `rotate_csrf_token()` 换掉会话密钥。如果用固定令牌，登录后所有写操作都会失效。

优先塞表单字段而不是请求头，是为了让这 103 处用例**顺便覆盖真实浏览器走的那条路径**，而不是全走 header 通道。

需要故意测试「没带令牌会被拒」时，用 `client.raw` 取原始客户端。

### 新增专项用例

`TestCSRF` 共 16 项，其中 3 项是**防回归**用例：

| 用例 | 作用 |
|---|---|
| `test_all_write_routes_require_token` | 遍历 `url_map`，24 条写路由逐条 POST 验证被拦。将来新增路由漏防护会直接失败 |
| `test_every_post_form_has_token_field` | 扫描 10 个模板的 21 个 POST 表单，确保都带 hidden 字段 |
| `test_mainjs_injects_token_into_every_write_fetch` | 扫描 `main.js`，8 处写请求都经过 `csrfHeaders` |

这三条的价值在于：CSRF 这类横切防护最容易的失效方式不是「代码写错了」，而是**「后来有人加新功能时漏了」**。

---

## 五、验证结果

| 项目 | 结果 |
|---|---|
| 全量测试套件 | 通过（原 145 项 + 新增 16 项） |
| `TestCSRF` 专项 | 16/16 |
| 核心行为冒烟 | 12 项全通过（无令牌被拒 / 三种通道 / 豁免 / 开关 / 多标签页 / 过期 / 篡改签名 / 跨会话） |
| 落 JS/模板检查 | 21 个表单 + 8 处 AJAX，0 遗漏 |

---

## 六、遗留事项

1. **页面停留超过 24 小时后提交会提示刷新** —— 这是「令牌带过期时间」方案的固有代价。抽屉类 AJAX 操作会在每次加载时用新签发的令牌刷新 meta 标签，不易触发；普通表单页面若确实需要，把 `CSRF_TOKEN_MAX_AGE` 调大即可。
2. **`csrf_exempt` 需要自律** —— 装饰器仅用于确实无副作用的内部接口，写操作路由一律不要加。防回归用例会跳过豁免路由，所以滥用它不会被自动发现。
3. **`SameSite=Lax` 保留** —— 作为第二道防线。两层互不依赖，任一层被绕过时另一层仍起作用。

---

## 七、变更文件清单

| 文件 | 变更 |
|---|---|
| `src/csrf.py` | **新增**，令牌生成/校验、`csrf_exempt`、请求校验入口 |
| `src/config.py` | 新增 `CSRF_ENABLED`、`CSRF_TOKEN_MAX_AGE` |
| `src/app.py` | 新增 `register_csrf_protection(app)`（`before_request` 钩子）；上下文处理器注入 `csrf_token` |
| `src/auth.py` | 登录成功时调用 `rotate_csrf_token()` |
| `src/templates/base.html` | 输出 `<meta name="csrf-token">` |
| `src/templates/errors/400.html` | **新增**，CSRF 校验失败的提示页 |
| 10 个模板的 21 个表单 | 插入 `<input type="hidden" name="csrf_token">` |
| `src/static/js/main.js` | 新增 `csrfToken()` / `csrfHeaders()` / `syncCsrfToken()`；8 处写请求注入令牌 |
| `tests/test_suite.py` | 新增 `CsrfClient` 与 `make_client`；18 处 `test_client()` 改用 `make_client`；新增 `TestCSRF`（16 项） |
| `.env.example` | 新增「CSRF 防护」配置项说明 |
| `docs/上线前待办.md` | DEF-002 章节改写为已修复；总览表、完成判定、下一步建议同步 |
| `docs/缺陷清单-2026-08-31.md` | DEF-002 标记已修复，补修复要点 |
| `CHANGELOG.md` | 新增 DEF-002 条目 |
| `README.md` | 常见问答新增 CSRF 相关条目；`.env` 表格补 2 项 |
