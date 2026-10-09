// 隐藏 Windows release 构建时的黑色控制台弹框（黑色弹框的根因）
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use rusqlite::Connection;
use serde::Serialize;
use std::path::PathBuf;
use tauri::AppHandle;

#[derive(Serialize, Clone)]
struct QaEntry {
    qid: String,
    date: String,
    category: String,
    status: String,
    phenomenon: String,
    root_cause: String,
    solution: String,
    files: String,
    /// 1 = 已归档（prune 只置位、永不删除）。Python 侧按 COALESCE(archived,0)=0 过滤，
    /// GUI 必须能区分，否则用户无法判断哪些条目会被 prune 移出默认视野。
    archived: i64,
}

/// 权威类别枚举 —— 必须与 SKILL.md「数据模型」一节逐字一致。
/// GUI 的 <select> 是这份清单的镜像；两处不一致会让下拉赋值变成 "" 并静默清空字段。
const VALID_CATEGORIES: [&str; 10] = [
    "Bug Fix",
    "Feature",
    "Refactor",
    "Performance",
    "Documentation",
    "Architecture",
    "Style",
    "Build",
    "Test",
    "Other",
];

/// 权威状态机（与 Python 侧 qa_tool.VALID_STATUSES 一致）。
const VALID_STATUSES: [&str; 5] = [
    "Pending",
    "已解决待验证",
    "已验证",
    "WontFix",
    "Unresolved",
];

/// 返回 qa.db 的路径（找不到就报绝不静默建空库）。
///
/// 查找顺序：
/// 1. 可执行文件所在目录的 `qa.db`（浏览器 exe 与 qa.db 同目录部署的标准用法）
/// 2. 从 exe 目录逐级向上（target/release -> target -> src-tauri -> tauri-app -> 项目根）
/// 3. 当前工作目录的 `qa.db`
/// 4. 用户漫游 AppData 的 `qa.db`
///
/// 找不到时返回 Err：**绝不**返回一个不存在的路径让 `Connection::open` 凭空建库
/// ——那会让用户看到「共 0 条」而不是「没找到 qa.db」，甚至误打开别人的库。
fn get_db_path(_app: &AppHandle) -> Result<PathBuf, String> {
    // 1. exe 旁
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(dir) = exe_path.parent() {
            let db_path = dir.join("qa.db");
            if db_path.is_file() {
                return Ok(db_path);
            }
        }
    }
    // 2. 从 exe 目录逐级向上找项目根的 qa.db。注意必须「先上移再检查」：
    //    写成「先检查再上移」会少覆盖一层，永远到不了项目根。
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(mut dir) = exe_path.parent().map(|p| p.to_path_buf()) {
            for _ in 0..5 {
                if !dir.pop() {
                    break;
                }
                let candidate = dir.join("qa.db");
                if candidate.is_file() {
                    return Ok(candidate);
                }
            }
        }
    }
    // 3. 当前工作目录
    let cwd = std::env::current_dir().unwrap_or_default().join("qa.db");
    if cwd.is_file() {
        return Ok(cwd);
    }
    // 4. AppData\Roaming\<identifier>\qa.db（用户漫游目录，最后兜底）
    if let Some(app_data) = dirs_roaming_dir() {
        let p = app_data.join("com.qalog.browser").join("qa.db");
        if p.is_file() {
            return Ok(p);
        }
    }
    // 都找不到：明确报错，绝不返回路径让 Connection::open 静默建空库
    Err("未找到 qa.db。请先在项目根运行：python <skill>/scripts/qa_tool.py setup".to_string())
}

/// 跨平台获取用户漫游目录，避免引入 dirs crate。
fn dirs_roaming_dir() -> Option<PathBuf> {
    #[cfg(target_os = "windows")]
    {
        std::env::var_os("APPDATA").map(PathBuf::from)
    }
    #[cfg(target_os = "macos")]
    {
        std::env::var_os("HOME").map(|h| PathBuf::from(h).join("Library/Application Support"))
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        std::env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
    }
}

/// 打开数据库并确保表结构存在（幂等建表 + 自动迁移老 schema）。
fn open_db(app: &AppHandle) -> Result<Connection, String> {
    let db_path = get_db_path(app)?;
    let conn = Connection::open(&db_path).map_err(|e| e.to_string())?;
    // 与 Python sqlite3 的 5s 默认对齐：hooks 正在写库时，读命令要肯等而不是立刻
    // SQLITE_BUSY（rusqlite 默认 busy_timeout=0，比 Python 严苛一个数量级）。
    conn.busy_timeout(std::time::Duration::from_secs(5))
        .map_err(|e| e.to_string())?;

    // 1. 建表（如不存在）。target schema：qid 是单一主键，没有 id 列。
    //    列集合与 scripts/db.py::TARGET_DDL 一致（含 P2 记忆列），否则 GUI 会把
    //    archived/importance 等列读成不存在而误判。
    conn.execute(
        "CREATE TABLE IF NOT EXISTS qa_entries (
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
            parent_qid TEXT,
            importance INTEGER DEFAULT 50,
            access_count INTEGER DEFAULT 0,
            last_access_at TEXT,
            tags TEXT DEFAULT '[]',
            source_session TEXT,
            source_commit TEXT,
            archived INTEGER DEFAULT 0,
            needs_review INTEGER DEFAULT 0
        )",
        [],
    )
    .map_err(|e| e.to_string())?;

    // 2. 检测老 schema (id INTEGER PK AUTOINCREMENT, qid TEXT UNIQUE)，
    //    若存在则一次性迁移到新 schema（CREATE-AS-INSERT-DROP-RENAME）。
    //    必须整体在事务里：中断在 DROP 与 RENAME 之间会永久丢掉全部记录。
    let has_legacy_id: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM pragma_table_info('qa_entries') WHERE name='id'",
            [],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())?;
    if has_legacy_id > 0 {
        let sql = "BEGIN IMMEDIATE;
            DROP TABLE IF EXISTS qa_entries_new;
            CREATE TABLE qa_entries_new (
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
                parent_qid TEXT,
                importance INTEGER DEFAULT 50,
                access_count INTEGER DEFAULT 0,
                last_access_at TEXT,
                tags TEXT DEFAULT '[]',
                source_session TEXT,
                source_commit TEXT,
                archived INTEGER DEFAULT 0,
                needs_review INTEGER DEFAULT 0
            );
            INSERT INTO qa_entries_new
                (qid, date, category, status, phenomenon, root_cause, solution, files, created_at)
            SELECT qid, date, category, status, phenomenon,
                   COALESCE(root_cause, ''), COALESCE(solution, ''), COALESCE(files, ''),
                   COALESCE(created_at, datetime('now','localtime'))
            FROM qa_entries;
            DROP TABLE qa_entries;
            ALTER TABLE qa_entries_new RENAME TO qa_entries;
            COMMIT;";
        if let Err(e) = conn.execute_batch(sql) {
            let _ = conn.execute_batch("ROLLBACK");
            return Err(format!("legacy migration failed（已回滚，原库未变）: {e}"));
        }
    }

    // 3. 补齐缺失列（幂等）：GUI 也可能是第一个打开旧库的进程。
    for (col, ddl) in MEMORY_COLUMNS {
        let has: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM pragma_table_info('qa_entries') WHERE name = ?1",
                [col],
                |row| row.get(0),
            )
            .unwrap_or(0);
        if has == 0 {
            if let Err(e) = conn.execute(ddl, []) {
                let _ = e; // 列已存在等情况可忽略；不阻断只读浏览
            }
        }
    }

    // 4. 3 位 qid（Q-53）补零成 4 位（Q-0053），与 db.py::ensure_schema 步骤 4 一致。
    //    不补零时 GUI 的数值排序与 Python 侧会分叉，且外部写入的 3 位条目永远查不到。
    let _ = conn.execute(
        "UPDATE qa_entries SET qid = 'Q-0' || substr(qid, 3) WHERE length(qid) = 5",
        [],
    );

    Ok(conn)
}

/// P2 记忆列（与 scripts/db.py::MEMORY_COLUMNS 逐字一致，顺序敏感）。
const MEMORY_COLUMNS: [(&str, &str); 10] = [
    ("updated_at", "ALTER TABLE qa_entries ADD COLUMN updated_at TEXT"),
    ("parent_qid", "ALTER TABLE qa_entries ADD COLUMN parent_qid TEXT"),
    ("importance", "ALTER TABLE qa_entries ADD COLUMN importance INTEGER DEFAULT 50"),
    ("access_count", "ALTER TABLE qa_entries ADD COLUMN access_count INTEGER DEFAULT 0"),
    ("last_access_at", "ALTER TABLE qa_entries ADD COLUMN last_access_at TEXT"),
    ("tags", "ALTER TABLE qa_entries ADD COLUMN tags TEXT DEFAULT '[]'"),
    ("source_session", "ALTER TABLE qa_entries ADD COLUMN source_session TEXT"),
    ("source_commit", "ALTER TABLE qa_entries ADD COLUMN source_commit TEXT"),
    ("archived", "ALTER TABLE qa_entries ADD COLUMN archived INTEGER DEFAULT 0"),
    ("needs_review", "ALTER TABLE qa_entries ADD COLUMN needs_review INTEGER DEFAULT 0"),
];

#[tauri::command]
fn get_entries(app: AppHandle) -> Result<Vec<QaEntry>, String> {
    let conn = open_db(&app)?;

    // 与 db.py get_next_qid 同语义：按 SUBSTR(qid,3) 的数值倒序。
    // 直接 ORDER BY qid DESC 只在等宽时正确，qid 破4 位（Q-10000）起会全局错乱。
    let mut stmt = conn
        .prepare(
            "SELECT qid, date, category, status, phenomenon, root_cause, solution, files,
                    COALESCE(archived, 0) AS archived
             FROM qa_entries ORDER BY CAST(SUBSTR(qid, 3) AS INTEGER) DESC",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |row| {
            Ok(QaEntry {
                qid: row.get(0)?,
                date: row.get(1)?,
                category: row.get(2)?,
                status: row.get(3)?,
                phenomenon: row.get(4)?,
                root_cause: row.get(5)?,
                solution: row.get(6)?,
                files: row.get(7)?,
                archived: row.get(8)?,
            })
        })
        .map_err(|e| e.to_string())?;

    let entries: Result<Vec<_>, _> = rows.collect();
    entries.map_err(|e| e.to_string())
}

/// 更新一条 QA 记录。qid 用于定位记录，其余字段为可更新的内容。
#[tauri::command]
fn update_entry(
    app: AppHandle,
    qid: String,
    category: String,
    status: String,
    phenomenon: String,
    root_cause: String,
    solution: String,
    files: String,
) -> Result<(), String> {
    let conn = open_db(&app)?;
    // 类别枚举也要校验：权威集合在 SKILL.md，前端 <select> 只是它的镜像，
    // 两者一旦漂移（例如历史上写成 Refactoring）就会静默写入非法值。
    if !VALID_CATEGORIES.iter().any(|v| *v == category) {
        return Err(format!(
            "invalid category '{}' (allowed: {})",
            category,
            VALID_CATEGORIES.join(", ")
        ));
    }
    // 状态机与 Python 侧同源校验（此前 GUI 可写入任意非法 status，绕过 qa_tool 的闸门）
    if !VALID_STATUSES.iter().any(|v| *v == status) {
        return Err(format!(
            "invalid status '{}' (allowed: {})",
            status,
            VALID_STATUSES.join(", ")
        ));
    }
    let affected = conn
        .execute(
            "UPDATE qa_entries
             SET category = ?, status = ?, phenomenon = ?,
                 root_cause = ?, solution = ?, files = ?,
                 updated_at = datetime('now','localtime')
             WHERE qid = ?",
            rusqlite::params![
                category, status, phenomenon, root_cause, solution, files, qid
            ],
        )
        .map_err(|e| e.to_string())?;
    if affected == 0 {
        return Err(format!("Entry qid={} not found", qid));
    }
    log_event(&conn, &qid, "update", "via QALogBrowser")?;
    Ok(())
}

/// 写审计流水（与 db.py::log_event 同一口径：GUI 也是一等写入端，不留痕则
/// `qa_tool history <ID>` 看不出 GUI 造成的改动，静默覆盖无法追溯）。
fn log_event(conn: &Connection, qid: &str, event: &str, detail: &str) -> Result<(), String> {
    conn.execute(
        "CREATE TABLE IF NOT EXISTS qa_events (id INTEGER PRIMARY KEY AUTOINCREMENT,
             qid TEXT NOT NULL, event TEXT NOT NULL, detail TEXT DEFAULT '',
             actor TEXT DEFAULT 'agent', created_at TEXT DEFAULT (datetime('now','localtime')))",
        [],
    )
    .map_err(|e| e.to_string())?;
    conn.execute(
        "INSERT INTO qa_events (qid, event, detail, actor) VALUES (?1, ?2, ?3, 'user')",
        rusqlite::params![qid, event, detail],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

/// 删除一条 QA 记录。
#[tauri::command]
fn delete_entry(app: AppHandle, qid: String) -> Result<(), String> {
    let conn = open_db(&app)?;
    // 审计先行：db.py 约定「删除也必须留痕」，且 qa_events 无外键，条目消失后流水仍在
    log_event(&conn, &qid, "delete", "via QALogBrowser")?;
    let affected = conn
        .execute("DELETE FROM qa_entries WHERE qid = ?", rusqlite::params![qid])
        .map_err(|e| e.to_string())?;
    if affected == 0 {
        return Err(format!("Entry qid={} not found", qid));
    }
    Ok(())
}

/// 取消归档（prune 只置 archived=1、永不删除；GUI 需要能恢复，否则用户只能去命令行）。
#[tauri::command]
fn unarchive_entry(app: AppHandle, qid: String) -> Result<(), String> {
    let conn = open_db(&app)?;
    let affected = conn
        .execute(
            "UPDATE qa_entries SET archived = 0 WHERE qid = ?",
            rusqlite::params![qid],
        )
        .map_err(|e| e.to_string())?;
    if affected == 0 {
        return Err(format!("Entry qid={} not found", qid));
    }
    log_event(&conn, &qid, "unarchive", "via QALogBrowser")?;
    Ok(())
}

fn main() {
    tauri::Builder::default()
        // 不注册 shell 插件：前端零引用，注册它只是徒增攻击面
        // （capabilities 里的 shell:allow-open 已同步移除）
        .invoke_handler(tauri::generate_handler![
            get_entries,
            update_entry,
            delete_entry,
            unarchive_entry
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
