---
name: qa-log-check
description: "Check and verify a QA entry in qa.db. When user says '请检查Q-XXX', extract the entry, analyze the solution against the problem, and verify correctness."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [qa, verification, code-review, audit]
    related_skills: [qa-log, qa-log-add-question, qa-log-fill-solution, qa-log-format-doc]
---

# QA Check Entry

当用户说 "请检查Q-XXX" 或类似请求时，从 `qa.db` 提取QA条目并进行彻底的代码审查，验证解决方案是否真正解决问题且没有引入新问题。**检查完成后必须运行 `format` 校验条目结构**。

> **v2.0**：数据源由 `QA.md` 改为 `qa.db`（SQLite），位于**项目根目录**。运行脚本前先 `cd <project-root>`。

## What to Do

Use the `terminal` tool for all commands below.

### Step 1: Extract the Entry
```bash
cd <project-root> && python scripts/qa_tool.py get <ID>
```

Record the full entry content for analysis.

### Step 2: Analyze the Problem
From the entry, identify:
- **现象/需求**: What was the observed problem or requirement?
- **根因**: What was identified as the root cause?

Write down the expected behavior: what should happen if the fix is correct.

### Step 3: Analyze the Solution
From the entry, identify:
- **解决方案**: What steps were taken?
- **涉及文件**: Which files were modified?

### Step 4: Verify the Fix (MANDATORY)
**Read the actual source code** in each affected file. Do NOT assume the solution is correct based on the QA entry alone.

Use the `read_file` or `terminal` tool to read the files listed in 涉及文件.

Check:
1. **Does the fix address the root cause?**
   - Trace the code path mentioned in 根因
   - Verify the changed code now handles the problematic condition correctly

2. **Does the fix achieve the expected behavior?**
   - If it was a bug: verify the bug no longer occurs
   - If it was a feature: verify the feature works as described

3. **Are there any new issues introduced?**
   - Check for regressions in related code
   - Verify no edge cases are broken
   - Check for syntax errors, logical errors, or resource leaks

### Step 5: Make a Decision

| Result | Action |
|--------|--------|
| Fix is correct and complete | Update status to `已验证` |
| Fix has issues but can be improved | Keep `已解决待验证`, provide feedback |
| Fix is wrong or incomplete | Update status to `Pending`, explain why |

### Step 6: Update the QA Entry

Use the `terminal` tool:

```bash
# If verified correct
cd <project-root> && python scripts/qa_tool.py update <ID> --status "已验证"

# If issues found - provide detailed feedback
cd <project-root> && python scripts/qa_tool.py update <ID> --status "已解决待验证" --answer "Revised solution: ..."

# If fix is wrong - reopen
cd <project-root> && python scripts/qa_tool.py update <ID> --status "Pending"
```

### Step 7: Format QA Entry (MANDATORY)

**必须校验 qa.db 条目结构**，确保：
- 引用代码、文件的地方使用 **粗体** 包裹（不是反引号）
- 多步骤解决方案使用有序列表 `1. 2. 3.`
- 表格格式正确（`涉及文件` 部分）
- 状态值合法（`Pending` / `已解决待验证` / `已验证` / `WontFix` / `Unresolved`）

```bash
cd <project-root> && python scripts/qa_tool.py format
```

**如果校验发现问题，必须通过 `qa_tool.py update` 修复对应条目**。

### Step 8: Ask for Commit (CRITICAL)

**When verified correct**, you MUST ask the user before committing:

```
检查通过！涉及以下文件：
- **app.py**
- **MainWindow.xaml**

是否提交这些更改？(是/否)
```

**等待用户回复。** 只有用户明确说"是"、"提交"、"确认"时才能继续。

### Step 9: Commit (Only if user confirms)

If user confirms, use the `terminal` tool:

```bash
cd <project-root>
git diff --name-only
git add <files from QA entry>
git commit -m "<type>: #Q-XXX <description>"
git push (if needed)
```

**提交信息格式（强制）：**

| 类型 | 格式 | 示例 |
|------|------|------|
| Bug 修复 | `fix: #Q-XXX <描述>` | `fix: #Q-029 修复保存按钮无响应` |
| 新功能 | `feat: #Q-XXX <描述>` | `feat: #Q-030 添加导出功能` |
| 重构 | `refactor: #Q-XXX <描述>` | `refactor: #Q-031 拆分上帝文件` |
| 测试 | `test: #Q-XXX <描述>` | `test: #Q-032 添加单元测试` |

**规则：**
- **必须包含 QA ID**（如 `#Q-029`）
- 只提交 QA 条目中列出的文件
- 永远不要自动提交 — 必须先询问用户

## QA 格式规范（CRITICAL）

### 代码/文件引用格式

**错误示例（使用反引号）：**
```markdown
修改了 **app.py** 中的 `Width` 属性
```

**正确示例（使用粗体）：**
```markdown
修改了 **app.py** 中的 **Width** 属性
```

### 解决方案格式

**多步骤必须使用有序列表：**
```markdown
**解决方案:**
1. 修改 **app.py** 中的 **Width** 属性为 340
2. 更新 **MainWindow.xaml** 中的列宽设置
3. 重新编译并测试
```

### 涉及文件表格格式

**必须使用正确的 Markdown 表格：**
```markdown
**涉及文件:**
| File | Change |
|------|--------|
| **app.py** | 修改 **Width** 属性从 250 到 340 |
| **MainWindow.xaml** | 更新列宽设置 |
```

### 多条目格式

**条目之间必须有分隔线：**
```markdown
## Q-001 | 2024-01-15 | Bug Fix | 已验证

**现象/需求:** ...
**根因:** ...
**解决方案:** ...
**涉及文件:** ...

---

## Q-002 | 2024-01-15 | Bug Fix | Pending

**现象/需求:** ...
...
```

## Verification Checklist

- [ ] Extracted entry using `get <ID>`
- [ ] Read actual source files in 涉及文件
- [ ] Traced the code path from 根因 to verify the fix
- [ ] Checked that expected behavior from 现象/需求 is achieved
- [ ] Verified no regressions in related code
- [ ] Confirmed no new bugs introduced
- [ ] Status updated correctly
- [ ] **Formatted QA document**
- [ ] **Code/file references use **bold** (not backticks)**
- [ ] **Solution uses ordered list 1. 2. 3.**
- [ ] **Table format is correct**
- [ ] **Asked user for commit confirmation**
- [ ] **Committed with QA ID in message (#Q-XXX)**
- [ ] **Only committed after user explicitly confirmed**

## Output Format

After checking, report:

```
## 检查报告: Q-XXX

### 问题分析
[分析现象/需求和根因]

### 解决方案分析
[分析解决方案和涉及文件]

### 代码审查结果
[详细说明代码审查发现]

### 结论
[已验证 / 需要修改 / 重新打开]

### 建议
[如有问题，提供具体修改建议]
```

## Example

User says: "请检查Q-029"

```bash
# Step 1: Extract entry
cd /path/to/project && python scripts/qa_tool.py get Q-029

# Step 4: Read actual code
read_file(path="/path/to/project/src/some_file.py")

# Step 6: Update if verified
cd /path/to/project && python scripts/qa_tool.py update Q-029 --status "已验证"

# Step 7: Format document
cd /path/to/project && python scripts/qa_tool.py format

# Step 8: Ask for commit
# 输出: "检查通过！涉及以下文件：- **app.py** 是否提交？(是/否)"
# 等待用户回复...

# Step 9: Commit only if user says yes
cd /path/to/project && git add app.py && git commit -m "fix: #Q-029 修复保存按钮无响应"
```
