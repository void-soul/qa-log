# QA Log Browser — Tauri 项目

桌面版 QA 记录浏览器，读取**使用此 skill 的项目根目录**下的 `qa.db`（SQLite）并展示。

> **v3.0 变更**：数据源由 `QA.md` 改为 `qa.db`。`qa.db` 位于使用 skill 的项目根目录，
> 脚本（`scripts/qa_tool.py`）与浏览器 exe 共用同一个数据库。

## 架构

```
使用 skill 的项目根目录/
├── qa.db               # SQLite 数据库（qa_entries 表）
└── QALogBrowser.exe    # 本项目的编译产物，读取同目录 qa.db
```

**找不到 `qa.db` 时直接报错**（提示先跑 `qa_tool.py setup`），绝不静默新建空库——
否则用户会看到「共 0 条」而不是「没找到 qa.db」，甚至误打开别人的库。

## 功能

- **浏览**：左侧列表 + 右侧详情，支持关键词搜索（200ms 防抖）、状态筛选
- **编辑**：详情页「编辑」打开表单，修改类别/状态/现象/根因/解决方案/涉及文件（调 `update_entry`）
  - **QID 只读**：定位键取自打开弹窗时的快照，绝不允许改 QID 误覆盖另一条记录
  - **类别下拉与 `SKILL.md` 权威枚举逐字一致**；遇到库里的未知类别（如 `Pattern`）会自动补进下拉，不会被静默清空
- **删除**：详情页「删除」二次确认后删除记录（调 `delete_entry`）
- **归档可见**：已归档条目（`prune` 只置 `archived=1`、永不删除）灰显 + 「已归档」角标，并提供「取消归档」按钮
- **审计留痕**：GUI 的更新/删除/取消归档都会写 `qa_events`，与 Python 侧同一口径（`qa_tool.py history <ID>` 可查）
- **自动补列**：GUI 也可能是第一个打开旧库的进程，缺列会自动 `ALTER TABLE` 补齐并补零 3 位 qid

## 后端命令

| 命令 | 参数 | 说明 |
|------|------|------|
| `get_entries` | — | 返回全部条目（按 qid 数值倒序，含 `archived`） |
| `update_entry` | qid, category, status, phenomenon, root_cause, solution, files | 更新一条记录（校验 category/status 枚举，写 `updated_at`） |
| `delete_entry` | qid | 删除一条记录（先写审计事件再删） |
| `unarchive_entry` | qid | 取消归档（`prune` 的逆操作） |

## 构建方式（MANDATORY：必须用 tauri CLI）

> ⚠️ **必须使用 tauri CLI（`npx tauri build`）构建，不能直接用 `cargo build`**。
> 直接 `cargo build` 不会把 `frontendDist` 前端资源嵌入 exe，运行时会去访问
> `devUrl`（`http://localhost:1420`），导致 **"localhost 拒绝访问"**。

```bash
cd /e/pro/skill/qa-log/tauri-app
npm install
npm run tauri dev            # 开发模式（自动先跑 build:dist）
npx tauri build --no-bundle  # 生产构建（嵌入前端资源，不生成安装包）
# 产物: src-tauri/target/release/QALogBrowser.exe   以 productName 命名，不是 qa-log-browser.exe
```

`frontendDist` 指向 `../dist`，由 `npm run build:dist` 从 `index.html` / `src/` / `vendor/`
拷贝生成，并已配进 `beforeDevCommand` / `beforeBuildCommand` —— 全新 clone 可直接构建，
不再依赖某次手工拷贝的残留 `dist/`。

构建完成后，将 `QALogBrowser.exe` 复制到 `../bin/`（作为 skill 的一部分分发）：
```bash
copy src-tauri/target/release/QALogBrowser.exe ../bin/QALogBrowser.exe
```

首次在某个项目使用时，把 exe 复制到该项目根目录即可（详见 `../SKILL.md` 的「首次使用初始化」）。

## 文件结构
```
tauri-app/
├── index.html              # 前端界面（GitHub Dark 主题）
├── src/
│   └── index.js            # 前端逻辑 + Tauri invoke 调用
├── dist/                   # 构建输出（前端静态资源）
├── src-tauri/
│   ├── src/main.rs         # Rust 后端（SQLite 读取 + 自动建表）
│   ├── Cargo.toml          # 依赖配置
│   ├── tauri.conf.json     # Tauri 配置
│   └── capabilities/       # 权限配置
└── package.json
```

## 版本说明
- `@tauri-apps/cli`: 2.11.x (npm)
- `tauri` crate: 2.x（`Cargo.lock` 锁定 tauri 2.11.5 + tauri-build 2.6.3，可正常构建）
- **已解决的历史构建问题**：
  1. `capabilities/*.json` 需包含 `identifier` 字段
  2. 需提供 `icons/` 目录（`icon.ico` 等）
  3. `rusqlite` 需启用 `bundled` 特性（Windows 无系统 sqlite3.lib，避免 `LNK1181: sqlite3.lib`）
  4. `frontendDist` 目录不存在导致构建失败 → 加 `beforeBuildCommand: npm run build:dist`

## 构建产物
```bash
npx tauri build --no-bundle
# → src-tauri/target/release/QALogBrowser.exe（已嵌入前端资源，可独立运行）
# 复制为 bin/QALogBrowser.exe 作为 skill 分发物：
Copy-Item target\release\QALogBrowser.exe ..\..\bin\QALogBrowser.exe
```

> 改了 `src/main.rs` / `src/index.js` / `index.html` 后**必须重新构建 exe**，
> 否则 `bin/QALogBrowser.exe` 仍是旧逻辑（GUI 的写入行为会与新脚本不一致）。
