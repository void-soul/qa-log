---
name: qa-log/memory-ops
description: "记忆系统运维：召回 / 巩固 / 健康报告 / 衰减归档 / 冲突检测。五条命令默认全是 dry-run，--apply 才落库；归档永不删除（可 --restore）。加载本技能前先读 references/qa-rules.md 的授权铁律。"
---

# 记忆运维（recall / consolidate / health / prune / conflicts）

> **统一规则（必读）：** 状态机、授权铁律、中文编码、提交规范统一见
> [`references/qa-rules.md`](../references/qa-rules.md)。冲突时以该文件为准。
> 本技能只讲**流程步骤**。

## 何时加载

- 用户问「以前有没有解决过类似问题」「找一下历史记录」→ `recall`
- 用户说「库里可能有重复条目 / 整理一下」→ `consolidate`
- 用户说「记忆库健康吗 / 有没有积压」→ `health`
- 用户说「清理一下旧记录 / 归档」→ `prune`
- 用户说「这两条记录说法冲突」→ `conflicts`

**全部在项目根目录执行**（脚本默认读写 `./qa.db`）。

---

## 1. recall —— 加权召回

```bash
python <skill>/scripts/qa_tool.py recall "关键词" -n 5
python <skill>/scripts/qa_tool.py recall --qid Q-0031 -n 5   # 找与某条相似的记忆
python <skill>/scripts/search_qa.py "关键词" --no-feedback   # 只查不改
```

字段权重：现象 3.0 / 根因 2.0 / 文件 2.0 / 方案 1.0，另加重要性、召回次数、新鲜度、关系引用。

**副作用（必须告知用户）**：默认**会回写** `access_count` 与 `last_access_at`（召回反馈闭环），
并在 `qa_events` 记一条 `recall`。只想看不想改就加 `--no-feedback`。

常用过滤：`-s/--status`、`-c/--category`（模糊）、`--include-archived`。

---

## 2. consolidate —— 巩固（去重 + 模式提炼）

```bash
python <skill>/scripts/qa_tool.py consolidate                      # dry-run：只给建议
python <skill>/scripts/qa_tool.py consolidate --apply --yes        # 执行
python <skill>/scripts/qa_tool.py consolidate --threshold 0.8 --no-pattern
```

- 合并语义：**只归档丢弃方（`archived=1`），绝不删除**，并写 `supersedes` 关系。
- `--apply` 还会为「同 category + 同模块首段」的同构条目组（≥5 条、组内平均相似度 ≥0.45）
  提炼一条 `category=Pattern` 的抽象条目，以 `derived_from` 链接子条目；**子条目原样保留**。
- O(n²) 扫描，库大时较慢，先看 dry-run 输出再决定。

---

## 3. health —— 记忆健康报告

```bash
python <skill>/scripts/qa_tool.py health            # 人读
python <skill>/scripts/qa_tool.py health --json     # 机器读（VS Code 面板消费同一份）
```

输出：状态分布 / 积压（`stale_pending`）/ 孤立（`orphans`）/ 重复对 / 冲突 / 近 7 日新增与召回。
重复对与冲突是 O(n²) 扫描，已按库指纹缓存——库没变时重复调用不会重算。

---

## 4. prune —— 衰减归档（**永不删除**）

```bash
python <skill>/scripts/qa_tool.py prune                                  # dry-run：只给建议
python <skill>/scripts/qa_tool.py prune --apply --yes                    # 执行归档
python <skill>/scripts/qa_tool.py prune --restore Q-0031                 # 恢复
```

命中条件（两条同时满足才建议）：状态是终态（`WontFix` / `Unresolved`）**或**
`已解决待验证` 且超过 180 天，**且** `access_count <= 2`。

> **授权铁律：** 归档虽不删除，但会让条目退出默认召回视野。
> **必须先向用户展示 dry-run 清单并取得明确同意**，再执行 `--apply`；用户要求恢复时用 `--restore`。

---

## 5. conflicts —— 冲突检测

```bash
python <skill>/scripts/qa_tool.py conflicts            # dry-run
python <skill>/scripts/qa_tool.py conflicts --link     # 记 contradicts 关系 + 置 needs_review
```

判定：现象相似度 ≥ 0.35 但根因或方案相似度 ≤ 0.35。
`--link` 会给双方打 `needs_review=1`，之后 `health` 报告会一直列出，**需人工裁决后再用
`update` 修正其中一条**。

---

## 与写入闸门的关系

| 动作 | 是否过 `memory_guard` |
|------|----------------------|
| `recall`（带反馈） | 否（只更新热度计数） |
| `consolidate --apply` | 合并不闸门；Pattern 条目**要过闸门**，被拒则跳过并说明 |
| `prune --apply` | 否（只置 `archived=1`） |
| `conflicts --link` | 否（只写关系与标记） |
| `append` / `update` | **是**，reject 时 exit 3，`--force` 才放行（放行会记 `guard_bypass`） |