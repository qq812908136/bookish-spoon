# 项目结构重构（档位 3）— 执行总结

> 执行日期：2026-08-31 20:42–21:15
> 提交：`519d9d5`（184 文件变更）
> 结果：**业务代码零改动，仅调整目录位置与路径推导；全量测试 121/121 通过**

---

## 一、做了什么

按「档位 3（src 分层）+ 隔离产物 + 复制缺失 bat」执行，共 5 类动作：

| 类别 | 动作 | 数量 |
|---|---|---|
| 结构分层 | 源码 → `src/`、测试 → `tests/`、脚本 → `scripts/`、文档 → `docs/` | 4 个新目录 |
| 路径解耦 | 修改硬编码路径耦合 | 7 个文件 |
| 产物隔离 | `build/`、`dist/`、发行版 zip、`env_info.txt`、v1/v2 交付包 → `_archive/` | 约 117 MB |
| 备份归位 | `data/*.bak-*` → `data/backup/` | 4 个文件 |
| 补齐脚本 | 从 v3 交付包复制 `清除数据.bat`、`灌入演示数据.bat` 到仓库根 | 2 个 bat |

---

## 二、新目录结构

```
督办系统/                          ← 根目录条目 24 → 11
├── src/                           ← 应用源码（495 KB）
│   ├── app.py config.py db.py models.py auth.py
│   ├── state_machine.py warning_engine.py scheduler.py seed_demo_data.py
│   ├── routes/        7 个蓝图
│   ├── templates/     18 个模板
│   └── static/        main.css / main.js / logo.svg
├── tests/                         ← test_suite.py（121 项）+ 报告生成器 + test_data/
├── scripts/                       ← build_delivery_package.py
├── docs/                          ← 8 份原有 + 改动待办清单 + 3 份梳理报告 + 迭代记录/ + 测试报告/
├── data/                          ← supervision.db（9 用户/45 任务）+ backup/
├── deliverables/                  ← v3（已发行，未动）+ v4（新建）+ zip
├── _archive/                      ← 归档区（117 MB，不入库）
├── start.bat build.bat 清除数据.bat 灌入演示数据.bat 开启局域网访问.bat
├── 督办系统.spec requirements.txt README.md
```

---

## 三、7 处路径耦合修改（关键，后续改动要注意）

| # | 文件 | 改动内容 |
|---|---|---|
| 1 | `src/config.py` | `BASE_DIR` 改为退一级 = 项目根（挂 `data/`）；`BUNDLE_DIR` 改为 `src/`（挂模板/静态）。打包后逻辑不变 |
| 2 | `督办系统.spec` | 入口 `src/app.py`；`pathex=['src']`；`datas` 加 `src/` 前缀 |
| 3 | `build.bat` | 改为 `python -m PyInstaller 督办系统.spec --noconfirm`，参数集中在 spec（单一真相源） |
| 4 | `start.bat` | 执行 `python src\app.py` |
| 5 | `tests/test_suite.py` | `PROJECT_DIR` 硬编码绝对路径 → 基于 `__file__` 推导；`TEST_DATA_DIR` 跟随 `tests/` |
| 6 | `tests/generate_test_report.py` | 目录自适应：自动识别**仓库布局**与**交付包布局**（`04_测试/`），默认输出随之切换 |
| 7 | `scripts/build_delivery_package.py` | 路径全部基于 `__file__`；新增 v4 生成 + **版本白名单安全闸门**（v1/v2/v3 拒绝重建） |

> ⚠️ **bat 编码铁律**：`start.bat`、`build.bat`、两个新 bat 均通过脚本以 GBK 字节写入 + CRLF 换行，并做了「GBK 可解码 + 存在 CRLF + 无 LF-only」三重回读校验。

---

## 四、验证结果

| 验证项 | 结果 |
|---|---|
| 全量测试 | **121/121 通过**（358 秒） |
| 状态机子集 | 26/26 通过 |
| 配置路径推导 | `BASE_DIR`=项目根、`BUNDLE_DIR`=src、数据库/模板/静态三路径均存在 ✅ |
| 真实进程启动 | `/`→302、`/login`→200、`/static/css/main.css`→200；7 蓝图 / 38 路由 |
| 演示数据库 | 9 用户 / 45 任务 ✅ |
| V4 交付包源码模式 | 在 `03_开发代码/` 下独立运行成功，`BASE_DIR` 正确指向该目录 ✅ |
| V4 zip | 231 条目，`testzip` 无损坏，9 个 bat 全部 GBK+CRLF，无 db 文件混入 ✅ |
| V3 未受影响 | mtime 保持 01:18/01:47，`git status` 干净 ✅ |

---

## 五、V4 交付包

- 路径：`deliverables/督办系统-交付包-v4/`（232 文件）+ `督办系统-交付包-v4.zip`（13.4 MB）
- 生成方式：`python scripts/build_delivery_package.py v4`
  - 01/02/04/05 从 v3 **只读复制**；03_开发代码 由当前源码**实时装配**
  - 04_测试 用 `docs/测试报告/` 的最新报告覆盖（121/121）
- **离线 exe 已用新 spec 重新打包**（PyInstaller 6.10.0，51 秒），与 `src/` 分层后的源码同源：
  - `督办系统.exe --seed-demo` 复现 **9 用户 / 45 任务 / 67 消息**（双种子修复在新二进制上成立）
  - 数据库正确落在 exe 同级 `data/`（`FROZEN` 分支未受影响）
  - 真实 HTTP 冒烟 6/6：登录 → 仪表盘 → Excel 导出（45 任务 / 11 列）→ 中文文件名 `督办任务列表_2026-08-31.xlsx`
- v3 保持已发行状态，未做任何改动

### 过程中修掉的一个真 bug

`build_delivery_package.py` 原本把 `.db` 一律当运行产物过滤，导致从 v3 复制 `05_离线程序` 时，**离线包内置的演示数据库（9/45）被丢掉**——用户启动后只能进初始化向导，而非直接可演示。

修复：`ignore` 改为工厂函数 `make_ignore(keep_demo_db)`，仅对 `05_离线程序/**/data/supervision.db` 放行（该文件是刻意内置的演示数据，不是运行产物）。

---

## 六、后续项

1. ~~离线 exe 未重新打包~~ → **已完成**（见上，v4 现在自带新 exe + 内置演示库）。
2. **架构文档三份重复**：`docs/architecture-design.md` 与 `02_设计文档/督办系统-架构设计-最新.md` 字节数完全相同（76789），建议合并正名（本次未动，避免影响已发行包）。
3. **仍缺失**：`CHANGELOG`、logging/logs、`.env.example`、CI —— 建议并入「上线前整改」同批处理。
4. **上线前安全整改**（DEF-001 SECRET_KEY / DEF-002 CSRF / DEF-004 0.0.0.0+dev server）仍未处理，见 `docs/上线前待办.md`。
