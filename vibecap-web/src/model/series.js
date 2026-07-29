// ═══════════════════════════════════════════════
// VIBECAP 项目层级数据模型
// 电视剧（Series）= 根，任务（Task）= 剪辑单元
// ═══════════════════════════════════════════════

// ── localStorage key ──
const SERIES_INDEX_KEY = 'vibecap-series'
const taskKey = (seriesId, taskId) => `vibecap-task-${seriesId}-${taskId}`

// ── Series ──
export function loadSeriesList() {
  try {
    const raw = localStorage.getItem(SERIES_INDEX_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

export function saveSeriesList(list) {
  localStorage.setItem(SERIES_INDEX_KEY, JSON.stringify(list))
}

export function createSeries(name) {
  const list = loadSeriesList()
  const s = { id: 's_' + Date.now(), name, createdAt: Date.now() }
  list.push(s)
  saveSeriesList(list)
  return s
}

export function deleteSeries(id) {
  const list = loadSeriesList().filter(s => s.id !== id)
  saveSeriesList(list)
  // 清理该剧下所有任务的 localStorage
  const keysToRemove = []
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i)
    if (k && k.startsWith(`vibecap-task-${id}-`)) keysToRemove.push(k)
  }
  keysToRemove.forEach(k => localStorage.removeItem(k))
}

// ── Task 列表（隶属于某个 Series）──
export function loadTasks(seriesId) {
  const prefix = `vibecap-task-${seriesId}-`
  const tasks = []
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i)
    if (k && k.startsWith(prefix)) {
      try {
        const raw = localStorage.getItem(k)
        if (raw) tasks.push(JSON.parse(raw))
      } catch {}
    }
  }
  return tasks.sort((a, b) => b.createdAt - a.createdAt)
}

export function createTask(seriesId, name, extras = {}) {
  const task = {
    id: 't_' + Date.now(),
    seriesId,
    name,
    status: 'editing',  // editing | reviewing | delivered
    picks: {},
    timeline: null,
    mediaCache: null,
    segments: [],
    narrText: extras.narrText || '',
    narrFileName: extras.narrFileName || '',
    audioFileName: extras.audioFileName || '',
    createdAt: Date.now(),
    updatedAt: Date.now(),
  }
  saveTask(task)
  return task
}

export function loadTask(seriesId, taskId) {
  try {
    const raw = localStorage.getItem(taskKey(seriesId, taskId))
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

export function saveTask(task) {
  task.updatedAt = Date.now()
  localStorage.setItem(taskKey(task.seriesId, task.id), JSON.stringify(task))
}

export function deleteTask(seriesId, taskId) {
  localStorage.removeItem(taskKey(seriesId, taskId))
}

// ── 兼容迁移：旧 vibecap-project → 新模型 ──
export function migrateLegacyProject() {
  try {
    const raw = localStorage.getItem('vibecap-project')
    if (!raw) return null
    const old = JSON.parse(raw)
    // 创建默认电视剧
    let list = loadSeriesList()
    if (list.length === 0) {
      list = [{ id: 's_legacy', name: '未分类项目', createdAt: Date.now() }]
      saveSeriesList(list)
    }
    const sid = list[0].id
    const task = {
      id: 't_legacy',
      seriesId: sid,
      name: old.name || '导入的任务',
      picks: old.picks || {},
      timeline: old.timeline || null,
      mediaCache: old.mediaCache || null,
      segments: old.segments || [],
      createdAt: old.createdAt || Date.now(),
      updatedAt: Date.now(),
    }
    saveTask(task)
    // 迁移后删除旧数据
    localStorage.removeItem('vibecap-project')
    return { seriesId: sid, taskId: task.id }
  } catch { return null }
}
