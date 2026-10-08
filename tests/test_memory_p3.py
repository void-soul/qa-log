#!/usr/bin/env python3
"""记忆系统 P3 自测：加权召回 + 召回反馈 + 巩固（去重合并 / 模式提炼）

    python tests/test_memory_p3.py
"""
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
import db as qa_db
import memory_recall as MR

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + str(detail)) if detail and not cond else ""))


def run_cli(args, cwd=None):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "qa_tool.py")] + args,
                          cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def add(conn, qid, cat, phen, root="", sol="", files="", imp=50):
    conn.execute("INSERT INTO qa_entries (qid,date,category,status,phenomenon,root_cause,"
                 "solution,files,importance) VALUES (?,?,?,?,?,?,?,?,?)",
                 (qid, "2026-10-08", cat, "已验证", phen, root, sol, files, imp))
    conn.commit()


def main():
    d = os.path.join(tempfile.gettempdir(), "qa_p3_test")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    dbp = os.path.join(d, "qa.db")
    conn = qa_db.connect(dbp)

    print("== 1. schema ==")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(qa_entries)")]
    check("archived 列存在", "archived" in cols, cols)

    print("== 2. 加权召回 ==")
    add(conn, "Q-0001", "Bug Fix", "相机预览流偶发黑屏，重启相机后恢复",
        "预览 URL 模板命中主码流，RTP 会话未重建", "切换类型时重建预览会话",
        "| File | Change |\n|------|--------|\n| src/Camera.cs | 重建会话 |")
    add(conn, "Q-0002", "Feature", "新增批量导出功能，支持 CSV 与 Excel",
        "导出逻辑分散在各页面", "统一导出服务",
        "| File | Change |\n|------|--------|\n| src/Export.cs | 新增 |")
    add(conn, "Q-0003", "Bug Fix", "预览黑屏问题排查：与 RTP 会话重建时机相关",
        "会话重建时机晚于首帧请求", "提前重建时机",
        "| File | Change |\n|------|--------|\n| src/Camera.cs | 提前重建 |", imp=80)
    hits = MR.recall(conn, "预览 黑屏 RTP 会话", limit=5, feedback=False)
    top = [h["qid"] for h in hits]
    check("命中相机相关条目", "Q-0001" in top and "Q-0003" in top, top)
    check("导出条目排后", top.index("Q-0002") > top.index("Q-0001") if "Q-0002" in top else True, top)
    s3 = [h["score"] for h in hits if h["qid"] == "Q-0003"]
    s1 = [h["score"] for h in hits if h["qid"] == "Q-0001"]
    check("高 importance 得分更高", bool(s3 and s1 and s3[0] > s1[0]), [(h["qid"], h["score"]) for h in hits])

    print("== 3. 召回反馈闭环 ==")
    b = conn.execute("SELECT access_count FROM qa_entries WHERE qid='Q-0001'").fetchone()[0]
    MR.recall(conn, "预览 黑屏 RTP 会话", limit=5, feedback=True)
    a, la = conn.execute("SELECT access_count, last_access_at FROM qa_entries WHERE qid='Q-0001'").fetchone()
    check("access_count 递增", (a or 0) == (b or 0) + 1, "%s->%s" % (b, a))
    check("last_access_at 回写", bool(la), la)
    ev = [r[0] for r in conn.execute("SELECT event FROM qa_events WHERE qid='Q-0001'")]
    check("recall 事件记录", "recall" in ev, ev)

    print("== 4. 归档默认排除 ==")
    conn.execute("UPDATE qa_entries SET archived=1 WHERE qid='Q-0002'")
    conn.commit()
    h1 = MR.recall(conn, "批量导出 CSV", limit=5, feedback=False)
    check("归档默认排除", all(h["qid"] != "Q-0002" for h in h1), [h["qid"] for h in h1])
    h2 = MR.recall(conn, "批量导出 CSV", limit=5, feedback=False, include_archived=True)
    check("include_archived 可召回", any(h["qid"] == "Q-0002" for h in h2), [h["qid"] for h in h2])
    conn.execute("UPDATE qa_entries SET archived=0 WHERE qid='Q-0002'")
    conn.commit()

    print("== 5. 巩固：近似 + 合并 ==")
    add(conn, "Q-0004", "Bug Fix", "相机预览流偶发黑屏，重启相机后可以恢复",
        "预览 URL 模板命中主码流，RTP 会话未重建", "切换相机类型时重建预览会话",
        "| File | Change |\n|------|--------|\n| src/Camera.cs | 重建预览会话 |")
    pairs = MR.find_near_duplicates(conn, threshold=0.6)
    keys = [{p["a"], p["b"]} for p in pairs]
    check("发现近似对", {"Q-0001", "Q-0004"} in keys,
          "%s / scores=%s" % (keys[:5], [(p["a"], p["b"], p["score"]) for p in pairs]))
    # keep_hint = 信息量更大的一方保留（本例 Q-0004 文本更长 → 留Q-0004，Q-0001 归档）
    hint = [p for p in pairs if {p["a"], p["b"]} == {"Q-0001", "Q-0004"}][0]
    keep_qid = hint["keep_hint"]
    drop_qid = hint["b"] if keep_qid == hint["a"] else hint["a"]
    p = run_cli(["--db", dbp, "consolidate", "--threshold", "0.6"], cwd=d)
    check("默认 dry-run", "dry-run" in p.stdout, p.stdout[-120:])
    p = run_cli(["--db", dbp, "consolidate", "--threshold", "0.6", "--apply", "--yes"], cwd=d)
    check("--apply 合并", "merged:" in p.stdout, p.stdout[-160:])
    row = conn.execute("SELECT archived FROM qa_entries WHERE qid=?", (drop_qid,)).fetchone()
    check("丢弃方归档未删除", bool(row) and row[0] == 1, "%s archived=%s" % (drop_qid, row and row[0]))
    keep = conn.execute("SELECT files FROM qa_entries WHERE qid=?", (keep_qid,)).fetchone()[0]
    check("保留方文件并入", "src/Camera.cs" in keep, keep[:60])
    lk = conn.execute("SELECT kind FROM qa_links WHERE from_qid=? AND to_qid=?",
                      (keep_qid, drop_qid)).fetchone()
    check("supersedes 关系", bool(lk) and lk[0] == "supersedes", lk)
    ev = [r[0] for r in conn.execute("SELECT event FROM qa_events WHERE qid=?", (drop_qid,))]
    check("merge 事件", "merge" in ev, ev)

    print("== 6. 模式提炼 ==")
    for i in range(1, 6):
        add(conn, "Q-01%02d" % i, "Refactor",
            "抽出统一的相机参数映射表，服务于预览与回放两条链路",
            "参数映射散落各处", "抽取共享映射表",
            "| File | Change |\n|------|--------|\n| src/Camera/Map.cs | 抽取 |")
    groups = MR.suggest_patterns(conn, min_size=5, min_sim=0.4)
    check("模式候选组", any("Q-0101" in g["qids"] for g in groups),
          [(g["category"], g["size"]) for g in groups])

    print("== 7. CLI recall / search_qa ==")
    p = run_cli(["--db", dbp, "recall", "预览 黑屏", "-n", "3"], cwd=d)
    check("recall CLI 输出分数+反馈提示", "已回写召回反馈" in p.stdout and "score=" in p.stdout, p.stdout[:150])
    p = run_cli(["--db", dbp, "recall", "--qid", "Q-0001", "-n", "3", "--no-feedback"], cwd=d)
    check("recall --qid 找相似", p.returncode == 0 and "Recall" in p.stdout, p.stdout[:120])
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "search_qa.py"), "预览",
                        "--db", dbp, "--no-feedback"], capture_output=True, text=True, encoding="utf-8")
    check("search_qa.py 可用", p.returncode == 0 and "Found" in p.stdout, p.stdout[:120])

    print("== 8. 真实库副本回归 ==")
    real = os.path.join(ROOT, "qa.db")
    if os.path.isfile(real):
        copy = os.path.join(d, "copy.db")
        shutil.copy2(real, copy)
        c1 = qa_db.connect(copy)
        n1 = c1.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
        hits = MR.recall(c1, "写入闸门", limit=5, feedback=False)
        n2 = c1.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
        check("召回不改数据", n1 == n2, "%d->%d" % (n1, n2))
        check("真实库可召回 Q-0003", any(h["qid"] == "Q-0003" for h in hits), [h["qid"] for h in hits])
        c1.close()

    conn.close()
    shutil.rmtree(d, ignore_errors=True)
    print("\n== 结果：%d passed, %d failed ==" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())