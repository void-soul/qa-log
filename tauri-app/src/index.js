// 不使用打包器时无法解析裸模块说明符 @tauri-apps/api/core，改走 window.__TAURI__
// tauri.conf.json 必须设置 app.withGlobalTauri = true
const invoke = window.__TAURI__ && window.__TAURI__.core
  ? window.__TAURI__.core.invoke
  : null

let allEntries = []
let filteredEntries = []
let selectedQid = null

async function loadEntries() {
  try {
    allEntries = await invoke('get_entries')
    filteredEntries = [...allEntries]
    renderList()
  } catch (e) {
    console.error('Failed to load entries:', e)
    // 错误信息走 textContent，不进 innerHTML：Rust 侧的错误可能带路径等内容
    const box = document.getElementById('entryList')
    box.textContent = ''
    const div = document.createElement('div')
    div.className = 'detail-empty'
    div.textContent = '加载失败: ' + e
    box.appendChild(div)
  }
}

function getStatusClass(status) {
  const map = { 'Pending': 'pending', '已解决待验证': 'resolved', '已验证': 'resolved', 'WontFix': 'wontfix', 'Unresolved': 'unresolved' }
  return map[status] || 'pending'
}

function escapeHtml(text) {
  if (!text) return ''
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

// 既要 HTML 转义又要安全嵌入 JS 单引号字符串（qid 用于 inline onclick）
function escapeAttr(text) {
  if (!text) return ''
  return String(text).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;')
}

// ---------- Markdown 渲染 ----------
// 用浏览器原生 DOM 做 HTML 转义（防 XSS），再交给 marked.parse 处理。
// 优点：用户在文本里随手写的 <script> 不会执行；表格/列表/代码块会正确渲染。
// 注意：escapeHtml 不处理 URL 协议，marked 的 cleanUrl 也只 encodeURI，
// 所以渲染后必须再做一次协议白名单（javascript:/file:/data: 一律降级为纯文本）。
const SAFE_SCHEME_RE = /^(https?:|mailto:|#|\/)/i
function safeHref(href) {
  const v = String(href || '').trim()
  return SAFE_SCHEME_RE.test(v) ? v : null
}

function renderMd(text) {
  const raw = (text == null ? '' : String(text))
  const trimmed = raw.trim()
  if (!trimmed || trimmed === '[待填写]') {
    return '<p class="md-placeholder">[待填写]</p>'
  }
  if (typeof window.marked === 'undefined') {
    // marked.min.js 没载入时的安全回退（不应发生，仅防炸）
    return `<p>${escapeHtml(raw).replace(/\n/g, '<br>')}</p>`
  }
  try {
    const html = window.marked.parse(escapeHtml(raw), { breaks: true, gfm: true })
    // 只给安全协议的链接加 target=_blank；不安全协议直接去掉 href（不可点击）
    return html.replace(/<a\s+href="([^"]*)"/gi, (m, href) => {
      const safe = safeHref(href)
      return safe === null
        ? '<a>'
        : '<a target="_blank" rel="noopener noreferrer" href="' + safe + '"'
    })
  } catch (e) {
    return `<p>${escapeHtml(raw)}</p>`
  }
}

function renderDetail(entry) {
  return `
    <div class="card">
      <div class="card-header">
        <div class="qid">${escapeHtml(entry.qid)}${entry.archived ? ' <span class="badge">已归档</span>' : ''}</div>
        <div class="meta">
          <span>${escapeHtml(entry.date)}</span>
          <span>${escapeHtml(entry.category)}</span>
          <span class="badge badge-${getStatusClass(entry.status)}">${escapeHtml(entry.status)}</span>
        </div>
        <div class="card-actions">
          ${entry.archived ? '<button class="btn" onclick="unarchiveEntry(\'' + escapeAttr(entry.qid) + '\')">取消归档</button>' : ''}
          <button class="btn btn-edit" onclick="openEditModal('${escapeAttr(entry.qid)}')">编辑</button>
          <button class="btn btn-delete" onclick="deleteEntry('${escapeAttr(entry.qid)}')">删除</button>
        </div>
      </div>
      <div class="section">
        <h3>现象/需求</h3>
        <div class="md">${renderMd(entry.phenomenon)}</div>
      </div>
      <div class="section">
        <h3>根因</h3>
        <div class="md">${renderMd(entry.root_cause)}</div>
      </div>
      <div class="section">
        <h3>解决方案</h3>
        <div class="md">${renderMd(entry.solution)}</div>
      </div>
      <div class="section">
        <h3>涉及文件</h3>
        <div class="md">${renderMd(entry.files)}</div>
      </div>
    </div>
  `
}

function renderList() {
  const list = document.getElementById('entryList')
  const stats = document.getElementById('stats')
  
  stats.textContent = `共 ${filteredEntries.length} 条`
  
  if (filteredEntries.length === 0) {
    list.innerHTML = '<div class="detail-empty">无匹配条目</div>'
    return
  }
  
  list.innerHTML = filteredEntries.map((e, i) => `
    <div class="entry-item ${i === 0 ? 'active' : ''} ${e.archived ? 'archived' : ''}" onclick="selectEntry('${escapeAttr(e.qid)}')" data-qid="${escapeAttr(e.qid)}">
      <div class="qid">${escapeHtml(e.qid)}${e.archived ? ' <span class="badge">已归档</span>' : ''}</div>
      <div class="qtitle">${escapeHtml(e.phenomenon || '')}</div>
      <div class="qmeta">
        <span>${escapeHtml(e.date)}</span>
        <span class="badge badge-${getStatusClass(e.status)}">${escapeHtml(e.status)}</span>
      </div>
    </div>
  `).join('')
  
  if (filteredEntries.length > 0) selectEntry(filteredEntries[0].qid)
}

function selectEntry(qid) {
  selectedQid = qid
  document.querySelectorAll('.entry-item').forEach(el => {
    el.classList.toggle('active', el.dataset.qid === qid)
  })
  const entry = allEntries.find(e => e.qid === qid)
  if (entry) {
    document.getElementById('detail').innerHTML = renderDetail(entry)
  }
}

// 搜索框每敲一键都会触发：加 200ms 防抖，避免长库下每键全量重建 DOM
let _searchTimer = null
function onSearchInput() {
  if (_searchTimer) clearTimeout(_searchTimer)
  _searchTimer = setTimeout(filter, 200)
}

function filter() {
  const query = document.getElementById('search').value.toLowerCase()
  const status = document.getElementById('statusFilter').value
  
  filteredEntries = allEntries.filter(e => {
    if (status && e.status !== status) return false
    if (query) {
      const haystack = `${e.qid} ${e.phenomenon} ${e.root_cause} ${e.solution}`.toLowerCase()
      if (!haystack.includes(query)) return false
    }
    return true
  })
  
  renderList()
}

function refresh() {
  loadEntries()
}

// ---------- 归档 / 恢复 ----------
// prune 只置 archived=1、永不删除（承诺「可恢复」），GUI 必须提供恢复入口，
// 否则用户只能回命令行 --restore。
async function unarchiveEntry(qid) {
  try {
    await invoke('unarchive_entry', { qid })
    await loadEntries()
  } catch (e) {
    alert('取消归档失败: ' + e)
  }
}

// ---------- 编辑 ----------
let editingQid = null

function openEditModal(qid) {
  const entry = allEntries.find(e => e.qid === qid)
  if (!entry) return
  editingQid = qid
  document.getElementById('editQid').value = entry.qid
  document.getElementById('editDate').value = entry.date
  const cat = document.getElementById('editCategory')
  if (!Array.from(cat.options).some(o => o.value === entry.category)) {
    // 库里存在未知类别（如历史值 Pattern）：补进下拉，绝不因 .value='' 而被清空
    const opt = document.createElement('option')
    opt.textContent = entry.category
    cat.appendChild(opt)
  }
  cat.value = entry.category
  document.getElementById('editStatus').value = entry.status
  document.getElementById('editPhenomenon').value = entry.phenomenon || ''
  document.getElementById('editRootCause').value = entry.root_cause || ''
  document.getElementById('editSolution').value = entry.solution || ''
  document.getElementById('editFiles').value = entry.files || ''
  document.getElementById('editModal').style.display = 'flex'
}

function closeEditModal() {
  document.getElementById('editModal').style.display = 'none'
  editingQid = null
}

async function saveEdit() {
  if (editingQid === null) return
  const payload = {
    qid: editingQid,   // 定位键取自打开弹窗时的快照，不信任 DOM 里的可编辑输入
    category: document.getElementById('editCategory').value,
    status: document.getElementById('editStatus').value,
    phenomenon: document.getElementById('editPhenomenon').value,
    root_cause: document.getElementById('editRootCause').value,
    solution: document.getElementById('editSolution').value,
    files: document.getElementById('editFiles').value,
  }
  try {
    await invoke('update_entry', payload)
    closeEditModal()
    await loadEntries()
  } catch (e) {
    alert('保存失败: ' + e)
  }
}

// ---------- 删除 ----------
async function deleteEntry(qid) {
  const entry = allEntries.find(e => e.qid === qid)
  const label = entry ? entry.qid : qid
  if (!confirm(`确定删除 ${label} 吗？此操作不可撤销。`)) return
  try {
    await invoke('delete_entry', { qid })
    await loadEntries()
    // 删除后清除详情，若列表为空则显示空提示
    if (filteredEntries.length === 0) {
      document.getElementById('detail').innerHTML = '<div class="detail-empty">无条目</div>'
    }
  } catch (e) {
    alert('删除失败: ' + e)
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadEntries()
})

window.refresh = refresh
window.selectEntry = selectEntry
window.filter = filter
window.openEditModal = openEditModal
window.closeEditModal = closeEditModal
window.saveEdit = saveEdit
window.deleteEntry = deleteEntry
