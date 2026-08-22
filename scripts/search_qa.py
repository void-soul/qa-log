#!/usr/bin/env python3
"""搜索 qa.db 中的 QA 条目。"""
import argparse
import os
import sys

# 共享 DB 逻辑（自动迁移 + 4 位零填充）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import connect, resolve_db_path

# 强制 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


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
    sql = f"SELECT * FROM qa_entries{where} ORDER BY qid DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def main():
    parser = argparse.ArgumentParser(description="Search qa.db entries")
    parser.add_argument("query", nargs="?", help="Search query (keyword or Q-ID)")
    parser.add_argument("-s", "--status", help="Filter by status (Pending, 已解决待验证, 已验证, WontFix, Unresolved)")
    parser.add_argument("-c", "--category", help="Filter by category (Bug Fix, Feature, etc.)")
    parser.add_argument("-n", "--limit", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--db", help="Path to qa.db (default: ./qa.db)")

    args = parser.parse_args()

    db_path = resolve_db_path(args.db)
    if not os.path.exists(db_path):
        print(f"{db_path} not found. Run 'python scripts/qa_tool.py setup' first.")
        return

    # connect() 会自动跑 ensure_schema，legacy DB 也能开
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
