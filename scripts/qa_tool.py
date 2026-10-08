#!/usr/bin/env python3
"""
QA database management toolkit — read/write qa.db (SQLite) entries.

qa.db is the single source of truth for QA records. It lives in the *project
root* where the skill is used (NOT inside the skill directory). The Tauri
desktop app reads the same qa.db.

Schema:
    qa_entries (
        qid         TEXT PRIMARY KEY,          -- e.g. Q-0001 (唯一标识+排序键，4 位零填充)
        date        TEXT NOT NULL,             -- YYYY-MM-DD
        category    TEXT NOT NULL,             -- Bug Fix / Feature / ...
        status      TEXT NOT NULL DEFAULT 'Pending',
        phenomenon  TEXT NOT NULL,             -- 现象/需求
        root_cause  TEXT DEFAULT '',           -- 根因
        solution    TEXT DEFAULT '',           -- 解决方案
        files       TEXT DEFAULT '',           -- 涉及文件 (markdown table)
        created_at  TEXT DEFAULT (datetime('now','localtime'))
    )

Subcommands:
  setup                Init qa.db (create table) + copy QALogBrowser.exe to project root
  summary              List all entries (ID + title only)
  get <ID>             Get full content of a single entry by ID
  append               Append a new entry (auto-increments ID; goes through memory guard)
  update <ID>          Update an existing entry's solution/status (goes through memory guard)
  next-id              Print the next available ID
  delete <ID>          Delete one entry (with confirmation prompt)
  format               Validate and report qa.db structure issues
  guard [ID]           Dry-run the memory write gate (exit 0=ok / 1=warn / 3=reject)
  split <ID>           Split a multi-topic entry into child entries (draft by default)
  history <ID>         Print audit trail (qa_events) + relations (qa_links) of one entry
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date

# 共享数据库逻辑（自动迁移 + 4 位零填充）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import (
    DB_NAME,
    add_link,
    connect as _db_connect,
    ensure_schema,
    get_next_qid,
    log_event,
    normalize_id,
    resolve_db_path,
)

# 记忆写入闸门（P1）：append/update 默认过 guard，reject 时拒绝写入
import memory_guard

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdin, "reconfigure"):
    # 强制 stdin 按 UTF-8 解码（Windows 默认可能用 GBK，导致管道/重定向的中文乱码）
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

# 兼容：其它脚本可能用 qa_tool.connect 导入
connect = _db_connect

# 兼容：DEFAULT_CWD_DB 仍按 cwd/qa.db 解析
DEFAULT_CWD_DB = os.path.join(os.getcwd(), DB_NAME)

# Valid status values — 权威状态机（唯一合法集合）
# 规范：Pending(待解决) -> 已解决待验证 -> 已验证；WontFix/Unresolved 为终止态
VALID_STATUSES = ("Pending", "已解决待验证", "已验证", "WontFix", "Unresolved")

# 常见非规范同义词 -> 提示应改用哪个规范状态（用于报错提示，不自动替换）
STATUS_SUGGESTIONS = {
    "已解决": "已验证",
    "解决": "已验证",
    "已修复": "已验证",
    "修复": "已验证",
    "待验证": "已解决待验证",
    "待确认": "已解决待验证",
    "待检查": "已解决待验证",
    "resolved": "已验证",
    "done": "已验证",
    "fixed": "已验证",
}


def normalize_status(status, strict=False):
    """把用户输入的状态标准化到规范集合；非法时返回 None（或 strict 时报错提示）。"""
    s = (status or "").strip()
    if s in VALID_STATUSES:
        return s
    # 尝试大小写/空白规范化（英文枚举）
    for v in VALID_STATUSES:
        if s.lower() == v.lower():
            return v
    return None

# Placeholder for unsolved fields
PLACEHOLDER = "[待填写]"

# 桌面浏览器 exe 名称（部署到项目根目录）
BROWSER_EXE = "QALogBrowser.exe"


def skill_root():
    """返回 skill 根目录（本脚本位于 <skill>/scripts/qa_tool.py）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bin_dir():
    """skill 内置 exe 所在目录：<skill>/bin。"""
    return os.path.join(skill_root(), "bin")


def ensure_qa_db(db_path=None):
    """Ensure qa.db exists with the schema. Returns (conn, created).

    `connect()` already calls `ensure_schema()` on every open, but we
    still need the `created` flag to know if we should print the
    "Database created at" message in `cmd_setup`.
    """
    path = resolve_db_path(db_path)
    created = not os.path.exists(path)
    conn = connect(path)
    return conn, created


def cmd_setup(args):
    """First-use setup in the project root:
    - ensure qa.db exists (create table if missing)
    - copy QALogBrowser.exe to the project root if missing
    """
    db_path = args.db or DEFAULT_CWD_DB
    project_root = os.path.dirname(os.path.abspath(db_path)) or os.getcwd()

    # 1. Init database
    conn, created = ensure_qa_db(db_path)
    conn.close()
    if created:
        print(f"Initialized {db_path}")
    else:
        print(f"{db_path} already exists")

    # 2. Copy browser exe if missing
    target_exe = os.path.join(project_root, BROWSER_EXE)
    source_exe = os.path.join(bin_dir(), BROWSER_EXE)
    if os.path.exists(target_exe):
        print(f"{BROWSER_EXE} already exists in project root")
    elif os.path.exists(source_exe):
        shutil.copy2(source_exe, target_exe)
        print(f"Copied {BROWSER_EXE} -> {target_exe}")
    else:
        print(f"WARNING: {source_exe} not found. Build it via tauri-app first, "
              f"or copy it into the skill bin/ directory.")


def cmd_recall(args):
    """加权召回（记忆系统 P3）：命中即回写access_count / last_access_at + recall 事件。"""
    import memory_recall as MR

    conn = connect(args.db)
    if args.qid:
        row = conn.execute(
            "SELECT phenomenon, root_cause, solution, files FROM qa_entries WHERE qid = ?",
            (normalize_id(args.qid),),
        ).fetchone()
        if row is None:
            print(f"Entry {normalize_id(args.qid)} not found.", file=sys.stderr)
            conn.close()
            sys.exit(1)
        query = " ".join(x for x in (row["phenomenon"], row["root_cause"],
                                     row["solution"], row["files"]) if x)[:400]
    else:
        query = args.query or ""
    if not query.strip():
        print("recall 需要查询词（或用 --qid 以某条内容为查询）", file=sys.stderr)
        conn.close()
        sys.exit(2)

    hits = MR.recall(conn, query, limit=args.limit,
                     include_archived=args.include_archived,
                     feedback=not args.no_feedback,
                     status=args.status, category=args.category)
    if not hits:
        print("No matching entries found.")
        conn.close()
        return
    print(f"Recall '{query[:60]}' → {len(hits)} hit(s)"
          + ("（已回写召回反馈）" if not args.no_feedback else "（未回写反馈）"))
    for h in hits:
        print(f"  score={h['score']:.3f}  {h['qid']} | {h['status']} | {h['category']} | "
              f"热度={h['access_count']}{' [archived]' if h['archived'] else ''}")
        print(f"        {h['title']}")
        print(f"        匹配字段: {h['match']}")
    conn.close()


def cmd_consolidate(args):
    """巩固（记忆系统 P3）：近似条目/模式提炼建议；--apply 才落库。"""
    import memory_recall as MR

    conn = connect(args.db)
    pairs = MR.find_near_duplicates(conn, threshold=args.threshold)
    groups = [] if args.no_pattern else MR.suggest_patterns(conn, min_size=args.min_size)

    print(f"[consolidate] 近似条目 {len(pairs)} 对（阈值 {args.threshold}）；模式候选 {len(groups)} 组")
    for p in pairs[:20]:
        print(f"  [{p['action']}] {p['a']} ↔ {p['b']}  score={p['score']}  建议保留 {p['keep_hint']}")
    for g in groups[:10]:
        print(f"  [pattern] {g['category']} / {'/'.join(g['modules'])}  "
              f"{g['size']} 条  平均相似度={g['avg_similarity']}")
        print(f"           {', '.join(g['qids'][:10])}")

    if not args.apply:
        print("\n[dry-run] 未做任何改动。确认后加 --apply 执行合并（丢弃方归档，不删除）。")
        conn.close()
        return
    if not pairs:
        print("\n[consolidate] 无可合并项")
        conn.close()
        return
    if not args.yes:
        try:
            ans = input("\n确认合并？丢弃方将被归档（recall --include-archived 可见）[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted", file=sys.stderr)
            conn.close()
            sys.exit(130)
        if ans not in ("y", "yes"):
            print("Aborted")
            conn.close()
            return

    done = failed = 0
    for p in pairs:
        keep = p["keep_hint"]
        drop = p["b"] if keep == p["a"] else p["a"]
        ok, msg = MR.merge_entries(conn, keep, drop)
        if ok:
            done += 1
            print(f"  merged: {msg}")
        else:
            failed += 1
            print(f"  FAILED: {p['a']} ↔ {p['b']}: {msg}")
    print(f"\n[consolidate] 合并 {done} 对，失败 {failed} 对")
    conn.close()


def cmd_health(args):
    """记忆健康报告（P4）。"""
    import json as _json
    import memory_health as MH
    conn = connect(args.db)
    r = MH.health_report(conn)
    if args.json:
        print(_json.dumps(r, ensure_ascii=False, indent=2))
        conn.close()
        return
    print("[health] total={} archived={} needs_review={}".format(
        r.get("total"), r.get("archived"), r.get("needs_review")))
    st = ", ".join('{}={}'.format(k, v) for k, v in (r.get("by_status") or {}).items())
    print("  by_status: {}".format(st or '(empty)'))
    print("  last7d: added={} recalled={}".format(r.get("added_7d"), r.get("recalled_7d")))
    for key, label in (('stale_pending', 'stale-pending'),
                      ('orphans', 'orphans'),
                      ('conflicts', 'conflicts')):
        items = r.get(key) or []
        print("  {}: {}".format(label, len(items)))
        for it in items[:5]:
            if isinstance(it, dict):
                print("    {} vs {}  {}".format(it.get("a"), it.get("b"), it.get("reason") or it.get("score")))
            else:
                print("    {}".format(it))
    dups = r.get('duplicate_pairs') or []
    print("  duplicate_pairs: {}".format(len(dups)))
    for d in dups[:5]:
        print("    {} vs {}  score={} (keep {})".format(d.get("a"), d.get("b"), d.get("score"), d.get("keep_hint")))
    conn.close()

def cmd_prune(args):
    """衰减归档（P4）：默认只给建议，--apply 才归档（永不删除）。"""
    import memory_health as MH
    conn = connect(args.db)
    if args.restore:
        qid = normalize_id(args.restore)
        MH.unarchive_entry(conn, qid)
        print("[prune] restored " + qid)
        conn.close()
        return
    sugg = MH.suggest_archive(conn, stale_days=args.stale_days, cold_access=args.cold_access)
    print("[prune] {} suggestion(s): terminal-or-stale AND cold".format(len(sugg)))
    for s in sugg[:20]:
        print("  {}  decay={:.3f}  {}  {}".format(s["qid"], s["score"], s["status"], s["reason"]))
        print("    " + (s.get("title") or ''))
    if not args.apply:
        print('')
        print("[dry-run] nothing changed. Use --apply to archive (reversible via --restore ID).")
        conn.close()
        return
    if not sugg:
        print("[prune] nothing to archive")
        conn.close()
        return
    if not args.yes:
        try:
            ans = input(chr(10) + "Archive {} entries? (archived=1 only, never deletes) [y/N] ".format(len(sugg))).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(chr(10) + "Aborted", file=sys.stderr)
            conn.close()
            sys.exit(130)
        if ans not in ('y', 'yes'):
            print("Aborted")
            conn.close()
            return
    for s in sugg:
        MH.archive_entry(conn, s["qid"], s["reason"])
        print("  archived: {}".format(s["qid"]))
    print(chr(10) + "[prune] archived {} (recall excludes them; --include-archived to see)".format(len(sugg)))
    conn.close()


def cmd_conflicts(args):
    """冲突检测（P4）：现象相似但根因/方案分歧。"""
    import memory_health as MH
    conn = connect(args.db)
    cs = MH.find_conflicts(conn)
    print("[conflicts] {} potential conflict(s)".format(len(cs)))
    for c in cs[:20]:
        print("  {} vs {}  {}".format(c["a"], c["b"], c["reason"]))
    if not cs:
        conn.close()
        return
    if not args.link:
        print('')
        print("[dry-run] nothing written. Use --link to record contradicts and set needs_review.")
        conn.close()
        return
    n = MH.mark_conflicts(conn, cs)
    print(chr(10) + "[conflicts] recorded {} contradicts link(s); both sides need review".format(n))
    conn.close()

def cmd_summary(args):
    """List all entries: ID + title only."""
    conn = connect(args.db)
    sql = "SELECT qid, date, category, status, phenomenon FROM qa_entries ORDER BY qid DESC"
    params = []
    if getattr(args, "limit", None):
        sql += " LIMIT ?"
        params.append(args.limit)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        print("No entries found.")
        conn.close()
        return
    for r in rows:
        title = r["phenomenon"]
        if len(title) > 50:
            title = title[:47] + "..."
        print(f"{r['qid']} | {r['date']} | {r['category']} | {r['status']} | {title}")
    conn.close()


def cmd_get(args):
    """Get full content of a single entry by ID."""
    conn = connect(args.db)
    target = normalize_id(args.id)
    row = conn.execute(
        "SELECT * FROM qa_entries WHERE qid = ?", (target,)
    ).fetchone()
    conn.close()
    if row is None:
        print(f"Entry {target} not found.")
        sys.exit(1)
    print(format_entry(row))
    print("---")


def format_entry(row):
    """Render a DB row as the familiar markdown-style QA entry."""
    root_cause = row["root_cause"] or PLACEHOLDER
    solution = row["solution"] or PLACEHOLDER
    files = row["files"] or PLACEHOLDER
    lines = [
        f"## {row['qid']} | {row['date']} | {row['category']} | {row['status']}",
        "",
        f"**现象/需求:** {row['phenomenon']}",
        "",
        f"**根因:** {root_cause}",
        "",
        f"**解决方案:** {solution}",
        "",
    ]
    if files == PLACEHOLDER:
        lines.append(f"**涉及文件:** {files}")
    else:
        lines.append(f"**涉及文件:**\n{files}")
    return "\n".join(lines)


def read_json_input(args):
    """读取 JSON 数据（用于 append/update）。

    来源优先级：
      1. --json 指定 JSON 字符串
      2. stdin 管道传入的 JSON
      3. 无则返回 None
    中文内容建议通过 JSON 方式传入，避免 Windows 命令行 ANSI/GBK 编码导致乱码。
    """
    raw = None
    from_json_flag = getattr(args, "json", None)
    if from_json_flag == "__STDIN__":
        # bare --json：从 stdin 管道读取（彻底避免命令行传中文）
        raw = sys.stdin.read().strip()
    elif from_json_flag:
        raw = from_json_flag
    elif not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
    if not raw:
        return None
    # 剥离可能的 UTF-8 BOM（PowerShell 管道到原生程序时会带 BOM）
    raw = raw.lstrip("\ufeff")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            if from_json_flag:
                print("Error: --json expects a JSON object", file=sys.stderr)
                sys.exit(1)
            return None
        return data
    except json.JSONDecodeError as e:
        if from_json_flag:
            print(f"Error: invalid JSON: {e}", file=sys.stderr)
            sys.exit(1)
        return None


def _guard_fields_from_data(data, category=None, status=None):
    """把 append/update 的 JSON 输入规整成 guard 用的字段字典。"""
    return {
        "phenomenon": (data.get("phenomenon") or data.get("question") or "").strip(),
        "root_cause": (data.get("root_cause") or "").strip(),
        "solution": (data.get("solution") or "").strip(),
        "files": (data.get("files") or "").strip(),
        "category": category or data.get("category") or "Other",
        "status": status or data.get("status") or "Pending",
    }


def _enforce_guard(fields, conn, exclude_qid=None, force=False, action=""):
    """跑写入闸门：reject 且未 --force → 打印报告并 exit 3；warn → 打印提示继续。"""
    result = memory_guard.check(fields, conn=conn, exclude_qid=exclude_qid)
    if result["level"] == "reject" and not force:
        print(memory_guard.format_report(result, title=f"[guard] 拒绝写入{action}"), file=sys.stderr)
        print("[guard] 如确认内容无误，可加 --force 强制写入。", file=sys.stderr)
        conn.close()
        sys.exit(3)
    if result["level"] != "ok":
        print(memory_guard.format_report(result, title=f"[guard] 提示{action}"), file=sys.stderr)
    return result


def cmd_guard(args):
    """干跑写入闸门：检查 JSON 草稿或库中已有条目，不落库。"""
    conn = connect(args.db)
    data = read_json_input(args)
    if args.id:
        target = normalize_id(args.id)
        row = conn.execute("SELECT * FROM qa_entries WHERE qid = ?", (target,)).fetchone()
        if row is None:
            print(f"Entry {target} not found.", file=sys.stderr)
            conn.close()
            sys.exit(1)
        fields = {
            "phenomenon": row["phenomenon"] or "", "root_cause": row["root_cause"] or "",
            "solution": row["solution"] or "", "files": row["files"] or "",
            "category": row["category"] or "", "status": row["status"] or "",
        }
        exclude = target
        title = f"[guard] 检查库中条目 {target}"
    else:
        fields = _guard_fields_from_data(data or {})
        exclude = None
        title = "[guard] 检查草稿"
    result = memory_guard.check(fields, conn=conn, exclude_qid=exclude)
    print(memory_guard.format_report(result, title=title))
    conn.close()
    sys.exit(3 if result["level"] == "reject" else (1 if result["level"] == "warn" else 0))


def cmd_split(args):
    """把一条含多条独立诉求的条目拆成多条子条目（默认只出草案）。"""
    conn = connect(args.db)
    qid = normalize_id(args.id)
    row = conn.execute("SELECT * FROM qa_entries WHERE qid = ?", (qid,)).fetchone()
    if row is None:
        print(f"Entry {qid} not found.", file=sys.stderr)
        conn.close()
        sys.exit(1)

    fields = {
        "phenomenon": row["phenomenon"] or "", "root_cause": row["root_cause"] or "",
        "solution": row["solution"] or "", "files": row["files"] or "",
        "category": row["category"] or "", "status": row["status"] or "",
    }
    plan = memory_guard.scan_split(fields)
    if not plan["drafts"]:
        print(f"[split] {qid} 未发现可拆分结构"
              + (f"（信号：{'; '.join(plan['reasons'])}）" if plan["reasons"] else ""))
        conn.close()
        return

    print(f"[split] {qid} 拆分草案：策略={plan['strategy']}，共 {len(plan['drafts'])} 条")
    for i, s in enumerate(plan["reasons"], 1):
        print(f"  信号{i}: {s}")
    for k, d in enumerate(plan["drafts"], 1):
        print(f"\n  ── 子条目 {k} ──")
        print("  现象/需求: " + (d["phenomenon"] or "").replace("\n", "\n              "))
        if d["files"]:
            print("  涉及文件:")
            for line in d["files"].splitlines():
                print("    " + line)

    if not args.apply:
        print("\n[dry-run] 未写入任何内容。确认后加 --apply 落库。")
        conn.close()
        return
    if not args.yes:
        try:
            ans = input(f"\n确认按上述草案拆分 {qid}？（会新建 {len(plan['drafts'])} 条）[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted", file=sys.stderr)
            conn.close()
            sys.exit(130)
        if ans not in ("y", "yes"):
            print("Aborted")
            conn.close()
            return

    created = []
    for d in plan["drafts"]:
        child = get_next_qid(conn)
        conn.execute(
            """INSERT INTO qa_entries
               (qid, date, category, status, phenomenon, root_cause, solution, files, parent_qid)
               VALUES (?, ?, ?, 'Pending', ?, ?, ?, ?, ?)""",
            (child, date.today().isoformat(), fields["category"],
             d["phenomenon"].strip(), PLACEHOLDER,
             f"{PLACEHOLDER}\n\n（拆分自 {qid}：根因/方案待分别补充）", d["files"], qid),
        )
        created.append(child)
        add_link(conn, child, qid, "derived_from", f"split of {qid}")
        log_event(conn, child, "split", f"parent={qid}")
    # 父条目追加子条目索引，细节下沉到子条目
    idx = "\n".join(f"- {c}（拆分自本条）" for c in created)
    conn.execute(
        """UPDATE qa_entries
           SET solution = COALESCE(NULLIF(solution,''), '') || char(10) || char(10) ||
               '**已拆分为以下子条目：**' || char(10) || ?,
               updated_at = datetime('now','localtime')
           WHERE qid = ?""",
        (idx, qid),
    )
    conn.commit()
    log_event(conn, qid, "split", "children=" + ",".join(created))
    conn.close()
    print(f"\n[split] {qid} 已拆分为: {', '.join(created)}")
    print(f"[split] 请分别补齐各子条目的根因/方案（当前为 {PLACEHOLDER}）")


def cmd_history(args):
    """打印某条记忆的完整操作流水（审计 + 关系）。"""
    conn = connect(args.db)
    qid = normalize_id(args.id)
    row = conn.execute(
        "SELECT qid, date, category, status, parent_qid, importance, access_count,"
        " last_access_at, created_at, updated_at FROM qa_entries WHERE qid = ?",
        (qid,),
    ).fetchone()
    if row is None:
        print(f"[history] 条目 {qid} 已不存在（可能被删除），以下为其审计流水：")
    else:
        print(f"[history] {row['qid']} | {row['date']} | {row['category']} | {row['status']}")
        print(f"  created_at={row['created_at']}  updated_at={row['updated_at']}")
        print(f"  parent_qid={row['parent_qid']}  importance={row['importance']}"
              f"  access_count={row['access_count']}  last_access_at={row['last_access_at']}")

    events = conn.execute(
        "SELECT id, event, actor, detail, created_at FROM qa_events WHERE qid = ? ORDER BY id",
        (qid,),
    ).fetchall()
    print(f"  审计流水（{len(events)} 条）:")
    for e in events:
        d = (e["detail"] or "").replace("\n", " ")[:120]
        print(f"    {e['created_at']}  {e['event']:<14} {e['actor']:<6} {d}")

    outs = conn.execute(
        "SELECT kind, to_qid, note FROM qa_links WHERE from_qid = ? ORDER BY id", (qid,)
    ).fetchall()
    ins = conn.execute(
        "SELECT kind, from_qid, note FROM qa_links WHERE to_qid = ? ORDER BY id", (qid,)
    ).fetchall()
    if outs:
        print("  出边关系:")
        for r in outs:
            print(f"    --{r['kind']}--> {r['to_qid']}  {r['note']}")
    if ins:
        print("  入边关系:")
        for r in ins:
            print(f"    <--{r['kind']}-- {r['from_qid']}  {r['note']}")

    kids = conn.execute(
        "SELECT qid FROM qa_entries WHERE parent_qid = ? ORDER BY qid", (qid,)
    ).fetchall()
    if kids:
        print("  子条目: " + ", ".join(k["qid"] for k in kids))
    conn.close()


def cmd_append(args):
    """Append a new entry with auto-generated ID."""
    conn, created = ensure_qa_db(args.db)
    qid = get_next_qid(conn)
    today = date.today().isoformat()
    data = read_json_input(args) or {}
    # 优先级：命令行参数 > JSON 字段
    category = args.category or data.get("category") or "Other"
    question = (args.question or data.get("question") or "").strip()

    _enforce_guard(_guard_fields_from_data(data, category=category, status="Pending"),
                   conn, force=getattr(args, "force", False), action="")

    conn.execute(
        """INSERT INTO qa_entries (qid, date, category, status, phenomenon)
           VALUES (?, ?, ?, 'Pending', ?)""",
        (qid, today, category, question),
    )
    conn.commit()
    log_event(conn, qid, "append", f"category={category}")
    conn.close()
    print(f"Created {qid}")


def cmd_update(args):
    """Update an existing entry's fields. Stamps updated_at automatically."""
    conn = connect(args.db)
    target = normalize_id(args.id)
    row = conn.execute("SELECT * FROM qa_entries WHERE qid = ?", (target,)).fetchone()
    if row is None:
        print(f"Entry {target} not found.")
        conn.close()
        sys.exit(1)

    def expand(v):
        return v.replace("\\n", "\n") if v else v

    data = read_json_input(args) or {}
    # 优先级：命令行参数 > JSON 字段 > 保留原值
    new_status = args.status or data.get("status") or row["status"]

    # 状态强校验：只接受权威状态机集合；非法值拒绝写入并提示
    if "status" in (data or {}) or args.status is not None:
        norm = normalize_status(new_status)
        if norm is None:
            hint = STATUS_SUGGESTIONS.get(new_status.strip().lower())
            msg = (f"Invalid status '{new_status}'. Allowed: {', '.join(VALID_STATUSES)}."
                   + (f" Did you mean '{hint}'?" if hint else ""))
            print(msg, file=sys.stderr)
            conn.close()
            sys.exit(2)
        new_status = norm
    new_phenomenon = expand(
        args.question if args.question is not None else
        (data.get("question") if "question" in data else None)
    ) if (args.question is not None or "question" in data) else row["phenomenon"]
    new_root_cause = expand(
        args.root_cause if args.root_cause is not None else
        (data.get("root_cause") if "root_cause" in data else None)
    ) if (args.root_cause is not None or "root_cause" in data) else (row["root_cause"] or "")
    new_solution = expand(
        args.answer if args.answer is not None else
        (data.get("solution") if "solution" in data else None)
    ) if (args.answer is not None or "solution" in data) else (row["solution"] or "")
    new_files = expand(
        args.files if args.files is not None else
        (data.get("files") if "files" in data else None)
    ) if (args.files is not None or "files" in data) else (row["files"] or "")

    # 写入闸门：按合并后的最终值检查（排除自身，避免自我判重）
    _enforce_guard(
        {"phenomenon": new_phenomenon, "root_cause": new_root_cause,
         "solution": new_solution, "files": new_files,
         "category": row["category"] or "", "status": new_status},
        conn, exclude_qid=target, force=getattr(args, "force", False),
        action=f"（{target}）")

    conn.execute(
        """UPDATE qa_entries
           SET status = ?, phenomenon = ?, root_cause = ?, solution = ?,
               files = ?, updated_at = datetime('now','localtime')
           WHERE qid = ?""",
        (new_status, new_phenomenon, new_root_cause, new_solution, new_files, target),
    )
    conn.commit()
    changed = []
    for label, old_v, new_v in (
        ("phenomenon", row["phenomenon"], new_phenomenon),
        ("root_cause", row["root_cause"] or "", new_root_cause),
        ("solution", row["solution"] or "", new_solution),
        ("files", row["files"] or "", new_files),
        ("status", row["status"], new_status),
    ):
        if (old_v or "") != (new_v or ""):
            changed.append(label)
    # 状态进入"已验证"是记忆可信度的关键跃迁，单独留痕
    evt = "verify" if (new_status == "已验证" and row["status"] != "已验证") else "update"
    log_event(conn, target, evt, "fields=" + (",".join(changed) if changed else "(无变化)"))
    conn.close()
    print(f"Updated {target}")


def cmd_delete(args):
    """Delete a single entry by ID. Prompts for confirmation unless -f."""
    qid = normalize_id(args.id)
    conn = connect(args.db)

    row = conn.execute(
        "SELECT qid, date, category, status, phenomenon FROM qa_entries WHERE qid = ?",
        (qid,),
    ).fetchone()
    if row is None:
        print(f"Error: {qid} not found", file=sys.stderr)
        conn.close()
        sys.exit(1)

    title = (row["phenomenon"] or "").strip()
    if len(title) > 60:
        title = title[:57] + "..."

    if args.dry_run:
        print(f"[dry-run] Would delete {qid}:")
        print(f"  {row['date']} | {row['category']} | {row['status']}")
        print(f"  {title}")
        conn.close()
        return

    if not args.force:
        print(f"About to delete {qid}:")
        print(f"  {row['date']} | {row['category']} | {row['status']}")
        print(f"  {title}")
        try:
            ans = input("Confirm? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted", file=sys.stderr)
            conn.close()
            sys.exit(130)
        if ans not in ("y", "yes"):
            print("Aborted")
            conn.close()
            return

    # 审计：删除也必须留痕（先写 event 再删；qa_events 无外键，条目消失后流水仍在）
    snapshot = " | ".join([
        str(row["date"] or ""), str(row["category"] or ""), str(row["status"] or ""),
        (title or "")[:120],
    ])
    log_event(conn, qid, "delete", snapshot)

    cur = conn.execute("DELETE FROM qa_entries WHERE qid = ?", (qid,))
    conn.commit()
    if cur.rowcount == 1:
        print(f"Deleted {qid}")
    else:
        print(f"Error: {qid} not found (race condition?)", file=sys.stderr)
        conn.close()
        sys.exit(1)
    conn.close()


def cmd_next_id(args):
    """Print the next available ID without creating anything."""
    conn = connect(args.db)
    print(get_next_qid(conn))
    conn.close()


def cmd_format(args):
    """Validate and report qa.db structure issues."""
    conn = connect(args.db)
    rows = conn.execute("SELECT * FROM qa_entries ORDER BY qid").fetchall()
    if not rows:
        print("No entries found.")
        conn.close()
        return

    issues = []
    for r in rows:
        # Status validation
        if r["status"] not in VALID_STATUSES:
            issues.append(f"{r['qid']}: Invalid status '{r['status']}'")
        # phenomenon must be non-empty
        if not (r["phenomenon"] or "").strip():
            issues.append(f"{r['qid']}: phenomenon (现象/需求) is empty")
        # files, if present, should be a markdown table
        files = r["files"] or ""
        if files and files != PLACEHOLDER and not files.lstrip().startswith("|"):
            issues.append(f"{r['qid']}: files (涉及文件) should be a markdown table")

    if issues:
        print(f"Found {len(issues)} issue(s):")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print(f"Validated {len(rows)} entries — all valid")
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="qa.db management toolkit — SQLite backend for QA records"
    )
    parser.add_argument("--db", help="Path to qa.db (default: ./qa.db in cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Init qa.db + copy browser exe to project root (first-use)")
    p_summary = sub.add_parser("summary", help="List all entries (ID + title)")
    p_summary.add_argument("-n", "--limit", type=int, help="Show only top N entries (newest first)")

    p_get = sub.add_parser("get", help="Get full content of one entry")
    p_get.add_argument("id", help="Entry ID (e.g., Q-0003 or just 3)")

    p_append = sub.add_parser("append", help="Append a new entry")
    p_append.add_argument("--category", "-c", help="Category (default: Other)")
    p_append.add_argument("--question", "-q", help="Question/phenomenon text (avoid Chinese via CLI)")
    p_append.add_argument("--force", action="store_true",
                          help="写入闸门 reject 时仍强制写入（默认拒绝）")
    p_append.add_argument("--json", nargs="?", const="__STDIN__", default=None,
                          help="JSON object as string, or bare --json to read from stdin. PREFERRED for Chinese.")

    p_guard = sub.add_parser("guard", help="干跑写入闸门：检查 JSON 草稿或库中已有条目（不落库）")
    p_guard.add_argument("id", nargs="?", help="检查库中已有条目（省略则检查 --json 草稿）")
    p_guard.add_argument("--json", nargs="?", const="__STDIN__", default=None,
                         help="JSON object as string, or bare --json to read from stdin.")

    p_split = sub.add_parser("split", help="把一条含多条独立诉求的条目拆成子条目（默认 dry-run）")
    p_split.add_argument("id", help="父条目 ID")
    p_split.add_argument("--apply", action="store_true", help="真正落库（默认只打印草案）")
    p_split.add_argument("--yes", action="store_true", help="跳过确认提示")

    p_update = sub.add_parser("update", help="Update an existing entry")
    p_update.add_argument("id", help="Entry ID")
    p_update.add_argument("--question", "-q", help="New question/phenomenon text (avoid Chinese via CLI)")
    p_update.add_argument("--status", "-s", help="New status (Pending, 已解决待验证, 已验证, WontFix, Unresolved)")
    p_update.add_argument("--root-cause", "-r", help="Root cause analysis")
    p_update.add_argument("--answer", "-a", help="Solution steps")
    p_update.add_argument("--files", "-f", help="Files changed table (| File | Change |)")
    p_update.add_argument("--force", action="store_true",
                          help="写入闸门 reject 时仍强制写入（默认拒绝）")
    p_update.add_argument("--json", nargs="?", const="__STDIN__", default=None,
                          help="JSON object as string, or bare --json to read from stdin. PREFERRED for Chinese.")

    p_next = sub.add_parser("next-id", help="Print next available ID")
    sub.add_parser("format", help="Validate qa.db structure")

    p_history = sub.add_parser("history", help="Print audit trail + relations of one entry")
    p_history.add_argument("id", help="Entry ID (e.g., Q-0003 or just 3)")

    p_delete = sub.add_parser("delete", help="Delete one entry by ID (with confirmation prompt)")
    p_delete.add_argument("id", help="Entry ID (e.g., Q-0003 or just 3)")
    p_delete.add_argument("-f", "--force", action="store_true", help="Skip confirmation prompt")
    p_delete.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")

    p_recall = sub.add_parser("recall", help="加权召回（字段权重 + 重要性 + 召回次数 + 新鲜度 + 关系）")
    p_recall.add_argument("query", nargs="?", help="查询词")
    p_recall.add_argument("--qid", help="以某条已存在记忆的内容作为查询（找相似记忆）")
    p_recall.add_argument("-n", "--limit", type=int, default=10, help="返回条数（默认 10）")
    p_recall.add_argument("-s", "--status", help="仅召回某状态")
    p_recall.add_argument("-c", "--category", help="按类别过滤（模糊）")
    p_recall.add_argument("--include-archived", action="store_true", help="包含已归档条目")
    p_recall.add_argument("--no-feedback", action="store_true", help="不回写召回反馈（只查不改）")

    p_consol = sub.add_parser("consolidate", help="巩固：近似条目/模式提炼建议（默认 dry-run）")
    p_consol.add_argument("--apply", action="store_true", help="真正执行合并（丢弃方归档，不删除）")
    p_consol.add_argument("--yes", action="store_true", help="跳过确认提示")
    p_consol.add_argument("--threshold", type=float, default=0.70, help="近似判定阈值（默认 0.70）")
    p_consol.add_argument("--min-size", type=int, default=5, help="模式提炼的最小条目数（默认 5）")
    p_consol.add_argument("--no-pattern", action="store_true", help="跳过模式提炼检测")

    p_health = sub.add_parser("health", help="Memory health report (P4)")
    p_health.add_argument("--json", action="store_true", help="Output raw JSON (for the extension panel)")

    p_prune = sub.add_parser("prune", help="Decay-based archive suggestions (P4, default dry-run)")
    p_prune.add_argument("--apply", action="store_true", help="Actually archive (archived=1, never deletes)")
    p_prune.add_argument("--yes", action="store_true", help="Skip confirmation")
    p_prune.add_argument("--restore", help="Un-archive one entry by ID")
    p_prune.add_argument("--stale-days", type=int, default=180, help="Stale threshold for 已解决待验证 (default 180)")
    p_prune.add_argument("--cold-access", type=int, default=2, help="Max access_count to be considered cold (default 2)")

    p_conf = sub.add_parser("conflicts", help="Detect contradictory entries (P4, default dry-run)")
    p_conf.add_argument("--link", action="store_true", help="Record contradicts links + set needs_review")

    args = parser.parse_args()

    commands = {
        "setup": cmd_setup,
        "summary": cmd_summary,
        "get": cmd_get,
        "append": cmd_append,
        "update": cmd_update,
        "next-id": cmd_next_id,
        "delete": cmd_delete,
        "format": cmd_format,
        "health": cmd_health,
        "prune": cmd_prune,
        "conflicts": cmd_conflicts,
        "recall": cmd_recall,
        "consolidate": cmd_consolidate,
        "guard": cmd_guard,
        "split": cmd_split,
        "history": cmd_history,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
