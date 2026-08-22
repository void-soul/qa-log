# qa.db Schema and Entry Format

v3.0 起数据源从 `QA.md`（Markdown）迁移为 `qa.db`（SQLite 单文件数据库）。

## 文件位置

`qa.db` 位于**使用此 skill 的项目根目录**（脚本默认读写 `./qa.db`），不在 skill 目录内。

## 表结构

```sql
CREATE TABLE IF NOT EXISTS qa_entries (
    qid         TEXT PRIMARY KEY,          -- e.g. Q-0001 (唯一标识+排序键，4 位零填充)
    date        TEXT NOT NULL,             -- YYYY-MM-DD
    category    TEXT NOT NULL,             -- Bug Fix / Feature / ...
    status      TEXT NOT NULL DEFAULT 'Pending',
    phenomenon  TEXT NOT NULL,             -- 现象/需求
    root_cause  TEXT DEFAULT '',           -- 根因
    solution    TEXT DEFAULT '',           -- 解决方案
    files       TEXT DEFAULT '',           -- 涉及文件 (markdown table)
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT                       -- 最后修改时间
);
```

由 `scripts/qa_tool.py setup` 自动创建（幂等，已存在则跳过）。

## Entry 渲染格式

`qa_tool.py get <ID>` 以如下 markdown 风格渲染单条记录：

```markdown
## Q-NNNN | YYYY-MM-DD | Category | Status

**现象/需求:** [Restated problem or requirement]

**根因:** [Why the bug occurred — with identifiers]

**解决方案:**
1. [Step 1 — what was done, with specific names and values]
2. [Step 2 — what was done, with specific names and values]

**涉及文件:**
| File | Change |
|------|--------|
| path/to/file.ext | What was changed: method/property value |
```

### Formatting Rules

1. **Ordered lists** for solution steps — use `1.`, `2.`, `3.` format
2. **Bold** around file identifiers: **BlotEyes.Player/MainWindow.xaml**（不用反引号）
3. **Bold** around property/method/values: **Width**, **250 → 340**, **InitializeComponent()**
4. **Table format** for files — never a flat list
5. **No placeholders** when content exists

### Field Descriptions

| Field | Description |
|-------|-------------|
| `qid` / `Q-NNNN` | Incrementing ID, zero-padded to 4 digits |
| `date` / `YYYY-MM-DD` | Date the question was asked |
| `category` | From the Categories table in SKILL.md |
| **现象/需求** (`phenomenon`) | The problem or requirement — restated in organized form |
| **根因** (`root_cause`) | Why the bug occurred — trace the code path, use identifiers |
| **解决方案** (`solution`) | Ordered list of steps taken, with specific names and values |
| **涉及文件** (`files`) | Table with file path and what was changed in each file |

## Complete Example (Real-World)

```markdown
## Q-0039 | 2026-01-15 | Bug Fix | 已验证

**现象/需求:** 播放端左侧工具栏宽度与录制端不一致，播放端视频预览区域被压缩

**根因:** 播放端和录制端是两个独立项目，初始开发时分别设置了不同的左栏宽度（播放端 **250**，录制端 **340**），导致界面元素对齐不一致

**解决方案:**
1. 在 **BlotEyes.Player/MainWindow.xaml** 中定位左侧面板的 **ColumnDefinition**
2. 将主网格左列 **Width="250"** 改为 **Width="340"**
3. 将非客户端区标题列 **Width="250"** 改为 **Width="340"**
4. 与录制端 **BlotEyes.Recorder/MainWindow.xaml** 的左栏宽度对齐

**涉及文件:**
| File | Change |
|------|--------|
| **BlotEyes.Player/MainWindow.xaml** | 左栏 **ColumnDefinition** **Width="250"** → **"340"**（两处：主网格左列 + 非客户端区标题列） |
```

## What NOT to do (Bad Example — Too Vague)

```markdown
## Q-0039 | 2026-01-15 | Bug Fix | 已验证

**现象/需求:** 播放端左侧工具栏宽度与录制端不一致

**根因:** 两个项目宽度设置不同

**解决方案:** 改了宽度

**涉及文件:** BlotEyes.Player/MainWindow.xaml
```

**What's wrong:**
- 根因 too vague — doesn't specify which property or value caused the issue
- 解决方案 is NOT an ordered list, no specific values, no method/property names
- 涉及文件 is NOT a table, no Change column, no bold identifiers

## Files Table Guidelines

- **One row per file** — list every file that was modified
- **Change column** — briefly state what was changed in this file, with identifiers
- File paths in **bold**
- If many files share the same change pattern, list each separately for clarity
- For discussion-only entries, use N/A row
