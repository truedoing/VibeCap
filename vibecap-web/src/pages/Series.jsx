import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { loadSeriesList, loadTasks, createTask, deleteTask, saveTask } from '../model/series'
import { ArrowLeft, Plus, Trash2, Clapperboard, Clock, FileText, Music, Upload, X } from 'lucide-react'

// ── 新建任务弹窗 ──
function NewTaskModal({ seriesId, onCreated, onClose }) {
  const [name, setName] = useState('')
  const [docxFile, setDocxFile] = useState(null)
  const [audioFile, setAudioFile] = useState(null)
  const [localPath, setLocalPath] = useState('')
  const [useLocalPath, setUseLocalPath] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createResult, setCreateResult] = useState(null)
  const docxInputRef = useRef(null)
  const audioInputRef = useRef(null)

  const handleCreate = async () => {
    if (!name.trim()) return
    setCreating(true)
    setCreateResult(null)

    try {
      const formData = new FormData()
      formData.append('drama', decodeURIComponent(seriesId))
      formData.append('name', name.trim())

      if (useLocalPath && localPath.trim()) {
        formData.append('local_path', localPath.trim())
      } else {
        if (docxFile) formData.append('docx', docxFile)
        if (audioFile) formData.append('audio', audioFile)
      }

      const resp = await fetch('/tasks/create', { method: 'POST', body: formData })
      const result = await resp.json()
      setCreateResult(result)

      if (result.ok) {
        onCreated({ name: name.trim(), segments: result.steps?.[0]?.output })
      }
    } catch (e) {
      setCreateResult({ ok: false, error: e.message })
    }
    setCreating(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="w-full max-w-lg mx-4 bg-card border border-border rounded-2xl shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-lg font-semibold text-foreground">新建剪辑任务</h2>
          <button onClick={onClose} className="p-1 rounded-md hover:bg-secondary text-muted-foreground">
            <X size={18} />
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-2 px-6 py-3 border-b border-border bg-secondary/30">
          {[1, 2].map(s => (
            <button key={s} onClick={() => setStep(s)}
              className={`flex-1 text-xs font-medium py-1.5 rounded-md transition-colors ${
                step === s ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
              }`}>
              {s === 1 ? '① 基本信息' : '② 上传解说素材'}
            </button>
          ))}
        </div>

        {/* Step 1: 基本信息 */}
        {step === 1 && (
          <div className="px-6 py-5 space-y-4">
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1.5">任务名称</label>
              <input
                autoFocus
                value={name}
                onChange={e => setName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') setStep(2) }}
                placeholder="如：第一集解说、大结局精剪"
                className="w-full bg-secondary border border-border rounded-lg px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-primary/50 transition-colors"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={onClose}
                className="px-4 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:bg-secondary transition-colors">
                取消
              </button>
              <button onClick={() => setStep(2)}
                disabled={!name.trim()}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-40 transition-opacity">
                下一步
              </button>
            </div>
          </div>
        )}

        {/* Step 2: 上传素材 */}
        {step === 2 && (
          <div className="px-6 py-5 space-y-4">
            {/* 模式切换 */}
            <div className="flex rounded-lg bg-secondary p-1">
              <button
                onClick={() => setUseLocalPath(false)}
                className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  !useLocalPath ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground'
                }`}
              >上传文件</button>
              <button
                onClick={() => setUseLocalPath(true)}
                className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  useLocalPath ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground'
                }`}
              >本地路径</button>
            </div>

            {useLocalPath ? (
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1.5">
                  素材目录路径（含解说文案.docx + 解说音频.wav）
                </label>
                <input
                  value={localPath}
                  onChange={e => setLocalPath(e.target.value)}
                  placeholder="/Users/zgl/剪辑/Task/Task7030/"
                  className="w-full bg-secondary border border-border rounded-lg px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-primary/50"
                />
              </div>
            ) : (
              <>
                {/* 解说文案 docx */}
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1.5">
                    解说文案 (.docx)
                  </label>
                  {docxFile ? (
                    <div className="flex items-center gap-3 p-3 rounded-lg border border-border bg-secondary/50">
                      <FileText size={18} className="text-blue-400 shrink-0" />
                      <span className="text-sm text-foreground truncate flex-1">{docxFile.name}</span>
                      <button onClick={() => setDocxFile(null)}
                        className="p-1 rounded hover:bg-secondary text-muted-foreground">
                        <X size={14} />
                      </button>
                    </div>
                  ) : (
                    <div onClick={() => docxInputRef.current?.click()}
                      className="flex flex-col items-center gap-2 p-4 rounded-lg border-2 border-dashed border-border hover:border-primary/40 cursor-pointer transition-colors"
                    >
                      <Upload size={20} className="text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">点击上传 .docx 解说文案</span>
                    </div>
                  )}
                  <input ref={docxInputRef} type="file" accept=".docx"
                    onChange={e => setDocxFile(e.target.files?.[0] || null)} className="hidden" />
                </div>

                {/* 解说音频 */}
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1.5">
                    解说音频 (.wav / .mp3)
                  </label>
                  {audioFile ? (
                    <div className="flex items-center gap-3 p-3 rounded-lg border border-border bg-secondary/50">
                      <Music size={18} className="text-green-400 shrink-0" />
                      <span className="text-sm text-foreground truncate flex-1">{audioFile.name}</span>
                      <button onClick={() => setAudioFile(null)}
                        className="p-1 rounded hover:bg-secondary text-muted-foreground">
                        <X size={14} />
                      </button>
                    </div>
                  ) : (
                    <div onClick={() => audioInputRef.current?.click()}
                      className="flex flex-col items-center gap-2 p-4 rounded-lg border-2 border-dashed border-border hover:border-primary/40 cursor-pointer transition-colors"
                    >
                      <Upload size={20} className="text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">点击上传解说音频</span>
                    </div>
                  )}
                  <input ref={audioInputRef} type="file" accept=".wav,.mp3"
                    onChange={e => setAudioFile(e.target.files?.[0] || null)} className="hidden" />
                </div>
              </>
            )}

            {/* 创建结果 */}
            {createResult && (
              <div className={`p-3 rounded-lg text-xs ${createResult.ok ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                {createResult.ok ? (
                  <div>
                    <p className="font-medium mb-1">✅ 任务创建成功</p>
                    {(createResult.steps || []).map((s, i) => (
                      <p key={i} className="opacity-75">{s.step}: {s.ok ? '✅' : '❌'}</p>
                    ))}
                  </div>
                ) : (
                  <p>❌ {createResult.error || '创建失败'}</p>
                )}
              </div>
            )}
            {/* Actions */}
            <div className="flex justify-between gap-2 pt-4">
              <button onClick={() => setStep(1)}
                className="px-4 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:bg-secondary transition-colors">
                ← 上一步
              </button>
              <div className="flex gap-2">
                <button onClick={onClose}
                  className="px-4 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:bg-secondary transition-colors">
                  取消
                </button>
                <button onClick={handleCreate}
                  disabled={!name.trim() || creating}
                  className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-40 transition-opacity">
                  {creating ? '创建中...' : '创建任务'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── 状态常量 ──
const STATUS_MAP = {
  editing:  { label: '剪辑中', cls: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
  reviewing:{ label: '审核中', cls: 'bg-blue-500/10 text-blue-400 border-blue-500/20' },
  delivered:{ label: '已交付', cls: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
}
const NEXT_STATUS = { editing: 'reviewing', reviewing: 'delivered', delivered: 'editing' }

// ── 任务卡片 ──
function TaskCard({ task, seriesId, onDelete, onStatusChange }) {
  const fmt = (ts) => {
    const d = new Date(ts)
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
  }
  const st = STATUS_MAP[task.status] || STATUS_MAP.editing

  const cycleStatus = (e) => {
    e.preventDefault()
    e.stopPropagation()
    const next = NEXT_STATUS[task.status] || 'editing'
    const updated = { ...task, status: next }
    saveTask(updated)
    onStatusChange()
  }

  return (
    <Link
      to={`/${seriesId}/${task.id}/planning`}
      className="group flex items-center gap-4 p-4 rounded-xl border border-border bg-card hover:border-primary/30 hover:shadow-sm transition-all"
    >
      <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
        <Clapperboard size={20} className="text-primary" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-foreground text-sm truncate">{task.name}</h3>
          {task.narrText && <FileText size={12} className="text-green-400 shrink-0" title="已上传解说文案" />}
          {task.audioFileName && <Music size={12} className="text-blue-400 shrink-0" title="已上传解说音频" />}
        </div>
        <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><Clock size={11} />{fmt(task.createdAt)}</span>
          <span>{Object.keys(task.picks || {}).length} 个已选镜头</span>
        </div>
      </div>
      {/* 状态标签 — 点击切换 */}
      <button onClick={cycleStatus}
        className={`text-[10px] font-medium px-2 py-0.5 rounded border ${st.cls} shrink-0 hover:opacity-80 transition-opacity cursor-pointer`}
        title="点击切换状态">
        {st.label}
      </button>
      <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <span className="text-xs text-primary font-medium">进入策划台 →</span>
      </div>
      <button
        onClick={(e) => onDelete(e, task)}
        className="p-1.5 rounded-md opacity-0 group-hover:opacity-100 hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-all shrink-0"
        title="删除"
      >
        <Trash2 size={14} />
      </button>
    </Link>
  )
}

// ── 主页 ──
export default function SeriesPage() {
  const { seriesId } = useParams()
  const nav = useNavigate()
  const [series, setSeries] = useState(null)
  const [tasks, setTasks] = useState([])
  const [showModal, setShowModal] = useState(false)

  const refresh = () => {
    const list = loadSeriesList()
    const s = list.find(x => x.id === seriesId)
    setSeries(s)
    setTasks(loadTasks(seriesId))
  }

  useEffect(refresh, [seriesId])

  if (!series) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-muted-foreground text-sm">电视剧不存在</p>
      </div>
    )
  }

  const handleDelete = (e, task) => {
    e.stopPropagation()
    e.preventDefault()
    if (confirm(`删除任务「${task.name}」？此操作不可恢复。`)) {
      deleteTask(seriesId, task.id)
      refresh()
    }
  }

  return (
    <div className="flex-1 flex flex-col overflow-auto bg-background">
      <div className="max-w-4xl mx-auto w-full p-6">
        {/* Back + header */}
        <button onClick={() => nav('/')}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-4 transition-colors">
          <ArrowLeft size={16} /> 返回项目列表
        </button>

        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-foreground">{series.name}</h1>
            <p className="text-sm text-muted-foreground mt-1">共 {tasks.length} 个剪辑任务</p>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
          >
            <Plus size={16} /> 新建任务
          </button>
        </div>

        {/* Task list */}
        {tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Clapperboard size={48} className="text-muted-foreground/30 mb-4" />
            <p className="text-muted-foreground text-sm mb-2">暂无剪辑任务</p>
            <p className="text-muted-foreground/60 text-xs">点击「新建任务」上传解说文案和音频</p>
          </div>
        ) : (
          <div className="space-y-3">
            {tasks.map(t => (
              <TaskCard key={t.id} task={t} seriesId={seriesId} onDelete={handleDelete} onStatusChange={refresh} />
            ))}
          </div>
        )}
      </div>

      {/* 新建任务弹窗 */}
      {showModal && (
        <NewTaskModal
          seriesId={seriesId}
          onCreated={() => refresh()}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  )
}
