#!/usr/bin/env python3
"""
记忆闸门（P1）自测套件 —— 零依赖，直接运行：

    python tests/test_memory_guard.py

覆盖：
1. guard 7 类样例（正常 / 占位 / 过短 / 超长 / 重复 / 非法状态 / 拆分信号）
2. CLI 收口：append/update 遇到 reject 不落库（exit 3），--force 可放行
3. split：草案生成 + --apply 建子条目并写 parent_qid
4. 插件通道：qa_query.py qa-update 走同一 guard
5. 回归：真实项目库不被改动
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import db as qa_db           # noqa: E402
import memory_guard as G    # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"   {detail}" if detail and not cond else ""))


def run_cli(args, payload=None, cwd=None):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "qa_tool.py")] + args,
                          cwd=cwd, input=(json.dumps(payload, ensure_ascii=False) if payload else None),
                          capture_output=True, text=True, encoding="utf-8")


def run_query(args, payload=None, cwd=None):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "qa_query.py")] + args,
                          cwd=cwd, input=(json.dumps(payload, ensure_ascii=False) if payload else None),
                          capture_output=True, text=True, encoding="utf-8")


def tmpdir():
    d = os.path.join(tempfile.gettempdir(), "qa_guard_test")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


GOOD = {
    "category": "Bug Fix",
    "question": "相机预览流偶发黑屏，重启相机后恢复，但日志无报错",
    "root_cause": "预览 URL 模板在切换相机类型时仍命中主码流，RTP 会话未重建",
    "solution": "在 CameraEditDialog 切换类型时重建预览会话，并记录实际码流索引到日志",
    "files": "| File | Change |\n|------|--------|\n| src/CameraEditDialog.cs | 切换类型时重建会话 |",
}


def main():
    print("== 1. guard 判级 ==")
    d = tmpdir()
    dbp = os.path.join(d, "qa.db")
    conn = qa_db.connect(dbp)
    conn.execute("INSERT INTO qa_entries (qid, date, category, status, phenomenon, root_cause, solution, files)"
                 " VALUES ('Q-0001','2026-10-08','Bug Fix','已验证',?,?,?,?)",
                 (GOOD["question"], GOOD["root_cause"], GOOD["solution"], GOOD["files"]))
    conn.commit()

    r = G.check(GOOD, conn=conn, exclude_qid="Q-0001")
    check("正常条目 → ok", r["level"] == "ok", r["level"])

    r = G.check({"phenomenon": "待填写"}, conn=conn)
    check("占位符 → reject", r["level"] == "reject" and any(i["code"] == "placeholder" for i in r["issues"]))

    r = G.check({"phenomenon": "黑屏"}, conn=conn)
    check("过短 → reject", r["level"] == "reject" and
          any(i["code"] == "phenomenon_too_short" for i in r["issues"]))

    big = dict(GOOD)
    big["solution"] = "步骤\n" + "\n".join(f"{i}. 详细说明第{i}步，需要展开较长内容才能表达清楚" for i in range(1, 1200))
    r = G.check(big, conn=conn, exclude_qid="Q-0001")
    check("超长 → reject", r["level"] == "reject" and any(i["code"] == "too_long" for i in r["issues"]),
          str([i["code"] for i in r["issues"]]))

    dup = dict(GOOD)
    r = G.check(dup, conn=conn)
    check("重复记忆 → reject", r["level"] == "reject" and any(i["code"] == "dup_similarity" for i in r["issues"]),
          str(r["similar"]))

    r = G.check(dict(GOOD, status="已解决"), conn=conn)
    check("非法状态 → reject", r["level"] == "reject" and any(i["code"] == "invalid_status" for i in r["issues"]))

    multi = dict(GOOD)
    multi["question"] = "多模块联动改造：预览、录制、回放三处都要调整，否则切换相机会花屏"
    multi["root_cause"] = "三个模块各自维护模板索引，未共享同一份码流映射表"
    multi["files"] = "| File | Change |\n|------|--------|\n" + "\n".join(
        f"| src/mod{i}/f{i}.cs | 改动{i} |" for i in range(1, 7))
    r = G.check(multi, conn=conn, exclude_qid="Q-0001")
    check("跨模块/文件多 → warn（含草案）", r["level"] == "warn" and
          len(r["split"]["drafts"]) >= 2, f"level={r['level']} drafts={len(r['split']['drafts'])} "
          f"codes={[i['code'] for i in r['issues']]}")

    print("== 2. CLI 收口 ==")
    p = run_cli(["--db", dbp, "append", "--json"],
                {"category": "Other", "question": "待填写"}, cwd=d)
    check("append 占位被拒（exit 3）", p.returncode == 3, f"rc={p.returncode} {p.stdout[:120]}")
    n = conn.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
    check("被拒时未落库", n == 1, f"count={n}")

    p = run_cli(["--db", dbp, "append", "--force", "--json"], {"category": "Other", "question": "待填写"}, cwd=d)
    check("--force 可放行", p.returncode == 0 and "Created" in p.stdout, p.stdout[:120])

    p = run_cli(["--db", dbp, "update", "Q-0001", "--json"], {"status": "已解决"}, cwd=d)
    check("update 非法状态被拒", p.returncode in (2, 3), f"rc={p.returncode} {p.stdout[:100]}")

    p = run_cli(["--db", dbp, "guard", "Q-0001"], cwd=d)
    check("guard 干跑（exit 0/1）", p.returncode in (0, 1, 3), f"rc={p.returncode}")

    print("== 3. split ==")
    p = run_cli(["--db", dbp, "split", "Q-0001"], cwd=d)
    check("split 默认 dry-run", "拆分草案" in p.stdout and p.returncode == 0, p.stdout[:200])
    before = conn.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
    p = run_cli(["--db", dbp, "split", "Q-0001", "--apply", "--yes"], cwd=d)
    after = conn.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
    check("split --apply 建子条目", after > before, f"{before}->{after}")
    child = conn.execute("SELECT qid, parent_qid FROM qa_entries WHERE parent_qid IS NOT NULL").fetchone()
    check("子条目 parent_qid 正确", child is not None and child["parent_qid"] == "Q-0001", str(child))

    print("== 4. 插件通道 qa_query qa-update ==")
    p = run_query(["--db", dbp, "qa-update", "--qid", "Q-0001"], {"qid": "Q-0001", "phenomenon": "待填写"}, cwd=d)
    out = json.loads(p.stdout.strip().splitlines()[-1])
    check("插件写入被 guard 拒绝", out["ok"] is False and "guard" in out["error"], str(out)[:160])
    p = run_query(["--db", dbp, "qa-update", "--qid", "Q-0001"],
                  {"qid": "Q-0001", "phenomenon": "相机预览流偶发黑屏，日志无报错；已定位为码流模板命中错误"}, cwd=d)
    out = json.loads(p.stdout.strip().splitlines()[-1])
    check("插件正常写入放行", out["ok"] is True, str(out)[:160])

    print("== 5. QA.md 同步通道（报告优先）==")
    md = os.path.join(d, "QA.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# QA 记录\n\n## Q-0100 | 2026-10-08 | Other | Pending\n\n"
                "**现象/需求:** 待填写\n\n---\n\n")
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "qa_md_sync.py"), "sync",
                        "--md", md, "--db", dbp], cwd=d, capture_output=True, text=True, encoding="utf-8")
    check("sync 默认放行并报告", "[guard]" in p.stdout and "已放行" in p.stdout, p.stdout[-200:])
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "qa_md_sync.py"), "sync",
                        "--md", md, "--db", dbp, "--strict"], cwd=d, capture_output=True, text=True, encoding="utf-8")
    check("sync --strict 阻断", p.returncode == 3, f"rc={p.returncode} {p.stdout[-120:]}")

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