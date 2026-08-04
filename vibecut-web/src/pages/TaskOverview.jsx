import { useNavigate } from 'react-router-dom'
import { useProject } from '../context/ProjectContext'
import { Film, Mic, ChevronRight, Tv, FolderOpen, Plus, RefreshCw, Upload, X, ChevronDown, ChevronUp } from 'lucide-react'
import { useState, useEffect } from 'react'

const NARR_DURATIONS = { 0: 26, 1: 24, 2: 12, 3: 5, 4: 15, 5: 56, 6: 18, 7: 18, 8: 45 }

const SLUG_MAP = { '都挺好': 'doutinghao' }
function toSlug(name) { return SLUG_MAP[name] || name }

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
      const data = await resp.json()
      setResult(data)
      if (data?.ok) onCreated()
    } catch (e) { setResult({ ok: false, error: e.message }) }
    setCreating(false)
  }

  return (
    <div className="p-3 border border-border rounded-lg bg-secondary/20 space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium">新建任务</h4>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X size={14} /></button>
      </div>
      <input autoFocus value={name} onChange={e => setName(e.target.value)}
        placeholder="任务名称，如 Task7030"
        className="w-full bg-card border border-border rounded-md px-2.5 py-1.5 text-xs outline-none focus:border-primary/50" />
      <div className="flex gap-1 text-[10px]">
        <button onClick={() => setUseLocalPath(false)}
          className={`px-2 py-1 rounded ${!useLocalPath ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground'}`}>上传文件</button>
        <button onClick={() => setUseLocalPath(true)}
          className={`px-2 py-1 rounded ${useLocalPath ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground'}`}>本地路径</button>
      </div>
      {useLocalPath ? (
        <input value={localPath} onChange={e => setLocalPath(e.target.value)}
          placeholder="素材目录路径"
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
      {result && (
        <p className={`text-[10px] ${result.ok ? 'text-green-400' : 'text-red-400'}`}>
          {result.ok ? '✅ 创建成功' : `❌ ${result.error || '失败'}`}
        </p>
      )}
      <button onClick={handleCreate} disabled={!name.trim() || creating}
        className="w-full py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium disabled:opacity-40">
        {creating ? '创建中...' : '创建任务'}
      </button>
    </div>
  )
}

export default function TaskOverview() {
  const { project, seriesId, taskId } = useProject()
  const nav = useNavigate()
  const [segments, setSegments] = useState([])

  // 嵌入式项目导航数据
  const [dramas, setDramas] = useState([])
  const [syncing, setSyncing] = useState(false)
  const [navExpanded, setNavExpanded] = useState(true)
  const [showNewTask, setShowNewTask] = useState(null)

  // 从后端加载所有剧集和任务
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
    } catch (e) {
      console.error('同步失败', e)
    }
    setSyncing(false)
  }

  useEffect(() => { syncFromBackend() }, [])

  // 加载当前任务的分段数据
  useEffect(() => {
    fetch(`/segments.json?task=${taskId}`)
      .then(r => r.json())
      .then(data => setSegments(data.segments || data))
      .catch(() => setSegments([]))
  }, [taskId])

  const picks = project?.picks || {}

  // 按 seg_id 分组统计 picks
  const pickStats = {}
  for (const [key, p] of Object.entries(picks)) {
    const [sidStr] = key.split('_')
    const sid = parseInt(sidStr)
    if (!pickStats[sid]) pickStats[sid] = { main: 0, supp: 0 }
    pickStats[sid].main += (p.main || []).filter(m => m.file).length
    pickStats[sid].supp += (p.supp || []).filter(s => s.file).length
  }

  const totalMain = Object.values(pickStats).reduce((s, v) => s + v.main, 0)
  const totalSupp = Object.values(pickStats).reduce((s, v) => s + v.supp, 0)
  const totalTTS = Object.values(NARR_DURATIONS).reduce((s, v) => s + v, 0)

  // 获取当前剧集名称
  const currentDrama = dramas.find(d => toSlug(d.name) === seriesId)
  const currentDramaName = currentDrama?.name || (seriesId === 'doutinghao' ? '都挺好' : decodeURIComponent(seriesId))
  const currentTasks = currentDrama?.taskList || []

  return (
    <div className="flex-1 flex flex-col overflow-auto bg-background">
      <div className="max-w-3xl mx-auto w-full p-6 space-y-5">

        {/* ── 嵌入式项目导航（可折叠）── */}
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <button
            onClick={() => setNavExpanded(!navExpanded)}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-accent/50 transition-colors"
          >
            <div className="flex items-center gap-2">
              <Tv size={14} className="text-primary" />
              <span className="text-sm font-medium text-foreground">项目导航</span>
              <span className="text-[10px] text-muted-foreground">
                · {currentDramaName} · {currentTasks.length} 个任务
              </span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={(e) => { e.stopPropagation(); syncFromBackend() }}
                disabled={syncing}
                className="p-1 rounded hover:bg-accent text-muted-foreground"
                title="刷新"
              >
                <RefreshCw size={12} className={syncing ? 'animate-spin' : ''} />
              </button>
              {navExpanded ? <ChevronUp size={14} className="text-muted-foreground" /> : <ChevronDown size={14} className="text-muted-foreground" />}
            </div>
          </button>

          {navExpanded && (
            <div className="border-t border-border">
              {/* 剧集列表 — 紧凑行 */}
              {dramas.length === 0 ? (
                <div className="px-4 py-6 text-center">
                  <p className="text-xs text-muted-foreground">{syncing ? '加载中...' : '暂无项目，点击刷新同步'}</p>
                </div>
              ) : (
                <div className="divide-y divide-border/50">
                  {dramas.map(d => {
                    const tasks = d.taskList || []
                    const isCurrentDrama = toSlug(d.name) === seriesId
                    return (
                      <div key={d.name} className={`${isCurrentDrama ? 'bg-primary/3' : ''}`}>
                        {/* 剧名行 */}
                        <div className="flex items-center gap-2 px-4 py-2">
                          <span className="text-xs font-medium text-foreground/80">{d.name}</span>
                          <span className="text-[10px] text-muted-foreground">({tasks.length})</span>
                          <div className="flex-1" />
                          <button
                            onClick={() => setShowNewTask(showNewTask === d.name ? null : d.name)}
                            className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                          >
                            <Plus size={10} /> 新建
                          </button>
                        </div>

                        {/* 新建任务表单 */}
                        {showNewTask === d.name && (
                          <div className="px-4 pb-2">
                            <NewTaskForm
                              dramaName={d.name}
                              onCreated={() => { setShowNewTask(null); syncFromBackend() }}
                              onClose={() => setShowNewTask(null)}
                            />
                          </div>
                        )}

                        {/* 任务列表 — 紧凑横向 chips */}
                        {tasks.length > 0 && (
                          <div className="flex flex-wrap gap-1 px-4 pb-2">
                            {tasks.map(t => {
                              const isCurrentTask = isCurrentDrama && t.name === taskId
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
                                  className={`flex items-center gap-1 px-2 py-1 rounded-md text-[11px] transition-colors border ${
                                    isCurrentTask
                                      ? 'bg-primary/10 border-primary/30 text-primary font-medium'
                                      : 'border-transparent hover:bg-accent text-foreground/70 hover:text-foreground'
                                  }`}
                                >
                                  <FolderOpen size={10} className={isCurrentTask ? 'text-primary' : 'text-muted-foreground'} />
                                  {t.name}
                                  <span className={`text-[9px] px-1 py-0.5 rounded border ${st.cls}`}>{st.label}</span>
                                </button>
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
          )}
        </div>

        {/* ── 当前任务概览卡片 ── */}
        <div>
          <h3 className="text-sm font-medium text-foreground mb-3">
            当前任务 · {taskId}
            <span className="text-xs text-muted-foreground ml-2">概览</span>
          </h3>
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2 mb-1">
                <Film size={14} className="text-blue-400" />
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">主镜头</span>
              </div>
              <span className="text-2xl font-bold text-foreground">{totalMain}</span>
              <span className="text-xs text-muted-foreground ml-1">个</span>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2 mb-1">
                <Film size={14} className="text-purple-400" />
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">补充镜头</span>
              </div>
              <span className="text-2xl font-bold text-foreground">{totalSupp}</span>
              <span className="text-xs text-muted-foreground ml-1">个</span>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2 mb-1">
                <Mic size={14} className="text-green-400" />
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">解说音频</span>
              </div>
              <span className="text-2xl font-bold text-foreground">{totalTTS}</span>
              <span className="text-xs text-muted-foreground ml-1">秒</span>
            </div>
          </div>
        </div>

        {/* ── 分段列表 ── */}
        <div>
          <h3 className="text-sm font-medium text-foreground mb-3">解说分段</h3>
          {segments.length === 0 ? (
            <p className="text-xs text-muted-foreground py-8 text-center">加载中...</p>
          ) : (
            <div className="space-y-1">
              {segments.map((seg, i) => {
                const stats = pickStats[seg.seg_id] || { main: 0, supp: 0 }
                const narrDur = NARR_DURATIONS[seg.seg_id] || 0
                const sentences = seg.sentences || seg.narration || []
                const done = stats.main > 0 || stats.supp > 0

                return (
                  <button
                    key={seg.seg_id}
                    onClick={() => nav(`/${seriesId}/${taskId}/planning?sid=${seg.seg_id}`)}
                    className="w-full flex items-center gap-3 px-4 py-3 rounded-lg border border-border bg-card hover:bg-accent/50 transition-colors text-left"
                  >
                    {/* 序号 */}
                    <span className="text-xs font-mono text-muted-foreground w-8 shrink-0">
                      S{seg.seg_id}
                    </span>

                    {/* 预览文本 */}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-foreground/80 truncate">
                        {Array.isArray(sentences)
                          ? sentences.map(s => typeof s === 'string' ? s : s.text).join(' ').substring(0, 60) + (sentences.length > 0 ? '...' : '')
                          : String(sentences).substring(0, 60)}
                      </p>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-[10px] text-muted-foreground">
                          {Array.isArray(sentences) ? sentences.length : 0} 句
                        </span>
                        <span className="text-[10px] text-muted-foreground">
                          解说 {narrDur}s
                        </span>
                      </div>
                    </div>

                    {/* 选取状态 */}
                    <div className="flex items-center gap-2 shrink-0">
                      {stats.main > 0 && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">
                          {stats.main}主
                        </span>
                      )}
                      {stats.supp > 0 && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400">
                          {stats.supp}补
                        </span>
                      )}
                      {!done && (
                        <span className="text-[10px] text-muted-foreground/50">待选</span>
                      )}
                      <ChevronRight size={14} className="text-muted-foreground/30" />
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
