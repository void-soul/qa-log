---
name: qa-log-fill-solution
description: "Fill in the solution for a QA entry (Phase 3). Use after solving a problem to record root cause, solution steps, and modified files in qa.db."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, logging, documentation, context, programming]
    related_skills: [qa-log, qa-log-add-question, qa-log-format-doc]
---

# Fill QA Solution Entry

Phase 3 of the qa-log workflow. Records the solution into an existing QA entry in `qa.db`.

> **规则**：状态机、编码（中文走 `--json`）、授权等统一遵循 [`references/qa-rules.md`](../references/qa-rules.md)。本阶段只设 `已解决待验证`，**不提交**。

> **v2.0**：数据源由 `QA.md` 改为 `qa.db`（SQLite），位于**项目根目录**。运行脚本前先 `cd <project-root>`。

## When to Use

- After solving a problem (Phase 2 complete)
- When Agent-2 needs to check Agent-1's work against a known QA entry

## What to Do

Use the `terminal` tool to run the following commands:

### Step 1: Get the Q-ID
You need the Q-ID from Phase 1 (e.g., `Q-0005`). If unknown, run:
```bash
cd <project-root> && python scripts/qa_tool.py summary
```

### Step 2: Run the update command

**含中文的字段必须用 Python `subprocess` + bare `--json`（stdin）传递，绝不能放命令行参数或 PowerShell 管道里**（编码规则见 [`references/qa-rules.md`](../references/qa-rules.md) 第 3 节）：

```python
import json, subprocess
payload = json.dumps({
    "status": "已解决待验证",
    "root_cause": "<根因>",
    "solution": "<解决方案>",
    "files": "<文件表>",
}, ensure_ascii=False)
subprocess.run(["python", "scripts/qa_tool.py", "update", "<ID>", "--json"],
               input=payload, encoding="utf-8")
```

**Replace placeholders:**
- `<project-root>`: actual path to project directory
- `<ID>`: Q-ID like `Q-0005`
- `<root cause>`: explanation of why the bug occurred, with **bold** around identifiers
- `<solution steps>`: ordered list of steps taken (1. 2. 3.)
- `<files table>`: Markdown table of changed files

> 本阶段设 `已解决待验证`（不设 `已验证`，不提交——提交见 check/batch-commit，需授权）。格式规范（粗体引用、有序列表、文件表格）详见 `qa-log/skills/format-doc`。

## Example

```python
import json, subprocess
payload = json.dumps({
    "status": "已解决待验证",
    "root_cause": "播放端和录制端是两个独立项目，初始开发时分别设置了不同的左栏宽度（播放端 **250**，录制端 **340**）",
    "solution": "1. 在 **BlotEyes.Player/MainWindow.xaml** 中定位左侧面板的 **ColumnDefinition**\n2. 将主网格左列 **Width=250** 改为 **Width=340**\n3. 与录制端对齐",
    "files": "| File | Change |\n|------|--------|\n| **BlotEyes.Player/MainWindow.xaml** | 左栏 **ColumnDefinition** **Width** 250 -> 340（两处） |",
}, ensure_ascii=False)
subprocess.run(["python", "scripts/qa_tool.py", "update", "Q-0005", "--json"],
               input=payload, encoding="utf-8")
```

Output:
```
Updated Q-0005
```

## Output Format

```
Updated Q-NNNN
```
