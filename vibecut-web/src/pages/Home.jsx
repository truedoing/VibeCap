import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { loadSeriesList, createSeries, createTask, loadTasks, saveTask } from '../model/series'
import { Plus, Tv, FolderOpen, RefreshCw, Upload, X, ChevronRight, ChevronDown, ChevronUp, AlertTriangle, CheckCircle, XCircle, Info } from 'lucide-react'

// Toast components (unchanged)
const TOAST_ICONS = { ok: CheckCircle, error: XCircle, info: Info }
const TOAST_CLASSES = {
  ok: 'border-green-500/20 bg-green-500/5 text-green-400',
  error: 'border-red-500/20 bg-red-500/5 text-red-400',
  info: 'border-blue-500/20 bg-blue-500/5 text-blue-400',
}
function ToastItem({ id, type, message, onDismiss }) {
  const Icon = TOAST_ICONS[type] || Info
  useEffect(() => {
    const t = setTimeout(() => onDismiss(id), 3500)
    return () => clearTimeout(t)
  }, [id, onDismiss])
  return (
    <div className={`flex items-center gap-2 px-4 py-3 rounded-lg border shadow-lg backdrop-blur-sm animate-in fade-in slide-in-from-top-2 duration-200 ${TOAST_CLASSES[type]}`}>
      <Icon size={14} className="shrink-0" />
      <span className="text-xs">{message}</span>
      <button onClick={() => onDismiss(id)} className="ml-auto shrink-0 opacity-60 hover:opacity-100"><X size={12} /></button>
    </div>
  )
}

let _toastId = 0
let _globalAddToast = null
export function showToast(type, message) {
  if (_globalAddToast) _globalAddToast({ id: ++_toastId, type, message })
}
function ToastContainer() {
  const [toasts, setToasts] = useState([])
  _globalAddToast = useCallback((t) => setToasts(prev => [...prev, t]), [])
  const dismiss = useCallback((id) => setToasts(prev => prev.filter(t => t.id !== id)), [])
  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
      {toasts.map(t => (
        <div key={t.id} className="pointer-events-auto">
          <ToastItem {...t} onDismiss={dismiss} />
        </div>
      ))}
    </div>
  )
}

function DeleteConfirmModal({ taskName, onConfirm, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-card border border-border rounded-xl p-6 w-[380px] shadow-2xl animate-in fade-in zoom-in-95 duration-150" onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center shrink-0">
            <AlertTriangle size={20} className="text-red-400" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-foreground">删除任务</h3>
            <p className="text-[11px] text-muted-foreground">此操作不可撤销</p>
          </div>
        </div>
        <p className="text-xs text-muted-foreground mb-1">将永久删除任务及所有关联数据：</p>
        <div className="p-3 rounded-lg bg-secondary/30 border border-border mb-5">
          <p className="text-sm font-medium text-foreground">{taskName}</p>
          <p className="text-[10px] text-muted-foreground mt-0.5">分段 ・ 时间轴缓存 ・ picks</p>
        </div>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 rounded-lg border border-border text-xs text-muted-foreground hover:bg-accent transition-colors">取消</button>
          <button onClick={onConfirm} className="px-4 py-2 rounded-lg bg-red-500/15 border border-red-500/20 text-xs text-red-400 hover:bg-red-500/25 transition-colors font-medium">确认删除</button>
        </div>
      </div>
    </div>
  )
}

function NewTaskForm({ dramaName, onCreated, onClose }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [docxFile, setDocxFile] = useState(null)
  const [audioFile, setAudioFile] = useState(null)
  const [localPath, setLocalPath] = useState('')
  const [useLocalPath, setUseLocalPath] = useState(false)
  const [creating, setCreating] = useState(false)
  const [result, setResult] = useState(null)

  const handleCreate = async () => {
    if (!name.trim()) return
    setCreating(true)
    try {
      const fd = new FormData()
      fd.append('drama', dramaName)
      fd.append('name', name.trim())
      if (description.trim()) fd.append('description', description.trim())
      if (useLocalPath && localPath.trim()) {
        fd.append('local_path', localPath.trim())
      } else {
        if (docxFile) fd.append('docx', docxFile)
        if (audioFile) fd.append('audio', audioFile)
      }
      const resp = await fetch('/tasks/create', { method: 'POST', body: fd })
      const data = await resp.json()
      setResult(data)
      if (data?.ok) onCreated()
    } catch (e) { setResult({ ok: false, error: e.message }) }
    setCreating(false)
  }

  return (
    <div className="p-3 border-t border-border bg-secondary/20 space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium">新建任务</h4>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X size={14} /></button>
      </div>
      <input autoFocus value={name} onChange={e => setName(e.target.value)}
        placeholder="任务名称，如 Task0804"
        className="w-full bg-card border border-border rounded-md px-2.5 py-1.5 text-xs outline-none focus:border-primary/50" />
      <textarea value={description} onChange={e => setDescription(e.target.value)}
        placeholder="任务描述（将自动填入编剧台选题），如：苏明成人物线：从妈宝到守护者"
        rows={2}
        className="w-full bg-card border border-border rounded-md px-2.5 py-1.5 text-xs outline-none focus:border-primary/50 resize-none" />
      <div className="flex gap-1 text-[10px]">
        <button onClick={() => setUseLocalPath(false)} className={`px-2 py-1 rounded ${!useLocalPath ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground'}`}>上传文件</button>
        <button onClick={() => setUseLocalPath(true)} className={`px-2 py-1 rounded ${useLocalPath ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground'}`}>本地路径</button>
      </div>
      {useLocalPath ? (
        <input value={localPath} onChange={e => setLocalPath(e.target.value)} placeholder="素材目录路径"
          className="w-full bg-card border border-border rounded-md px-2.5 py-1.5 text-xs outline-none focus:border-primary/50" />
      ) : (
        <div className="flex gap-2">
          <label className="flex-1 flex items-center gap-1 px-2 py-1 rounded border border-border text-[10px] cursor-pointer hover:bg-accent">
            <Upload size={10} /> {docxFile ? docxFile.name : '文案.docx'}
            <input type="file" accept=".docx" className="hidden" onChange={e => setDocxFile(e.target.files?.[0] || null)} />
          </label>
          <label className="flex-1 flex items-center gap-1 px-2 py-1 rounded border border-border text-[10px] cursor-pointer hover:bg-accent">
            <Upload size={10} /> {audioFile ? audioFile.name : '音频.wav'}
            <input type="file" accept=".wav,.mp3" className="hidden" onChange={e => setAudioFile(e.target.files?.[0] || null)} />
          </label>
        </div>
      )}
      {result && <p className={`text-[10px] ${result.ok ? 'text-green-400' : 'text-red-400'}`}>{result.ok ? '✅ 创建成功' : result.error || '失败'}</p>}
      <button onClick={handleCreate} disabled={!name.trim() || creating}
        className="w-full py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium disabled:opacity-40">
        {creating ? '创建中...' : '创建任务'}
      </button>
    </div>
  )
}

const SLUG_MAP = { '都挺好': 'doutinghao', '杨老师教育': 'yanglaoshi' }
function toSlug(name) { return SLUG_MAP[name] || encodeURIComponent(name) }

function TaskDetail({ task, dramaName }) {
  const nav = useNavigate()
  const [info, setInfo] = useState(null)

  useEffect(() => {
    fetch(`/segments.json?task=${encodeURIComponent(task.name)}`)
      .then(r => r.json())
      .then(data => {
        const segs = data.segments || []
        const narrCount = segs.filter(s => s.narration_text || s.highlight_text).length
        const totalChars = segs.reduce((sum, s) => sum + (s.narration_text || '').length, 0)
        const hasAudio = data.audio_verified || segs.some(s => s.audio_duration > 0)
        setInfo({ count: segs.length, narrCount, totalChars, hasAudio })
      })
      .catch(() => setInfo({ count: 0, narrCount: 0, totalChars: 0, hasAudio: false }))
  }, [task.name])

  return (
    <div className="px-4 pb-3 border-t border-border/50">
      <div className="p-3 rounded-lg bg-secondary/20 space-y-2">
        {/* 任务描述 — 始终显示，直接就是 task.description */}
        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">任务描述</p>
          <p className="text-xs text-foreground/80 leading-relaxed">
            {task.description || '暂无描述'}
          </p>
        </div>
        {/* 状态网格 */}
        <div className="grid grid-cols-3 gap-2">
          <div className="rounded bg-card px-2 py-1.5">
            <p className="text-[9px] text-muted-foreground">分段</p>
            <p className="text-sm font-bold text-foreground">{info ? info.count : '...'}</p>
          </div>
          <div className="rounded bg-card px-2 py-1.5">
            <p className="text-[9px] text-muted-foreground">解说词</p>
            <p className="text-sm font-bold text-foreground">{info ? info.narrCount : '...'}</p>
          </div>
          <div className="rounded bg-card px-2 py-1.5">
            <p className="text-[9px] text-muted-foreground">配音</p>
            <p className="text-sm font-bold text-foreground">{info ? (info.hasAudio ? '✅' : '―') : '...'}</p>
          </div>
        </div>
        <div className="flex gap-1.5">
          <button onClick={() => nav(`/${toSlug(dramaName)}/${task.name}/planning`)}
            className="flex-1 py-1 rounded text-[10px] bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 transition-colors font-medium">
            ✍️ 编剧台
          </button>
          <button onClick={() => nav(`/${toSlug(dramaName)}/${task.name}/voice`)}
            className="flex-1 py-1 rounded text-[10px] bg-green-500/10 text-green-400 hover:bg-green-500/20 transition-colors font-medium">
            🎙️ 配音台
          </button>
          <button onClick={() => nav(`/${toSlug(dramaName)}/${task.name}/vibe`)}
            className="flex-1 py-1 rounded text-[10px] bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 transition-colors font-medium">
            🎬 分镜台
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Home() {
  const nav = useNavigate()
  const [dramas, setDramas] = useState([])
  const [syncing, setSyncing] = useState(false)
  const [showNewTask, setShowNewTask] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [expandedTask, setExpandedTask] = useState(null)

  const syncFromBackend = async () => {
    setSyncing(true)
    try {
      const resp = await fetch('/dramas')
      const list = await resp.json()
      const enriched = await Promise.all(list.map(async (d) => {
        const tasksResp = await fetch(`/tasks?drama=${encodeURIComponent(d.name)}`)
        const tasks = await tasksResp.json()
        return { ...d, taskList: tasks }
      }))
      setDramas(enriched)
      let lsList = loadSeriesList()
      for (const d of enriched) {
        let existing = lsList.find(s => s.name === d.name)
        if (!existing) {
          existing = createSeries(d.name)
          lsList = loadSeriesList()
        }
        for (const t of (d.taskList || [])) {
          const existingTasks = loadTasks(existing.id)
          if (!existingTasks.find(et => et.name === t.name)) {
            const task = createTask(existing.id, t.name, {
              description: t.description || '',
              narrText: `${t.segments} 段解说`,
            })
            task._realName = t.name
            saveTask(task)
          } else {
            const et = existingTasks.find(et2 => et2.name === t.name)
            if (et && (t.description || '') !== (et.description || '')) {
              et.description = t.description || ''
              saveTask(et)
            }
          }
        }
      }
    } catch (e) {
      console.error('同步失败', e)
    }
    setSyncing(false)
  }

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    const resp = await fetch('/tasks/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ drama: deleteTarget.drama, name: deleteTarget.name })
    })
    const j = await resp.json()
    if (j.ok) {
      syncFromBackend()
      setDeleteTarget(null)
      showToast('ok', `任务「${deleteTarget.name}」已删除`)
    } else {
      setDeleteTarget(null)
      showToast('error', j.error || '删除失败')
    }
  }

  useEffect(() => { syncFromBackend() }, [])

  return (
    <div className="flex-1 flex flex-col overflow-auto bg-background">
      <div className="max-w-4xl mx-auto w-full p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-lg font-bold text-foreground">项目</h1>
            <p className="text-xs text-muted-foreground mt-0.5">
              {dramas.length > 0
                ? `${dramas.length} 部剧 · ${dramas.reduce((s, d) => s + (d.taskList?.length || 0), 0)} 个任务`
                : '同步项目数据'}
            </p>
          </div>
          <button onClick={syncFromBackend} disabled={syncing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-xs text-muted-foreground hover:bg-accent transition-all">
            <RefreshCw size={13} className={syncing ? 'animate-spin' : ''} />
            {syncing ? '同步中...' : '刷新'}
          </button>
        </div>

        {dramas.length === 0 && !syncing ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Tv size={48} className="text-muted-foreground/30 mb-4" />
            <p className="text-muted-foreground text-sm mb-2">还没有项目数据</p>
            <p className="text-muted-foreground/60 text-xs">点击「刷新」从后端同步项目</p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {dramas.map(d => {
              const tasks = d.taskList || []
              return (
                <div key={d.name} className="rounded-xl border border-border bg-card overflow-hidden">
                  <div className="flex items-center gap-4 p-4">
                    <div className="w-16 h-22 rounded-lg overflow-hidden bg-secondary shrink-0">
                      <img src={`/posters/${encodeURIComponent(d.name)}/cover.jpg`} alt={d.name}
                        className="w-full h-full object-cover"
                        onError={(e) => {
                          e.target.style.display = 'none'
                          e.target.parentElement.classList.add('flex', 'items-center', 'justify-center')
                          e.target.parentElement.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="text-muted-foreground/30"><rect x="2" y="2" width="20" height="20" rx="4"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M22 16l-5-5-7 7-3-3-5 5"/></svg>'
                        }}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h2 className="text-base font-bold text-foreground">{d.name}</h2>
                      <p className="text-[11px] text-muted-foreground mt-0.5">{tasks.length} 个任务</p>
                    </div>
                    <button onClick={(e) => { e.stopPropagation(); setShowNewTask(showNewTask === d.name ? null : d.name) }}
                      className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-border text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
                      <Plus size={13} /> 新建任务
                    </button>
                  </div>

                  {showNewTask === d.name && (
                    <NewTaskForm dramaName={d.name} onCreated={() => { setShowNewTask(null); syncFromBackend() }} onClose={() => setShowNewTask(null)} />
                  )}

                  {tasks.length > 0 && (
                    <div className="border-t border-border">
                      {tasks.map(t => {
                        const statusConfig = {
                          editing: { label: '剪辑中', cls: 'bg-blue-500/10 text-blue-400 border-blue-500/20' },
                          reviewing: { label: '审核中', cls: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20' },
                          delivered: { label: '已交付', cls: 'bg-green-500/10 text-green-400 border-green-500/20' },
                        }
                        const st = statusConfig[t.status] || statusConfig.editing
                        const cycleStatus = () => {
                          const order = ['editing', 'reviewing', 'delivered']
                          const next = order[(order.indexOf(t.status || 'editing') + 1) % 3]
                          fetch('/tasks/status', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ drama: d.name, name: t.name, status: next })
                          }).then(r => r.json()).then(j => {
                            if (!j.ok) showToast('error', j.error || '状态更新失败')
                            else syncFromBackend()
                          })
                        }
                        const deleteTask = (e) => {
                          e.stopPropagation()
                          e.preventDefault()
                          setDeleteTarget({ drama: d.name, name: t.name })
                        }
                        const isExpanded = expandedTask === `${d.name}||${t.name}`
                        return (
                          <div key={t.name}>
                            <div
                              onClick={() => nav(`/${toSlug(d.name)}/${t.name}/data`)}
                              className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-accent transition-colors border-b border-border last:border-b-0 cursor-pointer"
                            >
                              <div className="w-7 h-7 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                                <FolderOpen size={13} className="text-primary" />
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <p className="text-sm font-medium text-foreground">{t.name}</p>
                                  <span onClick={(e) => { e.stopPropagation(); cycleStatus() }}
                                    className={`text-[10px] px-1.5 py-0.5 rounded border cursor-pointer hover:opacity-80 ${st.cls}`}
                                  >{st.label}</span>
                                </div>
                                <p className="text-[11px] text-muted-foreground">
                                  {t.segments} 段解说
                                  {t.duration > 0 && ` · ${Math.round(t.duration)}秒`}
                                </p>
                                {t.description && (
                                  <p className="text-[10px] text-purple-400/60 mt-0.5 truncate max-w-[300px]"
                                     title={t.description}>📝 {t.description}</p>
                                )}
                              </div>
                              <button
                                onClick={(e) => { e.stopPropagation(); setExpandedTask(isExpanded ? null : `${d.name}||${t.name}`) }}
                                className="flex items-center justify-center w-6 h-6 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors shrink-0"
                                title="展开任务详情"
                              >
                                {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                              </button>
                              <ChevronRight size={14} className="text-muted-foreground/30" />
                              <button onClick={deleteTask}
                                className="flex items-center justify-center w-6 h-6 rounded hover:bg-red-500/10 text-muted-foreground hover:text-red-400 transition-colors shrink-0"
                                title="删除任务">
                                <X size={13} />
                              </button>
                            </div>
                            {isExpanded && <TaskDetail task={t} dramaName={d.name} />}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {deleteTarget && (
        <DeleteConfirmModal taskName={deleteTarget.name}
          onConfirm={handleDeleteConfirm}
          onClose={() => setDeleteTarget(null)} />
      )}
      <ToastContainer />
    </div>
  )
}
