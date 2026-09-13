// QA Log —— VSCode / CodeBuddy 扩展入口
//
// 结构：
//   · 侧边栏（两个活动栏入口）：单列列表，虚拟滚动，只负责浏览与选择
//   · 详情：点击列表项后在 IDE 中间区域打开 WebviewPanel（复用，非弹窗）
//       - QA      → QA 详情面板
//       - Agent 日志 → 用户输入历史（时间倒序），点击看单条全文
//   · hooks 管理：首次激活提示 + 侧边栏内一键启用/停用
//
// 数据访问：调用 Python 脚本 scripts/qa_query.py 输出 JSON（复用 db.py 的
// 建表/迁移逻辑，避开 Electron Node 对 node:sqlite 的版本差异）。

const vscode = require('vscode');
const { execFile } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

// 诊断输出：查看方式 → 命令面板 "输出: 显示输出通道" → 选 "QA Log"
const out = vscode.window.createOutputChannel('QA Log');
function diag(msg) {
  try { out.appendLine(`[${new Date().toLocaleTimeString()}] ${msg}`); } catch (_) { /* 忽略 */ }
}

const { qaListHtml, qaDetailHtml, logListHtml, logDetailHtml } = require('./views');

// ── CodeBuddy hooks 管理（Node 版，与 scripts/setup_hooks.py 逻辑一致） ────

const CB_SETTINGS = path.join(os.homedir(), '.codebuddy', 'settings.json');
const CB_BACKUP = CB_SETTINGS + '.bak-agentlog';
const HOOK_EVENTS = ['UserPromptSubmit', 'Stop'];

function hookScriptPath() {
  return path.join(path.dirname(scriptPath()), 'agent_log_hook.py');
}

function isOurHook(cfg, event) {
  const groups = (cfg.hooks && cfg.hooks[event]) || [];
  return groups.some((g) => (g.hooks || []).some((h) =>
    String(h.command || '').includes('agent_log_hook.py')));
}

function hookEntry() {
  const script = hookScriptPath().replace(/\\/g, '/');
  return [{
    hooks: [{ type: 'command', command: `python "${script}"`, timeout: 30 }],
  }];
}

function hooksInstalled(settingsPath = CB_SETTINGS) {
  try {
    if (!fs.existsSync(hookScriptPath())) return false;
    const cfg = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
    return HOOK_EVENTS.every((ev) => isOurHook(cfg, ev));
  } catch (_) {
    return false;
  }
}

function installHooks(settingsPath = CB_SETTINGS) {
  const script = hookScriptPath();
  if (!fs.existsSync(script)) {
    return { ok: false, message: `找不到 hook 脚本：${script}` };
  }
  let cfg = {};
  try {
    cfg = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
  } catch (e) {
    return { ok: false, message: `读取 ${settingsPath} 失败：${e.message}` };
  }
  const backup = settingsPath + '.bak-agentlog';
  if (fs.existsSync(settingsPath) && !fs.existsSync(backup)) {
    fs.copyFileSync(settingsPath, backup);
  }
  const hooks = (cfg.hooks = cfg.hooks || {});
  for (const ev of Object.keys(hooks)) {
    if (!HOOK_EVENTS.includes(ev) && isOurHook(cfg, ev)) delete hooks[ev];
  }
  for (const ev of HOOK_EVENTS) hooks[ev] = hookEntry();
  fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
  fs.writeFileSync(settingsPath, JSON.stringify(cfg, null, 2) + '\n', 'utf8');
  return { ok: true, message: 'hooks 已启用' };
}

function removeHooks(settingsPath = CB_SETTINGS) {
  let cfg;
  try {
    cfg = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
  } catch (e) {
    return { ok: false, message: `读取 ${settingsPath} 失败：${e.message}` };
  }
  if (!cfg.hooks) return { ok: true, message: '未安装' };
  for (const ev of HOOK_EVENTS) {
    if (isOurHook(cfg, ev)) delete cfg.hooks[ev];
  }
  if (!Object.keys(cfg.hooks).length) delete cfg.hooks;
  fs.writeFileSync(settingsPath, JSON.stringify(cfg, null, 2) + '\n', 'utf8');
  return { ok: true, message: 'hooks 已停用' };
}

// ── 路径与查询 ─────────────────────────────────────────────────────────────

function workspaceRoot() {
  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length) {
    return folders[0].uri.fsPath;
  }
  return process.cwd();
}

function dbPath() {
  const cfg = vscode.workspace.getConfiguration('qaLog');
  const explicit = (cfg.get('dbPath') || '').trim();
  if (explicit) {
    return explicit;
  }
  // 与 agent_log_hook.find_project_root 一致：从工作区根向上找第一个含 qa.db 的目录
  // （monorepo 场景下 qa.db 可能在上层），找不到则用工作区根
  let cur = workspaceRoot();
  for (let i = 0; i < 12 && cur; i++) {
    if (fs.existsSync(path.join(cur, 'qa.db'))) {
      return path.join(cur, 'qa.db');
    }
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  return path.join(workspaceRoot(), 'qa.db');
}

function scriptPath() {
  const cfg = vscode.workspace.getConfiguration('qaLog');
  const explicit = (cfg.get('scriptPath') || '').trim();
  if (explicit && fs.existsSync(explicit)) {
    return explicit;
  }
  const home = os.homedir();
  const candidates = [
    path.join(home, '.claude', 'skills', 'qa-log', 'scripts', 'qa_query.py'),
    path.join(home, '.agents', 'skills', 'qa-log', 'scripts', 'qa_query.py'),
    path.join(home, '.codebuddy', 'skills', 'qa-log', 'scripts', 'qa_query.py'),
    path.join(workspaceRoot(), 'scripts', 'qa_query.py'),
    'e:/pro/skill/qa-log/scripts/qa_query.py',
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      return c;
    }
  }
  return candidates[0];
}

function query(action, extra = [], dbOverride = null) {
  const cfg = vscode.workspace.getConfiguration('qaLog');
  const py = (cfg.get('pythonPath') || 'python').trim() || 'python';
  const script = scriptPath();
  const db = dbOverride || dbPath();

  diag(`query ${action}: db=${db} script=${script} python=${py} args=${JSON.stringify(extra)}`);

  if (!fs.existsSync(script)) {
    diag(`ERROR: qa_query.py 不存在: ${script}`);
    return Promise.reject(new Error(`找不到 qa_query.py（可在设置里指定 qaLog.scriptPath）：${script}`));
  }
  if (!fs.existsSync(db)) {
    diag(`ERROR: 数据库不存在: ${db}`);
    return Promise.reject(new Error(`找不到数据库：${db}`));
  }

  const args = [script, '--db', db, action, ...extra];
  return new Promise((resolve, reject) => {
    const run = (cmd, argv) => {
      const t0 = Date.now();
      execFile(cmd, argv, { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, windowsHide: true },
        (err, stdout, stderr) => {
          if (err && err.code === 'ENOENT' && cmd === py) {
            // python 不在 PATH 时回退 py -3（Windows 官方安装器）
            diag(`ENOENT: '${cmd}' 不可用，回退 'py -3'`);
            run('py', ['-3', ...argv]);
            return;
          }
          if (err && !stdout) {
            diag(`ERROR(${cmd}): ${err.message}${stderr ? ` | stderr: ${stderr.slice(0, 500)}` : ''}`);
            reject(new Error(`${err.message}${stderr ? `\n${stderr}` : ''}`));
            return;
          }
          const line = String(stdout || '').trim().split(/\r?\n/).filter(Boolean).pop();
          if (!line) {
            diag(`ERROR: 空输出(${cmd})${stderr ? ` | stderr: ${stderr.slice(0, 500)}` : ''}`);
            reject(new Error(`空输出${stderr ? `\n${stderr}` : ''}`));
            return;
          }
          let parsed;
          try {
            parsed = JSON.parse(line);
          } catch (e) {
            diag(`ERROR: JSON 解析失败: ${e.message} | 原始: ${line.slice(0, 300)}`);
            reject(new Error(`JSON 解析失败: ${e.message}\n原始输出: ${line.slice(0, 300)}`));
            return;
          }
          if (!parsed.ok) {
            diag(`ERROR: 脚本返回失败: ${parsed.error}`);
            reject(new Error(parsed.error || 'unknown error'));
            return;
          }
          const n = parsed.data && (parsed.data.entries || parsed.data.logs || parsed.data.projects || parsed.data.sessions)
            ? (parsed.data.entries || parsed.data.logs || parsed.data.projects || parsed.data.sessions).length : '?';
          diag(`OK ${action}: ${n} 行, ${Date.now() - t0}ms`);
          resolve(parsed.data);
        });
    };
    run(py, args);
  });
}

// ── 中间区域详情面板（复用同一面板，避免点开一堆积 tab） ─────────────────────

const panels = {}; // kind -> WebviewPanel

function showPanel(kind, title, html, onMessage) {
  let panel = panels[kind];
  if (panel) {
    panel.title = title;
    panel.webview.html = html;
    panel.reveal(vscode.ViewColumn.Active);
  } else {
    panel = vscode.window.createWebviewPanel(`qaLog.${kind}`, title, {
      viewColumn: vscode.ViewColumn.Active,
      preserveFocus: false,
    }, { enableScripts: true, localResourceRoots: [] });
    panel.onDidDispose(() => { delete panels[kind]; }, null, []);
    if (onMessage) {
      panel.webview.onDidReceiveMessage(onMessage, null, []);
    }
    panel.webview.html = html;
    panels[kind] = panel;
  }
  return panel;
}

function nonce() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let s = '';
  for (let i = 0; i < 32; i++) {
    s += chars[Math.floor(Math.random() * chars.length)];
  }
  return s;
}

// ── QA 视图（侧边栏） ──────────────────────────────────────────────────────

class QaViewProvider {
  constructor(context) {
    this.context = context;
  }

  async resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.onDidReceiveMessage((msg) => {
      if (!msg) return;
      if (msg.type === 'openDetail') {
        this.openDetail(String(msg.qid || ''));
      }
    });
    await this.render();
  }

  async openDetail(qid) {
    try {
      const data = await query('qa-get', ['--qid', qid]);
      showPanel('qaDetail', `QA ${qid}`, qaDetailHtml(data.entry, nonce()),
        (msg) => {
          if (msg && msg.type === 'copy') {
            vscode.env.clipboard.writeText(String(msg.text || ''));
            vscode.window.setStatusBarMessage('已复制: ' + msg.text, 2000);
          }
        });
    } catch (e) {
      vscode.window.showErrorMessage(`QA Log: ${e.message}`);
    }
  }

  async render() {
    if (!this.view) return;
    const n = nonce();
    const diagInfo = {
      db: dbPath(),
      script: scriptPath(),
      python: (vscode.workspace.getConfiguration('qaLog').get('pythonPath') || 'python'),
    };
    diag(`QA 视图刷新: db=${diagInfo.db}`);
    try {
      const data = await query('qa-list', []);
      this.view.webview.html = qaListHtml({ ...data, diag: diagInfo }, n);
    } catch (e) {
      this.view.webview.html = qaListHtml({ error: String(e.message || e), diag: diagInfo }, n);
    }
  }
}

// ── Agent 日志视图（侧边栏） ────────────────────────────────────────────────

class LogViewProvider {
  constructor(context) {
    this.context = context;
  }

  async resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    view.webview.onDidReceiveMessage((msg) => {
      if (!msg) return;
      if (msg.type === 'openLog') {
        this.openLog(Number(msg.id) || 0);
      } else if (msg.type === 'hooksInstall') {
        const r = installHooks();
        this.afterHooks(r, true);
      } else if (msg.type === 'hooksRemove') {
        const r = removeHooks();
        this.afterHooks(r, false);
      }
    });
    await this.render();
  }

  afterHooks(r, installed) {
    if (r.ok) {
      vscode.window.setStatusBarMessage(
        `Agent 日志 hooks ${installed ? '已启用（重启 CodeBuddy 生效）' : '已停用'}`, 4000);
    } else {
      vscode.window.showErrorMessage('hooks 配置失败: ' + r.message);
    }
    this.render();
  }

  async openLog(id) {
    try {
      const data = await query('log-list', ['--id', String(id)]);
      const log = (data.logs || [])[0];
      if (!log) {
        vscode.window.showWarningMessage(`日志记录不存在: #${id}`);
        return;
      }
      showPanel('logDetail', `输入 ${log.created_at || '#' + id}`,
        logDetailHtml(log, nonce()),
        (msg) => {
          if (msg && msg.type === 'copy') {
            vscode.env.clipboard.writeText(String(msg.text || ''));
            vscode.window.setStatusBarMessage('已复制全文', 2000);
          }
        });
    } catch (e) {
      vscode.window.showErrorMessage(`QA Log: ${e.message}`);
    }
  }

  async render() {
    if (!this.view) return;
    const n = nonce();
    // 只读本项目 qa.db 的 agent_log 表（hook 双写中的项目库），天然按项目隔离
    const db = dbPath();
    const diagInfo = {
      source: db,
      python: (vscode.workspace.getConfiguration('qaLog').get('pythonPath') || 'python'),
    };
    diag(`日志视图刷新: db=${db}`);
    try {
      const logs = await query('log-list', ['--event', 'user_prompt', '--limit', '500'], db);
      this.view.webview.html = logListHtml({
        ...logs,
        hooksInstalled: hooksInstalled(),
        diag: diagInfo,
      }, n);
    } catch (e) {
      this.view.webview.html = logListHtml({
        error: String(e.message || e),
        diag: diagInfo,
      }, n);
    }
  }
}

// ── 激活 ───────────────────────────────────────────────────────────────────

function activate(context) {
  diag(`激活: workspace=${workspaceRoot()} db=${dbPath()} script=${scriptPath()}`);
  const qaProvider = new QaViewProvider(context);
  const logProvider = new LogViewProvider(context);

  context.subscriptions.push(
    out,
    vscode.window.registerWebviewViewProvider('qaLog.qaView', qaProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    vscode.window.registerWebviewViewProvider('qaLog.logView', logProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('qaLog.refresh', () => {
      qaProvider.render();
      logProvider.render();
    }),
    vscode.commands.registerCommand('qaLog.openDb', async () => {
      const dir = path.dirname(dbPath());
      if (fs.existsSync(dir)) {
        await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(dir));
      } else {
        vscode.window.showWarningMessage(`目录不存在: ${dir}`);
      }
    }),
    vscode.commands.registerCommand('qaLog.setupHooks', async () => {
      const wasInstalled = hooksInstalled();
      const r = wasInstalled ? removeHooks() : installHooks();
      if (r.ok) {
        const nowInstalled = hooksInstalled();
        const msg = nowInstalled
          ? 'Agent 日志 hooks 已启用。重启 CodeBuddy 后生效。'
          : 'Agent 日志 hooks 已停用。';
        const pick = await vscode.window.showInformationMessage(msg, '知道了');
        logProvider.render();
        return pick;
      }
      vscode.window.showErrorMessage('hooks 配置失败: ' + r.message);
    }),
  );

  // 监听 qa.db 变化自动刷新（hook 持续写入；防抖）
  try {
    const dbDir = path.dirname(dbPath());
    if (fs.existsSync(dbDir)) {
      let timer = null;
      const watcher = vscode.workspace.createFileSystemWatcher(
        new vscode.RelativePattern(vscode.Uri.file(dbDir), 'qa.db*'));
      const refresh = () => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => { qaProvider.render(); logProvider.render(); }, 500);
      };
      watcher.onDidChange(refresh);
      watcher.onDidCreate(refresh);
      context.subscriptions.push(watcher);
    }
  } catch (_) { /* 忽略 */ }

  // 首次激活：hooks 未安装时提示一键启用（每个安装只提示一次）
  const promptedKey = 'qaLog.hooksPrompted';
  setTimeout(async () => {
    try {
      if (hooksInstalled()) return;
      if (context.globalState.get(promptedKey)) return;
      await context.globalState.update(promptedKey, true);
      const pick = await vscode.window.showInformationMessage(
        'QA Log：是否启用 Agent 会话自动记录？（把用户消息与回复写入项目 qa.db）',
        '启用', '暂不');
      if (pick === '启用') {
        const r = installHooks();
        if (r.ok) {
          vscode.window.showInformationMessage(
            'Agent 日志 hooks 已启用。重启 CodeBuddy 后生效。');
        } else {
          vscode.window.showErrorMessage('hooks 配置失败: ' + r.message);
        }
      }
    } catch (_) { /* 忽略 */ }
  }, 3000);
}

function deactivate() { }

module.exports = {
  activate, deactivate, installHooks, removeHooks, hooksInstalled,
};
