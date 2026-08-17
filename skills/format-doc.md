---
name: qa-log-format-doc
description: "Validate and reformat QA.md to ensure consistent structure and proper Markdown preview rendering."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, formatting, documentation, consistency]
    related_skills: [qa-log, qa-log-add-question, qa-log-fill-solution]
---

# Format QA Document

Validates and rewrites QA.md entries to ensure consistent structure and proper Markdown rendering.

## When to Use

- QA.md preview is broken or messy in the IDE/editor
- After multiple agents have edited QA.md and structure is inconsistent
- Periodic cleanup pass on the QA log
- **Mandatory after checking a QA entry** (Step 7 of qa-log-check)

## What to Do

Use the `terminal` tool:

### Step 1: Navigate to project root
Find the directory containing `QA.md`.

### Step 2: Run the formatter
```bash
cd <project-root> && python scripts/qa_tool.py format
```

### Step 3: Verify output
- If valid: `Formatted N entries`
- If issues: Lists each issue found

### Step 4: Fix issues if any
If the formatter reports issues, manually edit QA.md to fix them.

## What It Fixes

- Missing blank lines between sections
- Inconsistent formatting around identifiers
- Malformed tables in 涉及文件 section
- Mixed newline styles (CRLF vs LF)
- Trailing whitespace and inconsistent spacing

## Format Requirements (MANDATORY)

### 1. 引用格式：使用 **粗体**，不用反引号

**错误：**
```markdown
修改了 `app.py` 中的 `Width` 属性
```

**正确：**
```markdown
修改了 **app.py** 中的 **Width** 属性
```

### 2. 解决方案：有序列表

**必须使用 `1. 2. 3.` 格式：**
```markdown
**解决方案:**
1. 修改 **app.py** 中的 **Width** 属性为 340
2. 更新 **MainWindow.xaml** 中的列宽设置
3. 重新编译并测试
```

### 3. 涉及文件：正确表格

**必须使用 Markdown 表格：**
```markdown
**涉及文件:**
| File | Change |
|------|--------|
| **app.py** | 修改 **Width** 属性从 250 到 340 |
| **MainWindow.xaml** | 更新列宽设置 |
```

### 4. 条目分隔

**每个条目后必须有 `---` 分隔线：**
```markdown
## Q-001 | 2024-01-15 | Bug Fix | 已验证

**现象/需求:** ...
**根因:** ...
**解决方案:** ...
**涉及文件:** ...

---

## Q-002 | 2024-01-15 | Bug Fix | Pending
...
```

## Manual Format Check

Verify each entry has:
- Blank line after header line
- Blank line after each bold field label
- Ordered list for solution steps (1. 2. 3.)
- Table format for files (never flat list)
- `---` separator after each entry
- **Bold** for code/file references (not backticks)

## Example

```bash
cd /path/to/project && python scripts/qa_tool.py format
```

Output:
```
Formatted 15 entries — all valid
```

Or if issues found:
```
Found 2 issue(s):
  - Q-005: Header format issue
  - Q-012: Invalid status 'OLD_STATUS'
```
