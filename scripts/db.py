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

迁移覆盖范围（与 Tauri 后端 open_db() 一致）：
  1. 旧 schema: id INTEGER PK AUTOINCREMENT + qid TEXT UNIQUE
     -> 新 schema: qid TEXT PRIMARY KEY (无 id 列)
  2. 缺 updated_at 列：补上
  3. qid 长度=5 (Q-NNN) -> 长度=6 (Q-0NNN)
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
    updated_at TEXT
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
    # 0. agent_log 表（幂等，且不受 qa_entries 早返回影响）
    conn.execute(AGENT_LOG_DDL)
    for _ddl in AGENT_LOG_INDEX_DDL:
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
