# 059 修复概览：新建任务页截止日期选中后显示异常

## 问题
用户截图反馈：新建任务页「截止日期」选中后显示不对。第一轮把 `color:transparent + ::after` 改为独立 `.date-placeholder` 元素后，用户反馈「更难看了」——占位文字与原生 date input 内容/图标重叠。

## 根因
在原生 `input[type="date"]` 上方叠加自定义文字，会与浏览器自带的日期控件渲染层产生重叠或截断，不同浏览器实现差异大，叠加方案天然脆弱。

## 修复
彻底放弃叠加，改用 text/date 类型切换：
1. `templates/tasks/form.html`：去掉 `.date-input-wrapper` 与 `.date-placeholder`；input 默认 `type="text"` + `placeholder="点击选择截止日期"`；聚焦时切为 `type="date"`，失焦且空值时切回 `type="text"`；编辑任务有值时直接渲染 `type="date"`。
2. `static/css/main.css`：移除所有 `.date-input-wrapper` / `.date-placeholder` 规则，仅保留 `.date-input::placeholder` 颜色样式。
3. `static/js/main.js`：彻底移除 `initDatePlaceholder` 及其调用，不再用 JS 维护 placeholder 状态。
4. 版本号 bump：`20260830ae → 20260830af`（base / login / setup 三页）。

## 验证
- 单测 `TestTaskFormExtraFields.test_new_task_date_input_shows_text_placeholder` 通过。
- 真实 HTTP 验证 `/tasks/new` 下发 `main.css?v=20260830af` / `main.js?v=20260830af`，日期 input 为单一 text/date 切换结构。

## 同步
- 源码与 4 份交付包副本（`03_开发代码` + `05_离线程序/_internal`，v1 + v2）已同步。
- `督办系统-发行版.zip` 已外科手术式替换对应 9 个条目。

## 提交
`git commit 626f49c`
