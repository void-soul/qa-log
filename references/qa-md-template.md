# QA.md Template and Entry Format

## New QA.md Template

When `QA.md` does not exist in the project root, create it with this content:

```markdown
# QA Log

编程问答记录，按时间倒序排列。

---

```

The `scripts/qa_tool.py` auto-creates this header on first `append`. No manual creation needed.

## Entry Format

Each entry follows this structure (blank lines between sections for readability):

```markdown
## Q-NNN | YYYY-MM-DD | Category | Status

**现象/需求:** [Restated problem or requirement]

**根因:** [Why the bug occurred — with `identifiers`]

**解决方案:**
1. [Step 1 — what was done, with specific `names` and `values`]
2. [Step 2 — what was done, with specific `names` and `values`]
3. [Step 3 — ...]

**涉及文件:**
| File | Change |
|------|--------|
| `path/to/file.ext` | What was changed: `method/property` value |
| `path/to/file2.ext` | What was changed: `method/property` value |

---
```

### Formatting Rules

1. **Ordered lists** for solution steps — use `1.`, `2.`, `3.` format
2. **Backticks** around file identifiers: `BlotEyes.Player/MainWindow.xaml`
3. **Backticks** around property/method/values: `Width`, `250 → 340`, `InitializeComponent()`
4. **Table format** for files — never a flat list
5. **No `—` placeholders** when content exists

### Field Descriptions

| Field | Description |
|-------|-------------|
| `Q-NNN` | Incrementing ID, zero-padded to 3 digits |
| `YYYY-MM-DD` | Date the question was asked |
| `Category` | From the Categories table in SKILL.md |
| **现象/需求** | The problem or requirement — restated in organized form |
| **根因** | Why the bug occurred — trace the code path, use `identifiers` |
| **解决方案** | Ordered list of steps taken, with specific `names` and `values` |
| **涉及文件** | Table with file path and what was changed in each file |

## Complete Example (Real-World)

Below is a full entry with the level of detail expected when logging a resolved issue:

```markdown
## Q-039 | 2024-01-15 | Bug Fix | Resolved

**现象/需求:** 播放端左侧工具栏宽度与录制端不一致，播放端视频预览区域被压缩

**根因:** 播放端和录制端是两个独立项目，初始开发时分别设置了不同的左栏宽度（播放端 `250`，录制端 `340`），导致界面元素对齐不一致

**解决方案:**
1. 在 `BlotEyes.Player/MainWindow.xaml` 中定位左侧面板的 `ColumnDefinition`
2. 将主网格左列 `Width="250"` 改为 `Width="340"`
3. 将非客户端区标题列 `Width="250"` 改为 `Width="340"`
4. 与录制端 `BlotEyes.Recorder/MainWindow.xaml` 的左栏宽度对齐

**涉及文件:**
| File | Change |
|------|--------|
| `BlotEyes.Player/MainWindow.xaml` | 左栏 `ColumnDefinition` `Width="250"` → `"340"`（两处：主网格左列 + 非客户端区标题列） |

---
```

## What NOT to do (Bad Example — Too Vague)

```markdown
## Q-039 | 2024-01-15 | Bug Fix | Resolved

**现象/需求:** 播放端左侧工具栏宽度与录制端不一致

**根因:** 两个项目宽度设置不同

**解决方案:** 改了宽度

**涉及文件:** BlotEyes.Player/MainWindow.xaml

---
```

**What's wrong:**
- 根因 too vague — doesn't specify which property or value caused the issue
- 解决方案 is NOT an ordered list, no specific values, no method/property names
- 涉及文件 is NOT a table, no Change column, no backtick identifiers

## Multi-File Feature Entry

```markdown
## Q-040 | 2024-01-16 | Feature | Resolved

**现象/需求:** 新增键盘快捷键用于相机源切换

**根因:** 当前只能通过 UI 按钮切换相机源，无快捷键支持

**解决方案:**
1. 在 `LangService.cs` 中添加 `Hotkey_Source_Toggle` 词条，值为"源切换"
2. 在 `HotkeySettingsDialog.cs` 中添加源切换键的 UI 绑定区域
3. 在 `HotkeyService.cs` 中注册 `Ctrl+Shift+S` 为默认快捷键
4. 重构 `HotkeyService` 支持 per-camera 快捷键注册

**涉及文件:**
| File | Change |
|------|--------|
| `BlotEyes.Lang/LangService.cs` | 添加 `Hotkey_Source_Toggle` 词条 |
| `BlotEyes.Hotkeys/HotkeySettingsDialog.cs` | 新增源切换键的 UI 绑定区域 |
| `BlotEyes.Hotkeys/HotkeyService.cs` | 支持 per-camera 快捷键注册 |

---
```

## Discussion-Only Entries

```markdown
## Q-041 | 2024-01-16 | Understanding | Resolved

**现象/需求:** 本项目中间件链的工作方式

**根因:** N/A（知识性问题）

**解决方案:**
1. 解释了 4-中间件管道：`auth` → `rate-limit` → `validate` → `handler`
2. 每个中间件调用 `next()` 传递到下一个

**涉及文件:**
| File | Change |
|------|--------|
| N/A | 纯讨论，无代码修改 |

---
```

## Files Table Guidelines

- **One row per file** — list every file that was modified
- **Change column** — briefly state what was changed in this file, with `identifiers`
- File paths wrapped in backticks
- If many files share the same change pattern, list each separately for clarity
- For discussion-only entries, use N/A row
