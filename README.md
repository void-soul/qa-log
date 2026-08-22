# QA Log Skill

编程问答记录 Skill，数据存储于 SQLite 数据库 `qa.db`。

> **v3.0 变更**：数据源由 `QA.md`（Markdown）迁移为 `qa.db`（SQLite 单文件数据库），
> 位于**使用此 skill 的项目根目录**。脚本与 Tauri 桌面浏览器共用同一个 `qa.db`。

## 快速开始

### 在目标项目中初始化（首次使用）

进入你要记录 QA 的项目根目录，一条命令完成建库 + 部署浏览器：

```bash
cd /path/to/project
python <skill-path>/scripts/qa_tool.py setup
# 自动创建: qa.db + qa_entries 表
# 自动复制: bin/QALogBrowser.exe 到当前目录
```

### 添加记录

```bash
cd /path/to/project
python <skill-path>/scripts/qa_tool.py append \
  --category "Bug Fix" \
  --question "问题描述"
```

### 打开浏览器查看

```bash
./QALogBrowser.exe
# 或双击运行；自动读取同目录 qa.db
```

## 功能特性

- **GitHub Dark 主题** — 现代化深色 UI
- **类别与状态徽章** — 颜色区分 Pending/已验证/WontFix 等
- **ASCII 表格** — 涉及文件用框线表格渲染
- **实时搜索** — 关键词过滤 + 状态/分类筛选
- **SQLite 存储** — `qa.db` 单文件，零配置，脚本与 GUI 共用

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| CLI | Python 3.11 + sqlite3 | 数据存储与命令行 |
| 桌面客户端 | Tauri (Rust + WebView2) | 浏览器，读取同目录 qa.db |
| 数据库 | SQLite | 单文件 `qa.db`，零配置 |

## 文件清单

```
scripts/
├── db.py               # 共享 DB 逻辑（connect/ensure_schema，自动迁移 + 4 位零填充）
├── qa_tool.py          # CLI 工具 (setup/append/get/summary/update/delete/next-id/format)
├── search_qa.py        # 高级搜索
├── qa_md_sync.py       # QA.md ⇄ qa.db 增量合并
├── gen_commit_msg.py   # 生成 commit message
└── qa.db               # SQLite 数据库（在使用 skill 的项目根目录生成）
```

## Tauri 项目

位于 `tauri-app/`，编译产物 `QALogBrowser.exe` 部署到使用 skill 的项目根目录，
自动读取同目录 `qa.db` 显示数据。

构建与开发见 [tauri-app/README.md](tauri-app/README.md)。

## 架构

```
使用 skill 的项目根目录/
├── qa.db               # SQLite 数据库（qa_entries 表）
└── QALogBrowser.exe    # Tauri 桌面浏览器（读取同目录 qa.db）

skill 目录/
├── SKILL.md            # 技能入口
├── scripts/qa_tool.py  # agent 使用的 CLI
└── tauri-app/          # 桌面浏览器源码
```

核心原则：**每个解决的问题都成为可搜索的参考。**
