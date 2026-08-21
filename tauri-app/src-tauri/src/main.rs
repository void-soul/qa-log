use rusqlite::Connection;
use serde::Serialize;
use std::path::PathBuf;
use tauri::AppHandle;

#[derive(Serialize, Clone)]
struct QaEntry {
    id: i64,
    qid: String,
    date: String,
    category: String,
    status: String,
    phenomenon: String,
    root_cause: String,
    solution: String,
    files: String,
}

/// 返回 qa.db 的路径。
///
/// 优先在可执行文件所在目录查找 `qa.db`（浏览器 exe 部署到项目根目录时，
/// 即项目根目录）。若不存在，回退到当前工作目录的 `qa.db`。
fn get_db_path(_app: &AppHandle) -> PathBuf {
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(dir) = exe_path.parent() {
            let db_path = dir.join("qa.db");
            if db_path.exists() {
                return db_path;
            }
        }
    }
    std::env::current_dir().unwrap_or_default().join("qa.db")
}

/// 打开数据库并确保表结构存在（幂等建表）。
fn open_db(app: &AppHandle) -> Result<Connection, String> {
    let db_path = get_db_path(app);
    let conn = Connection::open(&db_path).map_err(|e| e.to_string())?;
    // 建表（与 scripts/qa_tool.py 的 schema 保持一致）
    conn.execute(
        "CREATE TABLE IF NOT EXISTS qa_entries (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            qid        TEXT UNIQUE NOT NULL,
            date       TEXT NOT NULL,
            category   TEXT NOT NULL,
            status     TEXT NOT NULL DEFAULT 'Pending',
            phenomenon TEXT NOT NULL,
            root_cause TEXT DEFAULT '',
            solution   TEXT DEFAULT '',
            files      TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )",
        [],
    )
    .map_err(|e| e.to_string())?;
    Ok(conn)
}

#[tauri::command]
fn get_entries(app: AppHandle) -> Result<Vec<QaEntry>, String> {
    let conn = open_db(&app)?;

    let mut stmt = conn
        .prepare(
            "SELECT id, qid, date, category, status, phenomenon, root_cause, solution, files
             FROM qa_entries ORDER BY id DESC",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |row| {
            Ok(QaEntry {
                id: row.get(0)?,
                qid: row.get(1)?,
                date: row.get(2)?,
                category: row.get(3)?,
                status: row.get(4)?,
                phenomenon: row.get(5)?,
                root_cause: row.get(6)?,
                solution: row.get(7)?,
                files: row.get(8)?,
            })
        })
        .map_err(|e| e.to_string())?;

    let entries: Result<Vec<_>, _> = rows.collect();
    entries.map_err(|e| e.to_string())
}

/// 更新一条 QA 记录。id 用于定位记录，其余字段为可更新的内容。
#[tauri::command]
fn update_entry(
    app: AppHandle,
    id: i64,
    qid: String,
    category: String,
    status: String,
    phenomenon: String,
    root_cause: String,
    solution: String,
    files: String,
) -> Result<(), String> {
    let conn = open_db(&app)?;
    let affected = conn
        .execute(
            "UPDATE qa_entries
             SET qid = ?, category = ?, status = ?, phenomenon = ?,
                 root_cause = ?, solution = ?, files = ?
             WHERE id = ?",
            rusqlite::params![
                qid, category, status, phenomenon, root_cause, solution, files, id
            ],
        )
        .map_err(|e| e.to_string())?;
    if affected == 0 {
        return Err(format!("Entry id={} not found", id));
    }
    Ok(())
}

/// 删除一条 QA 记录。
#[tauri::command]
fn delete_entry(app: AppHandle, id: i64) -> Result<(), String> {
    let conn = open_db(&app)?;
    let affected = conn
        .execute("DELETE FROM qa_entries WHERE id = ?", rusqlite::params![id])
        .map_err(|e| e.to_string())?;
    if affected == 0 {
        return Err(format!("Entry id={} not found", id));
    }
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            get_entries,
            update_entry,
            delete_entry
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
