# QA Log

Cross-session context preservation for programming Q&A. Logs questions and solutions to `QA.md` in the project root, making every solved problem a searchable reference for future sessions.

## Features

- **Structured 4-section format**: Phenomenon/Requirement, Root Cause, Solution, Files Changed
- **Multi-question decomposition**: Split one request into independent entries automatically
- **Token-efficient retrieval**: Scripts read/write entries without loading the entire file
- **Batch commit support**: Group changes by feature/domain before submitting

## Quick Start

```bash
# Log a new question
python scripts/qa_tool.py append --category "Bug Fix" --question "Save button not responding"

# List all entries
python scripts/qa_tool.py summary

# Get full entry
python scripts/qa_tool.py get Q-005

# Update with solution
python scripts/qa_tool.py update Q-005 \
  --status "已解决待验证" \
  --root-cause "Width property set incorrectly" \
  --answer "1. Modified Width in app.py\n2. Updated MainWindow.xaml" \
  --files "| File | Change |\n|------|--------|\n| **app.py** | **Width** 250 -> 340 |"
```

## CLI Reference

| Command | Args | Description |
|---------|------|-------------|
| `summary` | — | List all entries (ID + title) |
| `get <ID>` | `ID` (e.g., `Q-003` or `3`) | View full entry content |
| `append` | `-c/--category`, `-q/--question` | Add new entry (auto-increments ID) |
| `update <ID>` | `-q`, `-s`, `-r`, `-a`, `-f` | Update existing entry |
| `next-id` | — | Print next available ID |
| `format` | — | Validate and report QA.md structure issues |
| `search` | `query`, `-s/--status`, `-c/--category` | Search entries by keyword or filter |

### Update Fields

- `-q/--question`: Overwrites "Phenomenon/Requirement" field
- `-s/--status`: Status (`Pending` / `已解决待验证` / `已验证` / `WontFix` / `Unresolved`)
- `-r/--root-cause`: Root cause analysis
- `-a/--answer`: Solution steps
- `-f/--files`: Changed files table (`| File | Change |` format)

Literal `\n` in text args expands to real newlines; use `\n` to join multi-line content.

## Encoding (No Mojibake)

All scripts force UTF-8 output:
```python
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

On Windows, if using CLI directly, run `chcp 65001` first. Prefer Python invocation to avoid encoding issues.

## Sub-Skills

| Skill | Purpose |
|-------|---------|
| `qa-log/skills/add-question` | Phase 1: Log a new question |
| `qa-log/skills/fill-solution` | Phase 3: Fill in solution |
| `qa-log/skills/check` | Verify a QA entry against source code |
| `qa-log/skills/format-doc` | Validate and fix QA.md structure |
| `qa-log/skills/search` | Search historical QA entries |
| `qa-log/skills/batch-commit` | Batch commit by feature group |

## Entry Structure

```markdown
## Q-NNN | YYYY-MM-DD | Category | Status

**现象/需求:** [What was observed vs expected]

**根因:** [Why it happened, with `identifiers`]

**解决方案:**
1. Step one
2. Step two
3. Step three

**涉及文件:**
| File | Change |
|------|--------|
| `path/to/file.ext` | What changed: `method/property` value |

---
```

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

## Status Lifecycle

```
Pending ──solve──→ 已解决待验证 ──verify──→ 已验证
    │
    └──decide not to fix──→ WontFix
    │
    └──can't solve──→ Unresolved
```
