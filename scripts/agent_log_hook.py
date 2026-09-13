#!/usr/bin/env python3
"""
CodeBuddy hook → 自动把会话记录追加到 qa.db 的 agent_log 表。

只记录两种内容：
  1. user_prompt       用户发给 Agent 的消息（全文）
  2. assistant_reply   Agent 的回复

配置方式见 scripts/setup_hooks.py（一键配置），或本文档末尾的手动说明。

已知限制（实测）
----------------
- 用户消息：`UserPromptSubmit` 事件的 stdin 直接含 `prompt` 全文，完整可靠。
- Agent 回复正文：CodeBuddy 把会话正文存在受保护的 `messages` 文件里
  （Win32 打开返回 ACCESS_DENIED），hook 只能拿到 transcript 元数据。
  因此 assistant_reply 记录的是「回复完成摘要 + 尽力读取的正文片段」：
  若某版本 messages 可读则自动记录正文，否则记录统计摘要。
  不影响「回看每个项目聊过什么」的核心用途。

手动配置（~/.codebuddy/settings.json，推荐用 setup_hooks.py 自动完成）
-----------------------------------------------------------------------
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command",
                     "command": "python \"<skill>/scripts/agent_log_hook.py\"",
                     "timeout": 30 } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command",
                     "command": "python \"<skill>/scripts/agent_log_hook.py\"",
                     "timeout": 30 } ] }
    ]
  }
}

安全
----
本脚本只读 stdin JSON 与 transcript 文件，只写本地 qa.db；任何异常都以
exit 0 结束，绝不阻塞 CodeBuddy。
"""

import json
import os
import sqlite3
import sys

# ── UTF-8 强制（Windows 管道/重定向下防乱码） ───────────────────────────────
for _s in (sys.stdout, sys.stderr, sys.stdin):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_NAME = "qa.db"

MAX_CONTENT = 20000
MAX_META = 4000
MAX_TITLE = 100


def log_err(msg):
    """诊断信息写 stderr（hook 的 stderr 仅作 fallback，不会干扰 Agent）。"""
    try:
        print(f"[agent_log_hook] {msg}", file=sys.stderr)
    except Exception:
        pass


def read_event():
    """从 stdin 读取 hook 事件 JSON。"""
    try:
        raw = sys.stdin.read()
    except Exception as e:
        log_err(f"read stdin failed: {e}")
        return None
    if not raw or not raw.strip():
        return None
    raw = raw.lstrip("\ufeff")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log_err(f"invalid JSON: {e}")
        return None


# ── 项目定位与数据库 ────────────────────────────────────────────────────────

def find_project_root(cwd):
    """从 cwd 向上查找含 qa.db 的目录；找不到则返回 cwd 本身。"""
    if not cwd or not os.path.isdir(cwd):
        return os.getcwd()
    cur = os.path.abspath(cwd)
    for _ in range(12):
        if os.path.isfile(os.path.join(cur, DB_NAME)):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.abspath(cwd)


def open_db(db_path):
    """打开（必要时创建）指定路径的库，并确保表结构存在。

    锁策略：使用默认 DELETE 回滚日志（不用 WAL，避免 -wal/-shm 伴生文件），
    连接为短生命周期——写完 commit 后立即 close，锁随之释放。
    """
    import db as qa_db

    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        # 若库曾被设为 WAL，这里转回 DELETE 并 checkpoint 掉 -wal 文件（幂等）
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA busy_timeout=8000")
    except Exception:
        pass
    qa_db.ensure_schema(conn)
    return conn


# ── 工具函数 ────────────────────────────────────────────────────────────────

def make_title(text):
    if not text:
        return ""
    return " ".join(str(text).split())[:MAX_TITLE]


def clip(s, limit):
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= limit else s[:limit] + f"\n... [已截断，共 {len(s)} 字符]"


def next_seq(conn, session_id):
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM agent_log WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return (row[0] or 0) + 1


def insert_log(conn, session_id, project, event, role, title, content, meta):
    seq = next_seq(conn, session_id)
    conn.execute(
        """INSERT INTO agent_log
           (session_id, project, seq, event, role, title, content, meta, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))""",
        (
            session_id, project, seq, event, role,
            clip(title, MAX_TITLE),
            clip(content, MAX_CONTENT),
            clip(json.dumps(meta, ensure_ascii=False) if meta else "", MAX_META),
        ),
    )
    conn.commit()
    return seq


# ── transcript 解析（尽力获取回复正文） ─────────────────────────────────────

def transcript_stats(transcript_path):
    """读取 transcript（index.json）的消息分布统计；失败返回 None。"""
    if not transcript_path or not os.path.isfile(transcript_path):
        return None
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception as e:
        log_err(f"read transcript failed: {e}")
        return None
    msgs = data.get("messages") or []
    roles = {}
    for m in msgs:
        if isinstance(m, dict):
            r = m.get("role") or "?"
            roles[r] = roles.get(r, 0) + 1
    return {"total": len(msgs), "roles": roles,
            "requests": len(data.get("requests") or [])}


def try_read_reply_body(transcript_path):
    """尽力读取同目录 `messages` 里的回复正文。

    实测该文件通常被 CodeBuddy 保护（ACCESS_DENIED），读不到是正常情况；
    若某版本可读，则返回最近的正文片段。
    """
    if not transcript_path:
        return None
    mf = os.path.join(os.path.dirname(transcript_path), "messages")
    if not os.path.isfile(mf):
        return None
    try:
        with open(mf, "rb") as f:
            head = f.read(64 * 1024)
    except Exception as e:
        log_err(f"messages not readable (expected): {type(e).__name__}")
        return None
    text = head.decode("utf-8", "replace").strip()
    if not text:
        return None
    return text[-3000:] if len(text) > 3000 else text


# ── 事件处理 ────────────────────────────────────────────────────────────────

def record(ev, hook, session_id, project_root, cwd, transcript):
    """把一条事件写入项目根目录的 qa.db（单库，写完立即关闭释放锁）。"""
    conn = None
    try:
        conn = open_db(os.path.join(project_root, DB_NAME))

        if hook == "UserPromptSubmit":
            prompt = ev.get("prompt") or ""
            insert_log(
                conn, session_id, project_root,
                event="user_prompt", role="user",
                title=make_title(prompt),
                content=prompt,
                meta={"cwd": cwd, "transcript": transcript},
            )

        elif hook in ("Stop", "SubagentStop"):
            stats = transcript_stats(transcript)
            body = try_read_reply_body(transcript)
            # 去重：同一轮回复只记一次（以 assistant 消息数为签名）
            sig = f"回复 #{stats['roles'].get('assistant', 0) if stats else 0}"
            if body:
                content = body
            elif stats:
                content = (
                    f"（回复正文受 CodeBuddy 保护，仅记录摘要）"
                    f"assistant 消息 {stats['roles'].get('assistant', 0)} 条，"
                    f"本轮对话累计 {stats['total']} 条消息 / {stats['requests']} 次请求"
                )
            else:
                content = "回复完成。"
            dup = conn.execute(
                "SELECT 1 FROM agent_log WHERE session_id = ? "
                "AND event = 'assistant_reply' AND title = ? LIMIT 1",
                (session_id, sig),
            ).fetchone()
            if not dup:
                insert_log(
                    conn, session_id, project_root,
                    event="assistant_reply", role="assistant",
                    title=sig,
                    content=content,
                    meta={"transcript": transcript, "stats": stats},
                )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def handle(ev):
    hook = ev.get("hook_event_name") or ""
    session_id = ev.get("session_id") or "unknown"
    cwd = ev.get("cwd") or os.getcwd()
    transcript = ev.get("transcript_path") or ""

    project_root = find_project_root(cwd)
    record(ev, hook, session_id, project_root, cwd, transcript)


def main():
    ev = read_event()
    if not ev:
        log_err("no event payload (stdin empty)")
        return
    try:
        handle(ev)
    except Exception as e:
        # 绝不让 hook 失败影响 CodeBuddy 会话
        log_err(f"handle failed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
