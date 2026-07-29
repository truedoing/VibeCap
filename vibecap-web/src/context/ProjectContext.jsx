import { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { loadTask, saveTask, loadSeriesList, loadTasks, migrateLegacyProject } from '../model/series'
import { saveProject as saveLegacyProject, loadProject as loadLegacyProject } from '../model/project'

const TaskContext = createContext(null)

const EMPTY = { picks: {}, timeline: null, mediaCache: null, segments: [], name: '', id: '', seriesId: '', createdAt: 0, updatedAt: 0 }

// ── TaskProvider：从 URL 读取 seriesId/taskId，加载任务数据 ──
export function TaskProvider({ children }) {
  const { seriesId, taskId } = useParams()
  const [project, setProject] = useState(EMPTY)
  const saveTimer = useRef(null)
  const prevKey = useRef(null)

  // 加载任务（URL 使用名称，需解析为 internal ID）
  useEffect(() => {
    const key = `${seriesId}/${taskId}`
    if (key === prevKey.current && (project?.id)) return
    prevKey.current = key

    if (!seriesId || !taskId) return

    // 1) 直接用 seriesId/taskId 作为 internal ID 查找
    let task = loadTask(seriesId, taskId)

    // 2) 按名称匹配：seriesId 可能是 slug 或原名，taskId 是任务名
    if (!task) {
      const seriesList = loadSeriesList()
      const decoded = decodeURIComponent(seriesId)
      const matchedSeries = seriesList.find(s =>
        s.name === seriesId || s.name === decoded
      )
      if (matchedSeries) {
        const tasks = loadTasks(matchedSeries.id)
        task = tasks.find(t => t.name === taskId || t._realName === taskId)
      }
    }

    // 3) 尝试迁移旧数据
    if (!task) {
      const migrated = migrateLegacyProject()
      if (migrated && migrated.seriesId === seriesId && migrated.taskId === taskId) {
        task = loadTask(seriesId, taskId)
      }
    }

    // 4) 救助孤立数据（写入 vibecap-task-- 的 picks）
    if (task) {
      try {
        const orphan = JSON.parse(localStorage.getItem('vibecap-task--'))
        if (orphan?.picks && Object.keys(orphan.picks).length > 0) {
          // 合并孤立的 picks 到当前任务
          task = { ...task, picks: { ...task.picks, ...orphan.picks }, timeline: null, mediaCache: null }
          saveTask(task)
          localStorage.removeItem('vibecap-task--')
        }
      } catch {}
    }

    if (task) setProject(task)
  }, [seriesId, taskId])

  // 自动持久化
  const persist = useCallback((p) => {
    if (!p || !seriesId || !taskId) return
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => saveTask(p), 200)
  }, [seriesId, taskId])

  // picks 操作
  const handleAddPick = useCallback((sid, seq, type, clipRef) => {
    setProject(prev => {
      if (!prev) return prev
      const next = { ...prev, picks: { ...prev.picks } }
      const key = `${sid}_${seq}`
      next.picks[key] = prev.picks[key]
        ? { main: [...(prev.picks[key].main || [])], supp: [...(prev.picks[key].supp || [])] }
        : { main: [], supp: [] }
      const idx = next.picks[key][type].findIndex(c => c.ep === clipRef.ep && c.start === clipRef.start)
      if (idx >= 0) next.picks[key][type][idx] = { ...next.picks[key][type][idx], ...clipRef }
      else next.picks[key][type].push(clipRef)
      next.timeline = null
      next.mediaCache = null
      persist(next)
      return next
    })
  }, [persist])

  const handleRemovePick = useCallback((sid, seq, type, idx) => {
    setProject(prev => {
      if (!prev) return prev
      const next = { ...prev, picks: { ...prev.picks } }
      const key = `${sid}_${seq}`
      if (next.picks[key]) {
        next.picks[key] = { main: [...(next.picks[key].main || [])], supp: [...(next.picks[key].supp || [])] }
        next.picks[key][type].splice(idx, 1)
        if (next.picks[key].main.length === 0 && next.picks[key].supp.length === 0) delete next.picks[key]
      }
      next.timeline = null
      next.mediaCache = null
      persist(next)
      return next
    })
  }, [persist])

  const handleSaveTimelineCache = useCallback((elahProject, mediaState) => {
    setProject(prev => {
      if (!prev) return prev
      const next = { ...prev, timeline: elahProject, mediaCache: mediaState }
      persist(next)
      return next
    })
  }, [persist])

  const handleInvalidateTimeline = useCallback(() => {
    setProject(prev => {
      if (!prev) return prev
      const next = { ...prev, timeline: null, mediaCache: null }
      persist(next)
      return next
    })
  }, [persist])

  const value = {
    project,
    seriesId,
    taskId,
    addPick: handleAddPick,
    removePick: handleRemovePick,
    saveTimelineCache: handleSaveTimelineCache,
    invalidateTimeline: handleInvalidateTimeline,
  }

  return <TaskContext.Provider value={value}>{children}</TaskContext.Provider>
}

export function useProject() {
  const ctx = useContext(TaskContext)
  if (!ctx) throw new Error('useProject must be used within TaskProvider')
  return ctx
}

// ── 兼容层：给不需要 series/task 的页面（Home, SeriesPage）──
export function EmptyProjectProvider({ children }) {
  const empty = {
    project: EMPTY,
    seriesId: null,
    taskId: null,
    addPick: () => {},
    removePick: () => {},
    saveTimelineCache: () => {},
    invalidateTimeline: () => {},
  }
  return <TaskContext.Provider value={empty}>{children}</TaskContext.Provider>
}

// 向后兼容导出
export function ProjectProvider({ children }) {
  return children
}
