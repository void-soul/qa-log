"""记忆健康（P4）：衰减归档 + 冲突检测 + 健康报告"""
import json, sys
from datetime import datetime
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import memory_guard as G
import memory_recall as MR
STALE_PENDING_DAYS = 180
COLD_ACCESS_MAX = 2
HALF_LIFE_DAYS = 180.0
W_IMP, W_ACC, W_REC = 1.0, 0.5, 0.4
CONFLICT_PHEN_SIM = 0.35   # 实测：同问题中文短文本0.39~0.67，不同问题~0.0
CONFLICT_CAUSE_SIM = 0.35

def _days_since(ts):
    if not ts:
        return 365.0
    txt = str(ts).replace("T", " ").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(txt[:len(fmt) + 2], fmt)
            return max(0.0, (datetime.now() - dt).total_seconds() / 86400.0)
        except ValueError:
            continue
    return 365.0


def decay_score(row):
    imp = W_IMP * (float(row["importance"] or 50) / 100.0)
    acc = W_ACC * (float(row["access_count"] or 0) ** 0.5)
    fresh = min(_days_since(row["last_access_at"]), _days_since(row["updated_at"]))
    return round(imp + acc + W_REC * (0.5 ** (fresh / HALF_LIFE_DAYS)), 4)


def suggest_archive(conn, stale_days=STALE_PENDING_DAYS, cold_access=COLD_ACCESS_MAX):
    """归档建议（永不删除）。"""
    rows = conn.execute(
        "SELECT qid, status, importance, access_count, last_access_at, updated_at, phenomenon"
        " FROM qa_entries WHERE COALESCE(archived,0)=0").fetchall()
    out = []
    for r in rows:
        acc = int(r["access_count"] or 0)
        st, days = r["status"], _days_since(r["updated_at"])
        reason = None
        if st in ("WontFix", "Unresolved") and acc <= cold_access:
            reason = "终态(%s)且几乎未被召回(热度=%d)" % (st, acc)
        elif st == "已解决待验证" and days > stale_days and acc <= cold_access:
            reason = "已解决待验证挂起 %d 天且未被召回(热度=%d)" % (int(days), acc)
        if reason:
            out.append({"qid": r["qid"], "score": decay_score(r), "status": st,
                        "reason": reason, "title": (r["phenomenon"] or "")[:60]})
    out.sort(key=lambda x: x["score"])
    return out


def archive_entry(conn, qid, reason="decay"):
    """执行归档：只置 archived=1 + 记事件，永不删除。"""
    conn.execute("UPDATE qa_entries SET archived=1, updated_at=datetime('now','localtime')"
                 " WHERE qid=?", (qid,))
    conn.commit()
    from db import log_event
    log_event(conn, qid, "archive", reason)
    return True


def unarchive_entry(conn, qid):
    conn.execute("UPDATE qa_entries SET archived=0 WHERE qid=?", (qid,))
    conn.commit()
    from db import log_event
    log_event(conn, qid, "unarchive", "restored")
    return True


def find_conflicts(conn, phen_sim=CONFLICT_PHEN_SIM, cause_sim=CONFLICT_CAUSE_SIM):
    """冲突检测：现象很像但根因/方案分歧 -> 潜在矛盾（零依赖启发式）。"""
    rows = conn.execute(
        "SELECT qid, phenomenon, root_cause, solution, files, category"
        " FROM qa_entries WHERE COALESCE(archived,0)=0").fetchall()
    sigs = [G.field_shingles({"phenomenon": r["phenomenon"] or "",
                              "root_cause": r["root_cause"] or "",
                              "solution": r["solution"] or "",
                              "files": r["files"] or ""}) for r in rows]
    out = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            # 剪枝：现象上界不够阈值则不可能构成冲突（无假阴性）
            if G.jaccard_bound(sigs[i]["phenomenon"], sigs[j]["phenomenon"]) < phen_sim:
                continue
            ps = G.jaccard(sigs[i]["phenomenon"], sigs[j]["phenomenon"])
            if ps < phen_sim:
                continue
            cs = G.jaccard(sigs[i]["root_cause"], sigs[j]["root_cause"])
            ss = G.jaccard(sigs[i]["solution"], sigs[j]["solution"])
            if cs <= cause_sim or ss <= cause_sim:
                out.append({
                    "a": rows[i]["qid"], "b": rows[j]["qid"],
                    "phen_sim": round(ps, 3), "cause_sim": round(cs, 3),
                    "reason": "现象相似 %.2f 但根因/方案分歧（根因 %.2f / 方案 %.2f）"
                              % (ps, cs, ss),
                })
    return out


def mark_conflicts(conn, conflicts):
    """写 contradicts 关系 + 置 needs_review=1。"""
    from db import add_link, log_event
    for c in conflicts:
        add_link(conn, c["a"], c["b"], "contradicts", c["reason"])
        for q in (c["a"], c["b"]):
            conn.execute("UPDATE qa_entries SET needs_review=1 WHERE qid=?", (q,))
            log_event(conn, q, "conflict", c["reason"])
    conn.commit()
    return len(conflicts)


def _db_signature(conn):
    """库内容指纹：条目数 + 最新更新时间 + 召回热度 + 归档数 + 关系数。

    用来给下面两次 O(n^2) 扫描做缓存判定——库没变就不重算。
    """
    try:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(updated_at), ''), COALESCE(SUM(COALESCE(access_count,0)), 0),"
            " COALESCE(SUM(COALESCE(archived,0)), 0), COALESCE(SUM(COALESCE(needs_review,0)), 0),"
            " COALESCE(MAX(created_at), '') FROM qa_entries"
        ).fetchone()
    except Exception:
        return None
    try:
        n_links = conn.execute("SELECT COUNT(*) FROM qa_links").fetchone()[0]
    except Exception:
        n_links = 0
    return tuple(row) + (n_links,)


_scan_cache = {}


def health_report(conn):
    """记忆健康报告（CLI 与插件面板共用）。"""
    total = conn.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0]
    by_status = {r[0]: r[1] for r in conn.execute(
        "SELECT status, COUNT(*) FROM qa_entries GROUP BY status ORDER BY 2 DESC")}
    archived = conn.execute(
        "SELECT COUNT(*) FROM qa_entries WHERE COALESCE(archived,0)=1").fetchone()[0]
    needs = conn.execute(
        "SELECT COUNT(*) FROM qa_entries WHERE COALESCE(needs_review,0)=1").fetchone()[0]
    stale = [r["qid"] for r in conn.execute(
        "SELECT qid, updated_at FROM qa_entries WHERE status = ? AND COALESCE(archived,0)=0", ("已解决待验证",))
        if _days_since(r["updated_at"]) > STALE_PENDING_DAYS]
    linked = {r[0] for r in conn.execute(
        "SELECT DISTINCT from_qid FROM qa_links UNION SELECT DISTINCT to_qid FROM qa_links")}
    orphans = []
    for r in conn.execute("SELECT qid, files, tags, parent_qid FROM qa_entries"
                      " WHERE COALESCE(archived,0)=0"):
        has_files = bool(G.files_rows(r["files"] or ""))
        try:
            has_tags = len(json.loads(r["tags"] or "")) > 0
        except Exception:
            has_tags = False
        if not has_files and not has_tags and r["qid"] not in linked and not r["parent_qid"]:
            orphans.append(r["qid"])

    # duplicate_pairs / conflicts 是全表两两配对（O(n^2)），插件每次刷新都会调
    # health_report；按库指纹缓存，库没变就复用上次结果。
    sig = _db_signature(conn)
    if sig is None or _scan_cache.get("sig") != sig:
        _scan_cache.clear()
        _scan_cache["sig"] = sig
        try:
            _scan_cache["duplicate_pairs"] = MR.find_near_duplicates(conn)[:20]
            _scan_cache["conflicts"] = find_conflicts(conn)[:20]
        except Exception:
            _scan_cache["duplicate_pairs"] = []
            _scan_cache["conflicts"] = []

    return {
        "total": total, "archived": archived, "needs_review": needs,
        "by_status": by_status,
        "stale_pending": stale[:20],
        "orphans": orphans[:20],
        "duplicate_pairs": _scan_cache["duplicate_pairs"],
        "conflicts": _scan_cache["conflicts"],
        "added_7d": conn.execute(
            "SELECT COUNT(*) FROM qa_entries WHERE created_at >= datetime('now','-7 day')"
        ).fetchone()[0],
        "recalled_7d": conn.execute(
            "SELECT COUNT(*) FROM qa_events WHERE event='recall' AND created_at >= datetime('now','-7 day')"
        ).fetchone()[0],
    }
