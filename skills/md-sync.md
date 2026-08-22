---
name: qa-log-md-sync
description: "Incrementally merge QA.md into qa.db (and export back). Use when the user updates QA.md and wants it synced into qa.db, or needs to regenerate QA.md from qa.db."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, sync, import, export, markdown, sqlite]
    related_skills: [qa-log, qa-log-add-question, qa-log-fill-solution, qa-log-format-doc]
---

# QA MD ⇄ DB 增量合并

在 `qa.md`（Markdown 编辑面）与 `qa.db`（SQLite 唯一数据源）之间做**增量合并**。

## 触发条件

- 用户说「把 QA.md 合并进 qa.db」「同步 QA.md」「增量合并 qa.md 到 qa.db」等
- 编辑完 `qa.md` 后，需要把改动一键同步进 `qa.db`

## 工作原理

脚本 `<skill-path>/scripts/qa_md_sync.py` 支持两个方向：

| 命令 | 方向 | 语义 |
|------|------|------|
| `sync`（默认） | `qa.md` → `qa.db` | **增量**：只 INSERT 新条目、UPDATE 变更条目、跳过未变条目；**绝不删除** db 中 md 缺失的条目 |
| `export` | `qa.db` → `qa.md` | 全量重新生成 Markdown（编辑面/备份） |

## 工作流程

### 1. 增量合并 qa.md → qa.db

```bash
cd <project-root> && python <skill-path>/scripts/qa_md_sync.py sync
```

可选 `--md <path>` / `--db <path>` 覆盖默认 `./QA.md` / `./qa.db`。

输出示例：

```
Sync .../QA.md -> .../qa.db: 3 added, 2 updated, 151 unchanged (156 parsed; 156 in db)
```

### 2. 从 qa.db 重建 qa.md（编辑面）

```bash
cd <project-root> && python <skill-path>/scripts/qa_md_sync.py export
```

## CLI 参考

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `command` | `sync`（增量合并 QA.md → qa.db，默认）或 `export`（重建 QA.md） | `sync` |
| `--md <path>` | QA.md 路径 | `./QA.md` |
| `--db <path>` | qa.db 路径 | `./qa.db` |

## 增量判定

每条按 `(date, category, status, phenomenon, root_cause, solution, files)` 七元组比对：

- db 无该 `qid` → **added**（INSERT）
- 七元组不同 → **updated**（UPDATE）
- 完全相同 → **unchanged**（跳过，保留原始 `created_at`）

`sync` 只增改、不删除，避免 `qa.md` 不全时误删数据。

## 输出格式

```
Sync <md> -> <db>: <added> added, <updated> updated, <skipped> unchanged (<parsed> parsed; <total> in db)
Exported <n> entries -> <md>
```

## 示例

用户说「把 QA.md 增量合并进 qa.db」：

```bash
cd <project-root> && python <skill-path>/scripts/qa_md_sync.py sync
# → Sync .../QA.md -> .../qa.db: 2 added, 1 updated, 153 unchanged (156 parsed; 156 in db)
```
