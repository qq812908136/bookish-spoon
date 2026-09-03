# 迭代记录：抽屉页面 UI 对齐设计稿（#061）

> 日期：2026-09-03 ｜ 关联：改动待办清单 #061 ｜ 版本号 `20260903c → 20260903d`

## 背景

用户给出设计稿 `督办仓-离线版.html`，要求按此改造三处抽屉（任务详情 / 负责人 / 消息）的 UI。
原抽屉头部信息密度低、字段平铺、缺卡片层次，与设计稿的「小标签 + 徽标 + 主操作」+「信息卡网格 + 分块卡片」语言不一致。

## 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `src/templates/tasks/_drawer.html` | 任务详情抽屉改为卡片式：头部 main/actions、编辑提示条、大标题、两列信息卡网格、分块卡片（进度/长文本/流转/邮件/时间线）、危险块 |
| `src/templates/tasks/_owner_drawer.html` | 负责人抽屉头部统一 + 任务行白底卡片（hover 蓝边上浮） |
| `src/templates/messages/_drawer.html` | 消息抽屉头部统一（小标签 + 未读徽标 + 操作区） |
| `src/routes/message_routes.py` | 消息抽屉渲染上下文新增 `unread_count` |
| `src/static/css/main.css` | 新增卡片式设计语言约 200+ 行（drawer-header-main/actions、drawer-eyebrow、drawer-edit-tip、drawer-title-field、drawer-field-grid、drawer-info-card、drawer-block/title、owner-task-row、drawer-danger-block、progress-lg、custom-scrollbar 等） |
| `src/config.py` | `STATIC_VERSION` `20260903c` → `20260903d` |

## 关键约束

- **只动骨架与外观，不动 JS 交互契约**：行内编辑（`data-field`/`data-url`）、页签切换（`data-tab`）、流转提交（`.drawer-form`）、关闭（`.drawer-close`）等选择器与类名全部沿用原结构，仅重新排布 DOM + 新增 CSS。
- 静态资源版本号集中管理，改样式只改 `config.STATIC_VERSION` 一处。

## 验证

- 本地冒烟脚本（任务 / owner / 消息三抽屉 + CSS 新规则 + 版本注入）：**40/40 通过**。
- 全量测试 212 项、exe 实跑冒烟、v4 交付包重建（12 项复核）：见收尾动作。

## 收尾动作

1. 全量测试 `python -m unittest tests.test_suite`（预期 212 通过）。
2. 重打包 exe（`build.bat`）→ 拷演示库 → exe 实跑冒烟。
3. `python scripts/build_delivery_package.py v4` 重建交付包 + zip，12 项复核。
4. 提交推送（如用户要求）。
