#!/usr/bin/env python3
"""搜索 qa.db 中的 QA 条目。"""
import argparse
import os
import sqlite3
import sys

# 强制 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_NAME = "qa.db"


def resolve_db_path(explicit=None):
    """默认读取当前工作目录（项目根目录）的 qa.db。"""
    if explicit:
        return explicit
    return os.path.join(os.getcwd(), DB_NAME)


def connect(db_path=None):
    path = resolve_db_path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def search_entries(conn, query=None, status=None, category=None, limit=10):
    """在 qa.db 中搜索条目，支持关键词/状态/类别过滤。"""
    clauses = []
    params = []

    if status:
        clauses.append("status = ?")
        params.append(status)
    if category:
        clauses.append("category LIKE ?")
        params.append(f"%{category}%")
    if query:
        clauses.append(
            "(qid LIKE ? OR phenomenon LIKE ? OR root_cause LIKE ? OR solution LIKE ? OR files LIKE ?)"
        )
        kw = f"%{query}%"
        params.extend([kw, kw, kw, kw, kw])

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"SELECT * FROM qa_entries{where} ORDER BY id DESC LIMIT ?"
    params.append(limit)

    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        # 表不存在等
        return []


def main():
    parser = argparse.ArgumentParser(description="Search qa.db entries")
    parser.add_argument("query", nargs="?", help="Search query (keyword or Q-ID)")
    parser.add_argument("-s", "--status", help="Filter by status (Pending, 已解决待验证, 已验证, WontFix, Unresolved)")
    parser.add_argument("-c", "--category", help="Filter by category (Bug Fix, Feature, etc.)")
    parser.add_argument("-n", "--limit", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--db", help="Path to qa.db (default: ./qa.db)")

    args = parser.parse_args()

    if not os.path.exists(resolve_db_path(args.db)):
        print(f"{resolve_db_path(args.db)} not found. Run 'python scripts/qa_tool.py init' first.")
        return

    conn = connect(args.db)
    results = search_entries(conn, args.query, args.status, args.category, args.limit)

    if not results:
        print("No matching entries found.")
        conn.close()
        return

    print(f"Found {len(results)} entries:\n")
    for r in results:
        print(f"## {r['qid']} | {r['date']} | {r['category']} | {r['status']}")
        summary = (r["phenomenon"] or "")[:100]
        print(f"{summary}...")
        print("---")
    conn.close()


if __name__ == "__main__":
    main()
