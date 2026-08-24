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
**如果根因/解决方案/涉及文件含中文，必须用 `--json` 传递，禁止用 `-r/-a/-f` 直接传中文**（Windows 命令行 ANSI/GBK 编码会导致乱码）：

```bash
cd <project-root> && python scripts/qa_tool.py update <ID> --json '{"status":"已解决待验证","root_cause":"<根因>","solution":"<解决方案>","files":"<文件表>"}'
```

> ⚠️ **编码规则（强制）**：含中文的字段一律走 `--json`（UTF-8）传递，**绝不要**用 `-r/-a/-f "中文"` 形式把中文直接放命令行参数里。用 Python 脚本调用时，用 `json.dumps({...}, ensure_ascii=False)` 生成 JSON 字符串再传给 `--json`，确保 UTF-8。

**Replace placeholders:**
- `<project-root>`: actual path to project directory
- `<ID>`: Q-ID like `Q-0005`
- `<root cause>`: explanation of why the bug occurred, with **bold** around identifiers
- `<solution steps>`: ordered list of steps taken (1. 2. 3.)
- `<files table>`: Markdown table of changed files

> **多行内容提示**：JSON 中多行文本用 `\n` 转义；`--json` 也支持通过 stdin 管道传入（`python qa_tool.py update <ID> --json < file.json`）。

## Format Rules (CRITICAL)

- **Root cause**: explain WHY, trace code path, use **bold** for identifiers like **Width**, **InitializeComponent()**
- **Solution**: ordered list (`1.`, `2.`, `3.`), one action per step, wrap all identifiers in **bold**
- **Files**: Markdown table format:
  ```
  | File | Change |
  |------|--------|
  | **path/to/file.ext** | What was changed: **method/property** value |
  ```

## Windows/Git Bash Note（编码规则）

**在 Windows 上，中文内容绝不要直接放命令行参数里**（`-r/-a/-f/-q/-s`），会因 ANSI/GBK 代码页产生乱码。一律用 `--json` 传递：

```bash
# 正确 — 用 --json 传所有含中文的字段（UTF-8，无乱码）
cd /path/to/project && python scripts/qa_tool.py update Q-0005 --json '{"status":"已解决待验证","root_cause":"**Width** 属性设置错误","solution":"1. 修改 **app.py** 中 **Width** 为 340","files":"| File | Change |\n|------|--------|\n| **app.py** | **Width** 250 -> 340 |"}'

# 错误 — 命令行直接传中文，Windows 下会乱码
python scripts/qa_tool.py update Q-0005 -r "**Width** 属性设置错误"
```

**推荐做法**：用 Python 脚本调用并传 JSON，彻底规避命令行编码：
```python
import json, subprocess
payload = json.dumps({
    "status": "已解决待验证",
    "root_cause": "**Width** 属性设置错误",
    "solution": "1. 修改 **app.py** 中 **Width** 为 340",
    "files": "| File | Change |\n|------|--------|\n| **app.py** | **Width** 250 -> 340 |",
}, ensure_ascii=False)
subprocess.run(["python", "scripts/qa_tool.py", "update", "Q-0005", "--json", payload])
```

## 提交说明生成（Commit Message）

提交时应使用描述性commit message，而非仅关联QA编号。**Commit message 一律使用英文**。

```bash
# 方式1: 使用 gen_commit_msg.py 脚本（description 用英文）
echo '{"id":"Q-0001","description":"Fix save button not responding","type":"fix"}' | python scripts/gen_commit_msg.py
# 输出: fix: #Q-0001 Fix save button not responding

# 方式2: 手动构建（英文）
git commit -m "fix: #Q-0001 Fix save button not responding"
```

**提交规则：**
- **必须包含QA ID**（如 `#Q-0001`）作为追溯标记
- **Commit message 使用英文**描述具体修复/改动内容（不要在 commit 里写中文）
- **必须有描述性文字**说明具体修复了什么
- **分批次提交**：不同功能点分多个commit，不要一次性提交所有改动
- **使用Python脚本生成**避免命令行编码问题

## Status Values（MANDATORY 状态机）

`status` 字段**只允许** 5 个值，**不存在"已解决"这个状态**。填写解决方案后，**必须设为 `已解决待验证`**：

| Status | Meaning |
|--------|---------|
| `Pending` | 待解决 — Question logged, not yet solved (default) |
| `已解决待验证` | 已解决待验证 — Solution recorded, awaiting verification（**本阶段填完方案后设置**） |
| `已验证` | 已验证 — Verified correct by reviewer（**仅 check 审核确认后设置**，本阶段不要设） |
| `WontFix` | 决定不修复 |
| `Unresolved` | 无法解决 |

> ⚠️ **错误示例（禁止）**：`--status "已解决"` → 会被脚本拒绝。正确应为 `"已解决待验证"`。

## Example

```bash
cd /path/to/project && python scripts/qa_tool.py update Q-0005 --json '{"status":"已解决待验证","root_cause":"播放端和录制端是两个独立项目，初始开发时分别设置了不同的左栏宽度（播放端 **250**，录制端 **340**）","solution":"1. 在 **BlotEyes.Player/MainWindow.xaml** 中定位左侧面板的 **ColumnDefinition**\n2. 将主网格左列 **Width=250** 改为 **Width=340**\n3. 与录制端对齐","files":"| File | Change |\n|------|--------|\n| **BlotEyes.Player/MainWindow.xaml** | 左栏 **ColumnDefinition** **Width** 250 -> 340（两处） |"}'
```

Output:
```
Updated Q-0005
```

## Output Format

```
Updated Q-NNNN
```
