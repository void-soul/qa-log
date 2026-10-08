"""搜索 qa.db 中的 QA 条目（薄封装：统一走 memory_recall 的加权召回）。

与 `qa_tool.py recall` 同源：字段权重 + 重要性 + 召回次数 + 新鲜度 + 关系引用，
命中后回写召回反馈（access_count / last_access_at + recall 事件）。
加 --no-feedback 可退回纯查询语义。
"""
import argparse
import os
import sys

# 共享 DB 逻辑（自动迁移 + 4 位零填充）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import connect, resolve_db_path

# 强制 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import memory_recall as MR


def search_entries(conn, query=None, status=None, category=None, limit=10,
                   include_archived=False, feedback=False):
    """加权召回（返回 dict 列表）。无 query 时退化为最新列表。"""
    if not query:
        rows = conn.execute(
            "SELECT qid, date, category, status, phenomenon FROM qa_entries"
            " WHERE COALESCE(archived,0)=? ORDER BY qid DESC LIMIT ?",
            (0 if not include_archived else 1, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    return MR.recall(conn, query, limit=limit, include_archived=include_archived,
                     feedback=feedback, status=status, category=category)


def main():
    parser = argparse.ArgumentParser(description="Search qa.db entries (weighted recall)")
    parser.add_argument("query", nargs="?", help="Search query (keyword or Q-ID)")
    parser.add_argument("-s", "--status", help="Filter by status")
    parser.add_argument("-c", "--category", help="Filter by category")
    parser.add_argument("-n", "--limit", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--db", help="Path to qa.db (default: ./qa.db)")
    parser.add_argument("--no-feedback", action="store_true", help="只查不改（不回写召回反馈）")
    parser.add_argument("--include-archived", action="store_true", help="包含已归档条目")

    args = parser.parse_args()

    db_path = resolve_db_path(args.db)
    if not os.path.exists(db_path):
        print("%s not found. Run 'python scripts/qa_tool.py setup' first." % db_path)
        return

    conn = connect(args.db)
    results = search_entries(conn, args.query, args.status, args.category, args.limit,
                             include_archived=args.include_archived,
                             feedback=not args.no_feedback)
    if not results:
        print("No matching entries found.")
        conn.close()
        return

    print("Found %d entries:\n" % len(results))
    for r in results:
        score = "  score=%.3f" % r["score"] if "score" in r else ""
        print("## %s | %s | %s | %s%s" % (r["qid"], r["date"], r["category"], r["status"], score))
        print((r.get("phenomenon") or r.get("title") or "")[:100] + "...")
        print("---")
    conn.close()


if __name__ == "__main__":
    main()