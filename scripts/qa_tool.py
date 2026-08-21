#!/usr/bin/env python3
"""
QA database management toolkit — read/write qa.db (SQLite) entries.

qa.db is the single source of truth for QA records. It lives in the *project
root* where the skill is used (NOT inside the skill directory). The Tauri
desktop app reads the same qa.db.

Schema:
    qa_entries (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        qid         TEXT UNIQUE NOT NULL,      -- e.g. Q-001
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
  append               Append a new entry (auto-increments ID)
  update <ID>          Update an existing entry's solution/status
  next-id              Print the next available ID
  format               Validate and report qa.db structure issues
"""

import argparse
import os
import re
import shutil
import sqlite3
import sys
from datetime import date

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# DB file name. qa_tool.py should be run with cwd = project root.
DB_NAME = "qa.db"
DEFAULT_CWD_DB = os.path.join(os.getcwd(), DB_NAME)

# Valid status values
VALID_STATUSES = {"Pending", "已解决待验证", "已验证", "WontFix", "Unresolved"}

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


def resolve_db_path(explicit=None):
    """Return the path to qa.db.

    Priority:
      1. --db explicit argument
      2. ./qa.db in current working directory (project root)
    """
    if explicit:
        return explicit
    return DEFAULT_CWD_DB


def connect(db_path=None):
    """Open a connection to qa.db, creating the schema if needed."""
    path = resolve_db_path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn):
    """Create the qa_entries table if it does not exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS qa_entries (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            qid        TEXT UNIQUE NOT NULL,
            date       TEXT NOT NULL,
            category   TEXT NOT NULL,
            status     TEXT NOT NULL DEFAULT 'Pending',
            phenomenon TEXT NOT NULL,
            root_cause TEXT DEFAULT '',
            solution   TEXT DEFAULT '',
            files      TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()


def ensure_qa_db(db_path=None):
    """Ensure qa.db exists with the schema. Returns (conn, created)."""
    path = resolve_db_path(db_path)
    created = not os.path.exists(path)
    conn = connect(path)
    ensure_schema(conn)
    return conn, created


def get_next_qid(conn):
    """Find the highest existing QID and return the next one."""
    row = conn.execute("SELECT qid FROM qa_entries ORDER BY CAST(SUBSTR(qid,3) AS INTEGER) DESC LIMIT 1").fetchone()
    if row is None:
        return "Q-001"
    max_num = int(row["qid"][2:])
    return f"Q-{max_num + 1:03d}"


def normalize_id(id_str):
    """Normalize ID to Q-NNN format."""
    id_str = id_str.strip().upper()
    if not id_str.startswith("Q-"):
        num = id_str.lstrip("Q-").lstrip("0") or "1"
        id_str = f"Q-{int(num):03d}"
    return id_str


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


def cmd_summary(args):
    """List all entries: ID + title only."""
    conn = connect(args.db)
    rows = conn.execute(
        "SELECT qid, date, category, status, phenomenon FROM qa_entries ORDER BY id DESC"
    ).fetchall()
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


def cmd_append(args):
    """Append a new entry with auto-generated ID."""
    conn, created = ensure_qa_db(args.db)
    qid = get_next_qid(conn)
    today = date.today().isoformat()
    category = args.category or "Other"
    question = (args.question or "").strip()

    conn.execute(
        """INSERT INTO qa_entries (qid, date, category, status, phenomenon)
           VALUES (?, ?, ?, 'Pending', ?)""",
        (qid, today, category, question),
    )
    conn.commit()
    conn.close()
    print(f"Created {qid}")


def cmd_update(args):
    """Update an existing entry's fields."""
    conn = connect(args.db)
    target = normalize_id(args.id)
    row = conn.execute("SELECT * FROM qa_entries WHERE qid = ?", (target,)).fetchone()
    if row is None:
        print(f"Entry {target} not found.")
        conn.close()
        sys.exit(1)

    def expand(v):
        return v.replace("\\n", "\n") if v else v

    new_status = args.status or row["status"]
    new_phenomenon = expand(args.question) if args.question is not None else row["phenomenon"]
    new_root_cause = expand(args.root_cause) if args.root_cause is not None else (row["root_cause"] or "")
    new_solution = expand(args.answer) if args.answer is not None else (row["solution"] or "")
    new_files = expand(args.files) if args.files is not None else (row["files"] or "")

    conn.execute(
        """UPDATE qa_entries
           SET status = ?, phenomenon = ?, root_cause = ?, solution = ?, files = ?
           WHERE qid = ?""",
        (new_status, new_phenomenon, new_root_cause, new_solution, new_files, target),
    )
    conn.commit()
    conn.close()
    print(f"Updated {target}")


def cmd_next_id(args):
    """Print the next available ID without creating anything."""
    conn = connect(args.db)
    print(get_next_qid(conn))
    conn.close()


def cmd_format(args):
    """Validate and report qa.db structure issues."""
    conn = connect(args.db)
    rows = conn.execute("SELECT * FROM qa_entries ORDER BY id").fetchall()
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
    sub.add_parser("summary", help="List all entries (ID + title)")

    p_get = sub.add_parser("get", help="Get full content of one entry")
    p_get.add_argument("id", help="Entry ID (e.g., Q-003 or just 3)")

    p_append = sub.add_parser("append", help="Append a new entry")
    p_append.add_argument("--category", "-c", help="Category (default: Other)")
    p_append.add_argument("--question", "-q", help="Question/phenomenon text")

    p_update = sub.add_parser("update", help="Update an existing entry")
    p_update.add_argument("id", help="Entry ID")
    p_update.add_argument("--question", "-q", help="New question/phenomenon text")
    p_update.add_argument("--status", "-s", help="New status (Pending, 已解决待验证, 已验证, WontFix, Unresolved)")
    p_update.add_argument("--root-cause", "-r", help="Root cause analysis")
    p_update.add_argument("--answer", "-a", help="Solution steps")
    p_update.add_argument("--files", "-f", help="Files changed table (| File | Change |)")

    p_next = sub.add_parser("next-id", help="Print next available ID")
    sub.add_parser("format", help="Validate qa.db structure")

    args = parser.parse_args()

    commands = {
        "setup": cmd_setup,
        "summary": cmd_summary,
        "get": cmd_get,
        "append": cmd_append,
        "update": cmd_update,
        "next-id": cmd_next_id,
        "format": cmd_format,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
