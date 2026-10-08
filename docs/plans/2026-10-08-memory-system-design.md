# QA Log 记忆系统演进设计

- 日期：2026-10-08
- 状态：**P1 / P2 已实现**（2026-10-08），P3 / P4 待做
  - P1：写入闸门 + 拆分 → `scripts/memory_guard.py`、`qa_tool.py guard/split`、`tests/test_memory_guard.py`（19 项通过）
  - P2：schema 扩展 + 审计流水 + 关系表 → `scripts/db.py`（`MEMORY_COLUMNS` / `qa_links` / `qa_events` / `log_event` / `add_link`）、`qa_tool.py history`、`tests/test_memory_p2.py`（17 项通过）
  - 偏离说明：P1 提前引入了 `parent_qid` 列（原计划在 P2），使拆分关系可追溯；`recall` 事件留待 P3
- 决策点：按第 9 节默认值执行（1A 零依赖检索 / 2A 提示式拆分 / 3A 先做 P1 / 会话上限 3 条）
- 适用仓库：`qa-log`（skill 本体 + `vscode-extension` + `tauri-app`）

## 1. 背景与目标

QA Log 目前已经具备**记忆系统的骨架**：情景记忆（`agent_log`，hook 自动写入）、语义记忆（`qa_entries`，结构化提炼）、状态机闸门（`已验证` 需人类授权）、跨会话检索与 `#Q-XXXX` 溯源。

本设计把它从"结构化日志库"推进为**具备记忆系统核心特征**的系统，同时解决最现实的风险：**AI 滥用写入通道，把噪声灌进长期记忆**。

目标（按优先级）：

1. **写入闸门**：AI 无法写入低信息量、重复、超长的内容（约束优先于能力）
2. **粒度约束**：一条记忆只讲一件事；改动过多时自动拆分并建立关联
3. **记忆核心特征**：召回反馈、巩固（去重/合并/模式提炼）、遗忘（衰减/归档）、冲突检测、审计可查
4. **人机协同**：所有破坏性操作默认 dry-run；`已验证` 与合并/归档仍需人类确认

## 2. 非目标（YAGNI）

- 不做"AI 自动改写历史记忆内容"（只做建议 + 人确认）
- 不做云端同步 / 多用户协作（保持一项目一 `qa.db`、纯本地）
- 不做通用知识图谱可视化（只保留关系表 + 最小展示）
- 不在 P1 引入任何新的第三方运行时依赖

## 3. 现状

| 模块 | 职责 | 与本设计的关系 |
|---|---|---|
| `scripts/db.py` | `connect()` / `ensure_schema()` 幂等迁移 | P2 在此扩展 schema |
| `scripts/qa_tool.py` | agent 主 CLI：setup/append/update/summary/get/next-id/format/delete | P1 接入 guard；新增 `guard/recall/split/consolidate/archive` |
| `scripts/qa_query.py` | 插件读写接口（JSON over stdin/stdout） | P1 写入路径接入 guard（与 CLI 同源）；现状 `qa-update` **未校验 status**（见 5.2） |
| `scripts/qa_md_sync.py` | QA.md ⇄ qa.db 增量合并，**直接 `INSERT`/`UPDATE` qa_entries**（`:170`/`:183`） | 第三条写入通道，P1 必须一并收口（见 5.1） |
| `scripts/search_qa.py` | 关键词搜索 | P3 升级为加权召回，统一到 `qa_tool.py recall` |
| `scripts/agent_log_hook.py` | CodeBuddy hook → `agent_log` | P1 加噪声过滤（极短/连续重复） |
| `references/qa-rules.md` | 唯一权威规则源（状态机/授权/编码/提交） | P1 增「记忆写入纪律」 |
| `skills/*.md` | 7 个子技能流程 | P1 在 add-question / fill-solution 中插入 guard 步骤 |
| `vscode-extension/` | 侧边栏两视图 + 会话原文浏览 + QA 详情编辑 | P1 写入前提示；P4 增「记忆健康」视图 |

现有 `qa_entries` 字段：`qid, date, category, status, phenomenon, root_cause, solution, files, created_at, updated_at`
现有状态机：`Pending / 已解决待验证 / 已验证 / WontFix / Unresolved`

## 4. 设计总览

```
写入路径（agent CLI / 插件 / QA.md 同步 / 脚本）
        │
        ▼
  [ memory_guard.py ]  ← 唯一收口：校验 + 去重 + 拆分信号
        │  ok / warn(+拆分草案) / reject(+相似 QID)
        ▼
     qa.db ── qa_entries（语义记忆）
          ├─ qa_links   （条目关系：重复/取代/派生/冲突）
          ├─ qa_events  （审计流水：append/update/verify/merge/archive）
          └─ agent_log  （情景记忆，hook 自动写入）

检索：qa_tool.py recall → 加权召回（写入 access_count/last_access_at，形成正反馈）
巩固：consolidate --dry-run → 去重/合并/模式提炼（人确认后执行）
遗忘：score 排序 + 建议归档（archived=1，默认不参与检索，不删除）
```

核心原则：**约束在前，能力在后；所有破坏性动作默认 dry-run；人类保留最终信任判定权。**

## 5. P1：写入闸门与粒度约束（无 schema 变更）

### 5.1 模块与收口

新建 `scripts/memory_guard.py`，对外两个函数：

```python
def check_entry(payload, conn=None, mode="write") -> GuardResult
# GuardResult: {level: "ok"|"warn"|"reject", issues: [...], split_plan: [...], similar: [qid, ...]}

def scan_split(payload) -> list[dict]   # 拆分草案（不落库）
```

调用点（**四条通道缺一不可**，否则规则形同虚设）：

- `qa_tool.py append` / `qa_tool.py update`
- `qa_query.py qa-update`（插件写入路径）
- `qa_md_sync.py sync`（QA.md → qa.db 双向合并，`:170` INSERT / `:183` UPDATE 直写表）
- 新增 `qa_tool.py guard --json`（干跑校验，供技能流程与插件预检）

`qa_md_sync.py` 的特殊处理：QA.md 常含**人工批量整理**的内容，直接 reject 会打断既有工作流。因此策略为**报告优先**——`sync` 先跑 guard 统计不合规条目并打印清单，`--strict` 才拒绝写入，默认仍落库但记录 `qa_events(event='guard_bypass')`。

### 5.2 校验表

| 检查 | 判据（默认阈值） | 级别 | 提示内容 |
|---|---|---|---|
| 占位/噪声 | 空值、`无`、`N/A`、`待补充`、`test`、仅复述现象 | reject | 指出具体字段与原因 |
| 信息密度 | `phenomenon` < 8 字；去重后行占比 > 60% 或去重后字符 < 40 | reject | 要求补信息或合并 |
| 长度上限 | 现象 4KB / 根因 8KB / 方案 16KB / 文件 8KB | reject | 建议拆分或精简（不贴流水日志） |
| 重复记忆 | 与现有条目相似度 ≥ 0.82（同 category 或同文件优先比对） | reject | 报出相似 QID，建议 update 已有条目 |
| 状态字段 | 不在状态机 5 值内 | reject | 列出合法值 |
| 拆分信号 | 方案编号项 > 6；文件表行 > 5；现象独立编号项 ≥ 2；路径首段种类 > 3 | warn | 附拆分草案 |
| 硬拆分 | 文件表行 > 12 或方案 > 24KB | reject | 强制先拆分再写入 |

> **现状差异（已核实）**：CLI 侧 `qa_tool.py update` 已有状态强校验（非法值 exit 2），guard 属叠加；而插件侧 `qa_query.py act_qa_update` **完全不校验 status**，任何字符串都能落库（仅靠 UI 下拉约束）。这正是"写入必须收口"的实证理由。

> 相似度在 P1 使用**零依赖**方案：字符 3-gram 集合 + Jaccard/余弦（同 `recall` 共用实现）。阈值可配置于 `qa_tool.py` 常量或 `.qa-guard.json`。

### 5.3 拆分

- `qa_tool.py split Q-0012 --dry-run`：打印 N 条子条目草案（按编号项或模块分桶，各自携带现象片段与文件子集）
- `qa_tool.py split Q-0012 --apply`：落库子条目，`parent_qid` 指向父；建立 `derived_from` 关系；父条目 `status` 聚合规则——全部子项 `已验证` 时父可置 `已验证`（仍需人类授权）
- 父条目正文保留"总览 + 子条目链接"，细节下沉到子条目，避免重复叙述

### 5.4 规则增补（`references/qa-rules.md` 新增第 5 节「记忆写入纪律」）

1. **一次会话新增记忆上限默认 3 条**，超出需用户明确同意
2. 禁止写入：临时排错过程、被推翻的尝试、与本条无关的闲聊、重复表述、大段原始日志
3. **30 秒复用检验**：每条记忆必须能回答"未来的我遇到什么场景会需要它"，答不出就不写
4. 一条记忆只讲一件事；命中拆分信号必须先拆
5. 批量写入默认 dry-run，`--yes` 才落库（沿用授权铁律）
6. `已验证`、合并、归档仍需用户授权（不变）

### 5.5 agent_log 侧降噪

- 跳过长度 < 4 字符的消息；同一 `session_id` 内连续重复 title 去重
- 仅影响情景记忆的原样记录，不改语义记忆

### 5.6 P1 验收

- `qa_tool.py guard` 对 7 类样例分别返回预期级别（噪声 / 超长 / 重复 / 可拆分 / 正常）
- `qa_tool.py append` 遇到 reject 样例时**不落库**并打印可操作提示
- `split --dry-run` 对一条含 3 模块改动的记录产出 3 条草案；`--apply` 后子条目 `parent_qid`/关系正确
- 插件 `qa-update` 走同一 guard（对超长内容报错，而不是像现状那样静默写入）
- `qa_md_sync.py sync` 对不合规条目输出清单且默认不阻断
- **回归基线（实测，2026-10-08）**：本仓库 `qa.db` 的 `qa_entries` 为 **0 条**；外部库合计约 **1468 条 QA / 4862 条 agent_log，分布在 23 个 `qa.db`**（最大：`blot-eyes` 549、`any-version` 349、`mathsnap_app` 150、`magic-camera` 129、`paper-helper/service` 126）。guard 只在写入时生效，**历史库零改动、零误伤**

## 6. P2：Schema 扩展与审计流水

### 6.1 `qa_entries` 新增列（`ensure_schema` 幂等 ALTER）

| 列 | 类型 | 默认 | 用途 |
|---|---|---|---|
| `importance` | INTEGER | 50 | 重要性 0–100（初值按 category/影响面估算，可人工调） |
| `access_count` | INTEGER | 0 | 被召回次数（反馈信号） |
| `last_access_at` | TEXT | NULL | 最近召回时间（新鲜度衰减基准） |
| `tags` | TEXT | `[]` | JSON 数组，用于聚类与冲突检测 |
| `source_session` | TEXT | NULL | 溯源：产生该记忆的 CodeBuddy 会话 ID |
| `source_commit` | TEXT | NULL | 溯源：关联提交 hash |
| `parent_qid` | TEXT | NULL | 拆分/合并的父条目 |
| `archived` | INTEGER | 0 | 归档标记（默认检索排除） |

### 6.2 新表

```sql
CREATE TABLE IF NOT EXISTS qa_links (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_qid   TEXT NOT NULL,
    to_qid     TEXT NOT NULL,
    kind       TEXT NOT NULL,   -- relates_to|duplicates|supersedes|derived_from|contradicts
    note       TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_qa_links_from ON qa_links(from_qid);
CREATE INDEX IF NOT EXISTS idx_qa_links_to   ON qa_links(to_qid);

CREATE TABLE IF NOT EXISTS qa_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    qid        TEXT NOT NULL,
    event      TEXT NOT NULL,   -- append|update|verify|merge|split|archive|recall|delete|guard_bypass
    detail     TEXT DEFAULT '',
    actor      TEXT DEFAULT 'agent',   -- agent|user|tool
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_qa_events_qid ON qa_events(qid, id);
```

> **`delete` 必须留痕**：现状有两条删除入口（`qa_tool.py delete`、`qa_query.py qa-delete`），若删除不写审计，"完整操作历史"就不成立。实现上先写 `event='delete'`（含删除前快照摘要）再执行删除；`qa_events` 不设外键，删除后流水仍在。`guard_bypass` 用于记录 `qa_md_sync.py` 默认放行的不合规条目。

### 6.3 P2 验收

- 迁移在全部 23 个外部库上验证：执行任意 CLI 后自动补齐列与表，`qa_entries` 条数**零变化**（以 blot-eyes 549 / any-version 349 / mathsnap_app 150 / magic-camera 129 为基准抽验）
- 每次 append/update/verify/split/merge/archive/**delete**/recall 产生一条 `qa_events`（删除后仍可查到该条目的操作流水）
- `qa_tool.py history Q-0001` 可打印该记忆的完整操作流水

## 7. P3：召回反馈与巩固

### 7.1 加权召回

`qa_tool.py recall "<query>" [--limit N] [--include-archived]`

```
score = w1·field_match(标题/现象 权重 3 / 根因 2 / 方案 1 / 文件 2)
      + w2·importance/100
      + w3·log(1 + access_count)
      - w4·recency_decay(last_access_at, created_at)   （长期未被召回则轻微衰减）
      + w5·link_bonus（被引用次数）
```

- 零依赖实现：字符 3-gram 相似度 + 字段加权（与 guard 共用）
- **命中即回写** `access_count += 1`、`last_access_at = now`，并写 `qa_events(event='recall')`——形成"越有用越容易被找到"的正反馈
- 语义检索（可选层）预留接口 `EmbeddingProvider`；启用与否见第 9 节决策点

### 7.2 巩固

- `qa_tool.py consolidate --dry-run`：扫描近似对（相似度 ≥ 0.7）→ 输出建议：`merge`（保留信息量最高正文 + 合并 files + 保留最小 QID）、`duplicates`、`supersedes`；人工确认后 `--apply`
- 模式提炼：同一 `tags` 或同一模块下相似条目 ≥ K（默认 5）→ 建议生成 `category=Pattern` 抽象条目，并以 `derived_from` 链接子项
- 绝不自动删除；合并仅置 `archived=1` 并建立 `supersedes` 关系

### 7.3 P3 验收

- `recall` 对历史关键词命中排序合理（人工抽查 10 条）；命中条目的 `access_count` 递增
- `consolidate --dry-run` 在构造的重复样例上给出正确合并建议；`--apply` 后可回溯（`supersedes` + 归档而非删除）

## 8. P4：遗忘、冲突与「记忆健康」

- **衰减与归档**：`score` 低 + 长期未召回 + `status ∈ {WontFix, Unresolved}` → 建议 `archived=1`（默认检索排除，`--include-archived` 可见），永不删除
- **冲突检测**：同 `tags`/同文件下结论矛盾的条目（高相似现象 + 不同根因，或方案互斥）→ 标 `needs_review` 并写 `contradicts` 关系，进入待审列表
- **插件第三视图「记忆健康」**：重复率、`已解决待验证` 积压（> N 天未验证）、孤立条目（无 tags / 无 link / 无 files）、冲突待审、近 7 日新增与召回趋势
- 所有面板操作（合并/归档/拆分）走 dry-run 预览 + 二次确认

## 9. 决策点与默认值

| # | 决策 | 选项 | 默认（已预填，可改） |
|---|---|---|---|
| 1 | 语义检索 | A 零依赖加权（3-gram/TF-IDF + 权重），预留 embedding 接口；B 直接引入本地 embedding 模型（首次约 100MB） | **A** |
| 2 | 拆分强度 | A 命中信号只提示 + 一键拆分；B 超硬阈值直接拒绝写入 | **A**（硬阈值仍会 reject） |
| 3 | 交付顺序 | A 先做 P1 验证手感；B P1+P2 一起做 | **A** |
| 4 | 会话新增上限 | 默认 3 条 / 5 条 / 不限（仅靠 guard 拦质量） | **3 条** |

## 10. 风险与回退

| 风险 | 缓解 |
|---|---|
| guard 误判阻断正常记录 | 阈值集中在 `memory_guard.py` 顶部常量；提供 `--force` 与配置覆盖；reject 一律附可操作提示 |
| 相似度算法（3-gram）对长文/代码块不敏感 | 只作为"提示级"信号（除高阈值去重外）；P3 可替换为 embedding |
| schema 迁移破坏外部项目库 | 迁移与现有 `ensure_schema` 同模式（`ALTER TABLE ADD COLUMN` + `CREATE TABLE IF NOT EXISTS`），先备份 `qa.db.pre-memory.bak` |
| 规则过严导致 agent 少记录 | 上限与阈值可配；先跑 P1 观察一周再收紧 |
| 归档/合并造成信息丢失 | 只归档不删除；关系与审计流水可回溯 |
| **`qa.db` 整体丢失（已发生）** | 实测证据：本仓库 `qa.db` 于 2026-10-08 被重建（`agent_log` 最早记录为当日 21:23），导致 09-23 写入的 `Q-0001`/`Q-0002` 消失，而历史提交信息仍引用 `#Q-0001`/`#Q-0002`。缓解：P2 迁移前强制快照（`qa.db.pre-memory-YYYYMMDD.bak`）；建议对 `qa.db` 启用定期快照或纳入版本控制（需先确认是否含敏感信息）；`qa_tool.py doctor` 检测"库被重建但 git 历史含 QID 引用"的异常并告警 |

## 11. 分阶段交付

| 阶段 | 内容 | 影响面 | 预估 | 状态 |
|---|---|---|---|---|
| P1 | `memory_guard.py`、`guard/split` CLI、写入收口、规则增补、hook 降噪 | 无 schema 变更 | ~1 天 | ✅ 已实现 |
| P2 | schema 扩展、`qa_links`、`qa_events`、`history` 命令 | 幂等迁移 | ~0.5 天 | ✅ 已实现 |
| P3 | 加权召回 + 召回反馈、`consolidate`、模式提炼 | 检索体验 | ~1–2 天 | ✅ 已实现 |
| P4 | 衰减归档、冲突检测、插件「记忆健康」视图 | 插件 + CLI | ~1–2 天 | ⬜ 待做 |

每个阶段独立可验收，完成后更新本文件并在 `qa.db` 记一条 QA 条目。
