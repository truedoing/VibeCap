import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { loadSeriesList, createSeries, deleteSeries, createTask, loadTasks, saveTask } from '../model/series'
import { Plus, Trash2, Tv, FolderOpen, RefreshCw, Upload, FileText, Music, X } from 'lucide-react'

// ── 新建任务内联表单 ──
function NewTaskForm({ dramaName, onCreated, onClose }) {
  const [name, setName] = useState('')
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
      if (useLocalPath && localPath.trim()) {
        fd.append('local_path', localPath.trim())
      } else {
        if (docxFile) fd.append('docx', docxFile)
        if (audioFile) fd.append('audio', audioFile)
      }
      const resp = await fetch('/tasks/create', { method: 'POST', body: fd })
      setResult(await resp.json())
      if (result?.ok) onCreated()
    } catch (e) { setResult({ ok: false, error: e.message }) }
    setCreating(false)
  }

  return (
    <div className="p-4 border-t border-border bg-secondary/20 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium">新建任务</h4>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X size={16} /></button>
      </div>
      <input autoFocus value={name} onChange={e => setName(e.target.value)}
        placeholder="任务名称，如 Task7030"
        className="w-full bg-card border border-border rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/50" />
      <div className="flex gap-1 text-xs">
        <button onClick={() => setUseLocalPath(false)}
          className={`px-2 py-1 rounded ${!useLocalPath ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground'}`}>上传文件</button>
        <button onClick={() => setUseLocalPath(true)}
          className={`px-2 py-1 rounded ${useLocalPath ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground'}`}>本地路径</button>
      </div>
      {useLocalPath ? (
        <input value={localPath} onChange={e => setLocalPath(e.target.value)}
          placeholder="素材目录路径"
          className="w-full bg-card border border-border rounded-lg px-3 py-2 text-xs outline-none focus:border-primary/50" />
      ) : (
        <div className="flex gap-2">
          <label className="flex-1 flex items-center gap-1 px-2 py-1.5 rounded border border-border text-xs cursor-pointer hover:bg-accent">
            <Upload size={12} /> {docxFile ? docxFile.name : '文案.docx'}
            <input type="file" accept=".docx" className="hidden" onChange={e => setDocxFile(e.target.files?.[0] || null)} />
          </label>
          <label className="flex-1 flex items-center gap-1 px-2 py-1.5 rounded border border-border text-xs cursor-pointer hover:bg-accent">
            <Upload size={12} /> {audioFile ? audioFile.name : '音频.wav'}
            <input type="file" accept=".wav,.mp3" className="hidden" onChange={e => setAudioFile(e.target.files?.[0] || null)} />
          </label>
        </div>
      )}
      {result && (
        <p className={`text-xs ${result.ok ? 'text-green-400' : 'text-red-400'}`}>
          {result.ok ? '✅ 创建成功' : `❌ ${result.error || '失败'}`}
        </p>
      )}
      <button onClick={handleCreate} disabled={!name.trim() || creating}
        className="w-full py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-40">
        {creating ? '创建中...' : '创建任务'}
      </button>
    </div>
  )
}

// 简单拼音映射（后续可用 pinyin 库自动转换）
const SLUG_MAP = { '都挺好': 'doutinghao' }
function toSlug(name) { return SLUG_MAP[name] || name }
function fromSlug(slug) { return Object.entries(SLUG_MAP).find(([,v]) => v === slug)?.[0] || slug }

export default function Home() {
  const nav = useNavigate()
  const [dramas, setDramas] = useState([])
  const [syncing, setSyncing] = useState(false)
  const [showNewTask, setShowNewTask] = useState(null)  // drama name

  // 直接从后端拉取真实数据
  const syncFromBackend = async () => {
    setSyncing(true)
    try {
      const resp = await fetch('/dramas')
      const list = await resp.json()

      // 为每部剧获取任务列表
      const enriched = await Promise.all(list.map(async (d) => {
        const tasksResp = await fetch(`/tasks?drama=${encodeURIComponent(d.name)}`)
        const tasks = await tasksResp.json()
        return { ...d, taskList: tasks }
      }))
      setDramas(enriched)

      // 同时同步到 localStorage（保持兼容性）
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
              narrText: `${t.segments} 段解说`,
            })
            // 存实际任务名，Series 页用
            task._realName = t.name
            saveTask(task)
          }
        }
      }
    } catch (e) {
      console.error('同步失败', e)
    }
    setSyncing(false)
  }

  useEffect(() => { syncFromBackend() }, [])

  return (
    <div className="flex-1 flex flex-col overflow-auto bg-background">
      <div className="max-w-4xl mx-auto w-full p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-foreground">剪辑项目</h1>
            <p className="text-sm text-muted-foreground mt-1">选择一部电视剧，开始剪辑任务</p>
          </div>
          <button
            onClick={syncFromBackend}
            disabled={syncing}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:bg-accent transition-all"
          >
            <RefreshCw size={16} className={syncing ? 'animate-spin' : ''} />
            {syncing ? '同步中...' : '刷新'}
          </button>
        </div>

        {/* Dramas grid */}
        {dramas.length === 0 && !syncing ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Tv size={48} className="text-muted-foreground/30 mb-4" />
            <p className="text-muted-foreground text-sm mb-2">还没有剪辑项目</p>
            <p className="text-muted-foreground/60 text-xs">点击「刷新」从后端同步项目</p>
          </div>
        ) : (
          <div className="flex flex-col gap-6">
            {dramas.map(d => (
              <div key={d.name} className="rounded-xl border border-border bg-card overflow-hidden">
                {/* 电视剧头部 — 封面 + 标题 */}
                <div className="flex items-center gap-4 p-5">
                  {/* 封面图 */}
                  <div className="w-20 h-28 rounded-lg overflow-hidden bg-secondary shrink-0">
                    <img
                      src={`/posters/${encodeURIComponent(d.name)}/cover.jpg`}
                      alt={d.name}
                      className="w-full h-full object-cover"
                      onError={(e) => {
                        e.target.style.display = 'none'
                        e.target.parentElement.classList.add('flex', 'items-center', 'justify-center')
                        e.target.parentElement.innerHTML = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="text-muted-foreground/30"><rect x="2" y="2" width="20" height="20" rx="4"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M22 16l-5-5-7 7-3-3-5 5"/></svg>'
                      }}
                    />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h2 className="text-lg font-bold text-foreground">{d.name}</h2>
                    <p className="text-xs text-muted-foreground mt-1">
                      {d.taskList?.length || d.tasks || 0} 个剪辑任务
                    </p>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); setShowNewTask(showNewTask === d.name ? null : d.name) }}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                  >
                    <Plus size={14} /> 新建任务
                  </button>
                </div>

                {/* 新建任务表单 */}
                {showNewTask === d.name && (
                  <NewTaskForm dramaName={d.name} onCreated={() => { setShowNewTask(null); syncFromBackend() }} onClose={() => setShowNewTask(null)} />
                )}

                {/* 任务列表 */}
                {(d.taskList || []).length > 0 && (
                  <div className="border-t border-border">
                    {d.taskList.map((t, i) => {
                      const statusConfig = {
                        editing: { label: '剪辑中', cls: 'bg-blue-500/10 text-blue-400 border-blue-500/20' },
                        reviewing: { label: '审核中', cls: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20' },
                        delivered: { label: '已交付', cls: 'bg-green-500/10 text-green-400 border-green-500/20' },
                      }
                      const st = statusConfig[t.status] || statusConfig.editing
                      return (
                        <button
                          key={t.name}
                          onClick={() => nav(`/${toSlug(d.name)}/${t.name}/planning`)}
                          className="w-full flex items-center gap-3 px-5 py-3 text-left hover:bg-accent transition-colors border-b border-border last:border-b-0"
                        >
                          <div className="w-8 h-8 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                            <FolderOpen size={14} className="text-primary" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-medium text-foreground">{t.name}</p>
                              <span className={`text-[10px] px-1.5 py-0.5 rounded border ${st.cls}`}>{st.label}</span>
                            </div>
                            <p className="text-xs text-muted-foreground">
                              {t.segments} 段解说
                              {t.duration > 0 && ` · ${Math.round(t.duration)}秒`}
                            </p>
                          </div>
                          <span className="text-xs text-muted-foreground/50">→</span>
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
