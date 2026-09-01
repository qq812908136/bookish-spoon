# 督办系统 Git 使用说明

初始化日期：2026-08-30　|　仓库根目录：`C:\Users\王蓟冬\WorkBuddy\督办系统`

---

## 一、现在仓库里有什么

| 项目 | 状态 |
|---|---|
| 默认分支 | `main` |
| 首次提交 | `71d1ba7` 初始化版本库：督办系统 V2 基线 |
| 受控文件 | 162 个（源码、文档、模板、项目记忆） |
| 仓库体积 | 811 KB |
| 被忽略内容 | 约 126 MB（`build/`、`dist/`、离线程序、发行版 zip、数据库） |

**入库的**：`app.py`、`models.py`、`routes/`、`templates/`、`static/`、`docs/`、交付包中的文档与源码、`.workbuddy/memory/`。

**不入库的**（在 `.gitignore` 中排除）：

- `build/`、`dist/` —— PyInstaller 打包产物，可随时重新生成
- `deliverables/**/05_离线程序/` 与 `*.zip` —— 内含 Python 运行时，单份约 40 MB
- `data/*.db` 及 `*.bak-*` —— 数据库是运行产生的数据，不是源码
- `env_info.txt`、`*.log`、`__pycache__/`

---

## 二、每天只用的三个命令

```bash
git status              # 看看改了哪些文件
git add -A              # 把改动放进待提交区
git commit -m "说明"     # 存一个版本快照
```

想看历史：`git log --oneline`。

一句话原则：**做完一个小改动就提交一次**，提交说明写清楚"改了什么、为什么"。

---

## 三、Worktree：同时开多个工作目录

### 它解决什么问题

平时一个仓库只有一个工作目录，切分支就必须把当前改完的东西先收起来。
**Worktree 让你把不同分支同时检出到不同文件夹**，互不干扰——比如主目录跑着系统，另一个目录同时改新功能。

### 用法

```bash
# 1. 新建一个工作树（会自动建同名分支，分支名用连字符，原因见第四节）
git worktree add ../督办系统-新功能 feature-export

# 2. 查看当前有哪些工作树
git worktree list

# 3. 用完后移除
git worktree remove ../督办系统-新功能
```

新目录里是完整的副本，可以直接启动、调试。它和主目录**共享同一份提交历史**，任何一边提交，另一边都能看到。

### 实测结果

已验证可用：创建工作树 → 文件正确检出 → `start.bat` 保持 CRLF 换行且 GBK 编码正确 → 移除后仓库无残留、`git fsck` 无告警。

---

## 四、两个必须知道的坑

### 坑 1：分支名不要用斜杠

本机的 Git（WorkBuddy 自带 PortableGit 2.55）**无法创建含 `/` 的分支名**，例如 `feat/导出功能`。
现象很隐蔽：命令返回成功、不报错，但分支根本没建出来。

- ✅ 用连字符：`feature-export`、`fix-逾期计算`、`wt-check`
- ❌ 不要用：`feature/export`、`fix/overdue`

如果确实需要斜杠命名（比如要对接外部团队的规范），可以用备用命令，它会绕过这个问题：

```bash
git nb feat/导出功能        # 备选方案，替代 git branch
```

注意：用 `git nb` 建的分支不带操作日志，Worktree 中使用可能出现 HEAD 状态异常——**Worktree 场景请一律用连字符命名**。

### 坑 2：`.bat` 脚本的换行符

Windows 的 `cmd.exe` 要求 `.bat` 必须是 **GBK 编码 + CRLF 换行**。一旦被转成 LF，中文会变成乱码，cmd 还会把乱码当命令执行而报错。

本项目已在 `.gitattributes` 中强制保护：

```
*.bat text eol=crlf
*.cmd text eol=crlf
*.ps1 text eol=crlf
```

无论谁、在什么系统上检出，这些文件都会是 CRLF。同时 `core.autocrlf=false`，换行行为不依赖各人电脑的设置。**这两行配置不要删。**

---

## 五、命令速查

| 想做什么 | 命令 |
|---|---|
| 看当前状态 | `git status` |
| 看改动内容 | `git diff` |
| 提交 | `git add -A && git commit -m "说明"` |
| 看历史 | `git log --oneline` |
| 撤销未提交的改动 | `git checkout -- 文件名` |
| 新建分支并切换 | `git checkout -b feature-xxx` |
| 切回主分支 | `git checkout main` |
| 建工作树 | `git worktree add ../目录名 分支名` |
| 删工作树 | `git worktree remove ../目录名` |
| 看工作树列表 | `git worktree list` |

---

## 六、配置备注

提交身份是**仓库级**设置（只作用于本项目，未改动全局配置）：

```
user.name  = 王蓟冬
user.email = wangjidong@local
```

若要修改：

```bash
git config user.name "你的名字"
git config user.email "你的邮箱"
```

目前尚未连接远程仓库（GitHub / GitLab 等），所有版本都存在本机。需要备份或协作时再添加：

```bash
git remote add origin <仓库地址>
git push -u origin main
```
