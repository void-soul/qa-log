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

---

## 5. 记忆写入纪律（P1 闸门）

`qa_entries` 是长期记忆，写入质量比写入数量重要。所有写入通道（`qa_tool.py append/update`、插件 `qa_query.py qa-update`、`qa_md_sync.py sync`）都会经过 `scripts/memory_guard.py`。

### 5.1 硬约束（违反即被拒，exit 3）

- **不得写入占位内容**：`待填写` / `无` / `N/A` / `test` 等，现象/需求必须写清具体问题
- **现象/需求不得过短**（< 8 字符），不得整段重复表述（去重后有效内容 < 40 字判为噪声）
- **不得超长**：现象 4KB / 根因 8KB / 方案 16KB / 涉及文件 8KB——**不贴大段原始日志**，只写结论
- **不得重复记忆**：与既有条目相似度 ≥ 0.82（同类别或涉及相同文件）时拒绝，应改为 `update` 已有条目
- **状态只能是**状态机 5 值（见第 1 节），非法值一律拒绝

### 5.2 粒度约束：一条只讲一件事

命中以下任一信号会**警告并给出拆分草案**（`split_signal`），超出硬阈值则拒绝写入：

- 方案编号步骤 > 6 项
- 涉及文件表 > 5 行（> 12 行硬拒）
- 跨模块 > 3 个（按路径首段）
- 现象含 ≥ 3 个独立编号项且长度 > 300 字符

处理方式：

```bash
python <skill-path>/scripts/qa_tool.py split Q-0012            # 打印拆分草案（不写库）
python <skill-path>/scripts/qa_tool.py split Q-0012 --apply    # 确认后建子条目（写 parent_qid）
```

拆分后：父条目只留总览 + 子条目索引，细节下沉到子条目；子条目的根因/方案需**分别补齐**。

### 5.3 写入节奏与内容取舍

- **一次会话新增记忆上限默认 3 条**，超出需用户明确同意
- **禁止写入**：临时排错过程、被推翻的尝试、与本条无关的闲聊、重复表述
- **30 秒复用检验**：每条记忆必须能回答"未来的我遇到什么场景会需要它"，答不出就不写
- **批量写入默认 dry-run**，`--yes` / `--force` 才落库

### 5.4 例外与工具

- `qa_tool.py guard [ID] [--json]`：干跑校验，不落库；exit 0=ok / 1=warn / 3=reject
- `--force`：闸门 reject 时强制写入（仅在能说清理由时使用）
- `qa_md_sync.py sync`：QA.md 常含人工批量整理内容，默认**报告并放行**（不合规清单照常打印），加 `--strict` 才阻断
- 阈值集中在 `memory_guard.py` 顶部常量，需调整时改那里，不要在调用方绕过

### 5.5 审计与溯源（P2）

任何写操作都会在 `qa_events` 留痕：`append` / `update` / `verify`（状态首次进入「已验证」）/ `split` / `delete` / `guard_bypass`（QA.md 同步放行不合规条目）。条目间关系记在 `qa_links`（`derived_from` / `duplicates` / `supersedes` / `contradicts` / `relates_to`）。

- **删除也必须留痕**：先写 `delete` 事件再执行删除，`qa_events` 无外键，条目消失后流水仍在
- 查询审计：`python <skill-path>/scripts/qa_tool.py history Q-0003`
- 审计表只增不删；任何"清理历史"的诉求都要先经用户确认

### 5.6 召回与巩固（P3）

- **统一入口**：`python <skill-path>/scripts/qa_tool.py recall "<查询词>"`（加权：现象×3 / 根因×2 / 文件×2 / 方案×1 + 重要性 + 召回次数 + 新鲜度 + 关系引用）；`recall --qid Q-0003` 用于"找相似记忆"
- **召回即反馈**：命中会回写 `access_count` / `last_access_at` 并记 `recall` 事件——**常用条目权重会自然升高**；只想查不想改数据时加 `--no-feedback`
- 归档条目默认不参与召回，`--include-archived` 才可见（**永不删除**）
- **巩固**：`qa_tool.py consolidate` 默认只出建议（近似条目对 + Pattern 候选组）；`--apply` 才执行，且**只归档不删除**（被并入方 `archived=1` + `supersedes` 关系 + `merge` 事件）
- 短查询（≤4 字符）走"包含"判断，长查询走 3-gram 相似度——两者都零依赖

### 5.7 遗忘与冲突（P4）

- **衰减归档**：qa_tool.py prune 只给建议（终态 WontFix/Unresolved 且几乎未被召回，或已解决待验证挂起超 180 天且冷）；--apply 才归档，--restore 可恢复。**只置 archived=1，永不删除**，归档条目默认不参与召回（recall --include-archived 可见）
- **冲突检测**：qa_tool.py conflicts 检出「现象相似但根因/方案分歧」的条目（阈值 0.35，实测同问题中文短文本 0.39~0.67、不同问题约 0.0）；--link 才写 contradicts 关系并把双方标记 needs_review
- **健康报告**：qa_tool.py health（--json 供扩展面板消费）汇总状态分布/待验证积压/孤立条目/近似重复对/冲突/近 7 天趋势
- 这三个动作**默认全是 dry-run**，落库前需用户确认；归档与合并都可逆
