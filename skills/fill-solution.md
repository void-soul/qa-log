---
name: qa-log-fill-solution
description: "Fill in the solution for a QA entry (Phase 3). Use after solving a problem to record root cause, solution steps, and modified files."
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, logging, documentation, context, programming]
    related_skills: [qa-log, qa-log-add-question, qa-log-format-doc]
---

# Fill QA Solution Entry

Phase 3 of the qa-log workflow. Records the solution into an existing QA entry.

## When to Use

- After solving a problem (Phase 2 complete)
- When Agent-2 needs to check Agent-1's work against a known QA entry

## What to Do

Use the `terminal` tool to run the following commands:

### Step 1: Get the Q-ID
You need the Q-ID from Phase 1 (e.g., `Q-005`). If unknown, run:
```bash
cd <project-root> && python scripts/qa_tool.py summary
```

### Step 2: Run the update command
```bash
cd <project-root> && python scripts/qa_tool.py update <ID> --status "已解决待验证" --root-cause "<root cause>" --answer "<solution steps>" --files "<files table>"
```

**Replace placeholders:**
- `<project-root>`: actual path to project directory
- `<ID>`: Q-ID like `Q-005`
- `<root cause>`: explanation of why the bug occurred, with **bold** around identifiers
- `<solution steps>`: ordered list of steps taken (1. 2. 3.)
- `<files table>`: Markdown table of changed files

## Format Rules (CRITICAL)

- **Root cause**: explain WHY, trace code path, use **bold** for identifiers like **Width**, **InitializeComponent()**
- **Solution**: ordered list (`1.`, `2.`, `3.`), one action per step, wrap all identifiers in **bold**
- **Files**: Markdown table format:
  ```
  | File | Change |
  |------|--------|
  | **path/to/file.ext** | What was changed: **method/property** value |
  ```

## Windows/Git Bash Note

Use **single quotes** around parameter values containing backticks. Double quotes will strip them:

```bash
# Correct — single quotes preserve backticks
cd /path/to/project && python scripts/qa_tool.py update Q-005 -s "已解决待验证" -r '**Width** 属性设置错误' -a '1. 修改 **app.py** 中 **Width** 为 340' -f '| File | Change |\n|------|--------|\n| **app.py** | **Width** 250 -> 340 |'

# Wrong — double quotes eat backticks
python scripts/qa_tool.py update Q-005 -s "已解决待验证" -r "**Width** property"
```

## 提交说明生成（Commit Message）

提交时应使用描述性commit message，而非仅关联QA编号：

```bash
# 方式1: 使用 gen_commit_msg.py 脚本
echo '{"id":"Q-001","description":"修复保存按钮无响应","type":"fix"}' | python scripts/gen_commit_msg.py
# 输出: fix: #Q-001 修复保存按钮无响应

# 方式2: 手动构建（确保UTF-8）
git commit -m "fix: #Q-001 修复保存按钮点击无响应问题"
```

**提交规则：**
- **必须包含QA ID**（如 `#Q-001`）作为追溯标记
- **必须有描述性文字**说明具体修复了什么
- **分批次提交**：不同功能点分多个commit，不要一次性提交所有改动
- **使用Python脚本生成**避免命令行编码问题

## Status Values

| Status | Meaning |
|--------|---------|
| `Pending` | 待解决 — Question logged, not yet solved (default) |
| `已解决待验证` | 已解决待验证 — Solution recorded, awaiting verification |
| `已验证` | 已验证 — Verified correct by reviewer |

## Example

```bash
cd /path/to/project && python scripts/qa_tool.py update Q-005 -s "已解决待验证" -r '播放端和录制端是两个独立项目，初始开发时分别设置了不同的左栏宽度（播放端 **250**，录制端 **340**）' -a '1. 在 **BlotEyes.Player/MainWindow.xaml** 中定位左侧面板的 **ColumnDefinition**\n2. 将主网格左列 **Width="250"** 改为 **Width="340"**\n3. 将非客户端区标题列 **Width="250"** 改为 **Width="340"**\n4. 与录制端对齐' -f '| File | Change |\n|------|--------|\n| **BlotEyes.Player/MainWindow.xaml** | 左栏 **ColumnDefinition** **Width** 250 -> 340（两处） |'
```

Output:
```
Updated Q-005
```

## Output Format

```
Updated Q-NNN
```
