#!/usr/bin/env python3
"""
记忆召回与巩固（P3）

recall      加权召回：字段匹配 + 重要性 + 召回次数 + 新鲜度 + 关系引用；
            **命中即回写** access_count / last_access_at 并记 recall 事件（召回反馈闭环）
consolidate 巩固：近似条目去重/合并建议、模式（Pattern）提炼建议；默认只出建议，
            --apply 才落库（归档 + supersedes 关系 + merge 事件）

零依赖：相似度复用 memory_guard 的字符 3-gram；语义层预留 EmbeddingProvider 接口。
"""

import math
import re
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import memory_guard as G

# ── 评分权重（唯一调整入口） ──────────────────────────────────────────────────
W_FIELD = {"phenomenon": 3.0, "root_cause": 2.0, "solution": 1.0, "files": 2.0}
W_IMPORTANCE = 1.0        # importance / 100
W_ACCESS = 0.5            # log(1 + access_count) 归一
W_RECENCY = 0.4           # 新鲜度（最近被召回/更新越近越高）
W_LINK = 0.3              # 被关系引用的次数
HALF_LIFE_DAYS = 180.0    # 新鲜度半衰期

DUP_THRESHOLD = 0.70      # 巩固：相似度 ≥ 此值视为近似重复
PATTERN_MIN_SIZE = 5      # 模式提炼：同组至少条目数
PATTERN_MIN_SIM = 0.45    # 组内平均相似度下限
DEFAULT_LIMIT = 10


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


def score(sig_q, norm_q, row_sig, row_norm, importance, access_count, last_access_at, updated_at, link_count):
    """加权召回得分。"""
    total = 0.0
    detail = {}
    for f, w in W_FIELD.items():
        s = G.field_match(norm_q.get(f, ""), row_norm.get(f, ""),
                          sig_q.get(f, set()), row_sig.get(f, set()))
        if s > 0:
            total += w * s
            detail[f] = round(s, 3)
    total += W_IMPORTANCE * (float(importance or 50) / 100.0)
    total += W_ACCESS * math.log1p(float(access_count or 0))
    fresh = min(_days_since(last_access_at), _days_since(updated_at))
    total += W_RECENCY * math.pow(0.5, fresh / HALF_LIFE_DAYS)
    total += W_LINK * min(link_count, 10)
    return total, detail


def _link_counts(conn):
    out = {}
    for r in conn.execute(
        "SELECT to_qid, COUNT(*) FROM qa_links GROUP BY to_qid"
    ).fetchall():
        out[r[0]] = r[1]
    return out


def recall(conn, query, limit=DEFAULT_LIMIT, include_archived=False,
           feedback=True, status=None, category=None):
    """加权召回。返回 [{qid, score, title, status, category, fields}]（按分数降序）。"""
    sql = "SELECT qid, date, category, status, phenomenon, root_cause, solution, files," \
          " importance, access_count, last_access_at, updated_at, archived" \
          " FROM qa_entries WHERE 1=1"
    params = []
    if not include_archived:
        sql += " AND COALESCE(archived, 0) = 0"
    if status:
        sql += " AND status = ?"
        params.append(status)
    if category:
        sql += " AND category LIKE ?"
        params.append(f"%{category}%")
    rows = conn.execute(sql, params).fetchall()

    qfields = {f: query for f in W_FIELD}
    sig_q = G.field_shingles(qfields)
    norm_q = G.field_norms(qfields)
    links = _link_counts(conn)
    scored = []
    for r in rows:
        rowfields = {
            "phenomenon": r["phenomenon"], "root_cause": r["root_cause"],
            "solution": r["solution"], "files": r["files"],
        }
        row_sig = G.field_shingles(rowfields)
        row_norm = G.field_norms(rowfields)
        if not any(row_sig[f] for f in W_FIELD):
            continue
        s, detail = score(sig_q, norm_q, row_sig, row_norm, r["importance"], r["access_count"],
                          r["last_access_at"], r["updated_at"], links.get(r["qid"], 0))
        if query and not any(v > 0 for v in detail.values()):
            continue   # 与查询无关
        scored.append({
            "qid": r["qid"], "score": round(s, 4), "match": detail,
            "title": (r["phenomenon"] or "")[:80], "status": r["status"],
            "category": r["category"], "date": r["date"],
            "access_count": r["access_count"], "archived": r["archived"],
        })
    scored.sort(key=lambda x: -x["score"])
    hits = scored[:limit]

    if feedback and hits:
        for h in hits:
            conn.execute(
                "UPDATE qa_entries SET access_count = COALESCE(access_count,0) + 1,"
                " last_access_at = datetime('now','localtime') WHERE qid = ?",
                (h["qid"],),
            )
        conn.commit()
        try:
            from db import log_event
            for h in hits:
                log_event(conn, h["qid"], "recall",
                          f"query={query[:80]} score={h['score']}", actor="tool")
        except Exception:
            pass
    return hits


# ── 巩固：近似条目 ────────────────────────────────────────────────────────────

def _entry_sigs(conn):
    rows = conn.execute(
        "SELECT qid, category, status, phenomenon, root_cause, solution, files,"
        " archived FROM qa_entries WHERE COALESCE(archived,0) = 0"
    ).fetchall()
    out = []
    for r in rows:
        out.append((r, G.field_shingles({
            "phenomenon": r["phenomenon"], "root_cause": r["root_cause"],
            "solution": r["solution"], "files": r["files"],
        })))
    return out


def _info_len(row):
    return sum(len((row[k] or "")) for k in ("phenomenon", "root_cause", "solution", "files"))


def find_near_duplicates(conn, threshold=DUP_THRESHOLD):
    """扫描近似条目对 → [{a, b, score, action, reason}]。"""
    items = _entry_sigs(conn)
    pairs = []
    for i in range(len(items)):
        ra, sa = items[i]
        for j in range(i + 1, len(items)):
            rb, sb = items[j]
            # 剪枝：上界 < 阈值 → 不可能命中，跳过真算（无假阴性）
            if G.similarity_bound(sa, sb) < threshold:
                continue
            s = G.similarity(sa, sb)
            if s < threshold:
                continue
            # 已归档/已解决状态差异只作提示
            action = "duplicates" if s < 0.85 else "merge"
            pairs.append({
                "a": ra["qid"], "b": rb["qid"], "score": round(s, 3),
                "action": action,
                "reason": f"相似度 {s:.2f} ≥ {threshold}",
                "keep_hint": ra["qid"] if _info_len(ra) >= _info_len(rb) else rb["qid"],
            })
    pairs.sort(key=lambda x: -x["score"])
    return pairs


def suggest_patterns(conn, min_size=PATTERN_MIN_SIZE, min_sim=PATTERN_MIN_SIM):
    """按「相同 category + 相同文件首段模块」聚类，找可提炼为 Pattern 的组。"""
    rows = conn.execute(
        "SELECT qid, category, phenomenon, files FROM qa_entries WHERE COALESCE(archived,0)=0"
    ).fetchall()
    groups = {}
    for r in rows:
        mods = {G.module_of(f) for f, _ in G.files_rows(r["files"] or "")}
        key = (r["category"] or "", "|".join(sorted(mods)) if mods else "")
        if not mods:
            continue
        groups.setdefault(key, []).append(r)

    out = []
    for (cat, mods), rs in groups.items():
        if len(rs) < min_size:
            continue
        sigs = [G.field_shingles({"phenomenon": r["phenomenon"] or "",
                                   "root_cause": "", "solution": "", "files": r["files"] or ""})
                for r in rs]
        pair_scores = []
        for i in range(len(sigs)):
            for j in range(i + 1, len(sigs)):
                pair_scores.append(G.jaccard(sigs[i]["phenomenon"], sigs[j]["phenomenon"]))
        avg = sum(pair_scores) / len(pair_scores) if pair_scores else 0.0
        if avg >= min_sim:
            out.append({
                "category": cat, "modules": mods.split("|"),
                "qids": [r["qid"] for r in rs], "size": len(rs),
                "avg_similarity": round(avg, 3),
            })
    out.sort(key=lambda x: -x["size"])
    return out


PATTERN_PLACEHOLDER = "[待填写]"
PATTERN_MAX_CHILDREN = 20


def create_pattern_entry(conn, group, actor="tool"):
    """把一组同构条目提炼成一条 `category=Pattern` 的抽象条目（设计 7.2）。

    只**新增**抽象条目并以 `derived_from` 链接子项，绝不改动/归档/删除子条目
    （子条目的合并留给 consolidate 的 merge 建议，需人确认）。
    抽象条目同样过写入闸门；返回 (qid, msg)，被拒则返回 (None, reason)。
    """
    from db import add_link, get_next_qid, log_event

    qids = (group.get("qids") or [])[:PATTERN_MAX_CHILDREN]
    if not qids:
        return None, "empty group"
    mods = "/".join(group.get("modules") or []) or "(no-module)"
    cat = group.get("category") or "Other"
    phen = ("模式提炼：%s / %s ——由 %d 条同类具体记忆归纳（子条目见下）\n\n%s"
            % (cat, mods, group.get("size") or len(qids),
               "\n".join("- " + q for q in qids)))

    files_rows, seen = [], set()
    for q in qids:
        row = conn.execute("SELECT files FROM qa_entries WHERE qid = ?", (q,)).fetchone()
        for f, c in G.files_rows((row["files"] if row else "") or ""):
            if f in seen:
                continue
            seen.add(f)
            files_rows.append((f, c))
    files = ("| File | Change |\n|------|--------|\n"
             + "\n".join("| %s | %s |" % (f, c) for f, c in files_rows)) if files_rows else ""

    fields = {"phenomenon": phen, "root_cause": PATTERN_PLACEHOLDER,
              "solution": PATTERN_PLACEHOLDER, "files": files,
              "category": "Pattern", "status": "Pending"}
    res = G.check(fields, conn=conn)
    if res["level"] == "reject":
        codes = ",".join(i["code"] for i in res["issues"] if i["level"] == "reject")
        return None, "guard rejected (%s)" % codes

    qid = get_next_qid(conn)
    conn.execute(
        "INSERT INTO qa_entries (qid, date, category, status, phenomenon, root_cause,"
        " solution, files, importance) VALUES (?, date('now','localtime'), 'Pattern',"
        " 'Pending', ?, ?, ?, ?, 60)",
        (qid, phen, PATTERN_PLACEHOLDER, PATTERN_PLACEHOLDER, files),
    )
    conn.commit()
    for q in qids:
        add_link(conn, qid, q, "derived_from", "pattern abstracted from %s" % q)
    log_event(conn, qid, "pattern", "children=%d modules=%s" % (len(qids), mods), actor=actor)
    return qid, "pattern %s <- %d children" % (qid, len(qids))


def merge_entries(conn, keep, drop, actor="agent"):
    """合并：保留 keep，把 drop 的文件并入 keep，drop 归档 + supersedes 关系 + merge 事件。"""
    rk = conn.execute("SELECT * FROM qa_entries WHERE qid = ?", (keep,)).fetchone()
    rd = conn.execute("SELECT * FROM qa_entries WHERE qid = ?", (drop,)).fetchone()
    if rk is None or rd is None:
        return False, "entry not found"

    # 文件并集（按文件路径去重）
    rows = list(G.files_rows(rk["files"] or "")) + list(G.files_rows(rd["files"] or ""))
    seen, merged_rows = set(), []
    for f, c in rows:
        if f in seen:
            continue
        seen.add(f)
        merged_rows.append((f, c))
    table = "| File | Change |\n|------|--------|\n" + "\n".join(f"| {f} | {c} |" for f, c in merged_rows)

    # 现象取更长者（信息量更高），其余字段为空时补齐
    phen = rk["phenomenon"] if len(rk["phenomenon"] or "") >= len(rd["phenomenon"] or "") else rd["phenomenon"]
    root = rk["root_cause"] or rd["root_cause"] or ""
    sol = rk["solution"] or rd["solution"] or ""
    conn.execute(
        "UPDATE qa_entries SET phenomenon=?, root_cause=?, solution=?, files=?,"
        " importance=MAX(COALESCE(importance,50), COALESCE((SELECT importance FROM qa_entries WHERE qid=?),50)),"
        " access_count=COALESCE(access_count,0) + COALESCE((SELECT access_count FROM qa_entries WHERE qid=?),0),"
        " updated_at=datetime('now','localtime') WHERE qid=?",
        (phen, root, sol, table, drop, drop, keep),
    )
    conn.execute(
        "UPDATE qa_entries SET archived=1, updated_at=datetime('now','localtime') WHERE qid=?",
        (drop,),
    )
    conn.commit()
    try:
        from db import add_link, log_event
        add_link(conn, keep, drop, "supersedes", f"merged from {drop}")
        log_event(conn, keep, "merge", f"absorbed {drop}", actor=actor)
        log_event(conn, drop, "merge", f"merged into {keep}", actor=actor)
    except Exception:
        pass
    return True, f"{keep} <- {drop}"


class EmbeddingProvider:  # pragma: no cover - P3 预留接口
    """语义检索预留：将来接入本地 embedding 时替换 similarity 即可。"""
    name = "char3gram"

    @staticmethod
    def embed(text):
        return G.shingles(text)