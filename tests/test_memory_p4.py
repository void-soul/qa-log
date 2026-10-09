#!/usr/bin/env python3
"记忆系统 P4 自测：衰减归档 + 冲突检测 + 健康报告"
import json as _json
import os, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
import db as qa_db
import memory_health as MH
import memory_recall as MR
PASS, FAIL = [], []

def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "  PASS  " if cond else "  FAIL  "
    extra = ""
    if detail and not cond:
        extra = "   " + str(detail)
    print(mark + name + extra)

def run_cli(args, cwd=None):
    cmd = [sys.executable, os.path.join(SCRIPTS, "qa_tool.py")] + args
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")

def add(conn, qid, phen, status="已验证", root="", sol="",
        files="", imp=50, acc=0, updated=None):
    sql = "INSERT INTO qa_entries (qid,date,category,status,phenomenon,root_cause,solution,files,importance,access_count,updated_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
    vals = (qid, "2026-10-08", "Bug Fix", status, phen, root, sol, files, imp, acc,
            updated, "2026-10-08 00:00:00")
    conn.execute(sql, vals)
    conn.commit()

TBL_A = "| File | Change |\n|------|--------|\n| src/a.py | x |\n"
TBL_B = "| File | Change |\n|------|--------|\n| src/b.py | y |\n"

def main():
    d = os.path.join(tempfile.gettempdir(), "qa_p4_test")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    dbp = os.path.join(d, "qa.db")
    conn = qa_db.connect(dbp)

    print("== 1. schema ==")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(qa_entries)")]
    check("needs_review column", "needs_review" in cols, cols)

    print("== 2. archive suggestions ==")
    add(conn, "Q-0001", "某功能已确认不做，记录原因备查", status="WontFix")
    add(conn, "Q-0002", "另一条已解决但从未被召回的旧记录内容",
        status="已解决待验证", updated="2024-01-01 00:00:00")
    add(conn, "Q-0003", "高频使用的记录不应被归档处理",
        status="已解决待验证", updated="2024-01-01 00:00:00", acc=9, imp=90)
    sugg = MH.suggest_archive(conn)
    qids = set(s["qid"] for s in sugg)
    check("terminal+cold suggested", "Q-0001" in qids, qids)
    check("stale+cold suggested", "Q-0002" in qids, qids)
    check("hot entry not suggested", "Q-0003" not in qids, qids)

    print("== 3. archive apply / restore ==")
    p = run_cli(["--db", dbp, "prune"], cwd=d)
    check("prune defaults to dry-run", "dry-run" in p.stdout, p.stdout[-120:])
    n0 = conn.execute("SELECT COUNT(*) FROM qa_entries WHERE archived=1").fetchone()[0]
    check("dry-run changes nothing", n0 == 0, n0)
    p = run_cli(["--db", dbp, "prune", "--apply", "--yes"], cwd=d)
    n1 = conn.execute("SELECT COUNT(*) FROM qa_entries WHERE archived=1").fetchone()[0]
    check("--apply archives", n1 >= 2, n1)
    ev = [r[0] for r in conn.execute("SELECT event FROM qa_events WHERE qid=?", ("Q-0001",))]
    check("archive event logged", "archive" in ev, ev)
    p = run_cli(["--db", dbp, "prune", "--restore", "Q-0001"], cwd=d)
    n2 = conn.execute("SELECT COUNT(*) FROM qa_entries WHERE qid=? AND archived=1", ("Q-0001",)).fetchone()[0]
    check("--restore un-archives", n2 == 0, n2)

    print("== 4. archived excluded from recall ==")
    conn.execute("UPDATE qa_entries SET archived=1 WHERE qid=?", ("Q-0001",))
    conn.commit()
    hits = MR.recall(conn, "已确认不做", limit=5, feedback=False)
    got = [h["qid"] for h in hits]
    check("archived not recalled", "Q-0001" not in got, got)
    hits = MR.recall(conn, "已确认不做", limit=5, feedback=False, include_archived=True)
    got2 = [h["qid"] for h in hits]
    check("include_archived shows it", "Q-0001" in got2, got2)
    conn.execute("UPDATE qa_entries SET archived=0 WHERE qid=?", ("Q-0001",))
    conn.commit()

    print("== 5. conflict detection ==")
    add(conn, "Q-0010", "导出文件中文乱码，需要修复编码处理",
        root="模板未指定编码", sol="读取时指定 UTF-8",
        files=TBL_A)
    add(conn, "Q-0011", "导出文件中文乱码，需要排查编码链路问题",
        root="CSV 分隔符与转义规则冲突导致列错位错乱", sol="改用制表符并转义双引号",
        files=TBL_B)
    cs = MH.find_conflicts(conn)
    pairs = set(tuple(sorted([c["a"], c["b"]])) for c in cs)
    check("conflict pair found", ("Q-0010", "Q-0011") in pairs, pairs)
    p = run_cli(["--db", dbp, "conflicts"], cwd=d)
    check("conflicts default dry-run", "dry-run" in p.stdout, p.stdout[-120:])
    nr0 = conn.execute("SELECT COUNT(*) FROM qa_entries WHERE needs_review=1").fetchone()[0]
    check("dry-run does not mark", nr0 == 0, nr0)
    p = run_cli(["--db", dbp, "conflicts", "--link"], cwd=d)
    nr1 = conn.execute("SELECT COUNT(*) FROM qa_entries WHERE needs_review=1").fetchone()[0]
    check("--link sets needs_review", nr1 >= 2, nr1)
    lk = conn.execute("SELECT kind FROM qa_links WHERE kind=?", ("contradicts",)).fetchone()
    check("contradicts link written", lk is not None, lk)

    print("== 6. health report ==")
    r = MH.health_report(conn)
    keys = ("total", "by_status", "archived", "needs_review",
            "stale_pending", "orphans", "duplicate_pairs", "conflicts")
    check("report has key fields", all(k in r for k in keys), sorted(r.keys()))
    check("total matches rows", r["total"] >= 5, r["total"])
    p = run_cli(["--db", dbp, "health", "--json"], cwd=d)
    ok = False
    try:
        j = _json.loads(p.stdout)
        ok = j.get("total") == r["total"]
    except Exception:
        ok = False
    check("health --json emits valid JSON", ok, p.stdout[:120])

    print("== 7. real-db copy regression ==")
    real = os.path.join(ROOT, "qa.db")
    if os.path.isfile(real):
        copy = os.path.join(d, "copy.db")
        shutil.copy2(real, copy)
        c1 = qa_db.connect(copy)
        n1 = c1.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
        rr = MH.health_report(c1)
        n2 = c1.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
        check("health report is read-only", n1 == n2, (n1, n2))
        check("real db report ok", rr["total"] == n1, rr["total"])
        c1.close()

    conn.close()
    shutil.rmtree(d, ignore_errors=True)
    print()
    print("== result: {} passed, {} failed ==".format(len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  FAILED: " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ── 标准 runner 接入（pytest / python -m unittest discover）───────────────────
# 断言写在 main() 里；不加这段的话标准 runner 会报 "Ran 0 tests ... OK"（假绿）。
from _harness import make_script_test_case  # noqa: E402

TestChecks = make_script_test_case(__name__)
