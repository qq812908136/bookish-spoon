# 督办系统 — 演示库弱口令清理总览（2026-09-01）

> 承接 DEF-002 收尾后，按用户选择执行「清理演示弱口令」。

## 一、问题

演示数据中存在已知弱口令，属上线前安全整改清单的剩余项：
- 管理员 `admin` / `admin123`
- 8 位负责人 `zhangsan…zhengshi` / `123456`

DEF-005 只拦截了「新建弱口令」，已有弱口令账号仍可登录（不追溯设计）。正式上线前须清理。

## 二、新口令（强口令，满足 `PASSWORD_REQUIRE_STRENGTH=True`：≥8 位、含符号+数字+字母、不在黑名单、≠用户名）

| 角色 | 账号 | 新口令 |
|---|---|---|
| 管理员 | admin | `Supv#Admin2026` |
| 负责人（8 人） | zhangsan / lisi / wangwu / zhaoliu / sunqi / zhouba / wujiu / zhengshi | `Supv#Owner2026` |

## 三、改动清单

| 类别 | 文件 | 动作 |
|---|---|---|
| 源码 | `src/seed_demo_data.py` | 9 处 `admin123`/`123456` → 强口令（含 print 文案） |
| 源码 | `src/app.py`（初始化向导） | 5 处 → 强口令（含 print 文案） |
| 文档 | `docs/上线前待办.md` | 风险描述加「已清理」注脚；「下一步建议」第 2 项标记 ✅ 已完成 |
| 文档 | `CHANGELOG.md` | DEF-005 段「弱口令仍待改」→ 已清理；新增闭环条目 |
| 构建脚本 | `scripts/build_delivery_package.py` | README 模板账号表改为新强口令 + 修正用户名（实际为 zhangsan 等 8 人，原 owner01 不实） |
| 运行时数据 | `data/supervision.db` | 直接 UPDATE 9 个账号 `password_hash`（保留任务数据） |
| 运行时数据 | `deliverables/…-v3/05_离线程序/…/data/supervision.db` | 同上（重建 v4 时作为基线被复制） |
| 交付包 | `deliverables/督办系统-交付包-v4/`（重建） | 243 文件 / 13.5MB；离线库继承新口令、README 账号表更新、离线 exe 为 Sep-1 重建版 |

## 四、验证

- v4 离线库 9 账号新口令 `check_password_hash` 全部通过。
- v4 README 账号表已更新，无 `admin123`/`123456` 残留。
- 全量测试 `tests.test_suite` 重跑确认（后台任务 vbXtI8，预期 161/161，测试用独立库 `test_data/test_supervision.db` 与自有凭据，不受影响）。

## 五、提交

- `eaf205c` chore: 清理演示库弱口令（…），同步种子与初始化脚本
- 演示库 / 离线库（`*.db`）按 git 策略不入库，仅落盘 + 进 v4 zip。

## 六、仍挂起

1. **DEF-004 部署侧**：Waitress + HTTPS + 备份（按 `docs/生产部署指南.md`）。
2. **GitHub 私有仓推送**：暂缓，CI 当模板。
3. 演示账号正式交付前仍建议改密或重置（已在 README/CHANGELOG 标注）。
