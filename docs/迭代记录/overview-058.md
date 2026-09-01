# 058 改动概览

## 本次修复
左上角红框区域（图标 + 系统名 + 日期）现在不再可点击。

## 改动内容
- `templates/base.html`：将 `.topbar-brand` 由 `<a>` 改为 `<div>`，移除 `href`。
- `static/css/main.css`：为 `.topbar .topbar-brand` 增加 `cursor: default`。
- `templates/base.html` / `login.html` / `setup.html`：版本号统一 bump 到 `20260830ad`，确保浏览器拉取最新 CSS/JS。

## 验证结果
- 真实 HTTP 登录态实测：
  - `/dashboard` 返回的 `.topbar-brand` 是 `<div>`，块内无 `href`。
  - CSS/JS 查询参数为 `?v=20260830ad`。
  - 鼠标悬停该区域不再显示手型光标。

## 同步范围
- 4 份交付包副本（`03_开发代码` + `05_离线程序/_internal`，v1 + v2）。
- `督办系统-发行版.zip` 已外科手术式替换相关文件。

## 关联提交
`git commit 7560933`：057: 修复登出提示泄漏到首页；058: 顶栏品牌区改为不可点击
