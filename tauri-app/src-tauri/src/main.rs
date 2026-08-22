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
}

/// 返回 qa.db 的路径。
///
/// 查找顺序：
/// 1. 可执行文件所在目录的 `qa.db`（浏览器 exe 与 qa.db 同目录部署的标准用法）
/// 2. 项目根目录（开发期 src-tauri/target/release 启动时回退用）
/// 3. 当前工作目录的 `qa.db`
/// 4. 用户漫游 AppData 的 `qa.db`
///
/// 这样无论从哪个 cwd 启动，只要 qa.db 在 exe 旁边，就能找到；不会误打开
/// `C:\Windows\System32\qa.db` 这样的空文件。
fn get_db_path(_app: &AppHandle) -> PathBuf {
    // 1. exe 旁
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(dir) = exe_path.parent() {
            let db_path = dir.join("qa.db");
            if db_path.exists() {
                return db_path;
            }
        }
    }
    // 2. 项目根的 qa.db（target/release 调试用）
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(mut dir) = exe_path.parent().map(|p| p.to_path_buf()) {
            // 尝试往上找 3 层（target/release -> target -> src-tauri -> 根）
            for _ in 0..3 {
                let candidate = dir.join("qa.db");
                if candidate.exists() {
                    return candidate;
                }
                if !dir.pop() {
                    break;
                }
            }
        }
    }
    // 3. 当前工作目录
    let cwd = std::env::current_dir().unwrap_or_default().join("qa.db");
    if cwd.exists() {
        return cwd;
    }
    // 4. AppData\Roaming\<identifier>\qa.db（用户漫游目录，最后兜底）
    if let Some(app_data) = dirs_roaming_dir() {
        let id_dir = app_data.join("com.qalog.browser");
        if id_dir.exists() {
            let p = id_dir.join("qa.db");
            if p.exists() {
                return p;
            }
        }
    }
    // 都找不到则返回 exe 旁的路径（让 Connection::open 给出有意义的错误或自动建空表）
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .unwrap_or_default()
        .join("qa.db")
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
    let db_path = get_db_path(app);
    let conn = Connection::open(&db_path).map_err(|e| e.to_string())?;

    // 1. 建表（如不存在）。target schema：qid 是单一主键，没有 id 列。
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
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )",
        [],
    )
    .map_err(|e| e.to_string())?;

    // 2. 检测老 schema (id INTEGER PK AUTOINCREMENT, qid TEXT UNIQUE)，
    //    若存在则一次性迁移到新 schema（CREATE-AS-INSERT-DROP-RENAME）。
    let has_legacy_id: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM pragma_table_info('qa_entries') WHERE name='id'",
            [],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())?;
    if has_legacy_id > 0 {
        conn.execute_batch(
            "CREATE TABLE qa_entries_new (
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
            ALTER TABLE qa_entries_new RENAME TO qa_entries;",
        )
        .map_err(|e| e.to_string())?;
    }

    Ok(conn)
}

#[tauri::command]
fn get_entries(app: AppHandle) -> Result<Vec<QaEntry>, String> {
    let conn = open_db(&app)?;

    // 按 qid 倒序排列。qid 形如 Q-0001 ... Q-NNNN（4 位零填充），文本字典序与数值序一致
    // （统一 3 位零填充），所以直接 ORDER BY qid DESC 即可。
    let mut stmt = conn
        .prepare(
            "SELECT qid, date, category, status, phenomenon, root_cause, solution, files
             FROM qa_entries ORDER BY qid DESC",
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
    let affected = conn
        .execute(
            "UPDATE qa_entries
             SET category = ?, status = ?, phenomenon = ?,
                 root_cause = ?, solution = ?, files = ?
             WHERE qid = ?",
            rusqlite::params![
                category, status, phenomenon, root_cause, solution, files, qid
            ],
        )
        .map_err(|e| e.to_string())?;
    if affected == 0 {
        return Err(format!("Entry qid={} not found", qid));
    }
    Ok(())
}

/// 删除一条 QA 记录。
#[tauri::command]
fn delete_entry(app: AppHandle, qid: String) -> Result<(), String> {
    let conn = open_db(&app)?;
    let affected = conn
        .execute("DELETE FROM qa_entries WHERE qid = ?", rusqlite::params![qid])
        .map_err(|e| e.to_string())?;
    if affected == 0 {
        return Err(format!("Entry qid={} not found", qid));
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
