import { invoke } from '@tauri-apps/api/core'

let allEntries = []
let filteredEntries = []
let selectedId = null

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

function renderFilesTable(filesContent) {
  if (!filesContent || filesContent === '[待填写]') return '<p style="color:var(--fg-muted)">暂无文件信息</p>'
  const lines = filesContent.split('\n').filter(l => l.trim())
  if (lines.length < 2) return `<pre style="white-space:pre-wrap;font-family:Consolas,monospace">${escapeHtml(filesContent)}</pre>`
  
  let html = '<table class="files-table"><thead><tr>'
  const headers = lines[0].replace(/[|]/g, '').split(/\s+/).filter(Boolean)
  headers.forEach(h => html += `<th>${escapeHtml(h)}</th>`)
  html += '</tr></thead><tbody>'
  
  for (let i = 2; i < lines.length; i++) {
    const cells = lines[i].replace(/[|]/g, '').split(/\s{2,}/).filter(Boolean)
    if (cells.length >= 2) {
      html += '<tr>'
      cells.forEach(cell => html += `<td>${escapeHtml(cell.trim())}</td>`)
      for (let j = cells.length; j < headers.length; j++) html += '<td></td>'
      html += '</tr>'
    }
  }
  return html + '</tbody></table>'
}

function renderDetail(entry) {
  return `
    <div class="card">
      <div class="card-header">
        <div class="qid">${escapeHtml(entry.qid)}</div>
        <div class="meta">
          <span>📅 ${escapeHtml(entry.date)}</span>
          <span>📁 ${escapeHtml(entry.category)}</span>
          <span class="badge badge-${getStatusClass(entry.status)}">${escapeHtml(entry.status)}</span>
        </div>
      </div>
      <div class="section">
        <h3>现象/需求</h3>
        <p>${escapeHtml(entry.phenomenon || '[待填写]')}</p>
      </div>
      <div class="section">
        <h3>根因</h3>
        <p>${escapeHtml(entry.root_cause || '[待填写]')}</p>
      </div>
      <div class="section">
        <h3>解决方案</h3>
        <p>${escapeHtml(entry.solution || '[待填写]')}</p>
      </div>
      <div class="section">
        <h3>涉及文件</h3>
        ${renderFilesTable(entry.files)}
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
    <div class="entry-item ${i === 0 ? 'active' : ''}" onclick="selectEntry(${e.id})" data-id="${e.id}">
      <div class="qid">${escapeHtml(e.qid)}</div>
      <div class="qtitle">${escapeHtml(e.phenomenon || '')}</div>
      <div class="qmeta">
        <span>${escapeHtml(e.date)}</span>
        <span class="badge badge-${getStatusClass(e.status)}">${escapeHtml(e.status)}</span>
      </div>
    </div>
  `).join('')
  
  if (filteredEntries.length > 0) selectEntry(filteredEntries[0].id)
}

function selectEntry(id) {
  selectedId = id
  document.querySelectorAll('.entry-item').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.id) === id)
  })
  const entry = allEntries.find(e => e.id === id)
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

document.addEventListener('DOMContentLoaded', () => {
  loadEntries()
})

window.refresh = refresh
window.selectEntry = selectEntry
window.filter = filter
