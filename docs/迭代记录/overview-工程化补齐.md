# 执行概览：工程化补齐（2026-08-31）

> 提交：`1090d13`
> 范围：补齐项目最后 4 项缺失——`.env.example` / 文件日志 / CHANGELOG / CI

---

## 一、背景

档位 3 重构与文档收口完成后，项目仍缺 4 项工程化基础设施（此前标注为 P3）。本轮一次性补齐：

| 项 | 此前状态 | 补齐后 |
|---|---|---|
| 配置管理 | `SECRET_KEY` 等全部硬编码 | 支持环境变量 / `.env` 覆盖（默认值不变） |
| 日志 | 13 处 `app.logger` **只输出控制台**，关闭即丢 | 文件落盘 + 轮转 |
| CHANGELOG | 无 | `CHANGELOG.md`，按版本倒序 |
| CI | 无 | `.github/workflows/ci.yml` |

---

## 二、环境变量配置

### 设计

优先级：**系统环境变量 > `.env` 文件 > 代码默认值**

```
可覆盖项：SECRET_KEY / HOST / PORT / DEBUG / LOG_LEVEL / LOG_MAX_BYTES / LOG_BACKUP_COUNT
```

### 三条硬约束

**① 不配置 = 行为不变（最重要）**

打包成 exe 后 `.env` 通常不存在、环境变量也没设。此时若默认值有任何偏移，就会破坏已发行的离线程序。已逐项验证：

| 项 | 改动前 | 改动后（无 env） | 一致 |
|---|---|---|---|
| `SECRET_KEY` | `task-supervision-system-local-secret-key-2025` | 同左 | ✅ |
| `HOST` / `PORT` / `DEBUG` | `0.0.0.0` / `5000` / `False` | 同左 | ✅ |

**② 不引入 `python-dotenv`**

新增依赖要改 requirements → spec → 重打包 exe，成本远超收益。改用内置 20 行极简 `.env` 解析：忽略 `#` 注释、去引号、`OSError` 静默跳过、只补齐 `os.environ` 里不存在的键。

**③ 类型转换失败一律回退默认值**

```python
_env_int('PORT', 5000)   # 值非数字 → 5000，不抛异常
_env_bool('DEBUG', False) # 值无法识别 → False
```

### `.env` 读取位置

是 **`BASE_DIR`**（由 `config.py` 自身位置推导：开发时项目根、打包后 exe 同级），**不是当前工作目录** —— 有意设计，避免依赖 cwd。

> 调试教训：我最初在 `/tmp` 下放 `.env` 测试，得出「`.env` 没生效」的错误结论，实为测试位置不对。

### 对 DEF-001 的意义

`SECRET_KEY` 现可免改代码覆盖，为 P0 缺陷铺路。但**默认值仍是公开字符串**，不配置等于没修，已在 `docs/上线前待办.md` 明确标注「缓解但未消除」。

---

## 三、文件日志

### 此前的问题

`src/app.py`、`src/scheduler.py` 共 13 处 `app.logger` 调用，**只有控制台输出**。程序一关、窗口一闪，线上出问题时完全无从追查。

### 实现（`setup_logging()`）

输出到 `logs/supervision.log`：`RotatingFileHandler`，单文件 2 MB、保留 5 份、UTF-8、格式 `[时间] 级别 in 模块: 消息`。

### 三个防护点

| 风险 | 处理 |
|---|---|
| 日志目录不可写（只读部署） | **静默降级为仅控制台**，绝不因日志配置失败导致启动失败 |
| 测试反复 `create_app()` 导致 handler 累积、日志重复打印 | 用 `isinstance(h, RotatingFileHandler)` 判重，只添加一次 |
| 大量 app 实例堆出文件句柄 | `delay=True` 延迟打开，首次真正写日志时才开文件 |

### 落盘位置

打包后落在 exe 同级目录（已冒烟确认）。

---

## 四、CHANGELOG

`CHANGELOG.md`（仓库根，非 docs/ 内），按版本倒序只记**用户可见**变更：

- **V4（进行中）**：src 分层、构建产物隔离、交付包脚本化、env 配置、文件日志
- **v3.0**：Excel 导出、SVG 品牌图标、双种子修复（9/45/67）、121 项测试、已知问题表
- **v2.0**：抽屉交互、数据模型扩展（+3 列 / +2 表 / 自动迁移）、路由 26→37、视觉体系、术语统一
- **v1.0**：2 角色、5 态状态机、3 层预警、站内信、26 个路由

维护约定写在文件开头：**已发行版本不再改写**，发现遗漏在下个版本补记。

---

## 五、CI（`.github/workflows/ci.yml`）

### 关键决策：必须用 `windows-latest`

部署目标是 Windows，启动 bat 为 **GBK 编码**、防火墙命令为 **Windows 专有**。在 Linux 上跑会产生大量与目标环境无关的**假失败** —— CI 的价值在于反映真实部署环境。

### 结构

| Job | 触发 | 内容 |
|---|---|---|
| `test` | push / PR / 手动 | Python 3.11 + 3.12 矩阵；只装 Flask + openpyxl（**不装 pyinstaller**，仅打包需要，装上明显拖慢）；跑 121 项测试并上传报告 |
| `package` | 仅 `push tag (v*)` | 安装完整 requirements，PyInstaller 打包，上传离线程序 |

### ⚠️ 当前状态

**`git remote` 为空** —— 配置已写好并通过 YAML 校验，但需推送到远端仓库后才会真正运行。

---

## 六、构建脚本补漏

`03_开发代码` 的根目录文件清单此前不含 `.env.example` 与 `CHANGELOG.md` —— 拿到交付包的人看不到任何配置说明。已补入。

> 排查提醒：`ls -1` 不显示点开头的文件，`.env.example` 会看起来像「没复制进去」。可靠信号是条目数变化（232 → 234），或用 `ls -1a`。

---

## 七、验证结果

| 验证项 | 结果 |
|---|---|
| 全量测试 | **121 / 121 通过**（351.7 s） |
| 离线 exe 冒烟 | **7 / 7 通过** |
| 打包环境日志落盘 | 423 字节，内容含后台线程启动 / 预警扫描 / 启动地址 |
| env 三级优先级 | 默认值 / `.env` / 系统环境变量 三级实测通过 |
| 组合验证 | 交付包 `03_开发代码/` 下放 `.env` 设 `PORT=5001` → 源码模式启动后**仅监听 5001**，同时证明交付包源码可运行 + env 覆盖生效 |
| CI YAML | pyyaml 解析通过 |

离线 exe 冒烟明细：

```
[PASS] 1) GET /            -> 200 落地 /login
[PASS] 2) GET /login       -> 200 含登录表单
[PASS] 3) POST /login      -> 200 落地 /dashboard
[PASS] 4) GET /tasks       -> 200 含"任务"
[PASS] 5) GET /dashboard   -> 200 41680 字节
[PASS] 6) GET /tasks/export-> 200 xlsx 8974 字节
[PASS] 7) 打包环境日志落盘 -> 423 字节
```

日志实际内容：

```
[2026-08-31 22:09:56] INFO in app: 后台守护线程已启动（逾期扫描 + 预警扫描）
[2026-08-31 22:09:56] INFO in scheduler: 开始每日预警扫描 (2026-08-31 09:00)
[2026-08-31 22:09:56] INFO in app: 督办系统启动: http://127.0.0.1:5000 (本机)
[2026-08-31 22:09:56] INFO in app: 局域网访问地址: http://192.168.31.199:5000
```

验证后已清理交付包内临时产物（`.env`、`logs/`、`data/supervision.db`），`data/` 只留 `.gitkeep`。

---

## 八、变更清单（提交 `1090d13`，18 文件）

```
A  .env.example
A  .github/workflows/ci.yml
A  CHANGELOG.md
A  deliverables/.../v4/03_开发代码/.env.example
A  deliverables/.../v4/03_开发代码/CHANGELOG.md
M  .gitignore                      （+ .env / logs/）
M  README.md                       （+ 可选配置 .env、日志两节）
M  src/app.py                      （+ setup_logging）
M  src/config.py                   （+ .env 解析与环境覆盖）
M  scripts/build_delivery_package.py（+ 根目录文件清单补 2 项）
M  docs/README.md、docs/上线前待办.md、docs/项目目录结构说明.md
M  deliverables/.../v4/03_开发代码/ 下对应副本
```

v4 交付包重建：**exe 已重打包**（改了 `src/app.py` 与 `src/config.py`，必须重打才能与源码同源），新哈希 `0421e872`，234 文件 / zip 234 条目无 CRC 损坏。
