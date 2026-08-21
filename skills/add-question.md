---
name: qa-log-add-question
description: "Add a new question entry to qa.db. Use when the user asks a programming question or requests a code change — this is Phase 1 of the qa-log workflow."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, logging, documentation, context, programming]
    related_skills: [qa-log, qa-log-fill-solution, qa-log-format-doc]
---

# Add QA Question Entry

Phase 1 of the qa-log workflow. Logs a new question to `qa.db` (SQLite) with `Pending` status.

> **v2.0**：数据源由 `QA.md` 改为 `qa.db`（SQLite），位于**项目根目录**。运行脚本前先 `cd <project-root>`。

## When to Use

- User asks a programming question, debugging request, or code change request
- User's message contains multiple distinct sub-questions → call this once per sub-question

## What to Do

Use the `terminal` tool to run the following commands:

### Step 1: Determine project root
项目根目录即存放 `qa.db` 的目录。若该目录还没有 `qa.db`，先初始化（只需一次）：
```bash
cd <project-root> && python <skill-path>/scripts/qa_tool.py setup
```
`setup` 会创建 `qa.db` + 表结构，并把 `QALogBrowser.exe` 复制到项目根目录。

### Step 2: Decompose (if needed)
If the user's request has multiple distinct sub-questions, you will create multiple entries.

**Rule of thumb:** Each entry should be answerable independently. If fixing one doesn't resolve the other, they're separate entries.

### Step 3: Run the append command
For each question, run:
```bash
cd <project-root> && python scripts/qa_tool.py append --category "<Category>" --question "<One-line question>"
```

**Replace `<project-root>` with the actual path to the project directory.**

### Step 4: Record the ID
The output will be `Created Q-NNN`. Record this ID for later use by `qa-log-fill-solution`.

## Categories

| Category | Use when |
|----------|----------|
| Bug Fix | Debugging, error fixes, unexpected behavior |
| Feature | New functionality, additions |
| Architecture | System design, module structure, patterns |
| Refactoring | Code cleanup, optimization, no behavior change |
| Performance | Speed, memory, resource optimization |
| Config/Setup | Build, deploy, environment, dependencies |
| Understanding | Explanations, how-code-works, learning |
| Other | Anything that doesn't fit above |

## Example

User says: "修复保存按钮点击无响应的问题"

```bash
cd /path/to/project && python scripts/qa_tool.py append --category "Bug Fix" --question "保存按钮点击无响应"
```

Output:
```
Created Q-005
```

## Output Format

```
Created Q-NNN
```

Record the Q-ID for Phase 3.
