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

浏览器启动时若 `qa.db` 不存在或缺少 `qa_entries` 表，会自动创建（幂等），可直接运行。

## 构建方式（MANDATORY：必须用 tauri CLI）

> ⚠️ **必须使用 tauri CLI（`npx tauri build`）构建，不能直接用 `cargo build`**。
> 直接 `cargo build` 不会把 `frontendDist` 前端资源嵌入 exe，运行时会去访问
> `devUrl`（`http://localhost:1420`），导致 **"localhost 拒绝访问"**。

```bash
cd /e/pro/skill/qa-log/tauri-app
npm install
npm run tauri dev     # 开发模式（需先起前端 dev server）
npx tauri build --no-bundle   # 生产构建（嵌入前端资源，不生成安装包）
# 产物: src-tauri/target/release/qa-log-browser.exe
```

构建完成后，将 `QALogBrowser.exe` 复制到 `../bin/`（作为 skill 的一部分分发）：
```bash
copy src-tauri/target/release/qa-log-browser.exe ../bin/QALogBrowser.exe
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

## 构建产物
```bash
npx tauri build --no-bundle
# → src-tauri/target/release/qa-log-browser.exe（已嵌入前端资源，可独立运行）
# 复制为 bin/QALogBrowser.exe 作为 skill 分发物：
Copy-Item target\release\qa-log-browser.exe ..\..\bin\QALogBrowser.exe
```
