# QA Log — 权威规则（Single Source of Truth）

本文件是 qa-log skill 的**唯一权威规则源**。SKILL.md 与各子技能中的流程步骤均遵循本文件的规则；任何文档与本文件冲突时，**以本文件为准**。

---

## 1. 状态机（status 唯一合法值）

`qa_entries.status` 字段**只允许以下 5 个值**，不存在"已解决"等其它状态：

| 状态 | 含义 | 何时设置 | 谁设置 |
|------|------|---------|--------|
| `Pending` | 待解决 | 记录创建时（默认） | `append` 自动 |
| `已解决待验证` | 已解决，等待验证 | 解决问题、填写方案后 | agent（fill-solution） |
| `已验证` | 经验证正确 | 审核确认方案正确且无回归后 | agent（check，需授权） |
| `WontFix` | 决定不修复 | 问题判定不需要解决 | agent |
| `Unresolved` | 无法解决 | 尝试后仍无法解决 | agent |

### 状态流转
```
append ──► Pending ──► 已解决待验证 ──► 已验证
                        │  ▲
                        ▼  │
                      Pending（发现方案错误，重开）
```
`WontFix` / `Unresolved` 为终止态。

### `已解决` 等非规范值的处理（两处上下文，语义不同）

| 上下文 | 动作 | `已解决` 的结果 |
|--------|------|----------------|
| `qa_tool.py update -s` 输入 | 强校验 + 相近词提示 | **拒绝写入**，提示 `Did you mean '已验证'?` |
| `qa_md_sync.py sync` 解析 QA.md | 保守映射 | 映射为 **`已解决待验证`**（无法确认是否验证过） |

> 二者不冲突：`update` 是用户主动改状态的**输入提示**；`sync` 是从 QA.md 合并时的**保守兜底**。

### 脚本强校验
`qa_tool.py update` 传入不在 5 个合法值内的状态会被**拒绝**（`exit 2`）并提示相近词。合法值由 `db.py` / `qa_tool.py` / `qa_md_sync.py` 三处脚本共同保证。

---

## 2. 授权铁律（MANDATORY，最高优先级）

1. **禁止自动提交**——绝不未经用户明确允许就执行 `git commit`。
2. **每个 QA 记录，在"验证（设为 `已验证`）"和"提交"之前，必须先征得用户明确允许**（用户看到 diff + 状态变更说明后说"提交"/"确认"才算授权）。
3. 未获授权前，最多只做：记录、分析、标记 `已解决待验证`、展示 diff。**不得**设 `已验证`、不得 `git commit`。
4. **用户授权 = 用户看到变更内容后明确同意**，不是"进入某个流程"或"使用此技能"。
5. **绝不 `git push`**——除非用户另行单独明确授权。

---

## 3. 编码规则（中文防乱码）

**核心原则：中文内容绝不进命令行参数，也绝不走 PowerShell 文本管道。** 已实测确认的可靠/不可靠方式：

| 调用方式 | 可靠性 |
|---------|--------|
| 命令行直接传中文 `-q/-r/-a/-f/-s "中文"` | ❌ 乱码（GBK 破坏，如"相机"→"鐩告満"） |
| PowerShell 文本管道 `echo中文 \| python` | ❌ 中文变 `?` |
| **Python `subprocess` 传 stdin** | ✅ 100% 可靠 |
| **文件重定向 `python ... < file.json`** | ✅ 100% 可靠 |
| **bare `--json` + stdin（UTF-8）** | ✅ 100% 可靠 |

`qa_tool.py` 的 `append`/`update` 已支持 **bare `--json`**（不跟值，从 stdin 读 JSON），脚本已强制 UTF-8（`stdin/stdout/stderr` reconfigure + 剥离 BOM）。

### 可靠方式 A：Python subprocess（首选，最稳）
```python
import json, subprocess
payload = json.dumps({"category": "Bug Fix", "question": "中文现象"}, ensure_ascii=False)
subprocess.run(["python", "<skill>/scripts/qa_tool.py", "append", "--json"],
               input=payload, encoding="utf-8")
```

### 可靠方式 B：文件重定向（把 JSON 写 UTF-8 文件）
```bash
# 先写 UTF-8（无 BOM）JSON 文件，再重定向
python <skill>/scripts/qa_tool.py append --json < /tmp/payload.json
```

### 不可靠（禁止）：命令行/管道直接传中文
```bash
# ❌ 命令行参数里带中文 → 乱码
python qa_tool.py append -q "中文现象"

# ❌ PowerShell 文本管道 → 中文变 ?
echo '{"question":"中文"}' | python qa_tool.py append --json
```

- 命令行参数优先级高于 JSON 字段（两者都传时以命令行参数为准）。
- JSON 中多行文本用 `\n` 转义。

---

## 4. 提交规则

- **commit message 一律英文**（含任何非 ASCII 即非法），并包含 QA ID 追溯标记（如 `fix: #Q-0001 Fix save button not responding`）。
- **必须经 `gen_commit_msg.py` 脚本生成**（`python <skill-path>/scripts/gen_commit_msg.py`），禁止手写 `git commit -m`。
- 提交类型前缀：`fix` / `feat` / `refactor` / `test` / `docs` / `chore` / `perf` / `style`。
- **分批次提交**：不同功能点分多个 commit，不要一次性提交全部改动。
- **只 `git add` 审查过的文件**，绝不用 `git add -A`。
- 提交前**必须获得用户授权**（见第 2 节）。
