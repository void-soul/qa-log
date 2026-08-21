---
name: qa-log-format-doc
description: "Validate qa.db entries to ensure consistent structure. Use the qa_tool.py format subcommand to check status values, required fields, and files table format."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, formatting, documentation, consistency]
    related_skills: [qa-log, qa-log-add-question, qa-log-fill-solution]
---

# Format QA Document

校验 `qa.db` 中条目结构的一致性与合法性。

> **v2.0**：数据源由 `QA.md` 改为 `qa.db`（SQLite），位于**项目根目录**。运行脚本前先 `cd <project-root>`。

## When to Use

- qa.db 条目结构不一致或疑似损坏
- 多个 agent 编辑过 qa.db，需要一致性检查
- 定期清理 QA 记录
- **检查一个 QA 条目后必须运行**（qa-log-check 的 Step 7）

## What to Do

Use the `terminal` tool:

### Step 1: Navigate to project root
项目根目录即存放 `qa.db` 的目录。

### Step 2: Run the validator
```bash
cd <project-root> && python scripts/qa_tool.py format
```

### Step 3: Verify output
- 若无问题：`Validated N entries — all valid`
- 若有问题：逐条列出 issue

### Step 4: Fix issues if any
若校验发现问题，通过 `qa_tool.py update <ID>` 修复对应条目（修正状态值、补全字段、修正表格格式）。

## What It Validates

- 状态值是否为合法集合：`Pending` / `已解决待验证` / `已验证` / `WontFix` / `Unresolved`
- `现象/需求`（phenomenon）是否为空
- `涉及文件`（files）是否为空，若存在是否以 `|` 开头的 markdown 表格

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

## Manual Format Check

每条记录应满足：
- 状态值合法
- `现象/需求` 非空
- 解决方案使用有序列表 `1. 2. 3.`
- `涉及文件` 使用表格（不为空时）
- 代码/文件引用使用 **粗体**（不用反引号）

## Example

```bash
cd /path/to/project && python scripts/qa_tool.py format
```

Output:
```
Validated 15 entries — all valid
```

Or if issues found:
```
Found 2 issue(s):
  - Q-005: Invalid status 'OLD_STATUS'
  - Q-012: phenomenon (现象/需求) is empty
```
