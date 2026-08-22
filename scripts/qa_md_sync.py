#!/usr/bin/env python3
"""QA.md <-> qa.db incremental sync (qa-log v3).

Two directions:
  sync    (default)  Incrementally sync QA.md -> qa.db. Only *new* entries are
                     inserted and only *changed* entries are updated; unchanged
                     rows are skipped (created_at untouched). Never deletes
                     rows that are missing from QA.md.
  export             Regenerate QA.md from qa.db (useful to recreate the
                     Markdown editing surface or to take a backup).

Usage (run from the project root):
  python <skill-path>/scripts/qa_md_sync.py [sync|export] [--md QA.md] [--db qa.db]
"""
import argparse
import os
import re
import sys

# 共享 DB 逻辑（自动迁移 + 4 位零填充）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import DB_NAME, connect

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MD_NAME = "QA.md"

VALID_STATUSES = {"Pending", "已解决待验证", "已验证", "WontFix", "Unresolved"}

HEADER_RE = re.compile(r"^##\s+(Q-\d+)\s*\|")
SEPARATOR_RE = re.compile(r"^\s*-{3,}\s*$")
SECTION_RE = re.compile(r"^\*\*(.+?):\*\*(.*)$")

# Canonical section labels. Anything else (验证/附注/避坑/...) is folded into
# `solution` so no content is lost.
CANONICAL = {
    "现象/需求": "phenomenon",
    "根因": "root_cause",
    "根因/分析": "root_cause",
    "解决方案": "solution",
    "涉及文件": "files",
}


def map_status(raw):
    raw = (raw or "").strip()
    if raw in VALID_STATUSES:
        return raw
    if raw == "Resolved":
        return "已验证"  # legacy "solved" status
    # Q-0103/Q-0104/Q-0105 put a title in the status slot; treat as completed.
    return "已验证"


# ── QA.md parsing ────────────────────────────────────────────────────────────


def parse_md(text):
    """Parse QA.md into a list of entry dicts."""
    entries = []
    cur = None
    for line in text.splitlines():
        m = HEADER_RE.match(line)
        if m:
            if cur is not None:
                entries.append(cur)
            parts = line[3:].split(" | ", 3)
            cur = {
                "qid": m.group(1),
                "date": parts[1].strip() if len(parts) > 1 else "",
                "category": parts[2].strip() if len(parts) > 2 else "",
                "status_raw": parts[3].strip() if len(parts) > 3 else "",
                "lines": [],
            }
            continue
        if cur is None:
            continue
        if SEPARATOR_RE.match(line):
            continue
        cur["lines"].append(line)
    if cur is not None:
        entries.append(cur)
    return entries


def extract_sections(lines):
    """Return (fields, order) mapping section label -> text content."""
    fields, order = {}, []
    current_label, current_lines = None, []

    def flush():
        if current_label is not None:
            content = "\n".join(current_lines).strip()
            if current_label in fields:
                fields[current_label] = (fields[current_label] + "\n\n" + content).strip()
            else:
                fields[current_label] = content
                order.append(current_label)

    for line in lines:
        m = SECTION_RE.match(line)
        if m:
            flush()
            current_label = m.group(1).strip()
            rest = m.group(2).strip()
            current_lines = [rest] if rest else []
        else:
            if current_label is not None:
                current_lines.append(line)
    flush()
    return fields, order


def entry_to_row(entry):
    fields, order = extract_sections(entry["lines"])
    phenomenon = fields.get("现象/需求", "").strip()
    root_cause = (fields.get("根因") or fields.get("根因/分析") or "").strip()
    solution = fields.get("解决方案", "").strip()
    files = fields.get("涉及文件", "").strip()

    extra = []
    for label in order:
        if label in CANONICAL:
            continue
        content = fields[label].strip()
        if content:
            extra.append(f"**{label}:**\n{content}")
    if extra:
        folded = "\n\n".join(extra)
        solution = f"{solution}\n\n{folded}" if solution else folded

    return (
        entry["date"],
        entry["category"],
        map_status(entry["status_raw"]),
        phenomenon,
        root_cause,
        solution,
        files,
    )


# ── Commands ────────────────────────────────────────────────────────────────


def cmd_sync(md_path, db_path):
    if not os.path.exists(md_path):
        print(f"{md_path} not found — nothing to sync. "
              f"(Run `export` first to regenerate it, or pass --md <path>.)")
        return 1

    with open(md_path, "r", encoding="utf-8-sig") as f:
        entries = parse_md(f.read())

    # connect() 会自动跑 ensure_schema，legacy schema 自动迁移
    conn = connect(db_path)

    added = updated = skipped = 0
    for e in entries:
        row = conn.execute("SELECT * FROM qa_entries WHERE qid=?", (e["qid"],)).fetchone()
        vals = entry_to_row(e)
        if row is None:
            conn.execute(
                "INSERT INTO qa_entries "
                "(qid, date, category, status, phenomenon, root_cause, solution, files) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (e["qid"],) + vals,
            )
            added += 1
        else:
            current = (row["date"], row["category"], row["status"], row["phenomenon"],
                       row["root_cause"], row["solution"], row["files"])
            if current == vals:
                skipped += 1
            else:
                conn.execute(
                    "UPDATE qa_entries SET date=?, category=?, status=?, phenomenon=?, "
                    "root_cause=?, solution=?, files=?, updated_at=datetime('now','localtime') "
                    "WHERE qid=?",
                    vals + (e["qid"],),
                )
                updated += 1

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
    conn.close()

    print(f"Sync {md_path} -> {db_path}: "
          f"{added} added, {updated} updated, {skipped} unchanged "
          f"({len(entries)} parsed; {total} in db)")
    return 0


def cmd_export(db_path, md_path):
    if not os.path.exists(db_path):
        print(f"{db_path} not found — nothing to export.")
        return 1

    conn = connect(db_path)
    # 按 qid 排序输出（旧代码用 id，会在 modern schema 上失败）
    rows = conn.execute("SELECT * FROM qa_entries ORDER BY qid").fetchall()
    conn.close()

    lines = ["# QA 记录", ""]
    for r in rows:
        lines.append(f"## {r['qid']} | {r['date']} | {r['category']} | {r['status']}")
        lines.append("")
        lines.append(f"**现象/需求:** {r['phenomenon']}")
        lines.append("")
        if r["root_cause"]:
            lines.append(f"**根因:** {r['root_cause']}")
            lines.append("")
        if r["solution"]:
            lines.append(f"**解决方案:** {r['solution']}")
            lines.append("")
        if r["files"]:
            lines.append("**涉及文件:**")
            lines.append(r["files"])
            lines.append("")
        lines.append("---")
        lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Exported {len(rows)} entries -> {md_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="QA.md <-> qa.db incremental sync (qa-log v3)"
    )
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "export"],
                        help="sync (QA.md -> qa.db, default) | export (qa.db -> QA.md)")
    parser.add_argument("--md", help=f"Path to {MD_NAME} (default: ./{MD_NAME})")
    parser.add_argument("--db", help=f"Path to {DB_NAME} (default: ./{DB_NAME})")

    args = parser.parse_args()

    md_path = args.md or os.path.join(os.getcwd(), MD_NAME)
    db_path = args.db or os.path.join(os.getcwd(), DB_NAME)

    if args.command == "export":
        sys.exit(cmd_export(db_path, md_path))
    sys.exit(cmd_sync(md_path, db_path))


if __name__ == "__main__":
    main()
