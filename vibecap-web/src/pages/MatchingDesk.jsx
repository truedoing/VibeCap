import { useState, useEffect, useRef, useCallback, Fragment } from 'react'
import { useProject } from '../context/ProjectContext'

// 预览视频 session 标识
const pvSid = sessionStorage.getItem('pvSid') || (() => { const s = Math.random().toString(36).slice(2, 10); sessionStorage.setItem('pvSid', s); return s })()
import { Search, ChevronDown, ChevronRight, Play, Download, X, Film, User, PanelLeftClose, PanelLeft } from 'lucide-react'
import { Button } from '../components/ui/button'
import { cn } from '../lib/utils'

// ── 常量 ──
const CHARS = ["蒙总", "蒙太", "明玉", "老蒙", "沈浩"]

// ── 辅助：人物高亮 HTML ──
function highlightHtml(text) {
  if (!text) return ''
  let s = text
  CHARS.forEach(c => { s = s.replaceAll(c, `<span class="char-hl">${c}</span>`) })
  return s
}

function Highlighted({ text, className }) {
  return <span className={className} dangerouslySetInnerHTML={{ __html: highlightHtml(text) }} />
}

// ── 组件 ──
export default function MatchingDesk() {
  // ── State ──
  const [segments, setSegments] = useState([])
  const [openSeg, setOpenSeg] = useState(null)
  const [leftCollapsed, setLeftCollapsed] = useState(false)

  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searchStatus, setSearchStatus] = useState('')
  const [searching, setSearching] = useState(false)
  const [epFilter, setEpFilter] = useState(null)  // null=全部, 27/28/29=按集筛选

  const [curSid, setCurSid] = useState(null)
  const [curSeq, setCurSeq] = useState(null)
  const [curMark, setCurMark] = useState(null)
  const [selectedIdx, setSelectedIdx] = useState(null)

  const [adjStart, setAdjStart] = useState(0)
  const [adjEnd, setAdjEnd] = useState(0)
  const [playerSrc, setPlayerSrc] = useState('')
  const [playerStatus, setPlayerStatus] = useState('选择一个搜索结果以预览视频')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [playbackRate, setPlaybackRate] = useState(1.25)

  // 分镜描述持久化
  const [storyboard, setStoryboard] = useState(() => {
    try { return JSON.parse(localStorage.getItem('vibecap-storyboard') || '{}') } catch { return {} }
  })
  const saveStoryboard = useCallback((sid, seq, text) => {
    setStoryboard(prev => {
      const next = { ...prev }
      const key = `${sid}_${seq}`
      if (text.trim()) next[key] = text.trim()
      else delete next[key]
      try { localStorage.setItem('vibecap-storyboard', JSON.stringify(next)) } catch {}
      return next
    })
  }, [])
  const [narrationRef, setNarrationRef] = useState('')
  const [shots, setShots] = useState([])
  const [activeShot, setActiveShot] = useState(null)
  const [shotsLoading, setShotsLoading] = useState(false)

  const { project, addPick: ctxAddPick, removePick: ctxRemovePick } = useProject()
  const picks = project.picks
  const [actionStatus, setActionStatus] = useState('')

  const playerRef = useRef(null)

  // ── Effects ──
  useEffect(() => {
    fetch(`/segments.json?t=${Date.now()}`)
      .then(r => r.json())
      .then(data => {
        const segs = data.segments || []
        setSegments(segs)
        if (segs.length > 0) setOpenSeg(segs[0].seg_id)
      })
      .catch(() => setSearchStatus('⚠ 加载文案失败'))
  }, [])

  useEffect(() => {
    if (playerRef.current) playerRef.current.playbackRate = playbackRate
  }, [playbackRate, playerSrc])

  // ── Handlers ──
  const doSearch = useCallback(async (q, mode) => {
    if (!q || !q.trim()) return
    setSearching(true)
    setSearchStatus('搜索中...')
    setResults([])
    setSelectedIdx(null)
    setCurMark(null)
    try {
      const r = await fetch(`/search?q=${encodeURIComponent(q)}&mode=${mode}`)
      const data = await r.json()
      data.sort((a, b) => b.score - a.score)
      setResults(data)
      setSearchStatus(`${data.length} 个结果`)
      setEpFilter(null)  // 新搜索重置筛选
    } catch (e) {
      setSearchStatus('⚠ 搜索失败')
    } finally {
      setSearching(false)
    }
  }, [])

  const pickSentence = useCallback((sid, seq) => {
    setCurSid(sid)
    setCurSeq(seq)
    setCurMark(null)
    setSelectedIdx(null)
    // 停止当前视频
    if (playerRef.current) {
      playerRef.current.pause()
      playerRef.current.currentTime = 0
    }
    setPlayerSrc('')
    setPlayerStatus('选择结果以预览')
    setResults([])
    setSearchStatus('')
    setActionStatus('')

    const seg = segments.find(s => s.seg_id === sid)
    if (!seg) return

    // 填充文案参考
    let refText = ''
    if (seq === 'D') {
      refText = (seg.highlight_text || '').substring(0, 200)
    } else {
      const sentences = (seg.narration_text || '').split(/[。！？]/).filter(s => s.trim())
      if (sentences[seq]) refText = sentences[seq].trim()
    }
    setNarrationRef(refText)
    // 异步获取 AI 分镜方案
    setShots([])
    setActiveShot(null)
    setShotsLoading(true)
    setQuery('')  // 切换句子时清空，等 AI 返回后填入
    fetch('/storyboard_suggest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ narration: refText })
    }).then(r => r.json()).then(d => {
      const list = d.suggestions || []
      setShots(list)
      if (list.length > 0) {
        setQuery(list[0])
        setActiveShot(0)
      }
    }).catch(() => {}).finally(() => setShotsLoading(false))
  }, [segments, storyboard])

  const search = useCallback(() => {
    doSearch(query, 'semantic')
  }, [query, doSearch])

  const markResult = useCallback((idx, ep, start, end) => {
    setCurMark({ ep, start, end, pvFile: null })
    setSelectedIdx(idx)
    // 清空旧视频，请求新预览
    setPlayerSrc('')
    setPreviewLoading(true)
    setPlayerStatus('加载预览中...')
    fetch(`/preview_video?ep=${ep}&t=${start}&sid=${pvSid}`)
      .then(r => r.json()).then(d => {
        if (d.url) {
          setPlayerSrc(d.url + '?t=' + Date.now())
          setCurMark(prev => prev ? { ...prev, pvFile: d.file } : null)
          // 用后端返回的实际 clip 起止时间，而非猜测值
          if (d.start != null) setAdjStart(d.start)
          if (d.end != null) setAdjEnd(d.end)
          setPlayerStatus(d.file || '预览就绪')
        } else {
          setPlayerStatus('⚠ 无预览URL')
        }
      }).catch(() => setPlayerStatus('⚠ 预览请求失败'))
      .finally(() => setPreviewLoading(false))
  }, [])

  const previewAdj = useCallback(() => {
    if (!curMark) return
    setPreviewLoading(true)
    setPlayerStatus(`跳转至 ${adjStart.toFixed(1)}s...`)
    fetch(`/preview_video?ep=${curMark.ep}&t=${adjStart}&sid=${pvSid}`)
      .then(r => r.json()).then(d => {
        if (d.url) {
          setPlayerSrc(d.url + '?t=' + Date.now())
          setCurMark(prev => prev ? { ...prev, pvFile: d.file } : null)
          // 用后端返回的实际 clip 起止时间
          if (d.start != null) setAdjStart(d.start)
          if (d.end != null) setAdjEnd(d.end)
          setPlayerStatus(d.file || '预览就绪')
        }
      }).catch(() => {})
      .finally(() => setPreviewLoading(false))
  }, [curMark, adjStart])

  const downloadHQ = useCallback(() => {
    if (!curMark?.pvFile) return
    setActionStatus(`✅ /clips/${curMark.pvFile}`)
  }, [curMark])

  const addPick = useCallback(async (type) => {
    if (!curMark) return
    // 使用用户调整后的起止时间（adjStart/adjEnd），而非 VLM 场景参考时间
    const start = adjStart
    const end = adjEnd
    const duration = end - start
    const { ep, pvFile } = curMark

    // 先添加到状态（立即响应 UI）
    ctxAddPick(curSid, curSeq, type, { ep, start, end, file: null, duration })

    // 异步复制预览文件为永久 clip
    if (pvFile) {
      try {
        const r = await fetch('/copy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            pv_file: pvFile,
            sid: curSid, seq: String(curSeq), type,
            ep, start, end,
          })
        })
        const d = await r.json()
        if (d.ok && d.file) {
          ctxAddPick(curSid, curSeq, type, { ep, start, end, file: d.file, duration })
          setActionStatus(`✅ /clips/${d.file}`)
        }
      } catch (e) { /* ignore */ }
    }
  }, [curMark, curSid, curSeq, ctxAddPick, adjStart, adjEnd])

  const removePick = useCallback((type, idx) => {
    ctxRemovePick(curSid, curSeq, type, idx)
  }, [curSid, curSeq, ctxRemovePick])

  const currentPicks = picks[`${curSid}_${curSeq}`] || { main: [], supp: [] }

  const getPickSummary = useCallback((sid, seq) => {
    const p = picks[`${sid}_${seq}`]
    if (!p) return null
    const parts = []
    if (p.main?.length) parts.push(`${p.main.length}主`)
    if (p.supp?.length) parts.push(`${p.supp.length}补`)
    return parts.length > 0 ? parts.join(' ') : null
  }, [picks])

  // ── Render ──
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 工具栏 */}
      <div className="flex items-center gap-3 px-3 py-1.5 border-b border-border bg-card/50 flex-shrink-0">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setLeftCollapsed(c => !c)}
        >
          {leftCollapsed ? <PanelLeft className="size-4" /> : <PanelLeftClose className="size-4" />}
          <span className="text-xs">{leftCollapsed ? '展开' : '隐藏'}</span>
        </Button>
        <span className="text-xs text-muted-foreground">点击句子 → 选镜头 → 预览调整 → 添加到确认列表</span>
      </div>

      {/* 三栏主体 */}
      <div className="flex-1 flex overflow-hidden">
        {/* ═══ 左栏：文案 ═══ */}
        <div className={cn(
          'custom-scrollbar overflow-y-auto overflow-x-hidden border-r border-border flex-shrink-0 transition-all duration-200',
          leftCollapsed ? 'w-0 border-r-0' : 'w-80'
        )}>
          {!leftCollapsed && (
            <div className="p-2">
              {segments.map(seg => {
                const isOpen = openSeg === seg.seg_id
                const sentences = (seg.narration_text || '').split(/[。！？]/).filter(s => s.trim())
                return (
                  <div key={seg.seg_id} className="mb-1.5">
                    {/* Segment header */}
                    <button
                      onClick={() => setOpenSeg(isOpen ? null : seg.seg_id)}
                      className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-card border border-border hover:bg-accent transition-colors text-left"
                    >
                      <span className="text-[10px] text-muted-foreground/50 mr-1" title="有解说音频">🔊</span>
                      <span className="text-sm font-medium text-warning">seg_{seg.seg_id}</span>
                      {isOpen ? <ChevronDown className="size-3.5 text-muted-foreground" /> : <ChevronRight className="size-3.5 text-muted-foreground" />}
                    </button>

                    {isOpen && (
                      <div className="mt-1 ml-1 pl-2 border-l-2 border-border/50">
                        {/* Highlight text */}
                        {seg.highlight_text && (
                          <button
                            onClick={() => pickSentence(seg.seg_id, 'D')}
                            className="w-full text-left px-2.5 py-1.5 mb-1 rounded-r-lg bg-destructive/10 border-l-[3px] border-warning hover:bg-destructive/15 transition-colors"
                          >
                            <span className="text-[10px] text-warning/70">{storyboard[`${seg.seg_id}_D`] ? "◆" : "◇"} S{seg.seg_id}-D</span>
                            {' '}<span className="text-[11px] text-warning leading-snug">
                              <Highlighted text={seg.highlight_text.substring(0, 80)} />
                              {seg.highlight_text.length > 80 && '...'}
                            </span>
                          </button>
                        )}

                        {/* Narration sentences */}
                        {sentences.map((s, i) => {
                          const summary = getPickSummary(seg.seg_id, i)
                          return (
                            <div key={i} className="flex items-start gap-1.5 py-1.5 px-1 border-b border-border/30 hover:bg-accent/50 rounded transition-colors group">
                              <span className="text-[10px] text-info font-mono min-w-[38px] pt-0.5 select-none">{storyboard[`${seg.seg_id}_${i}`] ? "◆" : "◇"} S{seg.seg_id}-{i}</span>
                              <button
                                onClick={() => pickSentence(seg.seg_id, i)}
                                className="flex-1 text-left text-xs text-foreground/85 leading-relaxed cursor-pointer hover:text-foreground"
                              >
                                <Highlighted text={s.trim() + '。'} />
                              </button>
                              <button
                                onClick={() => pickSentence(seg.seg_id, i)}
                                className="p-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity text-purple hover:bg-purple/10 flex-shrink-0"
                              >
                                <Search className="size-3" />
                              </button>
                              {summary && (
                                <span className="text-[10px] text-success font-medium min-w-[40px] text-right">{summary}</span>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
              {segments.length === 0 && (
                <p className="text-xs text-muted-foreground p-4 text-center">加载文案中...</p>
              )}
            </div>
          )}
        </div>

        {/* ═══ 中栏：搜索 + 结果 ═══ */}
        <div className="flex-1 flex flex-col min-w-0 border-r border-border">
          {/* 分镜方案（结构化列表） */}
          {(shots.length > 0 || shotsLoading) && (
            <div className="p-3 border-b border-border bg-card/20 flex-shrink-0">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground/50">分镜方案</span>
                <button
                  onClick={() => {
                    const newShot = ''
                    setShots(prev => [...prev, newShot])
                    setActiveShot(shots.length)
                    setQuery('')
                  }}
                  className="text-[10px] px-2 py-0.5 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                >+ 添加镜头</button>
              </div>
              {shotsLoading ? (
                <p className="text-[11px] text-muted-foreground/50 px-1">🤖 生成分镜方案中...</p>
              ) : (
                <div className="space-y-1">
                  {shots.map((shot, i) => (
                    <div
                      key={i}
                      className={cn(
                        'flex items-start gap-2 px-2 py-1.5 rounded text-xs group transition-colors cursor-pointer',
                        activeShot === i
                          ? 'bg-info/10 border border-info/20'
                          : 'hover:bg-accent/50 border border-transparent'
                      )}
                    >
                      <button
                        onClick={() => {
                          setQuery(shot)
                          setActiveShot(i)
                          if (curSid != null) saveStoryboard(curSid, curSeq, shot)
                        }}
                        className="flex-1 text-left text-foreground/80 leading-relaxed"
                      >
                        {shot || <span className="text-muted-foreground/40 italic">空镜头，点击编辑</span>}
                      </button>
                      <button
                        onClick={() => {
                          setShots(prev => prev.filter((_, j) => j !== i))
                          if (activeShot === i) setActiveShot(null)
                          if (activeShot > i) setActiveShot(prev => prev - 1)
                        }}
                        className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all flex-shrink-0"
                      >
                        <X className="size-3" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 搜索区：文案参考 + 画面分镜描述 */}
          <div className="p-3 border-b border-border bg-card/30 flex-shrink-0 space-y-2">
            {/* 文案参考（只读） */}
            {narrationRef && (
              <div className="text-xs text-muted-foreground/70 bg-muted/30 px-3 py-2 rounded-lg border border-border/50">
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground/50 mr-2">文案参考</span>
                {narrationRef}
              </div>
            )}
            {/* 画面分镜描述（可编辑） */}
            <div className="flex gap-2">
              <div className="flex-1 relative">
                <textarea
                  value={query}
                  onChange={e => {
                    const val = e.target.value
                    setQuery(val)
                    if (curSid != null) saveStoryboard(curSid, curSeq, val)
                    // 同步更新当前选中镜头
                    if (activeShot !== null) {
                      setShots(prev => prev.map((s, i) => i === activeShot ? val : s))
                    }
                  }}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); search() } }}
                  placeholder={curSid != null ? "用画面语言描述这个分镜要表现什么…" : "点击左侧句子，然后在这里写画面描述…"}
                  className="w-full h-16 px-3 py-2 text-sm bg-background border border-input rounded-lg resize-none focus:outline-none focus:ring-1 focus:ring-ring placeholder:text-muted-foreground/50"
                  rows={3}
                />
                {query && (
                  <button
                    onClick={() => { setQuery(''); if (curSid != null) saveStoryboard(curSid, curSeq, ''); setResults([]); setSearchStatus('') }}
                    className="absolute top-1.5 right-1.5 p-0.5 rounded text-muted-foreground hover:text-foreground"
                  >
                    <X className="size-3" />
                  </button>
                )}
              </div>
              <Button onClick={search} disabled={searching || !query.trim()} className="h-16 px-4">
                <Search className="size-4" />
                <span className="text-xs">{searching ? '检索中' : '检索匹配素材'}</span>
              </Button>
            </div>
            {searchStatus && (
              <p className="text-xs text-muted-foreground">{searchStatus}</p>
            )}
          </div>

          {/* 按集筛选页签 — 动态检测结果中的集数 */}
          {results.length > 0 && (
            <div className="flex gap-1 px-3 pt-2">
              {(() => {
                const eps = [...new Set(results.map(r => r.ep))].sort((a,b) => a-b)
                return [null, ...eps].map(ep => {
                  const count = ep === null ? results.length : results.filter(r => r.ep === ep).length
                  if (count === 0 && ep !== null) return null
                  return (
                    <button
                      key={ep ?? 'all'}
                      onClick={() => setEpFilter(ep)}
                      className={cn(
                        'px-3 py-1 text-xs rounded-full border transition-all',
                        epFilter === ep
                          ? 'bg-info/15 border-info text-info font-medium'
                          : 'border-border text-muted-foreground hover:bg-accent'
                      )}
                    >
                      {ep === null ? `全部 (${count})` : `EP${ep} (${count})`}
                    </button>
                  )
                })
              })()}
            </div>
          )}

          {/* 结果列表 */}
          <div className="flex-1 overflow-y-auto custom-scrollbar p-3">
            {results.length === 0 && !searching && (
              <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
                <Search className="size-8 opacity-30" />
                <p className="text-sm">填写画面描述后点击「检索匹配画面」</p>
                <p className="text-xs opacity-60">用视觉语言描述你想找的画面</p>
              </div>
            )}
            {results
              .filter(s => epFilter === null || s.ep === epFilter)
              .map((s, i) => (
                <button
                  key={`${s.ep}_${s.start.toFixed(0)}`}
                  onClick={() => markResult(i, s.ep, s.start, s.end)}
                  className={cn(
                    'w-full text-left p-3 rounded-lg border mb-1.5 transition-all cursor-pointer',
                    selectedIdx === i
                      ? 'border-info bg-info/5 shadow-sm shadow-info/10'
                      : 'border-border bg-card hover:bg-accent'
                  )}
                >
                  <div className="flex items-center gap-2 text-[10px] text-muted-foreground mb-1">
                    <span>EP{s.ep}</span>
                    <span>{s.start.toFixed(0)}s - {s.end.toFixed(0)}s</span>
                    <span className="text-muted-foreground/50">({s.duration}s)</span>
                    <span className="ml-auto inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple/15 text-purple">
                      {s.score.toFixed(1)}
                    </span>
                  </div>
                  <div className="text-xs text-foreground/85 leading-relaxed">
                    <Highlighted text={s.description} />
                  </div>
                  {s.asr && (
                    <div className="text-[11px] text-success/80 leading-relaxed mt-1">
                      <Highlighted text={s.asr.substring(0, 100)} />
                    </div>
                  )}
                </button>
              ))}
          </div>
        </div>

        {/* ═══ 右栏：预览 + picks ═══ */}
        <div className="w-[420px] min-w-[380px] flex flex-col flex-shrink-0">
          <div className="flex-1 overflow-y-auto custom-scrollbar p-3 flex flex-col">
            {/* 当前句子 */}
            <div className="text-xs text-muted-foreground mb-2 flex items-center gap-1.5">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">当前句子</span>
              <span className="text-warning font-medium">
                {curSid ? `S${curSid}-${curSeq}` : '—'}
              </span>
            </div>

            {/* 视频播放器 */}
            <div className="relative bg-black rounded-lg overflow-hidden mb-2 border border-border">
              <video
                key={playerSrc || 'empty'}
                ref={playerRef}
                src={playerSrc || undefined}
                controls
                className="w-full aspect-video"
                onError={() => setPlayerStatus('⚠ 视频加载失败，请重试')}
              />
              {!playerSrc && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/80 text-muted-foreground">
                  <div className="text-center">
                    <Play className="size-8 mx-auto mb-1 opacity-30" />
                    <p className="text-xs">选择结果以预览</p>
                  </div>
                </div>
              )}
            </div>

            {curMark && (
              <p className="text-[11px] text-muted-foreground/60 mb-1">
                📍 场景参考: EP{curMark.ep} {curMark.start.toFixed(0)}s–{curMark.end.toFixed(0)}s ({(curMark.end - curMark.start).toFixed(0)}s)
              </p>
            )}
            <p className="text-[11px] text-muted-foreground mb-3 truncate">{playerStatus}</p>

            {/* 时间调整 */}
            <div className="flex items-center gap-2 text-xs mb-3 flex-wrap">
              <span className="text-muted-foreground">起始</span>
              <input
                type="number"
                value={adjStart}
                onChange={e => setAdjStart(parseFloat(e.target.value) || 0)}
                step="0.5"
                className="w-16 px-2 py-1 text-xs bg-background border border-input rounded focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <span className="text-muted-foreground">s</span>
              <span className="text-muted-foreground">结束</span>
              <input
                type="number"
                value={adjEnd}
                onChange={e => setAdjEnd(parseFloat(e.target.value) || 0)}
                step="0.5"
                className="w-16 px-2 py-1 text-xs bg-background border border-input rounded focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <span className="text-muted-foreground">s</span>
              <Button variant="outline" size="sm" onClick={previewAdj} disabled={!curMark}>
                <Play className="size-3" />预览
              </Button>
              <Button variant="outline" size="sm" className="text-success border-success/30 hover:bg-success/10" onClick={downloadHQ} disabled={!curMark}>
                <Download className="size-3" />高清
              </Button>
              <span className="text-muted-foreground text-[10px] ml-1">倍速</span>
              <select
                value={playbackRate}
                onChange={e => setPlaybackRate(parseFloat(e.target.value))}
                className="px-1.5 py-1 text-xs bg-background border border-input rounded focus:outline-none"
              >
                <option value="0.5">0.5x</option>
                <option value="0.75">0.75x</option>
                <option value="1">1x</option>
                <option value="1.25">1.25x</option>
                <option value="1.5">1.5x</option>
                <option value="2">2x</option>
              </select>
            </div>

            {/* 添加按钮 */}
            <div className="flex gap-2 mb-3">
              <Button
                variant="outline"
                className="flex-1 border-success/40 text-success hover:bg-success/10 hover:text-success gap-1.5"
                size="sm"
                onClick={() => addPick('main')}
                disabled={!curMark || previewLoading}
              >
                <Film className="size-3.5" />添加为主镜头
              </Button>
              <Button
                variant="outline"
                className="flex-1 border-purple/40 text-purple hover:bg-purple/10 hover:text-purple gap-1.5"
                size="sm"
                onClick={() => addPick('supp')}
                disabled={!curMark || previewLoading}
              >
                <User className="size-3.5" />添加为补充
              </Button>
            </div>

            {/* 已选镜头列表 */}
            <div className="flex-1 overflow-y-auto custom-scrollbar space-y-1.5">
              {currentPicks.main.map((m, i) => (
                <div key={`main-${i}`} className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-success/10 border border-success/20 text-xs">
                  <span className="truncate flex items-center gap-1.5 min-w-0">
                    <Film className="size-3 text-success flex-shrink-0" />
                    <span className="text-success/60 font-medium flex-shrink-0">主{i + 1}</span>
                    <span className="text-foreground/80">EP{m.ep} {m.start.toFixed(0)}s</span>
                    {m.file ? (
                      <a href={`素材clips/${m.file}`} target="_blank" rel="noreferrer" className="text-info hover:underline truncate">{m.file}</a>
                    ) : (
                      <span className="text-muted-foreground/50 text-[10px]">提取中...</span>
                    )}
                  </span>
                  <button onClick={() => removePick('main', i)} className="text-muted-foreground hover:text-destructive flex-shrink-0">
                    <X className="size-3.5" />
                  </button>
                </div>
              ))}
              {currentPicks.supp.map((s, i) => (
                <div key={`supp-${i}`} className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-purple/10 border border-purple/20 text-xs">
                  <span className="truncate flex items-center gap-1.5 min-w-0">
                    <User className="size-3 text-purple flex-shrink-0" />
                    <span className="text-purple/60 font-medium flex-shrink-0">补{i + 1}</span>
                    <span className="text-foreground/80">EP{s.ep} {s.start.toFixed(0)}s</span>
                    {s.file ? (
                      <a href={`素材clips/${s.file}`} target="_blank" rel="noreferrer" className="text-info hover:underline truncate">{s.file}</a>
                    ) : (
                      <span className="text-muted-foreground/50 text-[10px]">提取中...</span>
                    )}
                  </span>
                  <button onClick={() => removePick('supp', i)} className="text-muted-foreground hover:text-destructive flex-shrink-0">
                    <X className="size-3.5" />
                  </button>
                </div>
              ))}
              {currentPicks.main.length === 0 && currentPicks.supp.length === 0 && (
                <div className="text-center py-6 text-xs text-muted-foreground/60">
                  <Film className="size-5 mx-auto mb-1 opacity-30" />
                  选中镜头后点击上方按钮添加
                </div>
              )}
            </div>

            {/* 操作状态 */}
            {actionStatus && (
              <div className="text-[11px] text-muted-foreground mt-2 pt-2 border-t border-border" dangerouslySetInnerHTML={{ __html: actionStatus }} />
            )}

            {/* 存储提示 */}
            <p className="text-[10px] text-muted-foreground/40 mt-2 text-center">
              picks 自动保存到 localStorage
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
