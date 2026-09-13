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
  /* 会话原文浏览（中间面板：上列表下详情） */
  .sessd {
    flex: 2 1 0; min-height: 120px; overflow-y: auto;
    padding: 10px 16px 24px;
    border-top: 1px solid var(--vscode-panel-border, rgba(128,128,128,.35));
    background: var(--vscode-editor-background, transparent);
  }
  .sessd h4 { margin: 12px 0 4px; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; opacity: .7; font-weight: 600; }
  .sessd h4:first-child { margin-top: 0; }
  .sessd pre {
    margin: 0; padding: 8px 10px; overflow-x: auto;
    background: var(--vscode-textCodeBlock-background, rgba(128,128,128,.12));
    border-radius: 4px; font-family: var(--vscode-editor-font-family, monospace);
    font-size: 12px; white-space: pre-wrap; word-break: break-word;
  }
  .sessd pre.clamp { max-height: 12em; overflow: hidden; cursor: pointer; }
  .dragbar {
    flex: 0 0 4px; cursor: row-resize; background: transparent;
    border-top: 1px solid var(--vscode-panel-border, rgba(128,128,128,.35));
  }
  .dragbar:hover, .dragbar.active {
    background: var(--vscode-focusBorder, rgba(128,128,128,.45));
  }
  /* Markdown 渲染（QA 详情字段） */
  .md { line-height: 1.65; word-break: break-word; }
  .md p { margin: 0 0 8px; }
  .md p:last-child { margin-bottom: 0; }
  .md h1, .md h2, .md h3, .md h4 { margin: 12px 0 6px; line-height: 1.4; }
  .md ul, .md ol { margin: 4px 0 8px; padding-left: 22px; }
  .md code {
    font-family: var(--vscode-editor-font-family, monospace); font-size: 12px;
    background: var(--vscode-textCodeBlock-background, rgba(128,128,128,.15));
    padding: 1px 4px; border-radius: 3px;
  }
  .md pre {
    background: var(--vscode-textCodeBlock-background, rgba(128,128,128,.12));
    padding: 8px 10px; border-radius: 4px; overflow-x: auto; margin: 6px 0;
  }
  .md pre code { background: transparent; padding: 0; }
  .md table { border-collapse: collapse; margin: 6px 0; }
  .md th, .md td { border: 1px solid var(--vscode-panel-border, rgba(128,128,128,.4)); padding: 4px 8px; }
  .md blockquote { margin: 6px 0; padding: 2px 12px; border-left: 3px solid var(--vscode-panel-border, rgba(128,128,128,.4)); opacity: .85; }
  .md a { color: var(--vscode-textLink-foreground); }
  .md .ph { opacity: .45; font-style: italic; }
  /* QA 详情编辑表单 */
  .qaform { padding: 12px 18px 24px; max-width: 980px; }
  .qaform label { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; opacity: .7; margin: 10px 0 3px; font-weight: 600; }
  .qaform label:first-child { margin-top: 0; }
  .qaform input, .qaform select, .qaform textarea {
    width: 100%; box-sizing: border-box;
    background: var(--vscode-input-background); color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border, rgba(128,128,128,.4));
    border-radius: 4px; padding: 5px 8px; font-size: 13px;
    font-family: var(--vscode-font-family); outline: none;
  }
  .qaform textarea { min-height: 90px; resize: vertical; font-family: var(--vscode-editor-font-family, monospace); font-size: 12px; line-height: 1.55; }
  .qaform .row { display: flex; gap: 10px; }
  .qaform .row > div { flex: 1; }
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
        el.dataset.idx = String(i);
        if (i === selectedIdx) el.classList.add('active');
        frag.appendChild(el);
      }
      spacer.appendChild(frag);
    }
    container.addEventListener('scroll', () => update(), { passive: true });

    function pick(idx) {
      selectedIdx = idx;
      select(idx);
      if (onPick) onPick(items[idx], idx);
    }

    // 点击行 → pick（事件委托；行是动态挂载的，不能逐行绑事件）
    container.addEventListener('click', (e) => {
      const row = e.target && e.target.closest ? e.target.closest('.vrow') : null;
      if (!row || row.parentElement !== spacer) return;
      const idx = parseInt(row.dataset.idx, 10);
      if (!isNaN(idx)) pick(idx);
    });

    function select(idx) {
      selectedIdx = idx;
      Array.from(spacer.children).forEach((el) => el.classList.remove('active'));
      const el = spacer.children[idx - (visible ? visible[0] : 0)];
      if (el) el.classList.add('active');
    }

    return {
      render() { spacer.style.height = (items.length * ROW_H) + 'px'; visible = null; update(); },
      select: select,
      pick: pick,
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

function page(nonce, csp, bodyHtml, scriptHtml, preScriptHtml) {
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
${preScriptHtml || ''}
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

// ── 中间面板：QA 详情（Markdown 渲染 + 浏览/编辑双模式 + 删除） ────────────

function qaDetailHtml(entry, nonce, markedSrc) {
  const csp = `default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';`;
  const body = `
  <div class="detail" id="view"></div>
  <div class="qaform hidden" id="edit"></div>`;
  const script = `
  const E = ${jsonScript(entry)};
  const STATUS_CLASS = ${jsonScript(STATUS_CLASS)};
  const STATUSES = ['Pending', '已解决待验证', '已验证', 'WontFix', 'Unresolved'];

  // Markdown 渲染：先 HTML 转义再 parse，用户输入的 <script> 不会执行
  function md(text) {
    const raw = (text == null ? '' : String(text)).trim();
    if (!raw || raw === '[待填写]') return '<p class="ph">[待填写]</p>';
    const escaped = esc(raw);
    if (typeof marked === 'undefined') return '<pre style="white-space:pre-wrap">' + escaped + '</pre>';
    try { return marked.parse(escaped, { breaks: true, gfm: true }); }
    catch (e) { return '<pre>' + escaped + '</pre>'; }
  }

  function stCls(st) { return (STATUS_CLASS[st] || '').split(' ')[1] || 'b-pending'; }

  function renderView() {
    const v = $('view');
    v.innerHTML =
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:4px">'
      + '<span style="font-weight:600;font-size:15px;color:var(--vscode-textLink-foreground)">' + esc(E.qid) + '</span>'
      + '<span class="badge ' + stCls(E.status) + '">' + esc(E.status || '') + '</span>'
      + '<span class="sub">' + esc(E.date || '') + '</span>'
      + '<span class="sub">' + esc(E.category || '') + '</span>'
      + '<span style="flex:1"></span>'
      + '<button class="btn" id="cp">复制 QID</button>'
      + '<button class="btn" id="ed">编辑</button>'
      + '<button class="btn" id="del">删除</button></div>'
      + '<h4>现象 / 需求</h4><div class="md">' + md(E.phenomenon) + '</div>'
      + '<h4>根因</h4><div class="md">' + md(E.root_cause) + '</div>'
      + '<h4>解决方案</h4><div class="md">' + md(E.solution) + '</div>'
      + '<h4>涉及文件</h4><div class="md">' + md(E.files) + '</div>';
    $('cp').addEventListener('click', () => vscode.postMessage({ type: 'copy', text: E.qid }));
    $('ed').addEventListener('click', renderEdit);
    $('del').addEventListener('click', () => vscode.postMessage({ type: 'delete', qid: E.qid }));
  }

  function renderEdit() {
    const f = $('edit');
    const opt = (st) => '<option value="' + esc(st) + '"' + (st === E.status ? ' selected' : '') + '>' + esc(st) + '</option>';
    const ta = (id, label, val) =>
      '<label for="' + id + '">' + label + '</label><textarea id="' + id + '">' + esc(val || '') + '</textarea>';
    f.innerHTML =
      '<div class="row">'
      + '<div><label for="fdate">日期</label><input id="fdate" value="' + esc(E.date || '') + '"></div>'
      + '<div><label for="fcat">分类</label><input id="fcat" value="' + esc(E.category || '') + '"></div>'
      + '<div><label for="fst">状态（状态机）</label><select id="fst">' + STATUSES.map(opt).join('') + '</select></div>'
      + '</div>'
      + ta('fphen', '现象 / 需求', E.phenomenon)
      + ta('fcause', '根因', E.root_cause)
      + ta('fsol', '解决方案', E.solution)
      + ta('ffiles', '涉及文件', E.files)
      + '<div style="margin-top:12px;display:flex;gap:8px">'
      + '<button class="btn primary" id="sv">保存</button>'
      + '<button class="btn" id="cx">取消</button></div>';
    $('view').classList.add('hidden');
    f.classList.remove('hidden');
    $('sv').addEventListener('click', () => {
      vscode.postMessage({ type: 'save', data: {
        qid: E.qid,
        date: $('fdate').value.trim(),
        category: $('fcat').value.trim(),
        status: $('fst').value,
        phenomenon: $('fphen').value,
        root_cause: $('fcause').value,
        solution: $('fsol').value,
        files: $('ffiles').value,
      } });
    });
    $('cx').addEventListener('click', () => {
      f.classList.add('hidden');
      v.classList.remove('hidden');
    });
  }

  // Markdown 内的链接 → 系统浏览器打开
  document.addEventListener('click', (e) => {
    const a = e.target && e.target.closest ? e.target.closest('a') : null;
    if (a && a.href && /^https?:/i.test(a.href)) {
      e.preventDefault();
      vscode.postMessage({ type: 'openExternal', url: a.href });
    }
  });

  renderView();`;
  return page(nonce, csp, body, script, markedSrc || '');
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

// ── 中间面板：会话原文浏览（上=虚拟滚动列表，下=选中消息全文） ───────────────

function sessionHtml(data, nonce) {
  const csp = `default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';`;
  const body = `
  <div class="col">
    <div class="toolbar">
      <span class="sub" id="info"></span>
      <span class="sub" id="hint">点击行在下方看全文 · 滚动按需加载</span>
    </div>
    <div class="vlist" id="list" style="flex: 3 1 0"></div>
    <div class="dragbar" id="drag" title="拖动调整上下比例"></div>
    <div class="sessd" id="d" style="flex: 2 1 0"><div class="empty">（选择消息查看全文）</div></div>
  </div>`;
  const script = `
  const DATA = ${jsonScript(data)};
  const skeleton = DATA.skeleton || [];
  const contents = {};
  let lastRange = '';
  let pendingShow = (typeof DATA.targetIdx === 'number' && DATA.targetIdx >= 0) ? DATA.targetIdx : null;

  function summarize(role, parts) {
    if (role === 'tool') {
      const r = parts.find((x) => x.type === 'tool-result');
      if (r) return (r.name || 'tool') + ' · ' + String(r.text || '').replace(/\\s+/g, ' ').slice(0, 90);
      return 'tool';
    }
    const texts = parts.filter((x) => x.type === 'text').map((x) => x.text).join(' ').replace(/\\s+/g, ' ').trim();
    const call = parts.find((x) => x.type === 'tool-call');
    const reasoning = parts.filter((x) => x.type === 'reasoning').map((x) => x.text).join(' ').replace(/\\s+/g, ' ').trim();
    if (texts) return texts.slice(0, 200);
    if (call) return '🔧 ' + (call.name || 'tool') + ' · ' + String(call.text || '').replace(/\\s+/g, ' ').slice(0, 80);
    if (reasoning) return '💭 ' + reasoning.slice(0, 120);
    return '(空)';
  }

  function showDetail(idx) {
    const m = skeleton[idx];
    if (!m) return;
    const parts = contents[m.id] || [];
    const titles = { text: m.role === 'user' ? '用户消息' : '回复正文', reasoning: '思考过程',
      'tool-call': '工具调用（参数）', 'tool-result': '工具结果', error: '读取失败' };
    let html = '<h4>#' + (idx + 1) + ' · ' + esc(m.role) + '</h4>';
    if (!parts.length) { html += '<pre>（内容加载中…）</pre>'; }
    for (const p of parts) {
      html += '<h4>' + esc(titles[p.type] || p.type) + '</h4><pre>' + esc(p.text || '(空)') + '</pre>';
    }
    $('d').innerHTML = html;
    attachClamp($('d'));
    $('d').scrollTop = 0;
  }

  const list = virtualList($('list'), skeleton,
    (m, idx) => {
      const el = document.createElement('div');
      el.className = 'vrow';
      let dot = '#6e7681';
      if (m.role === 'user') dot = '#1f6feb';
      else if (m.role === 'assistant') dot = '#238636';
      const p = contents[m.id];
      const label = p ? summarize(m.role, p) : '…';
      el.title = label;
      el.innerHTML = '<span class="dot" style="background:' + dot + '"></span>'
        + '<span class="text">' + esc((idx + 1) + '. ' + label) + '</span>'
        + '<span class="sub">' + esc(m.role) + '</span>';
      if (idx === DATA.targetIdx) el.style.fontWeight = '600';
      return el;
    },
    (m, idx) => { list.select(idx); showDetail(idx); });

  function requestRange() {
    const top = Math.max(0, $('list').scrollTop);
    const h = $('list').clientHeight || 400;
    const from = Math.max(0, Math.floor(top / ROW_H) - 12);
    const to = Math.min(skeleton.length, Math.ceil((top + h) / ROW_H) + 12);
    const key = from + ':' + to;
    if (key === lastRange) return;
    lastRange = key;
    vscode.postMessage({ type: 'range', from: from, to: to });
  }

  $('list').addEventListener('scroll', requestRange, { passive: true });

  window.addEventListener('message', (ev) => {
    const m = ev.data || {};
    if (m.type === 'window' && m.items) {
      Object.assign(contents, m.items);
      list.render();
      requestRange();
      if (pendingShow != null && contents[skeleton[pendingShow] && skeleton[pendingShow].id]) {
        showDetail(pendingShow);
        pendingShow = null;
      }
    }
  });

  $('info').textContent = '会话 ' + (DATA.sessionId || '') + ' · ' + skeleton.length + ' 条消息'
    + (DATA.targetIdx >= 0 ? ' · 已定位 #' + (DATA.targetIdx + 1) : ' · 未找到目标消息');

  // ── 上下分栏拖拽 ──
  let dragging = null;
  $('drag').addEventListener('mousedown', (e) => {
    dragging = { y: e.clientY, h: $('list').getBoundingClientRect().height };
    $('drag').classList.add('active');
    document.body.style.cursor = 'row-resize';
    e.preventDefault();
  });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const colH = document.body.getBoundingClientRect().height - 4;
    const nh = Math.max(80, Math.min(colH - 80, dragging.h + (e.clientY - dragging.y)));
    $('list').style.flex = '0 0 auto';
    $('list').style.height = nh + 'px';
    $('d').style.flex = '1 1 0';
  });
  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = null;
    $('drag').classList.remove('active');
    document.body.style.cursor = '';
    list.render();
    requestRange();
  });

  if (pendingShow != null) {
    // 初始定位到目标消息（列表中央），等首屏内容到达后自动展示全文
    setTimeout(() => {
      $('list').scrollTop = Math.max(0, DATA.targetIdx * ROW_H - ($('list').clientHeight || 400) / 2);
      list.render();
      list.select(DATA.targetIdx);
      requestRange();
    }, 30);
  } else {
    requestRange();
  }`;
  return page(nonce, csp, body, script);
}

module.exports = { qaListHtml, qaDetailHtml, logListHtml, logDetailHtml, sessionHtml };
