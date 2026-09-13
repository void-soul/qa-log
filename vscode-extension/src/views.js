// Webview HTML 生成
//
// 结构：
//   · 侧边栏：单列列表（虚拟滚动、单行省略）—— 只负责浏览与选择
//   · 详情：由扩展用 createWebviewPanel 打开在 IDE 中间区域（复用同一面板）
//
// 导出：
//   qaListHtml     侧边栏 · QA 列表
//   qaDetailHtml   中间面板 · QA 单条详情
//   logListHtml    侧边栏 · Agent 用户输入历史（时间倒序）
//   logDetailHtml  中间面板 · 单条用户输入详情（含归属会话 ID）

const ROW_H = 26; // 与 CSS .vrow 保持一致

/** 安全地把数据注入 <script>（转义 < 防止提前闭合） */
function jsonScript(data) {
  return JSON.stringify(data === undefined ? null : data)
    .replace(/</g, '\\u003c')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

const COMMON_CSS = `
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0; padding: 0;
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size, 13px);
    color: var(--vscode-foreground);
    background: transparent;
  }
  .col { display: flex; flex-direction: column; height: 100%; }
  .toolbar {
    flex: 0 0 auto; display: flex; gap: 6px; align-items: center;
    padding: 8px; background: var(--vscode-sideBar-background);
    border-bottom: 1px solid var(--vscode-panel-border, rgba(128,128,128,.35));
  }
  .toolbar input, .toolbar select {
    flex: 1 1 auto; min-width: 0;
    background: var(--vscode-input-background);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border, transparent);
    border-radius: 4px; padding: 4px 6px; font-size: 12px; outline: none;
  }
  .toolbar select { flex: 0 0 auto; max-width: 110px; }
  .btn {
    background: var(--vscode-button-secondaryBackground, rgba(128,128,128,.2));
    color: var(--vscode-button-secondaryForeground, inherit);
    border: none; border-radius: 4px; padding: 3px 8px;
    font-size: 11px; cursor: pointer; white-space: nowrap;
  }
  .btn:hover { background: var(--vscode-button-secondaryHoverBackground, rgba(128,128,128,.3)); }
  .btn.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
  .btn.primary:hover { background: var(--vscode-button-hoverBackground); }
  .sub { font-size: 10px; opacity: .6; white-space: nowrap; }
  /* 虚拟滚动列表（侧边栏） */
  .vlist { flex: 1 1 auto; overflow-y: auto; position: relative; }
  .vspacer { position: relative; width: 100%; }
  .vrow {
    position: absolute; left: 0; right: 0; height: ${ROW_H}px;
    display: flex; align-items: center; gap: 6px; padding: 0 10px;
    cursor: pointer; white-space: nowrap; overflow: hidden;
    border-bottom: 1px solid rgba(128,128,128,.12);
  }
  .vrow:hover { background: var(--vscode-list-hoverBackground); }
  .vrow.active { background: var(--vscode-list-activeSelectionBackground); }
  .vrow .text { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dot { flex: 0 0 auto; width: 8px; height: 8px; border-radius: 50%; background: #8957e5; }
  .dot.d-resolved { background: #1f6feb; }
  .dot.d-verified { background: #238636; }
  .dot.d-wontfix  { background: #6e7681; }
  .dot.d-unres    { background: #9e6a03; }
  /* 详情面板（中间区域） */
  .detail { padding: 14px 18px 30px; line-height: 1.65; max-width: 900px; }
  .detail h4 {
    margin: 16px 0 4px; font-size: 11px; text-transform: uppercase;
    letter-spacing: .5px; opacity: .7; font-weight: 600;
  }
  .detail h4:first-child { margin-top: 2px; }
  .detail pre {
    margin: 0; padding: 10px; overflow-x: auto;
    background: var(--vscode-textCodeBlock-background, rgba(128,128,128,.12));
    border-radius: 4px; font-family: var(--vscode-editor-font-family, monospace);
    font-size: 12px; white-space: pre-wrap; word-break: break-word;
  }
  .detail pre.clamp { max-height: 12em; overflow: hidden; cursor: pointer; }
  .badge {
    font-size: 10px; padding: 1px 6px; border-radius: 8px;
    background: var(--vscode-badge-background);
    color: var(--vscode-badge-foreground); white-space: nowrap;
  }
  .badge.b-pending  { background: #8957e5; color: #fff; }
  .badge.b-resolved { background: #1f6feb; color: #fff; }
  .badge.b-verified { background: #238636; color: #fff; }
  .badge.b-wontfix  { background: #6e7681; color: #fff; }
  .badge.b-unres    { background: #9e6a03; color: #fff; }
  .empty, .err, .spin { padding: 16px; opacity: .75; line-height: 1.6; }
  .err { color: var(--vscode-errorForeground); }
  .banner {
    flex: 0 0 auto; display: flex; gap: 8px; align-items: center;
    padding: 6px 10px; font-size: 12px;
    background: rgba(143, 89, 229, .15);
    border-bottom: 1px solid rgba(128,128,128,.3);
  }
  /* 时间线（会话详情面板） */
  .tl { max-width: 900px; padding: 6px 18px 30px; }
  .tl-row {
    position: relative; padding: 6px 0 6px 16px;
    border-left: 1px solid var(--vscode-panel-border, rgba(128,128,128,.3));
  }
  .tl-row::before {
    content: ''; position: absolute; left: -4px; top: 12px;
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--vscode-textLink-foreground);
  }
  .tl-row.e-user_prompt::before     { background: #1f6feb; }
  .tl-row.e-assistant_reply::before { background: #238636; }
  .tl-role { font-size: 10px; text-transform: uppercase; letter-spacing: .5px; opacity: .6; }
  .tl-body { margin-top: 3px; white-space: pre-wrap; word-break: break-word; line-height: 1.5; }
  .hidden { display: none !important; }
`;

/** 通用脚本：虚拟滚动 + clamp 折叠 + 复制 */
const COMMON_JS = `
  const ROW_H = ${ROW_H};
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const vscode = acquireVsCodeApi();

  // 虚拟滚动：固定行高，只渲染可见窗口（+overscan），上千条也只挂载几十个节点
  function virtualList(container, items, renderRow, onPick) {
    const spacer = document.createElement('div');
    spacer.className = 'vspacer';
    container.textContent = '';
    container.appendChild(spacer);
    let selectedIdx = -1, visible = null;

    function update() {
      const top = Math.max(0, container.scrollTop);
      const from = Math.max(0, Math.floor(top / ROW_H) - 8);
      const to = Math.min(items.length, Math.ceil((top + container.clientHeight) / ROW_H) + 8);
      if (visible && from === visible[0] && to === visible[1]) return;
      visible = [from, to];
      spacer.textContent = '';
      const frag = document.createDocumentFragment();
      for (let i = from; i < to; i++) {
        const el = renderRow(items[i], i);
        el.style.top = (i * ROW_H) + 'px';
        if (i === selectedIdx) el.classList.add('active');
        frag.appendChild(el);
      }
      spacer.appendChild(frag);
    }
    container.addEventListener('scroll', () => update(), { passive: true });

    return {
      render() { spacer.style.height = (items.length * ROW_H) + 'px'; visible = null; update(); },
      select(idx) {
        selectedIdx = idx;
        Array.from(spacer.children).forEach((el) => el.classList.remove('active'));
        const el = spacer.children[idx - (visible ? visible[0] : 0)];
        if (el) el.classList.add('active');
      },
      pick(idx) { selectedIdx = idx; this.select(idx); if (onPick) onPick(items[idx], idx); },
    };
  }

  // 长文本折叠
  function attachClamp(root) {
    Array.from(root.querySelectorAll('pre')).forEach((pre) => {
      if (pre.scrollHeight > 200 && pre.textContent.length > 800) {
        pre.classList.add('clamp');
        pre.addEventListener('click', () => pre.classList.toggle('clamp'));
      }
    });
  }
`;

function page(nonce, csp, bodyHtml, scriptHtml) {
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>${COMMON_CSS}</style>
</head>
<body>
${bodyHtml}
<script nonce="${nonce}">
${COMMON_JS}
${scriptHtml}
</script>
</body>
</html>`;
}

const STATUS_CLASS = {
  'Pending': 'd-pending b-pending',
  '已解决待验证': 'd-resolved b-resolved',
  '已验证': 'd-verified b-verified',
  'WontFix': 'd-wontfix b-wontfix',
  'Unresolved': 'd-unres b-unres',
};

// ── 侧边栏：QA 列表 ────────────────────────────────────────────────────────

function qaListHtml(data, nonce) {
  const csp = `default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';`;
  const body = `
  <div class="col">
    <div class="toolbar">
      <input id="q" type="text" placeholder="搜索 QID / 现象 / 根因 / 方案…">
      <select id="st">
        <option value="">全部</option>
        <option>Pending</option>
        <option>已解决待验证</option>
        <option>已验证</option>
        <option>WontFix</option>
        <option>Unresolved</option>
      </select>
      <span class="sub" id="cnt"></span>
    </div>
    <div class="vlist" id="list"></div>
  </div>`;
  const script = `
  const DATA = ${jsonScript(data)};
  const STATUS_CLASS = ${jsonScript(STATUS_CLASS)};
  const DIAG = (DATA && DATA.diag) || {};

  if (DATA && DATA.error) {
    document.body.innerHTML = '<div class="err">' + esc(DATA.error)
      + '<br><span style="opacity:.7;font-size:11px">数据源: ' + esc(DIAG.db || '')
      + ' · script: ' + esc(DIAG.script || '') + ' · python: ' + esc(DIAG.python || '') + '</span></div>';
  } else {
    const entries = (DATA && DATA.entries) || [];
    let filtered = entries.slice();
    const cls = (st) => (STATUS_CLASS[st] || 'd-pending').split(' ')[0];

    const list = virtualList($('list'), filtered,
      (e) => {
        const el = document.createElement('div');
        el.className = 'vrow';
        el.title = (e.qid || '') + ' [' + (e.status || '') + '] ' + (e.phenomenon || '');
        el.innerHTML = '<span class="dot ' + cls(e.status) + '"></span>'
          + '<span class="text">' + esc(e.phenomenon || '') + '</span>'
          + '<span class="sub">' + esc(e.qid || '') + '</span>';
        return el;
      },
      (e, idx) => { list.select(idx); vscode.postMessage({ type: 'openDetail', qid: e.qid }); });

    function showEmpty() {
      $('list').innerHTML = '<div class="empty">当前项目还没有 QA 记录。<br>'
        + '<span style="opacity:.6;font-size:11px">数据源: ' + esc(DIAG.db || '') + '</span></div>';
    }

    function applyFilter() {
      const kw = $('q').value.trim().toLowerCase();
      const st = $('st').value;
      filtered = entries.filter((e) => {
        if (st && e.status !== st) return false;
        if (!kw) return true;
        return [e.qid, e.phenomenon, e.root_cause, e.solution, e.files, e.category]
          .join(' ').toLowerCase().includes(kw);
      });
      $('cnt').textContent = filtered.length + ' 条';
      if (!filtered.length && !entries.length) { showEmpty(); return; }
      if (!filtered.length) { $('list').innerHTML = '<div class="empty">无匹配条目</div>'; return; }
      list.render();
    }
    $('q').addEventListener('input', applyFilter);
    $('st').addEventListener('change', applyFilter);
    applyFilter();
  }`;
  return page(nonce, csp, body, script);
}

// ── 中间面板：QA 详情 ──────────────────────────────────────────────────────

function qaDetailHtml(entry, nonce) {
  const csp = `default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';`;
  const body = `<div class="detail" id="d"></div>`;
  const script = `
  const E = ${jsonScript(entry)};
  const STATUS_CLASS = ${jsonScript(STATUS_CLASS)};

  const stCls = (STATUS_CLASS[E.status] || '').split(' ')[1] || 'b-pending';
  $('d').innerHTML =
    '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
    + '<span style="font-weight:600;font-size:15px;color:var(--vscode-textLink-foreground)">' + esc(E.qid) + '</span>'
    + '<span class="badge ' + stCls + '">' + esc(E.status || '') + '</span>'
    + '<span class="sub">' + esc(E.date || '') + '</span>'
    + '<span class="sub">' + esc(E.category || '') + '</span>'
    + '<button class="btn" id="cp">复制 QID</button></div>'
    + '<h4>现象 / 需求</h4><pre>' + esc(E.phenomenon || '') + '</pre>'
    + '<h4>根因</h4><pre>' + esc(E.root_cause || '—') + '</pre>'
    + '<h4>解决方案</h4><pre>' + esc(E.solution || '—') + '</pre>'
    + '<h4>涉及文件</h4><pre>' + esc(E.files || '—') + '</pre>';
  attachClamp($('d'));
  $('cp').addEventListener('click', () => vscode.postMessage({ type: 'copy', text: E.qid }));`;
  return page(nonce, csp, body, script);
}

// ── 侧边栏：Agent 日志（用户输入历史，时间倒序） ────────────────────────────

function logListHtml(data, nonce) {
  const csp = `default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';`;
  const body = `
  <div class="col">
    <div class="banner hidden" id="hooksBanner">
      <span>日志未启用 — 自动记录用户输入</span>
      <button class="btn primary" id="btnHooks">启用</button>
    </div>
    <div class="toolbar">
      <input id="q" type="text" placeholder="搜索输入历史…">
      <span class="sub" id="cnt"></span>
      <button class="btn" id="btnHooksMini" title="hooks 配置状态 / 启用或停用">⚙</button>
    </div>
    <div class="vlist" id="list"></div>
  </div>`;
  const script = `
  const DATA = ${jsonScript(data)};
  const HOOKS_INSTALLED = ${jsonScript(!!(data && data.hooksInstalled))};

  // ── hooks 配置 ──
  const hooksBtn = $('btnHooksMini');
  function setHooksUI(installed, pending) {
    $('hooksBanner').classList.toggle('hidden', !!installed);
    hooksBtn.textContent = installed ? '⚙✓' : '⚙';
    hooksBtn.title = installed ? '自动记录已启用。点击可停用' : '自动记录未启用。点击立即启用';
    hooksBtn.dataset.installed = installed ? '1' : '0';
    hooksBtn.disabled = !!pending;
  }
  setHooksUI(HOOKS_INSTALLED, false);
  function toggleHooks() {
    const installed = hooksBtn.dataset.installed === '1';
    setHooksUI(installed, true);
    vscode.postMessage({ type: installed ? 'hooksRemove' : 'hooksInstall' });
  }
  $('btnHooks').addEventListener('click', toggleHooks);
  hooksBtn.addEventListener('click', toggleHooks);

  // ── 用户输入历史（时间倒序） ──
  const DIAG = (DATA && DATA.diag) || {};
  if (DATA && DATA.error) {
    document.body.innerHTML = '<div class="err">' + esc(DATA.error)
      + '<br><span style="opacity:.7;font-size:11px">数据源: ' + esc(DIAG.source || '')
      + ' · python: ' + esc(DIAG.python || '') + '</span></div>';
  } else {
    const logs = (DATA && DATA.logs) || [];
    let filtered = logs.slice();
    const hhmm = (t) => {
      // created_at 形如 YYYY-MM-DD HH:MM:SS → 显示 MM-DD HH:MM
      const m = String(t || '').match(/^\\d{4}-(\\d{2}-\\d{2}) (\\d{2}:\\d{2})/);
      return m ? m[1] + ' ' + m[2] : String(t || '');
    };

    const list = virtualList($('list'), filtered,
      (l) => {
        const el = document.createElement('div');
        el.className = 'vrow';
        el.title = l.title || '';
        el.innerHTML = '<span class="dot" style="background:#1f6feb"></span>'
          + '<span class="text">' + esc(l.title || '(无内容)') + '</span>'
          + '<span class="sub">' + esc(hhmm(l.created_at)) + '</span>';
        return el;
      },
      (l, idx) => { list.select(idx); vscode.postMessage({ type: 'openLog', id: l.id }); });

    function applyFilter() {
      const kw = $('q').value.trim().toLowerCase();
      filtered = logs.filter((l) => {
        if (!kw) return true;
        return [l.title, l.content].join(' ').toLowerCase().includes(kw);
      });
      $('cnt').textContent = filtered.length + ' 条';
      if (!filtered.length && !logs.length) {
        // 明确空：给出诊断线索而不是让人摸不着头脑
        $('list').innerHTML = '<div class="empty">本项目还没有输入历史。<br>'
          + '确认已启用自动记录（点击上方 ⚙）并在启用后<b>重启 CodeBuddy</b>，'
          + '然后发一条消息试试。<br>'
          + '<span style="opacity:.6;font-size:11px">数据源: ' + esc(DIAG.source || '') + '</span></div>';
        $('cnt').textContent = '0 条';
        list.render();
        return;
      }
      list.render();
    }
    $('q').addEventListener('input', applyFilter);
    applyFilter();

    window.addEventListener('message', (ev) => {
      const m = ev.data || {};
      if (m.type === 'hooksResult') {
        setHooksUI(!!m.installed, false);
      }
    });
  }`;
  return page(nonce, csp, body, script);
}

// ── 中间面板：单条用户输入详情 ─────────────────────────────────────────────

function logDetailHtml(log, nonce) {
  const csp = `default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';`;
  const body = `
  <div class="detail" id="d"></div>`;
  const script = `
  const L = ${jsonScript(log)};
  const projName = (p) => String(p || '').split(/[\\\\/]/).filter(Boolean).pop() || '(未知项目)';

  $('d').innerHTML =
    '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
    + '<span style="font-weight:600;font-size:14px">用户输入</span>'
    + '<span class="sub">' + esc(L.created_at || '') + '</span>'
    + '<span class="sub">' + esc(projName(L.project)) + '</span>'
    + '<button class="btn" id="cp">复制全文</button></div>'
    + '<h4>内容</h4><pre>' + esc(L.content || L.title || '') + '</pre>'
    + '<h4>归属会话</h4><pre>' + esc(L.session_id || '') + '</pre>';
  attachClamp($('d'));
  $('cp').addEventListener('click', () => vscode.postMessage({ type: 'copy', text: L.content || L.title || '' }));`;
  return page(nonce, csp, body, script);
}

module.exports = { qaListHtml, qaDetailHtml, logListHtml, logDetailHtml };
