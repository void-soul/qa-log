"""Shared database helpers for the qa-log scripts.

提供：
  DB_NAME             默认数据库文件名
  resolve_db_path()   解析 --db 参数 / cwd/qa.db
  ensure_schema()     幂等：建表 + 老 schema 迁移 + 4 位零填充
  connect()           打开连接并自动调 ensure_schema
  get_next_qid()      4 位零填充下一个 qid
  normalize_id()      把 "1" / "Q-001" / "Q-0001" 都标准化为 "Q-0001"

两张表：
  qa_entries   QA 记录（问题/根因/解决方案/涉及文件）
  agent_log    Agent 会话日志（由 CodeBuddy hooks 自动追加，见 agent_log_hook.py）

记忆系统 P2 新增：
  qa_events    审计流水（append/update/verify/split/delete/guard_bypass/recall…）
  qa_links     条目关系（derived_from/duplicates/supersedes/contradicts/relates_to）
  qa_entries 新增列：parent_qid / importance / access_count / last_access_at /
               tags / source_session / source_commit / archived

迁移覆盖范围（与 Tauri 后端 open_db() 一致）：
  1. 旧 schema: id INTEGER PK AUTOINCREMENT + qid TEXT UNIQUE
     -> 新 schema: qid TEXT PRIMARY KEY (无 id 列)
  2. 缺 updated_at 列：补上
  3. 缺 P2 记忆列：逐条幂等补齐
  4. qid 长度=5 (Q-NNN) -> 长度=6 (Q-0NNN)

审计助手：
  log_event(conn, qid, event, detail, actor)   写一条流水（best-effort）
  add_link(conn, from_qid, to_qid, kind, note) 建关系（幂等）
"""
import os
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_NAME = "qa.db"

# Target schema (modern). qid is the only primary key; no separate integer id.
TARGET_DDL = """
CREATE TABLE qa_entries (
    qid        TEXT PRIMARY KEY,
    date       TEXT NOT NULL,
    category   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'Pending',
    phenomenon TEXT NOT NULL,
    root_cause TEXT DEFAULT '',
    solution   TEXT DEFAULT '',
    files      TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT,
    parent_qid TEXT,           -- 拆分关系：子条目指向父条目
    importance   INTEGER DEFAULT 50,   -- 重要性 0-100（排序权重）
    access_count INTEGER DEFAULT 0,    -- 被召回次数（召回反馈）
    last_access_at TEXT,               -- 最近召回时间（新鲜度衰减基准）
    tags         TEXT DEFAULT '[]',    -- JSON 数组，聚类/冲突检测用
    source_session TEXT,               -- 溯源：CodeBuddy 会话 ID
    source_commit  TEXT,               -- 溯源：关联提交 hash
    archived      INTEGER DEFAULT 0,   -- 归档标记（默认不参与召回，不删除）
    needs_review  INTEGER DEFAULT 0    -- 冲突待审标记（contradicts 命中时置1）
    )
    """

# Agent 会话日志表（由 CodeBuddy hooks 自动写入）
#
# 设计要点：
#  - event: user_prompt(用户消息) / tool_use(工具调用) / assistant_reply(回复摘要)
#           / session_start / session_end
#  - title : 概要（用户消息前若干字），便于列表快速浏览
#  - content: 正文（用户消息全文 / 工具调用摘要 / 回复摘要）
#  - meta  : JSON 附加信息（工具名、token、文件列表等）
#  - seq   : 同一 session 内的自增序号，用于稳定排序与增量去重
AGENT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS agent_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    project    TEXT NOT NULL DEFAULT '',
    seq        INTEGER NOT NULL DEFAULT 0,
    event      TEXT NOT NULL,
    role       TEXT DEFAULT '',
    title      TEXT DEFAULT '',
    content    TEXT DEFAULT '',
    meta       TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime'))
)
"""

AGENT_LOG_INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_agent_log_session ON agent_log(session_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_agent_log_project ON agent_log(project, id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_log_created ON agent_log(created_at)",
]

# 记忆系统 P2：关系表（条目间 duplicates / supersedes / derived_from / contradicts …）
QA_LINKS_DDL = """
CREATE TABLE IF NOT EXISTS qa_links (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_qid   TEXT NOT NULL,
    to_qid     TEXT NOT NULL,
    kind       TEXT NOT NULL,   -- relates_to|duplicates|supersedes|derived_from|contradicts
    note       TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime'))
)
"""

QA_LINKS_INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_qa_links_from ON qa_links(from_qid)",
    "CREATE INDEX IF NOT EXISTS idx_qa_links_to   ON qa_links(to_qid)",
]

# 记忆系统 P2：审计流水
# 事件：append|update|verify|merge|split|archive|recall|delete|guard_bypass
# 删除条目也必须留痕 → 先写 event 再删；本表无外键，条目消失后流水仍在。
QA_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS qa_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    qid        TEXT NOT NULL,
    event      TEXT NOT NULL,
    detail     TEXT DEFAULT '',
    actor      TEXT DEFAULT 'agent',   -- agent|user|tool
    created_at TEXT DEFAULT (datetime('now','localtime'))
)
"""

QA_EVENTS_INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_qa_events_qid ON qa_events(qid, id)",
]

# P2 追加列：(列名, ALTER 语句)。ensure_schema 逐条幂等补齐。
MEMORY_COLUMNS = [
    ("parent_qid", "ALTER TABLE qa_entries ADD COLUMN parent_qid TEXT"),
    ("importance", "ALTER TABLE qa_entries ADD COLUMN importance INTEGER DEFAULT 50"),
    ("access_count", "ALTER TABLE qa_entries ADD COLUMN access_count INTEGER DEFAULT 0"),
    ("last_access_at", "ALTER TABLE qa_entries ADD COLUMN last_access_at TEXT"),
    ("tags", "ALTER TABLE qa_entries ADD COLUMN tags TEXT DEFAULT '[]'"),
    ("source_session", "ALTER TABLE qa_entries ADD COLUMN source_session TEXT"),
    ("source_commit", "ALTER TABLE qa_entries ADD COLUMN source_commit TEXT"),
    ("archived", "ALTER TABLE qa_entries ADD COLUMN archived INTEGER DEFAULT 0"),
    ("needs_review", "ALTER TABLE qa_entries ADD COLUMN needs_review INTEGER DEFAULT 0"),
]


def log_event(conn, qid, event, detail="", actor="agent"):
    """写一条审计流水（best-effort：失败不阻断主流程）。"""
    try:
        conn.execute(
            "INSERT INTO qa_events (qid, event, detail, actor) VALUES (?, ?, ?, ?)",
            (qid, event, (detail or "")[:2000], actor),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def add_link(conn, from_qid, to_qid, kind, note=""):
    """建立条目关系（幂等：同 (from,to,kind) 已存在则跳过）。best-effort。"""
    try:
        dup = conn.execute(
            "SELECT 1 FROM qa_links WHERE from_qid=? AND to_qid=? AND kind=?",
            (from_qid, to_qid, kind),
        ).fetchone()
        if dup:
            return False
        conn.execute(
            "INSERT INTO qa_links (from_qid, to_qid, kind, note) VALUES (?, ?, ?, ?)",
            (from_qid, to_qid, kind, (note or "")[:500]),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        return False


def resolve_db_path(explicit=None):
    """Return the path to qa.db.

    Priority:
      1. --db explicit argument
      2. ./qa.db in current working directory (project root)
    """
    if explicit:
        return explicit
    return os.path.join(os.getcwd(), DB_NAME)


def _table_exists(conn):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='qa_entries'"
    ).fetchone() is not None


def _has_column(conn, column):
    return conn.execute(
        "SELECT 1 FROM pragma_table_info('qa_entries') WHERE name = ?",
        (column,),
    ).fetchone() is not None


def ensure_schema(conn, verbose=False):
    """Idempotent schema migration. Safe to call on every connection open.

    Steps:
      0. Ensure `agent_log` table + indexes exist (independent of qa_entries).
      1. If `qa_entries` does not exist, create it with the target schema.
      2. If the legacy `id INTEGER PK` column exists, rebuild the table
         so `qid` becomes the sole primary key.
      3. If `updated_at` column is missing, add it (NULL by default).
      4. Pad any 3-digit qid (length=5) to 4-digit (length=6).
    """
    # 0. agent_log / qa_links / qa_events 表（幂等，且不受 qa_entries 早返回影响）
    conn.execute(AGENT_LOG_DDL)
    for _ddl in AGENT_LOG_INDEX_DDL:
        conn.execute(_ddl)
    conn.execute(QA_LINKS_DDL)
    for _ddl in QA_LINKS_INDEX_DDL:
        conn.execute(_ddl)
    conn.execute(QA_EVENTS_DDL)
    for _ddl in QA_EVENTS_INDEX_DDL:
        conn.execute(_ddl)

    if not _table_exists(conn):
        if verbose:
            print("[ensure_schema] Creating qa_entries with target schema")
        conn.execute(TARGET_DDL)
        conn.commit()
        return

    changed = False

    # 2. legacy id-PK migration
    if _has_column(conn, "id"):
        if verbose:
            print("[ensure_schema] Migrating legacy id-PK schema to qid-PK...")
        conn.executescript(
            """
            CREATE TABLE qa_entries_new (
                qid        TEXT PRIMARY KEY,
                date       TEXT NOT NULL,
                category   TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'Pending',
                phenomenon TEXT NOT NULL,
                root_cause TEXT DEFAULT '',
                solution   TEXT DEFAULT '',
                files      TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            INSERT INTO qa_entries_new
                (qid, date, category, status, phenomenon, root_cause, solution, files, created_at)
            SELECT qid, date, category, status, phenomenon,
                   COALESCE(root_cause, ''), COALESCE(solution, ''), COALESCE(files, ''),
                   COALESCE(created_at, datetime('now','localtime'))
            FROM qa_entries;
            DROP TABLE qa_entries;
            ALTER TABLE qa_entries_new RENAME TO qa_entries;
            """
        )
        if verbose:
            print("[ensure_schema]   legacy migration done")
        changed = True

    # 3. add updated_at if missing
    if not _has_column(conn, "updated_at"):
        conn.execute("ALTER TABLE qa_entries ADD COLUMN updated_at TEXT")
        if verbose:
            print("[ensure_schema] Added updated_at column")
        changed = True

    # 3b. 记忆系统列（P2）：parent_qid / importance / access_count / last_access_at
    #     / tags / source_session / source_commit，逐条幂等补齐
    for col, ddl in MEMORY_COLUMNS:
        if not _has_column(conn, col):
            conn.execute(ddl)
            if verbose:
                print(f"[ensure_schema] Added column {col}")
            changed = True

    # 4. auto-pad 3-digit qids to 4-digit
    cur = conn.execute(
        "UPDATE qa_entries SET qid = 'Q-0' || substr(qid, 3) WHERE length(qid) = 5"
    )
    if cur.rowcount > 0:
        if verbose:
            print(f"[ensure_schema] Padded {cur.rowcount} qid(s) from 3-digit to 4-digit")
        changed = True

    if changed:
        conn.commit()


def connect(db_path=None, verbose=False):
    """Open a connection to qa.db, auto-running ensure_schema().

    Every open is a fresh opportunity to migrate — the schema check is
    cheap (a few PRAGMA selects) and idempotent.
    """
    path = resolve_db_path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn, verbose=verbose)
    return conn


def get_next_qid(conn):
    """Find the highest existing QID and return the next one (4-digit).

    The CAST/SUBSTR trick ignores the "Q-" prefix and zero-padding; works
    uniformly for 3-digit, 4-digit, or mixed entries.
    """
    row = conn.execute(
        "SELECT qid FROM qa_entries ORDER BY CAST(SUBSTR(qid,3) AS INTEGER) DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "Q-0001"
    max_num = int(row["qid"][2:])
    return f"Q-{max_num + 1:04d}"


def normalize_id(id_str):
    """Normalize user input to canonical 4-digit Q-NNNN format.

    Accepts: "1", "01", "001", "Q-1", "Q-01", "Q-001", "Q-0001", "q-1", " 1 ".
    Returns: "Q-0001" etc.
    """
    id_str = id_str.strip().upper()
    if not id_str.startswith("Q-"):
        num = id_str.lstrip("Q-").lstrip("0") or "1"
        id_str = f"Q-{int(num):04d}"
    return id_str
