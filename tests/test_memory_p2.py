#!/usr/bin/env python3
"""
记忆系统 P2 自测：schema 迁移 + 审计流水 + 关系表 + history

    python tests/test_memory_p2.py
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import db as qa_db  # noqa: E402

PASS, FAIL = [], []
MEMORY_COLS = ["parent_qid", "importance", "access_count", "last_access_at",
               "tags", "source_session", "source_commit"]


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   {detail}" if detail and not cond else ""))


def run_cli(args, payload=None, cwd=None):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "qa_tool.py")] + args,
                          cwd=cwd, input=(json.dumps(payload, ensure_ascii=False) if payload else None),
                          capture_output=True, text=True, encoding="utf-8")


def columns(conn):
    return [r[1] for r in conn.execute("PRAGMA table_info(qa_entries)")]


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def main():
    d = os.path.join(tempfile.gettempdir(), "qa_p2_test")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    dbp = os.path.join(d, "qa.db")

    print("== 1. 老库迁移（id PK + 无 P2 列）==")
    legacy = sqlite3.connect(dbp)
    legacy.executescript("""
        CREATE TABLE qa_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qid TEXT UNIQUE, date TEXT, category TEXT, status TEXT,
            phenomenon TEXT, root_cause TEXT, solution TEXT, files TEXT,
            created_at TEXT);
        INSERT INTO qa_entries (qid,date,category,status,phenomenon)
            VALUES ('Q-001','2026-01-01','Bug Fix','已验证','老库记录内容，验证迁移不丢数据');
    """)
    legacy.commit()
    legacy.close()

    conn = qa_db.connect(dbp)
    cols = columns(conn)
    check("legacy id-PK 已迁移为 qid PK", "id" not in cols, str(cols[:5]))
    check("P2 记忆列齐备", all(c in cols for c in MEMORY_COLS),
          str([c for c in MEMORY_COLS if c not in cols]))
    check("qa_links/qa_events 已建", {"qa_links", "qa_events"} <= tables(conn), str(tables(conn)))
    n = conn.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
    check("老数据零丢失", n == 1, f"count={n}")

    print("== 2. 幂等（重复 connect）==")
    conn2 = qa_db.connect(dbp)
    check("二次迁移不报错且列不重复", len(columns(conn2)) == len(set(columns(conn2))))
    conn2.close()

    print("== 3. 审计流水 ==")
    p = run_cli(["--db", dbp, "append", "--json"],
                {"category": "Feature", "question": "新增功能：记忆闸门上线后写入需过闸"}, cwd=d)
    check("append 成功", p.returncode == 0 and "Created Q-0002" in p.stdout, p.stdout[:120])
    ev = [r[0] for r in conn.execute("SELECT event FROM qa_events WHERE qid='Q-0002'")]
    check("append 事件已记录", "append" in ev, str(ev))

    p = run_cli(["--db", dbp, "update", "Q-0002", "--json"],
                {"root_cause": "闸门未接入所有写入通道", "solution": "统一在 memory_guard 收口"}, cwd=d)
    ev = [r[0] for r in conn.execute("SELECT event FROM qa_events WHERE qid='Q-0002' ORDER BY id")]
    check("update 事件已记录", ev.count("update") >= 1, str(ev))

    run_cli(["--db", dbp, "update", "Q-0002", "--json"], {"status": "已验证"}, cwd=d)
    ev = [r[0] for r in conn.execute("SELECT event FROM qa_events WHERE qid='Q-0002' ORDER BY id")]
    check("verify 事件独立记录", "verify" in ev, str(ev))

    print("== 4. split 关系 ==")
    conn.execute("INSERT INTO qa_entries (qid,date,category,status,phenomenon,files)"
                 " VALUES ('Q-0100','2026-10-08','Feature','Pending','多模块改造记录', ?)",
                 ("| File | Change |\n|------|--------|\n"
                  "| src/a/x.cs | a |\n| src/b/y.cs | b |\n| src/c/z.cs | c |",))
    conn.commit()
    p = run_cli(["--db", dbp, "split", "Q-0100", "--apply", "--yes"], cwd=d)
    links = conn.execute("SELECT from_qid, to_qid, kind FROM qa_links").fetchall()
    check("split 建立 derived_from 关系", any(l[2] == "derived_from" and l[1] == "Q-0100" for l in links), str(links))
    ev = [r[0] for r in conn.execute("SELECT event FROM qa_events WHERE qid='Q-0100'")]
    check("父条目 split 事件", "split" in ev, str(ev))

    print("== 5. 删除留痕 ==")
    run_cli(["--db", dbp, "delete", "Q-0002", "-f"], cwd=d)
    gone = conn.execute("SELECT COUNT(*) FROM qa_entries WHERE qid='Q-0002'").fetchone()[0]
    ev = [r[0] for r in conn.execute("SELECT event FROM qa_events WHERE qid='Q-0002' ORDER BY id")]
    check("条目已删除", gone == 0)
    check("删除后仍有审计流水（delete 事件）", "delete" in ev, str(ev))

    print("== 6. history 命令 ==")
    p = run_cli(["--db", dbp, "history", "Q-0002"], cwd=d)
    check("history 打印已删条目流水", "已不存在" in p.stdout and "delete" in p.stdout, p.stdout[:200])
    p = run_cli(["--db", dbp, "history", "Q-0100"], cwd=d)
    check("history 打印关系与子条目", ("derived_from" in p.stdout) and ("子条目" in p.stdout), p.stdout[:200])

    print("== 7. 真实库迁移回归（副本）==")
    real = os.path.join(ROOT, "qa.db")
    if os.path.isfile(real):
        copy = os.path.join(d, "copy.db")
        shutil.copy2(real, copy)
        c1 = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        before = c1.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
        c1.close()
        c2 = qa_db.connect(copy)
        after = c2.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
        check("真实库副本迁移后条数不变", before == after, f"{before} -> {after}")
        check("副本补齐 P2 列", all(x in columns(c2) for x in MEMORY_COLS))
        c2.close()

    conn.close()
    shutil.rmtree(d, ignore_errors=True)
    print(f"\n== 结果：{len(PASS)} passed, {len(FAIL)} failed ==")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())