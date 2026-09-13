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
const { execFile, execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

// 诊断输出：查看方式 → 命令面板 "输出: 显示输出通道" → 选 "QA Log"
const out = vscode.window.createOutputChannel('QA Log');
function diag(msg) {
  try { out.appendLine(`[${new Date().toLocaleTimeString()}] ${msg}`); } catch (_) { /* 忽略 */ }
}

const { qaListHtml, qaDetailHtml, logListHtml, logDetailHtml, sessionHtml } = require('./views');

// marked.min.js（vendored，与 tauri-app 同源）整个内联进 webview，避免 CSP 资源加载问题
const MARKED_SRC = (() => {
  try { return fs.readFileSync(path.join(__dirname, '..', 'vendor', 'marked.min.js'), 'utf8'); }
  catch (_) { return ''; }
})();

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

/** CodeBuddy 会话本地存储根目录（会话原文 JSON） */
const CB_HISTORY_ROOT = path.join(process.env.LOCALAPPDATA || '', 'CodeBuddyExtension', 'Data');

/** 在会话存储里定位 sessionId 对应的目录。
 * 同一 sessionId 可能有多份副本（不同窗口实例各写一份，新鲜度不同）：
 * 优先用 hook 记录的 transcript 路径（实时副本）；否则扫描全部候选，
 * 取 index.json 修改时间最新的那份。 */
function findTranscriptDir(sessionId, metaTranscript) {
  if (metaTranscript && fs.existsSync(metaTranscript)) {
    return path.dirname(metaTranscript);
  }
  if (!sessionId) return null;
  const candidates = [];
  try {
    for (const userDir of fs.readdirSync(CB_HISTORY_ROOT)) {
      const ideDir = path.join(CB_HISTORY_ROOT, userDir, 'CodeBuddyIDE');
      if (!fs.existsSync(ideDir)) continue;
      for (const uid of fs.readdirSync(ideDir)) {
        const histDir = path.join(ideDir, uid, 'history');
        if (!fs.existsSync(histDir)) continue;
        for (const ws of fs.readdirSync(histDir)) {
          const cand = path.join(histDir, ws, sessionId);
          const idxFile = path.join(cand, 'index.json');
          if (fs.existsSync(idxFile)) {
            let mtime = 0;
            try { mtime = fs.statSync(idxFile).mtimeMs; } catch (_) { /* 忽略 */ }
            candidates.push({ dir: cand, mtime });
          }
        }
      }
    }
  } catch (_) { /* 存储目录不存在等 */ }
  if (!candidates.length) return null;
  candidates.sort((a, b) => b.mtime - a.mtime);
  return candidates[0].dir;
}

/** 解析单条消息文件为内容片段列表（text/reasoning/tool-call/tool-result） */
function parseMessageParts(mdir, id) {
  try {
    const raw = JSON.parse(fs.readFileSync(path.join(mdir, id + '.json'), 'utf8'));
    const inner = typeof raw.message === 'string' ? JSON.parse(raw.message) : (raw.message || {});
    const parts = [];
    for (const c of (inner.content || [])) {
      if (c.type === 'text' || c.type === 'reasoning') {
        parts.push({ type: c.type, text: String(c.text || '').slice(0, 60000) });
      } else if (c.type === 'tool-call') {
        parts.push({ type: 'tool-call', name: c.toolName || '', text: JSON.stringify(c.args ?? null, null, 2).slice(0, 30000) });
      } else if (c.type === 'tool-result') {
        parts.push({ type: 'tool-result', name: c.toolName || '', text: JSON.stringify(c.result ?? c, null, 2).slice(0, 60000) });
      } else {
        parts.push({ type: c.type || 'other', text: JSON.stringify(c).slice(0, 5000) });
      }
    }
    return parts;
  } catch (e) {
    return [{ type: 'error', text: String(e.message || e) }];
  }
}

/** 打开会话原文浏览面板（中间区域）。成功返回 true；找不到会话存储返回 false */
function openSessionBrowser(log) {
  let meta = {};
  try { meta = JSON.parse(log.meta || '{}'); } catch (_) { /* 忽略 */ }
  const dir = findTranscriptDir(log.session_id, meta.transcript);
  if (!dir) return false;

  let skeleton = [];
  try {
    const idx = JSON.parse(fs.readFileSync(path.join(dir, 'index.json'), 'utf8'));
    skeleton = (idx.messages || []).filter((m) => m && m.id).map((m) => ({ id: m.id, role: m.role || '?' }));
  } catch (_) { return false; }
  if (!skeleton.length) return false;
  const mdir = path.join(dir, 'messages');

  // index.json 常落后于 messages/ 文件（最新消息还没进索引）：
  // 把未被索引引用的消息文件按 mtime 追加到骨架末尾，保证最新对话可见可定位
  try {
    const known = new Set(skeleton.map((m) => m.id));
    const orphans = [];
    for (const f of fs.readdirSync(mdir)) {
      if (!f.endsWith('.json')) continue;
      const id = f.slice(0, -5);
      if (known.has(id)) continue;
      let mtime = 0;
      try { mtime = fs.statSync(path.join(mdir, f)).mtimeMs; } catch (_) { continue; }
      orphans.push({ id, mtime });
    }
    orphans.sort((a, b) => a.mtime - b.mtime);
    for (const o of orphans) {
      let role = 'assistant';
      try {
        const raw = JSON.parse(fs.readFileSync(path.join(mdir, o.id + '.json'), 'utf8'));
        role = raw.role || 'assistant';
      } catch (_) { /* 忽略 */ }
      skeleton.push({ id: o.id, role });
    }
    if (orphans.length) diag(`会话浏览: 追加 ${orphans.length} 条未索引消息`);
  } catch (_) { /* messages 目录缺失等 */ }

  // 定位：在 user 消息正文中找包含记录正文前 60 字符的那条
  let targetIdx = -1;
  const needle = String(log.content || '').replace(/\s+/g, ' ').trim().slice(0, 60);
  if (needle) {
    for (let i = 0; i < skeleton.length; i++) {
      if (skeleton[i].role !== 'user') continue;
      const text = parseMessageParts(mdir, skeleton[i].id).map((p) => p.text || '').join(' ').replace(/\s+/g, ' ');
      if (text.includes(needle)) { targetIdx = i; break; }
    }
  }

  const cache = new Map();
  const getParts = (id) => {
    if (!cache.has(id)) cache.set(id, parseMessageParts(mdir, id));
    if (cache.size > 3000) cache.delete(cache.keys().next().value);
    return cache.get(id);
  };

  diag(`会话浏览: ${dir} · ${skeleton.length} 条消息 · 定位于 #${targetIdx + 1}`);

  // 每次打开都是全新面板（旧面板的 range 处理器闭包了旧会话数据，不能复用）
  if (panels['session']) {
    try { panels['session'].dispose(); } catch (_) { /* 忽略 */ }
  }
  const panel = vscode.window.createWebviewPanel('qaLog.session',
    `会话 ${String(log.session_id || '').slice(0, 8)}`,
    { viewColumn: vscode.ViewColumn.Active, preserveFocus: false },
    { enableScripts: true, localResourceRoots: [] });
  panel.onDidDispose(() => { delete panels['session']; }, null, []);
  panel.webview.onDidReceiveMessage((msg) => {
    if (!msg || msg.type !== 'range') return;
    const from = Math.max(0, Number(msg.from) || 0);
    const to = Math.min(skeleton.length - 1, Number(msg.to) || 0);
    const items = {};
    for (let i = from; i <= to; i++) items[skeleton[i].id] = getParts(skeleton[i].id);
    panel.webview.postMessage({ type: 'window', items });
  }, null, []);
  panel.webview.html = sessionHtml({ skeleton, targetIdx, sessionId: log.session_id || '' }, nonce());
  panels['session'] = panel;
  return true;
}

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

// ── QA 详情写操作（更新/删除，JSON 走 stdin 规避命令行中文乱码） ────────────

let qaDetailState = null;   // {entry}
let refreshViews = () => {}; // activate 时注入（重渲染两个侧边栏视图）

function qaWrite(action, args, inputObj) {
  const cfg = vscode.workspace.getConfiguration('qaLog');
  const py = (cfg.get('pythonPath') || 'python').trim() || 'python';
  const argv = [scriptPath(), '--db', dbPath(), action, ...args];
  const run = (cmd) => execFileSync(cmd, argv, {
    input: JSON.stringify(inputObj || {}), encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024, windowsHide: true,
  });
  let stdout;
  try {
    stdout = run(py);
  } catch (e) {
    if (e && e.code === 'ENOENT' && py === 'python') stdout = run('py');
    else {
      const so = String((e && e.stdout) || '');
      if (so.trim()) stdout = so;
      else throw new Error(String((e && e.message) || e));
    }
  }
  const line = String(stdout || '').trim().split(/\r?\n/).filter(Boolean).pop();
  let parsed;
  try { parsed = JSON.parse(line); } catch (_) { throw new Error('JSON 解析失败: ' + (line || '').slice(0, 200)); }
  if (!parsed.ok) throw new Error(parsed.error || 'unknown error');
  return parsed.data;
}

function qaDetailMessage(msg) {
  if (!msg) return;
  if (msg.type === 'copy') {
    vscode.env.clipboard.writeText(String(msg.text || ''));
    vscode.window.setStatusBarMessage('已复制: ' + msg.text, 2000);
    return;
  }
  if (msg.type === 'openExternal') {
    try { vscode.env.openExternal(vscode.Uri.parse(String(msg.url || ''))); } catch (_) { /* 忽略 */ }
    return;
  }
  if (msg.type === 'save') {
    const d = msg.data || {};
    try {
      const res = qaWrite('qa-update', ['--qid', String(d.qid || '')], d);
      qaDetailState = { entry: res.entry };
      const panel = panels['qaDetail'];
      if (panel) panel.webview.html = qaDetailHtml(res.entry, nonce(), MARKED_SRC);
      vscode.window.setStatusBarMessage(`已保存 ${d.qid}`, 3000);
      refreshViews();
    } catch (e) {
      vscode.window.showErrorMessage('QA Log 保存失败: ' + e.message);
    }
    return;
  }
  if (msg.type === 'delete') {
    const qid = String(msg.qid || '');
    vscode.window.showInformationMessage(
      `确定删除 ${qid} 吗？此操作不可撤销。`, { modal: true }, '删除').then((pick) => {
      if (pick !== '删除') return;
      try {
        qaWrite('qa-delete', ['--qid', qid]);
        vscode.window.setStatusBarMessage(`已删除 ${qid}`, 3000);
        if (panels['qaDetail']) { try { panels['qaDetail'].dispose(); } catch (_) { /* 忽略 */ } }
        refreshViews();
      } catch (e) {
        vscode.window.showErrorMessage('QA Log 删除失败: ' + e.message);
      }
    });
  }
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
      qaDetailState = { entry: data.entry };
      showPanel('qaDetail', `QA ${qid}`, qaDetailHtml(data.entry, nonce(), MARKED_SRC),
        qaDetailMessage);
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
      // 优先打开会话原文浏览（中间区域大面板）；找不到会话存储则回落旧详情
      if (openSessionBrowser(log)) return;
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
  refreshViews = () => { qaProvider.render(); logProvider.render(); };
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
