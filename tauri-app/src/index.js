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
    document.getElementById('entryList').innerHTML = 
      '<div class="detail-empty">加载失败: ' + e + '</div>'
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
    // 给所有链接加 target=_blank，避免内嵌网页可能不可点击
    return html.replace(/<a\s+href=/g, '<a target="_blank" rel="noopener noreferrer" href=')
  } catch (e) {
    return `<p>${escapeHtml(raw)}</p>`
  }
}

function renderDetail(entry) {
  return `
    <div class="card">
      <div class="card-header">
        <div class="qid">${escapeHtml(entry.qid)}</div>
        <div class="meta">
          <span>${escapeHtml(entry.date)}</span>
          <span>${escapeHtml(entry.category)}</span>
          <span class="badge badge-${getStatusClass(entry.status)}">${escapeHtml(entry.status)}</span>
        </div>
        <div class="card-actions">
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
    <div class="entry-item ${i === 0 ? 'active' : ''}" onclick="selectEntry('${escapeAttr(e.qid)}')" data-qid="${escapeAttr(e.qid)}">
      <div class="qid">${escapeHtml(e.qid)}</div>
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

// ---------- 编辑 ----------
let editingQid = null

function openEditModal(qid) {
  const entry = allEntries.find(e => e.qid === qid)
  if (!entry) return
  editingQid = qid
  document.getElementById('editQid').value = entry.qid
  document.getElementById('editDate').value = entry.date
  document.getElementById('editCategory').value = entry.category
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
    qid: document.getElementById('editQid').value.trim(),
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
