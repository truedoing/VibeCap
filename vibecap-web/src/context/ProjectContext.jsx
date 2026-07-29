import { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { loadTask, saveTask, migrateLegacyProject } from '../model/series'
import { saveProject as saveLegacyProject, loadProject as loadLegacyProject } from '../model/project'

const TaskContext = createContext(null)

const EMPTY = { picks: {}, timeline: null, mediaCache: null, segments: [], name: '', id: '', seriesId: '', createdAt: 0, updatedAt: 0 }

// ── TaskProvider：从 URL 读取 seriesId/taskId，加载任务数据 ──
export function TaskProvider({ children }) {
  const { seriesId, taskId } = useParams()
  const [project, setProject] = useState(EMPTY)
  const saveTimer = useRef(null)
  const prevKey = useRef(null)

  // 加载任务
  useEffect(() => {
    const key = `${seriesId}/${taskId}`
    if (key === prevKey.current && project) return
    prevKey.current = key

    if (!seriesId || !taskId) return

    let task = loadTask(seriesId, taskId)
    if (!task) {
      // 尝试迁移旧数据
      const migrated = migrateLegacyProject()
      if (migrated && migrated.seriesId === seriesId && migrated.taskId === taskId) {
        task = loadTask(seriesId, taskId)
      }
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
