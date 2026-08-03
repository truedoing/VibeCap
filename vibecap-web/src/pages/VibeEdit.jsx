/**
 * Vibe 沉浸式剪辑台
 * 双引擎：程序引擎(大预览+底部时间轴) + 源引擎(AI面板内轻量定位)
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useProject } from '../context/ProjectContext'

import '@elah/editor/styles.css'
import {
  EditorProvider, Preview, Timeline,
  createDefaultDemuxerFactory,
  useTimelineEngine,
  useTracksStore, usePlaybackStore, useMediaLibraryStore,
  secondsToFrames, generateId,
} from '@elah/editor'

import ScriptPanel from '../components/ScriptPanel'
import StoryboardPanel from '../components/StoryboardPanel'
import ChatPanel from '../components/ChatPanel'
import { colors } from '../styles/theme'
import { divider as dividerStyle } from '../styles/mixins'
import SourceInspector from '../components/SourceInspector'
import TimelineControls from '../components/TimelineControls'
import ClipLinker from '../hooks/useLinkedClips'
import { buildProjectFromProxyPicks, linkClipPair, clearLinkedPairs } from '../lib/timelineBuilder'
import { fetchProxyManifest, proxyUrlForEpisode, proxyInfoForEpisode } from '../lib/proxyEngine'
import { migratePicks } from '../model/migrate'

const FPS = 25
const STAGE = { width: 1920, height: 1080 }
const programEngineRef = { current: null }
const T = { border: colors.border, borderSubtle: colors.borderSubtle, bgPanel: colors.bg, bgSecondary: '#0D1017' }

// ═══════════════════════════════════
// 可拖拽分隔条
// ═══════════════════════════════════
function VBar({ onMouseDown }) {
  return <div onMouseDown={onMouseDown} style={{ width: 4, cursor: 'col-resize', background: T.border, flexShrink: 0 }}
    onMouseEnter={e => e.currentTarget.style.background = '#E11D48'}
    onMouseLeave={e => e.currentTarget.style.background = T.border} />
}
function HBar({ onMouseDown }) {
  return <div onMouseDown={onMouseDown} style={{ height: 6, cursor: 'ns-resize', background: T.border, borderTop: `1px solid ${T.borderSubtle}`, borderBottom: `1px solid ${T.borderSubtle}`, flexShrink: 0 }}
    onMouseEnter={e => e.currentTarget.style.background = '#E11D48'}
    onMouseLeave={e => e.currentTarget.style.background = T.border} />
}

// ═══════════════════════════════════
// 程序引擎数据加载
// ═══════════════════════════════════
function ProgramLoader({ prgTLRef, proxyManifest, onReady }) {
  const engine = useTimelineEngine()
  const { project, saveTimelineCache } = useProject()
  const didInit = useRef(false)
  const saveTimer = useRef(null)

  // 初始化：创建 4 个固定轨道（一次性，不覆盖）
  useEffect(() => {
    try {
    programEngineRef.current = engine
    window.__vibe_prg_engine = engine
    if (didInit.current) return
    const timeline = project?.timeline
    const mediaCache = project?.mediaCache
    const vibeTimeline = project?.vibe_timeline
    const vibeMediaCache = project?.vibe_mediaCache
    if (vibeTimeline && vibeMediaCache?.assets) {
      engine.loadProject(vibeTimeline)
      const store = useMediaLibraryStore.getState()
      for (const id of (vibeMediaCache.order || [])) {
        if (vibeMediaCache.assets[id] && !store.assets[id]) store.addAsset(vibeMediaCache.assets[id])
      }
      didInit.current = true
      if (onReady) setTimeout(onReady, 50)
      setTimeout(() => prgTLRef?.current?.fitToWindow(), 100)
      return
    }
    clearLinkedPairs()
    // v0.11: 口播2轨, 电视剧4轨 (segments有source_start → interview)
    const hasDirectSource = window.__vibe_segments?.some?.(s => s.source_start > 0)
    const isInterview = hasDirectSource
    const t = isInterview ? [
      { id: generateId(), name: '原声主镜头', kind: 'video', order: 0, height: 52, locked: false, disabled: false, muted: false, solo: false, volume: 1 },
      { id: generateId(), name: '原声主镜头 音频', kind: 'audio', order: 0, height: 44, locked: false, disabled: false, muted: false, solo: false },
    ] : [
      { id: generateId(), name: '补充镜头', kind: 'video', order: 0, height: 44, locked: false, disabled: false, muted: true, solo: false },
      { id: generateId(), name: '原声主镜头', kind: 'video', order: 2, height: 52, locked: false, disabled: false, muted: false, solo: false, volume: 1 },
      { id: generateId(), name: '原声主镜头 音频', kind: 'audio', order: 1, height: 44, locked: false, disabled: false, muted: false, solo: false },
      { id: generateId(), name: '旁白 TTS', kind: 'audio', order: 3, height: 44, locked: false, disabled: false, muted: false, solo: false },
    ]
    const c = {}
    t.forEach(tr => { c[tr.id] = [] })
    engine.loadProject({ id: 'vibecap-prg', fps: FPS, stage: STAGE, tracks: t, clips: c, transitions: [], version: 1, masterVolume: 1 })
    didInit.current = true
    if (onReady) setTimeout(onReady, 50)
    setTimeout(() => prgTLRef?.current?.fitToWindow(), 100)
    } catch(e) { console.error('[prg] init error:', e) }
  }, [engine])

  // proxyManifest 就绪 → 给空轨道加占位 clip（确保轨道显示）
  const didPlaceholders = useRef(false)
  useEffect(() => {
    if (!didInit.current || !proxyManifest?.proxies?.length || didPlaceholders.current) return
    try {
      const phSrc = `/proxies/${proxyManifest.proxies[0].file}`
      const prj = engine.getProject()
      for (const track of prj.tracks) {
        if (track.name?.startsWith('源')) continue
        const clips = prj.clips[track.id] || []
        if (clips.length === 0) {
          engine.addClip({ type: track.kind, trackId: track.id, name: '·', src: phSrc, startFrame: 0, durationFrames: 1, sourceStartFrame: 0, sourceDurationFrames: 1, volume: 0, opacity: 0.001 })
        }
      }
      didPlaceholders.current = true
    } catch(e) { console.error('[prg] placeholder error:', e) }
  }, [proxyManifest])

  // 自动保存 — 仅当有实际内容时
  useEffect(() => {
    if (!didInit.current) return
    let empty = true
    const save = () => {
      clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(() => {
        const prj = engine.getProject()
        const hasContent = Object.values(prj.clips || {}).some(arr => arr.some(c => c.src && c.src.length > 5))
        if (hasContent || !empty) {
          empty = false
          saveTimelineCache(prj, { assets: useMediaLibraryStore.getState().assets, order: useMediaLibraryStore.getState().order }, 'vibe')
        }
      }, 300)
    }
    engine.on('change', save)
    engine.on('history:change', save)
    return () => { engine.off('change', save); engine.off('history:change', save); clearTimeout(saveTimer.current) }
  }, [engine, saveTimelineCache])

  return null
}

// ═══════════════════════════════════
// 主页面
// ═══════════════════════════════════
export default function VibeEdit() {
  const { taskId } = useParams()
  const { project, addPick } = useProject()
  const prgTLRef = useRef(null)
  const demuxRef = useRef(null)

  const [scriptW, setScriptW] = useState(300)
  const [aiW, setAiW] = useState(400)
  const [scriptCollapsed, setScriptCollapsed] = useState(false)
  const [aiCollapsed, setAiCollapsed] = useState(false)
  const [bottomPct, setTimelinePct] = useState(28)
  const [segments, setSegments] = useState([])
  const [curSid, setCurSid] = useState(null)
  const [curSeq, setCurSeq] = useState('0')
  const [curNarration, setCurNarration] = useState('')
  const [proxyManifest, setProxyManifest] = useState(null)
  const [prgReady, setPrgReady] = useState(false)
  const [storySuggestions, setStorySuggestions] = useState(null)
  const prgCurrentFrame = usePlaybackStore(s => s.currentFrame)  // 顶层调用，供源检视器同步

  if (!demuxRef.current) { try { demuxRef.current = createDefaultDemuxerFactory() } catch(e) { console.warn('[vibe] demux:', e) } }

  useEffect(() => { fetchProxyManifest().then(setProxyManifest) }, [])
  // 卸载前清理 portal 节点
  useEffect(() => {
    return () => {
      const mount = document.getElementById('source-inspector-mount')
      if (mount) while (mount.firstChild) mount.removeChild(mount.firstChild)
    }
  }, [])
  useEffect(() => {
    if (!taskId) return
    fetch(`/segments.json?task=${taskId}`).then(r => r.json()).then(d => {
      setSegments(d.segments || [])
      window.__vibe_segments = d.segments || []  // v0.11: 供 ProgramLoader 检测 interview mode
      if (d.segments?.length && curSid == null) setCurSid(d.segments[0].seg_id)
    }).catch(() => {})
  }, [taskId])

  const handleSelectSegment = useCallback((sid, seq) => {
    setCurSid(sid); setCurSeq(seq || '0')
    const seg = segments.find(s => s.seg_id === sid)
    if (seg) {
      let ref = ''
      if (seq === 'D') ref = (seg.highlight_text || '').substring(0, 200)
      else { const ss = (seg.narration_text || '').split(/[。！？]/).filter(s => s.trim()); ref = (ss[parseInt(seq) || 0] || '').trim() }
      setCurNarration(ref)
      setStorySuggestions(null)

      // v0.11: 段直达 — 如果 segment 已有 source_start, 直接 seek 源检视器, 跳过 AI 搜索
      const ss = seg.source_start
      const se = seg.source_end
      if (ss != null && ss > 0) {
        const ep = seg.episode_marker?.episode || seg.video_episode || 1
        const startSec = ss
        const endSec = (se != null && se > ss) ? se : ss + 8
        if (window.__sourceLoadEpisode) {
          window.__sourceLoadEpisode(ep, startSec, endSec)
        }
      }
    }
  }, [segments])

  // AI 搜索结果 → 加载第一个结果 + 设置标记
  const handleSearch = useCallback((results) => {
    if (!results?.length) return
    const ep = results[0].ep
    if (window.__sourceLoadEpisode) window.__sourceLoadEpisode(ep)
    if (window.__sourceSetMarkers) window.__sourceSetMarkers(results)
  }, [])

  // 点击搜索结果卡片 → 加载对应剧集 + seek 到对应时间
  const handlePreviewClick = useCallback((result) => {
    if (!result) return
    const t = result.sourceStartSec ?? result.start ?? 0
    const e = result.sourceEndSec ?? result.end ?? (t + 10)
    if (window.__sourceLoadEpisode) window.__sourceLoadEpisode(result.ep, t, e)
  }, [])

  // 添加到节目引擎（inFrames, outFrames 由源检视器传入）
  const handleAddToProgram = useCallback((ep, inFrames, outFrames) => {
    const engine = programEngineRef.current
    if (!engine) return
    const proxy = proxyUrlForEpisode(ep, proxyManifest)
    if (!proxy) return

    const sf = inFrames ?? 0; const of = outFrames ?? (sf + secondsToFrames(5, FPS))
    const df = of - sf
    const insertFrame = usePlaybackStore.getState().currentFrame || 0
    const prj = engine.getProject()
    const prgVid = prj.tracks.find(t => t.name === '原声主镜头')
    const prgAud = prj.tracks.find(t => t.name === '原声主镜头 音频')
    if (!prgVid || !prgAud) return

    engine.batch(() => {
      // 移除占位 clip
      for (const [tid, tClips] of Object.entries(prj.clips)) {
        for (const c of tClips) { if (c.name === '·') engine.removeClip(c.id, tid) }
      }
      const v = engine.addClip({ type: 'video', trackId: prgVid.id, name: `S${curSid ?? '?'} EP${ep}`, src: proxy, startFrame: insertFrame, durationFrames: df, sourceStartFrame: sf, sourceDurationFrames: df, volume: 1, opacity: 1 })
      const a = engine.addClip({ type: 'audio', trackId: prgAud.id, name: `S${curSid ?? '?'} EP${ep}`, src: proxy, startFrame: insertFrame, durationFrames: df, sourceStartFrame: sf, sourceDurationFrames: df, volume: 1 })
      linkClipPair(v.id, a.id)
    }, 'src→prg')

    if (curSid != null && curSeq != null) {
      addPick(curSid, curSeq, 'main', { ep, sourceStartSec: sf / FPS, sourceEndSec: of / FPS })
    }
  }, [proxyManifest, curSid, curSeq, addPick])

  // 拖拽
  const dragX = (get, set, min, maxPct) => (e) => {
    e.preventDefault(); const start = get(); const sx = e.clientX
    const vw = document.documentElement.clientWidth
    const mv = (ev) => set(Math.max(min, Math.min(vw * maxPct, start - (sx - ev.clientX))))
    const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up) }
    document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up)
  }
  const dragTimeline = (e) => {
    e.preventDefault(); const s = bottomPct; const sy = e.clientY
    const h = e.currentTarget.parentElement.clientHeight
    const mv = (ev) => setBottomPct(Math.max(20, Math.min(60, s + (sy - ev.clientY) / h * 100)))
    const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up) }
    document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up)
  }

  const chatCtx = { sid: curSid, seq: curSeq, narration: curNarration, taskId }
  const proxyEps = proxyManifest?.proxies?.map(p => p.ep)?.join(",") || ""
  const leftW = scriptCollapsed ? 0 : scriptW
  const rightW = aiCollapsed ? 0 : aiW

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* ── 节目引擎 ── */}
      <EditorProvider fps={FPS} defaultTrackHeight={36} stage={STAGE}>
        <ProgramLoader prgTLRef={prgTLRef} proxyManifest={proxyManifest} onReady={() => setPrgReady(true)} />
        <ClipLinker />

        <div className="elah-root" style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          {/* ── 左：脚本 + 预览 + 时间轴 ── */}
          <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', flex: `${100 - bottomPct}%`, minHeight: 0, overflow: 'hidden' }}>
              <div style={{ width: leftW, flexShrink: 0, overflow: 'hidden', transition: 'width 0.15s' }}>
                {!scriptCollapsed && (
                  <div className="h-full flex flex-col">
                    <div className="flex items-center justify-between px-3 py-2 border-b border-border/50 shrink-0" style={{ minHeight: 32 }}>
                      <span className="text-xs font-medium text-foreground">脚本段</span>
                      <button onClick={() => setScriptCollapsed(true)} className="text-muted-foreground hover:text-foreground shrink-0">◀</button>
                    </div>
                    <ScriptPanel segments={segments} curSid={curSid} curSeq={curSeq} onPickSentence={handleSelectSegment} picks={project.picks} collapsed={false} />
                    <StoryboardPanel suggestions={storySuggestions} curSid={curSid} curSeq={curSeq} onSearch={(q) => { if (window.__sourceSearchQuery) window.__sourceSearchQuery(q) }} />
                  </div>
                )}
              </div>
              {scriptCollapsed ? <div style={{ width: 4, flexShrink: 0, cursor: 'col-resize', background: T.border }} onClick={() => setScriptCollapsed(false)} title="展开" />
                : <VBar onMouseDown={dragX(() => scriptW, setScriptW, 200, 0.45)} />}
              <div style={{ flex: 1, minWidth: 200, position: 'relative', background: '#000' }}>
                {demuxRef.current && <Preview demuxerFactory={demuxRef.current} style={{ width: '100%', height: '100%' }} />}
              </div>
            </div>
            <HBar onMouseDown={dragTimeline} />
            <div style={{ height: `${bottomPct}%`, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
              <TimelineControls timelineRef={prgTLRef} showTrackButtons={true} showRebuild={true} />
              <Timeline key={prgReady ? 'ready' : 'init'} ref={prgTLRef} fps={FPS} sidebarWidth={160} style={{ flex: 1, minHeight: 0, minWidth: 0 }} />
            </div>
          </div>

          {/* ── 右：AI + 源检视器（全高）── */}
          {aiCollapsed ? <div style={{ width: 4, flexShrink: 0, cursor: 'col-resize', background: T.border }} onClick={() => setAiCollapsed(false)} title="展开" />
            : <VBar onMouseDown={dragX(() => aiW, setAiW, 260, 0.45)} />}
          <div style={{ width: rightW, flexShrink: 0, overflow: 'hidden', display: rightW === 0 ? 'none' : 'flex', flexDirection: 'column', borderLeft: `1px solid ${T.border}` }}>
            <div className="flex items-center justify-between px-3 py-2 border-b border-border/50 shrink-0">
              <span className="text-xs font-medium text-foreground">AI 搜索</span>
              <button onClick={() => setAiCollapsed(true)} className="text-muted-foreground hover:text-foreground">▶</button>
            </div>
            <div style={{ flex: `${100 - bottomPct}%`, minHeight: 0, overflow: 'hidden' }}>
              <ChatPanel context={chatCtx} onPreview={handlePreviewClick} onPick={null} onSearch={handleSearch} onSuggestions={setStorySuggestions} eps={proxyEps} />
            </div>
            {/* AI搜索 / 源预览 分隔条 — 拖拽同步两侧底部面板高度 */}
            <div onMouseDown={(e) => {
              e.preventDefault(); const s = bottomPct; const sy = e.clientY
              const ph = e.currentTarget.parentElement.clientHeight
              const mv = (ev) => setBottomPct(Math.max(20, Math.min(60, s + (sy - ev.clientY) / ph * 100)))
              const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up) }
              document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up)
            }} style={{ height: 5, flexShrink: 0, cursor: 'ns-resize', background: T.border, borderTop: `1px solid ${T.borderSubtle}` }}
              onMouseEnter={e => e.currentTarget.style.background = '#E11D48'}
              onMouseLeave={e => e.currentTarget.style.background = T.border} />
            <div style={{ height: `${bottomPct}%`, flexShrink: 0, display: 'flex', flexDirection: 'column', borderTop: `1px solid ${T.border}` }}>
              {proxyManifest && (
                <SourceInspector proxyManifest={proxyManifest} onAddToProgram={handleAddToProgram} timelineFrame={prgCurrentFrame} />
              )}
            </div>
          </div>
        </div>
      </EditorProvider>
    </div>
  )
}
