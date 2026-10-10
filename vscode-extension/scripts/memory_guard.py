#!/usr/bin/env python3
"""
记忆写入闸门（memory guard）—— 设计的 P1 落地

职责：所有写入 qa_entries 的通道（qa_tool append/update、插件 qa_query qa-update、
qa_md_sync sync）都必须过这里，避免 AI 把噪声灌进长期记忆。

检查分三档：
  reject  禁止写入（占位/无信息量/超长/重复记忆/非法状态/硬拆分信号）
  warn    允许写入但提示（拆分信号：多模块、多步骤、多个独立诉求）
  ok      通过

相似度为零依赖实现（字符 3-gram + Jaccard，字段加权），P3 若引入 embedding
只需替换 similarity()/find_similar()。

阈值集中在下方常量；`--force` / force=1 可跳过 reject（写入审计由 P2 记录）。
"""

import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PLACEHOLDER = "[待填写]"

# ── 阈值（唯一调整入口） ──────────────────────────────────────────────────────
MAX_BYTES = {
    "phenomenon": 4 * 1024,
    "root_cause": 8 * 1024,
    "solution": 16 * 1024,
    "files": 8 * 1024,
}
MIN_PHENOMENON_CHARS = 8          # 现象/需求最短字符数
MIN_UNIQUE_CHARS = 40             # 去重后最少有效字符
MIN_UNIQUE_LINE_RATIO = 0.40      # 去重行占比下限
DUP_SIMILARITY = 0.82             # 与既有条目相似度 ≥ 此值判为重复记忆

WARN_STEPS = 6                    # 方案编号步骤 > N 提示拆分
WARN_FILES_ROWS = 5               # 文件表行数 > N 提示拆分
WARN_MODULES = 3                  # 跨模块数 > N 提示拆分（路径首段）
WARN_PHENOMENON_ITEMS = 3         # 现象独立编号项 ≥ N 提示拆分
WARN_PHENOMENON_CHARS = 300       # 且现象长度 > N 才提示（避免短列表误报）

HARD_SPLIT_FILES_ROWS = 12        # 文件表行数硬阈值 → 强制先拆
HARD_SPLIT_SOLUTION_BYTES = 24 * 1024

SHINGLE_N = 3
FIELD_WEIGHTS = {"phenomenon": 0.5, "root_cause": 0.2, "solution": 0.2, "files": 0.1}

PLACEHOLDER_VALUES = {
    "", "-", "--", "—", "无", "没有", "暂无", "n/a", "na", "none", "null",
    "待填写", PLACEHOLDER, "test", "测试", "todo", "tbd", "fix", "修复一下",
}

FILE_RE = re.compile(
    r"[A-Za-z0-9_@][\w./\\-]*\.(?:ts|tsx|js|jsx|mjs|cjs|py|cs|go|rs|java|kt|vue|svelte|"
    r"json|md|yml|yaml|sql|css|scss|html|xaml|sh|ps1|toml|xml|proto|lua|rb|php|swift|"
    r"c|cc|cpp|h|hpp)"
)
NUMBERED_RE = re.compile(r"^\s{0,3}(\d+)[.、)]\s*(.+)$")


def _valid_statuses():
    """权威状态集合（单一来源在 qa_tool，这里惰性导入避免循环依赖）。"""
    try:
        from qa_tool import VALID_STATUSES  # type: ignore
        return tuple(VALID_STATUSES)
    except Exception:
        return ("Pending", "已解决待验证", "已验证", "WontFix", "Unresolved")


# ── 文本工具 ──────────────────────────────────────────────────────────────────

def _norm(text):
    """归一化：去 markdown 表格竖线、压缩空白、转小写。"""
    s = (text or "").replace("|", " ")
    s = re.sub(r"[*#`_>]+", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def shingles(text, n=SHINGLE_N):
    """字符 n-gram 集合（短文本退化为整串）。"""
    s = _norm(text)
    if not s:
        return set()
    if len(s) <= n:
        return {s}
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / float(len(a) + len(b) - inter)


def field_shingles(fields):
    return {k: shingles(fields.get(k, "")) for k in FIELD_WEIGHTS}


def field_norms(fields):
    return {k: _norm(fields.get(k, "")) for k in FIELD_WEIGHTS}


# 短查询（≤4 字符）无法用 3-gram 比对，退化为"包含"判断
SHORT_QUERY_MAX = 4


def field_match(needle_norm, field_norm, sig_a, sig_b):
    """单字段匹配得分：短串走包含判断，长串走 3-gram Jaccard。"""
    if not needle_norm:
        return 0.0
    if len(needle_norm) <= SHORT_QUERY_MAX:
        if not field_norm:
            return 0.0
        return 1.0 if needle_norm in field_norm else 0.0
    return jaccard(sig_a, sig_b)


def similarity(sig_a, sig_b, norm_a=None, norm_b=None):
    """字段加权相似度（0~1），按「双方都非空的字段」归一化。

    归一化方式必须按参与字段求权重和：append 时只有 phenomenon 有值，若按全部
    字段权重（合计 1.0）作分母，得分上限只有 phenomenon 的 0.5，永远够不到
    DUP_SIMILARITY(0.82) —— 重复检测会在「新增记忆」这个主入口上彻底失效。
    """
    total = 0.0
    denom = 0.0
    for f, w in FIELD_WEIGHTS.items():
        sa, sb = sig_a.get(f, set()), sig_b.get(f, set())
        if not sa or not sb:
            continue          # 只有一侧有内容 → 该字段不参与比对
        denom += w
        s = jaccard(sa, sb)
        if s == 0.0 and norm_a and norm_b:
            na, nb = norm_a.get(f, ""), norm_b.get(f, "")
            if na and nb and (len(na) <= SHORT_QUERY_MAX or len(nb) <= SHORT_QUERY_MAX):
                if (len(na) <= SHORT_QUERY_MAX and na in nb) or (len(nb) <= SHORT_QUERY_MAX and nb in na):
                    s = 1.0
        total += w * s
    if denom <= 0.0:
        return 0.0
    return total / denom


def jaccard_bound(a, b):
    """Jaccard 上界：min(|A|,|B|) / max(|A|,|B|)（只比集合大小，不求交集）。

    用于免算剪枝：真实 Jaccard 一定 <= 该值，故上界不够阈值时可安全跳过（无假阴性）。
    """
    if not a or not b:
        return 0.0
    lo, hi = (len(a), len(b)) if len(a) <= len(b) else (len(b), len(a))
    return float(lo) / hi if hi else 0.0


def similarity_bound(sig_a, sig_b):
    """加权相似度的**上界**：按参与字段加权各自的 jaccard_bound，用于 O(n^2) 扫描剪枝。"""
    total = 0.0
    denom = 0.0
    for f, w in FIELD_WEIGHTS.items():
        sa, sb = sig_a.get(f, set()), sig_b.get(f, set())
        if not sa or not sb:
            continue
        denom += w
        total += w * jaccard_bound(sa, sb)
    if denom <= 0.0:
        return 0.0
    return total / denom


def _file_tokens(text):
    return {m.group(0).lower() for m in FILE_RE.finditer(text or "")}


# ── 拆分信号 ──────────────────────────────────────────────────────────────────

def files_rows(files_text):
    """解析 files 字段的 markdown 表格行 → [(file, change)]。"""
    rows = []
    for line in (files_text or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        first = cells[0]
        if not first or set(first) <= set("-: "):   # 分隔行
            continue
        rows.append((first, cells[1]))
    return rows


def numbered_items(text):
    """抽取顶层编号项 → [整行文本]。"""
    return [m.group(0).strip() for m in NUMBERED_RE.finditer(text or "") if len(m.group(2).strip()) >= 10]


def module_of(path_text):
    p = (path_text or "").strip().replace("\\", "/")
    if "/" in p:
        return p.split("/")[0]
    return "(root)"


def scan_split(fields):
    """生成拆分草案（不落库）。

    策略优先级：by_module（按文件首段模块分组）> by_numbered（按现象编号项）。
    返回 {strategy, reasons, drafts:[{phenomenon, files}]}
    """
    phen = fields.get("phenomenon") or ""
    sol = fields.get("solution") or ""
    files_text = fields.get("files") or ""
    rows = files_rows(files_text)
    reasons = []

    # 信号 1：文件表行数
    if len(rows) > HARD_SPLIT_FILES_ROWS:
        reasons.append(f"文件表 {len(rows)} 行 > 硬阈值 {HARD_SPLIT_FILES_ROWS}")
    elif len(rows) > WARN_FILES_ROWS:
        reasons.append(f"文件表 {len(rows)} 行 > {WARN_FILES_ROWS}")

    # 信号 2：方案步骤数
    steps = numbered_items(sol)
    if len(steps) > WARN_STEPS:
        reasons.append(f"方案编号步骤 {len(steps)} 项 > {WARN_STEPS}")

    # 信号 3：跨模块
    groups = {}
    for f, c in rows:
        groups.setdefault(module_of(f), []).append((f, c))
    if len(groups) > WARN_MODULES:
        reasons.append(f"跨 {len(groups)} 个模块 > {WARN_MODULES}")

    # 信号 4：现象含多个独立诉求
    items = numbered_items(phen)
    if len(items) >= WARN_PHENOMENON_ITEMS and len(phen) > WARN_PHENOMENON_CHARS:
        reasons.append(f"现象含 {len(items)} 个独立编号项且长度 {len(phen)} 字符")

    drafts = []
    strategy = None
    # 策略 A：按模块分组（每组至少 1 个文件，且模块数 ≥2）
    if len(groups) >= 2:
        head = next((ln.strip() for ln in phen.splitlines() if ln.strip()), "")
        for mod in sorted(groups):
            sub_rows = groups[mod]
            table = "| File | Change |\n|------|--------|\n" + "\n".join(
                f"| {f} | {c} |" for f, c in sub_rows)
            title = head if (head and len(head) <= 80) else ""
            drafts.append({
                "phenomenon": (f"{title}\n\n（模块：{mod}）" if title else f"（模块：{mod}）"),
                "files": table,
            })
        strategy = "by_module"
    # 策略 B：按现象编号项
    if not drafts and len(items) >= WARN_PHENOMENON_ITEMS and len(phen) > WARN_PHENOMENON_CHARS:
        for it in items:
            body = NUMBERED_RE.match(it)
            text = body.group(2).strip() if body else it
            paths = sorted({m.group(0) for m in FILE_RE.finditer(text)})
            drafts.append({
                "phenomenon": text,
                "files": ("| File | Change |\n|------|--------|\n"
                          + "\n".join(f"| {p} | |" for p in paths)) if paths else "",
            })
        strategy = "by_numbered"

    return {"strategy": strategy, "reasons": reasons, "drafts": drafts}


# ── 重复记忆检测 ──────────────────────────────────────────────────────────────

def find_similar(fields, conn, exclude_qid=None, limit=3):
    """在库中查找与 payload 高度相似的既有条目 → [{qid, score}]。

    不做「同 category / 同文件」的硬跳过——那会让「不同类、又没有文件表」的纯文本
    重复整条漏检（append 恰恰没有 files）。这两个信号降级为同分时的排序偏好，
    性能改由 similarity_bound 剪枝保证（无假阴性）。
    """
    if conn is None:
        return []
    target = field_shingles(fields)
    target_norms = field_norms(fields)
    tgt_files = _file_tokens(fields.get("files", ""))
    tgt_cat = (fields.get("category") or "").strip()
    try:
        rows = conn.execute(
            "SELECT qid, category, phenomenon, root_cause, solution, files FROM qa_entries"
        ).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        if exclude_qid and r["qid"] == exclude_qid:
            continue
        row_fields = {
            "phenomenon": r["phenomenon"], "root_cause": r["root_cause"],
            "solution": r["solution"], "files": r["files"],
        }
        row_sigs = field_shingles(row_fields)
        if similarity_bound(target, row_sigs) < DUP_SIMILARITY:
            continue   # 上界都不够阈值 → 无需真算（无假阴性）
        score = similarity(target, row_sigs, norm_a=target_norms,
                           norm_b=field_norms(row_fields))
        if score >= DUP_SIMILARITY:
            same_cat = bool(tgt_cat) and (r["category"] or "") == tgt_cat
            share_files = bool(tgt_files & _file_tokens(r["files"] or ""))
            out.append({"qid": r["qid"], "score": round(score, 3),
                        "prefer": (1 if same_cat else 0) + (1 if share_files else 0)})
    out.sort(key=lambda x: (-x["score"], -x["prefer"], x["qid"]))
    return [{"qid": o["qid"], "score": o["score"]} for o in out[:limit]]


# ── 主检查 ────────────────────────────────────────────────────────────────────

def _bytes(text):
    return len((text or "").encode("utf-8"))


def _is_placeholder(value):
    return _norm(value) in PLACEHOLDER_VALUES


def check(fields, conn=None, exclude_qid=None):
    """检查一条记忆草稿。

    fields: {phenomenon|question, root_cause, solution, files, category, status}
    返回 {level, issues[], similar[], split{}}
    """
    phen = (fields.get("phenomenon") or fields.get("question") or "").strip()
    root = (fields.get("root_cause") or "").strip()
    sol = (fields.get("solution") or "").strip()
    files_text = (fields.get("files") or "").strip()
    status = (fields.get("status") or "").strip()
    payload = {"phenomenon": phen, "root_cause": root, "solution": sol,
               "files": files_text, "category": fields.get("category") or ""}

    issues = []

    def add(code, level, field, msg):
        issues.append({"code": code, "level": level, "field": field, "message": msg})

    # 1) 现象占位 / 过短
    if _is_placeholder(phen):
        add("placeholder", "reject", "phenomenon", "现象/需求为占位或空内容，必须写清具体问题")
    elif len(phen) < MIN_PHENOMENON_CHARS:
        add("phenomenon_too_short", "reject", "phenomenon",
            f"现象/需求仅 {len(phen)} 字符（< {MIN_PHENOMENON_CHARS}），信息量不足")

    # 2) 信息密度：去重后有效内容（仅对已填写根因/方案的记录生效，
    #    否则 Pending 阶段的简述会被误杀）
    body = "\n".join(x for x in (phen, root, sol) if x)
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    uniq_lines = {l for l in lines}
    uniq_chars = len(_norm(body).replace(" ", ""))
    if body and (root or sol) and (
            uniq_chars < MIN_UNIQUE_CHARS or
            (len(lines) >= 4 and len(uniq_lines) / float(len(lines)) < MIN_UNIQUE_LINE_RATIO)):
        add("low_information", "reject", "content",
            f"内容重复度过高（去重后 {uniq_chars} 字 / {len(lines)} 行）——合并表述或补充根因")

    # 3) 长度上限
    for f, text in (("phenomenon", phen), ("root_cause", root),
                    ("solution", sol), ("files", files_text)):
        n = _bytes(text)
        if n > MAX_BYTES[f]:
            add("too_long", "reject", f,
                f"{f} 长度 {n} 字节 > 上限 {MAX_BYTES[f]}——请拆分条目或精简（不要贴大段日志）")

    # 4) 状态机
    if status and status not in _valid_statuses():
        add("invalid_status", "reject", "status",
            f"非法状态 '{status}'，合法值：{', '.join(_valid_statuses())}")

    # 5) 重复记忆
    similar = find_similar(payload, conn, exclude_qid=exclude_qid)
    if similar:
        add("dup_similarity", "reject", "phenomenon",
            "与既有条目高度重复：" +
            ", ".join(f"{s['qid']}({s['score']})" for s in similar) +
            "——应 update 已有条目而不是新增")

    # 6) 拆分信号
    split = scan_split(payload)
    if split["reasons"]:
        hard = (len(files_rows(files_text)) > HARD_SPLIT_FILES_ROWS or
                _bytes(sol) > HARD_SPLIT_SOLUTION_BYTES)
        add("hard_split" if hard else "split_signal",
            "reject" if hard else "warn", "content",
            "命中拆分信号（" + "；".join(split["reasons"]) + "）" +
            ("——必须先 `qa_tool.py split` 拆分后再写入" if hard else
             "——建议 `qa_tool.py split <ID> --dry-run` 查看拆分草案"))

    level = "ok"
    if any(i["level"] == "reject" for i in issues):
        level = "reject"
    elif any(i["level"] == "warn" for i in issues):
        level = "warn"

    return {"level": level, "issues": issues, "similar": similar, "split": split}


def format_report(result, title=""):
    """把 check() 结果渲染成可读文本。"""
    lines = []
    if title:
        lines.append(title)
    if result["level"] == "ok":
        lines.append("[guard] OK — 通过")
        return "\n".join(lines)
    icon = "REJECT" if result["level"] == "reject" else "WARN"
    lines.append(f"[guard] {icon} — {len(result['issues'])} issue(s)")
    for i in result["issues"]:
        lines.append(f"  - ({i['level']}/{i['code']}) {i['field']}: {i['message']}")
    sp = result.get("split") or {}
    if sp.get("drafts"):
        lines.append(f"  拆分草案（策略 {sp['strategy']}，{len(sp['drafts'])} 条）：")
        for k, d in enumerate(sp["drafts"], 1):
            first = (d["phenomenon"] or "").replace("\n", " ")[:70]
            nfiles = len(files_rows(d["files"]))
            lines.append(f"    {k}. {first}  [文件 {nfiles} 行]")
    return "\n".join(lines)