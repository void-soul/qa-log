#!/usr/bin/env python3
"""
qa.db 查询接口（JSON 输出）—— 供 VSCode 插件等外部调用。

插件通过子进程调用本脚本获取数据，避免 Node 侧 SQLite 依赖与版本差异；
同时复用 scripts/db.py 的 schema 保证（自动建表 / 自动迁移）。

用法
----
  python qa_query.py --db <qa.db> <action> [options]

actions
  qa-list      [--limit N] [--status S] [--category C] [--query Q]   列出 QA 记录
  qa-get       --qid Q-0001                                          单条 QA 记录
  log-list     [--limit N] [--project P] [--session S] [--event E] [--query Q]
                                                                    列出 Agent 日志
  log-sessions [--limit N] [--project P]                             Agent 会话汇总
  projects                                                           出现过的项目列表
  stats                                                              统计信息

输出（始终为单行 JSON，便于插件解析）
  {"ok": true,  "data": ...}
  {"ok": false, "error": "..."}
"""

import argparse
import json
import os
import sqlite3
import sys

for _s in (sys.stdout, sys.stderr, sys.stdin):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_NAME = "qa.db"


def emit(ok, data=None, error=None):
    """输出单行 JSON 并退出。"""
    payload = {"ok": ok}
    if ok:
        payload["data"] = data
    else:
        payload["error"] = error
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0 if ok else 1)


def connect(db_path):
    """打开 qa.db（只读打开失败则退回普通打开），并确保 schema 存在。"""
    import db as qa_db

    if not os.path.isfile(db_path):
        emit(False, error=f"qa.db not found: {db_path}")

    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        qa_db.ensure_schema(conn)
    except Exception:
        # 只读挂载等场景下建表失败不应阻塞查询
        pass
    return conn


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


# ── actions ────────────────────────────────────────────────────────────────

def act_qa_list(conn, a):
    sql = "SELECT qid, date, category, status, phenomenon, root_cause, solution, files, created_at, updated_at FROM qa_entries"
    where, params = [], []
    if a.status:
        where.append("status = ?")
        params.append(a.status)
    if a.category:
        where.append("category LIKE ?")
        params.append(f"%{a.category}%")
    if a.query:
        where.append("(qid LIKE ? OR phenomenon LIKE ? OR root_cause LIKE ? OR solution LIKE ? OR files LIKE ?)")
        kw = f"%{a.query}%"
        params += [kw] * 5
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY qid DESC"
    if a.limit:
        sql += " LIMIT ?"
        params.append(a.limit)
    emit(True, {"entries": rows_to_dicts(conn.execute(sql, params).fetchall())})


def act_qa_get(conn, a):
    qid = (a.qid or "").strip().upper()
    if not qid.startswith("Q-"):
        qid = "Q-" + qid.lstrip("Q-").zfill(4)
    row = conn.execute("SELECT * FROM qa_entries WHERE qid = ?", (qid,)).fetchone()
    if row is None:
        emit(False, error=f"not found: {qid}")
    emit(True, {"entry": dict(row)})


def act_log_list(conn, a):
    sql = ("SELECT id, session_id, project, seq, event, role, title, content, meta, created_at "
           "FROM agent_log")
    where, params = [], []
    if a.id:
        where.append("id = ?")
        params.append(a.id)
    if a.project:
        where.append("project LIKE ?")
        params.append(f"%{a.project}%")
    if a.session:
        where.append("session_id = ?")
        params.append(a.session)
    if a.event:
        where.append("event = ?")
        params.append(a.event)
    if a.query:
        where.append("(title LIKE ? OR content LIKE ?)")
        kw = f"%{a.query}%"
        params += [kw, kw]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id DESC"
    if a.limit:
        sql += " LIMIT ?"
        params.append(a.limit)
    emit(True, {"logs": rows_to_dicts(conn.execute(sql, params).fetchall())})


def act_log_sessions(conn, a):
    sql = """
        SELECT session_id,
               MAX(project)                                   AS project,
               MIN(created_at)                                AS started_at,
               MAX(created_at)                                AS ended_at,
               COUNT(*)                                       AS total,
               SUM(CASE WHEN event='user_prompt'     THEN 1 ELSE 0 END) AS prompts,
               SUM(CASE WHEN event='tool_use'        THEN 1 ELSE 0 END) AS tools,
               SUM(CASE WHEN event='assistant_reply' THEN 1 ELSE 0 END) AS replies,
               (SELECT title FROM agent_log b
                 WHERE b.session_id = agent_log.session_id AND b.event='user_prompt'
                 ORDER BY b.id LIMIT 1)                      AS first_prompt
        FROM agent_log AS agent_log
    """
    where, params = [], []
    if a.project:
        where.append("project LIKE ?")
        params.append(f"%{a.project}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY session_id ORDER BY ended_at DESC"
    if a.limit:
        sql += " LIMIT ?"
        params.append(a.limit)
    emit(True, {"sessions": rows_to_dicts(conn.execute(sql, params).fetchall())})


def act_projects(conn, a):
    rows = conn.execute(
        "SELECT project, COUNT(DISTINCT session_id) AS sessions, COUNT(*) AS logs, "
        "MIN(created_at) AS first_seen, MAX(created_at) AS last_seen "
        "FROM agent_log WHERE project <> '' GROUP BY project ORDER BY last_seen DESC"
    ).fetchall()
    emit(True, {"projects": rows_to_dicts(rows)})


def act_stats(conn, a):
    qa = conn.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
    st = rows_to_dicts(conn.execute(
        "SELECT status, COUNT(*) AS n FROM qa_entries GROUP BY status ORDER BY n DESC"
    ).fetchall())
    logs = conn.execute("SELECT COUNT(*) FROM agent_log").fetchone()[0]
    sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM agent_log").fetchone()[0]
    emit(True, {"qa_total": qa, "qa_by_status": st, "log_total": logs, "log_sessions": sessions})


ACTIONS = {
    "qa-list": act_qa_list,
    "qa-get": act_qa_get,
    "log-list": act_log_list,
    "log-sessions": act_log_sessions,
    "projects": act_projects,
    "stats": act_stats,
}


def main():
    p = argparse.ArgumentParser(description="qa.db JSON query interface")
    p.add_argument("action", choices=sorted(ACTIONS.keys()))
    p.add_argument("--db", default=os.path.join(os.getcwd(), DB_NAME),
                   help="path to qa.db (default: ./qa.db)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--status")
    p.add_argument("--category")
    p.add_argument("--query")
    p.add_argument("--qid")
    p.add_argument("--id", type=int, help="agent_log 主键精确匹配（log-list 用）")
    p.add_argument("--project")
    p.add_argument("--session")
    p.add_argument("--event")
    a = p.parse_args()

    try:
        conn = connect(a.db)
    except SystemExit:
        raise
    except Exception as e:
        emit(False, error=f"open db failed: {e}")

    try:
        ACTIONS[a.action](conn, a)
    except Exception as e:
        emit(False, error=f"{type(e).__name__}: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
