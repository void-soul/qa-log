---
name: qa-log
description: "Use when the user asks a programming question or requests a code change. Logs the question and its solution to qa.db (SQLite) in the project root using a structured 4-section format: 现象/需求, 根因, 解决方案, 涉及文件. Supports multi-question decomposition and token-efficient retrieval via scripts."
version: 3.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, logging, documentation, context, programming]
    related_skills: [code-audit, systematic-debugging]
---

# QA Log — Cross-Session Context Preservation

当用户提出编程问题或要求代码变更时，使用此技能记录问题和解决方案到 `qa.db`。

**核心原则：** 每个解决的问题都成为可搜索的参考。

**提交规则：** git commit message 一律使用**英文**编写（描述部分不要写中文），并包含 QA ID 追溯标记（如 `fix: #Q-0001 Fix save button`）。详见 `skills/check.md` 与 `skills/batch-commit.md`。

> **存储说明（v3.0）**：数据源已从 `QA.md`（Markdown）迁移为 `qa.db`（SQLite 单文件数据库）。
> `qa.db` 位于**使用此 skill 的项目根目录**（不是 skill 目录）。脚本默认读写 `./qa.db`，
> 因此运行脚本前请先 `cd <project-root>`。Tauri 桌面浏览器读取同一个 `qa.db`。

## 首次使用初始化（MANDATORY）

在项目的第一次使用时，一条命令同时完成「建库 + 部署浏览器 exe」：

```bash
cd <project-root> && python <skill-path>/scripts/qa_tool.py setup
```

`setup` 会：
1. 若项目根目录无 `qa.db`，创建 `qa.db` + `qa_entries` 表（已有则跳过）
2. 若项目根目录无 `QALogBrowser.exe`，从 skill 的 `bin/` 目录复制过来（已有则跳过）

之后直接双击 `QALogBrowser.exe` 即可查看 `qa.db` 数据。

> 开发调试时也可 `cd <skill-path>/tauri-app && npm run tauri dev`（前端 dev 服务器）。

## 目录结构

```
<skill-path>/                            # skill 自身目录（只读分发）
├── SKILL.md                             # 本文件（主入口）
├── README.md                            # 同上但给人类阅读的精简版
├── bin/
│   └── QALogBrowser.exe                 # Tauri 桌面浏览器（由 setup 复制到项目根）
├── scripts/
│   ├── db.py                            # 共享 DB 逻辑：connect/ensure_schema（自动迁移 + 4 位零填充）
│   ├── qa_tool.py                       # 主 CLI：增/改/查/格式化/删除
│   ├── search_qa.py                     # 关键词搜索 CLI
│   ├── qa_md_sync.py                    # QA.md ⇄ qa.db 增量合并
│   └── gen_commit_msg.py                # 生成带 #Q-XXXX 追溯标记的 commit message
├── skills/                              # 7 个子技能（按需加载）
│   ├── add-question.md                  # Phase 1: 记录问题
│   ├── fill-solution.md                 # Phase 3: 填写方案
│   ├── check.md                         # 检查/验证
│   ├── format-doc.md                    # 格式校验
│   ├── search.md                        # 搜索
│   ├── batch-commit.md                  # 分批提交
│   └── md-sync.md                       # QA.md 合并
├── references/                          # 参考文档
│   ├── qa-md-template.md                # QA.md Markdown 模板
│   └── skill-organization-pattern.md    # skill 组织模式说明
└── tauri-app/                           # Tauri 源码（开发/重建用）

<project-root>/                          # 使用此 skill 的项目根（运行时数据）
├── qa.db                                # SQLite 数据库（脚本默认 ./qa.db）
├── QALogBrowser.exe                     # 桌面浏览器（由 setup 部署）
└── QA.md                                # 可选：Markdown 编辑面（由 qa_md_sync.py 维护）
```

## 对外提供的能力

### 能力1: 记录问题与解决方案

**触发条件：** 用户提出编程问题、调试请求或代码变更要求

**工作流程：**
1. 加载 `qa-log/skills/add-question` 技能，记录问题
2. 正常解决问题
3. 加载 `qa-log/skills/fill-solution` 技能，记录解决方案

### 能力2: 检查QA条目

**触发条件：** 用户说 "请检查Q-XXXX" 或类似请求

**工作流程：**
1. 加载 `qa-log/skills/check` 技能
2. 提取条目、分析、审查代码、做出判断、更新状态
3. **询问用户是否提交**（检查通过后必须）
4. 仅在用户确认后提交涉及的代码文件

### 辅助能力

**搜索条目：** 加载 `qa-log/skills/search` 技能，按关键词、状态、类别搜索历史QA记录

**格式检查：** 加载 `qa-log/skills/format-doc` 技能，验证和修复 qa.db 条目结构

**分批次提交：** 加载 `qa-log/skills/batch-commit` 技能，按功能分组提交代码，避免一次性提交全部

**QA.md ⇄ qa.db 增量合并：** 加载 `qa-log/skills/md-sync` 技能，把 QA.md 改动增量合并进 qa.db（或反向导出）

## 何时跳过

- 非编程问题
- 简单事实查询
- 用户明确说"跳过QA记录"

## 子技能

|| 技能 | 用途 |
||------|------|
|| `qa-log/skills/add-question` | Phase 1: 记录问题 |
|| `qa-log/skills/fill-solution` | Phase 3: 填写方案 |
|| `qa-log/skills/check` | 检查验证 |
|| `qa-log/skills/format-doc` | 格式检查 |
|| `qa-log/skills/search` | 搜索历史QA条目 |
|| `qa-log/skills/batch-commit` | 分批次提交代码 |
|| `qa-log/skills/md-sync` | 增量合并 QA.md → qa.db |

## CLI 参考（scripts/qa_tool.py）

`qa_tool.py` 直接读写项目根目录的 `qa.db`，支持以下子命令：

| 子命令 | 参数 | 说明 |
|--------|------|------|
| `setup` | — | 首次使用：建 `qa.db` + 复制 `QALogBrowser.exe` 到项目根目录 |
| `summary` | `-n/--limit` | 列出所有条目（ID + 标题）。`-n N` 只显示前 N 条（按 qid DESC）|
| `get <ID>` | `ID`（如 `Q-0003` 或 `3`） | 查看单条完整内容 |
| `append` | `-c/--category`, `-q/--question` | 新增条目（ID 自动递增，状态默认 Pending） |
| `update <ID>` | `-q/--question`, `-s/--status`, `-r/--root-cause`, `-a/--answer`, `-f/--files` | 更新已有条目（自动写 `updated_at`） |
| `next-id` | — | 打印下一个可用 ID |
| `delete <ID>` | `-f/--force`, `--dry-run` | 删除单条（默认有确认提示）。`--force` 跳过确认；`--dry-run` 只显示不删 |
| `format` | — | 校验并报告 qa.db 条目结构问题 |

> **`delete` 安全设计**：默认打印待删条目 + ID + 日期 + 类别 + 状态 + 标题，要求键入 `y` 确认。脚本/Python 调用请加 `-f` 跳过交互；不确定时用 `--dry-run` 预览。

**`update` 可修改字段说明：**
- `-q/--question`：覆盖「现象/需求」字段（即新增时写入的问题文本）。**用于修正乱码或改写需求描述**。
- `-s/--status`：状态（`Pending` / `已解决待验证` / `已验证` / `WontFix` / `Unresolved`）。
- `-r/--root-cause`：根因分析（覆盖「根因」）。
- `-a/--answer`：解决方案步骤（覆盖「解决方案」）。
- `-f/--files`：变更文件表（覆盖「涉及文件」，`| File | Change |` 格式）。

所有文本参数中字面量 `\\n` 会被展开为真实换行；多行内容建议用 `\\n` 拼接。

> **乱码预防：** 所有脚本已强制使用UTF-8编码（`sys.stdout.reconfigure(encoding="utf-8")`）。
> Windows环境下如需在命令行直接使用，请先执行 `chcp 65001` 切换到UTF-8代码页。
> 推荐通过 Python 脚本调用避免命令行编码问题（中文参数勿直接在 shell 中传递）。

## 数据模型（qa_entries 表）

`qa.db` 中只有一张表 `qa_entries`，主键是 `qid`（TEXT，4 位零填充如 `Q-0001`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `qid` | TEXT PRIMARY KEY | 唯一 ID + 排序键，4 位零填充。`append` 时自动分配（`get_next_qid`），`update` 时不可改 |
| `date` | TEXT | 记录日期，`append` 时自动写入 `YYYY-MM-DD` |
| `category` | TEXT NOT NULL | 类别（`Bug Fix` / `Feature` / `Refactor` / `Performance` / `Documentation` / `Architecture` / `Style` / `Build` / `Test` / `Other`） |
| `status` | TEXT NOT NULL | 状态（`Pending` / `已解决待验证` / `已验证` / `WontFix` / `Unresolved`）。**默认 `Pending`** |
| `phenomenon` | TEXT | 现象/需求（即用户问题）。`append --question` 写入，后续可用 `update -q` 覆盖 |
| `root_cause` | TEXT | 根因分析。`update -r` 写入 |
| `solution` | TEXT | 解决方案步骤。`update -a` 写入 |
| `files` | TEXT | 涉及文件表（Markdown 格式 `| File | Change |\n|------|--------|\n| ... |`）。`update -f` 写入 |
| `created_at` | TEXT | 创建时间（ISO 8601 UTC），`append` 时自动 |
| `updated_at` | TEXT | 最后修改时间，`update` 时自动 |

> **类别与状态无外键约束**，可自由取任意字符串，但建议遵循上表约定。`check` / `format` 子技能会校验。

## CLI 参考（scripts/qa_md_sync.py）

`qa_md_sync.py` 在 `QA.md`（Markdown 编辑面）与 `qa.db` 之间做**增量合并**，支持以下子命令：

| 子命令 | 参数 | 说明 |
|--------|------|------|
| `sync`（默认） | `--md`, `--db` | 增量合并 `QA.md` → `qa.db`：INSERT 新条目、UPDATE 变更条目、跳过未变条目；**绝不删除** db 中 md 缺失的条目 |
| `export` | `--md`, `--db` | 从 `qa.db` 全量重建 `QA.md`（编辑面/备份） |

```bash
# 增量合并（默认）
cd <project-root> && python <skill-path>/scripts/qa_md_sync.py sync

# 反向导出（重建 QA.md）
cd <project-root> && python <skill-path>/scripts/qa_md_sync.py export
```

`--md` / `--db` 默认 `./QA.md` / `./qa.db`。详见 [`skills/md-sync.md`](skills/md-sync.md)。

## 自动迁移

所有 `scripts/*.py` 在 `connect()` 时都会自动调 `scripts/db.py::ensure_schema()`，每次打开是幂等的：

1. **`qa_entries` 表不存在** → 用现代 schema 创建（`qid TEXT PRIMARY KEY`）
2. **legacy schema**（`id INTEGER PK + qid TEXT UNIQUE`）→ 自动 `CREATE-INSERT-DROP-RENAME` 迁移到现代 schema
3. **缺 `updated_at` 列** → 自动 `ALTER TABLE ADD COLUMN` 补上
4. **3 位 qid**（`length=5`）→ 自动 `UPDATE` 补 `0` 前缀成 4 位（`length=6`）

迁移是向前兼容的，不需要人工介入。legacy 备份文件 `qa.db.pre-*.bak` 仍可保留以供回滚。

> **手动迁移时机：** 仅在外部工具/手写 SQL 把 qid 改成 3 位后，下一次 `qa_tool.py <任意命令>` 调用会自动修回。

## 技能组织说明

所有子技能统一存放在 `qa-log/skills/` 目录下，通过嵌套路径访问。不要创建单独的顶级子技能目录。

详见 [`references/skill-organization-pattern.md`](references/skill-organization-pattern.md)
