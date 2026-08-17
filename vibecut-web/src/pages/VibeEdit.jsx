/**
 * 分镜台 v3 — 段落级分镜设计
 * 双引擎：节目引擎(大预览+底部时间轴) + 分镜序列面板(右侧)
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
import StoryboardOutline from '../components/StoryboardOutline'
import StoryboardSequence from '../components/StoryboardSequence'
import { colors } from '../styles/theme'
import { divider as dividerStyle } from '../styles/mixins'
import SourceInspector from '../components/SourceInspector'
import TimelineControls from '../components/TimelineControls'
import ClipLinker from '../hooks/useLinkedClips'
import { buildProjectFromProxyPicks, linkClipPair, clearLinkedPairs } from '../lib/timelineBuilder'
import { fetchProxyManifest, proxyUrlForEpisode, proxyInfoForEpisode } from '../lib/proxyEngine'
import { buildPicksFromStoryboard } from '../lib/storyboardUtils'
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
function ProgramLoader({ prgTLRef, proxyManifest, onReady, segments, taskId, storyboard, projectType }) {
  const engine = useTimelineEngine()
  const { project, saveTimelineCache } = useProject()
  const didInit = useRef(false)
  const saveTimer = useRef(null)

  // 优先用显式传入的 projectType，fallback 到旧推断逻辑
  const resolvedType = projectType || segments?.project_type || (segments?.length > 0 && segments.some(s => s.source_start > 0) ? 'interview' : 'drama')
  const isInterview = resolvedType === 'interview'

  useEffect(() => {
    try {
    programEngineRef.current = engine
    window.__vibe_prg_engine = engine

    const vibeTimeline = project?.vibe_timeline
    const vibeMediaCache = project?.vibe_mediaCache

    if (vibeTimeline && vibeMediaCache?.assets) {
      if (didInit.current) return
      const cachedTrackCount = vibeTimeline.tracks?.length || 0
      const expectedTrackCount = isInterview ? 2 : 4
      if (cachedTrackCount !== expectedTrackCount) {
        console.log(`[prg] 缓存模式不匹配 (cached=${cachedTrackCount} expected=${expectedTrackCount}), 重新初始化`)
      } else {
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
    }

    clearLinkedPairs()
    const t = isInterview ? [
      { id: generateId(), name: '原声主镜头', kind: 'video', order: 0, height: 52, locked: false, disabled: false, muted: false, solo: false, volume: 1 },
      { id: generateId(), name: '原声主镜头 音频', kind: 'audio', order: 0, height: 44, locked: false, disabled: false, muted: false, solo: false },
    ] : [
      { id: generateId(), name: '补充镜头', kind: 'video', order: 0, height: 44, locked: false, disabled: false, muted: true, solo: false },
      { id: generateId(), name: '原声主镜头', kind: 'video', order: 2, height: 52, locked: false, disabled: false, muted: false, solo: false, volume: 1 },
      { id: generateId(), name: '原声主镜头 音频', kind: 'audio', order: 1, height: 44, locked: false, disabled: false, muted: false, solo: false },
      { id: generateId(), name: '旁白 TTS', kind: 'audio', order: 3, height: 44, locked: false, disabled: false, muted: false, solo: false },
    ]

    if (didInit.current) {
      const prj = engine.getProject()
      const prevTrackCount = prj.tracks?.length || 0
      const newTrackCount = t.length
      if (prevTrackCount !== newTrackCount) {
        for (const track of prj.tracks) {
          const clips = prj.clips[track.id] || []
          for (const c of [...clips]) engine.removeClip(c.id, track.id)
        }
      }
    }

    const c = {}
    t.forEach(tr => { c[tr.id] = [] })
    engine.loadProject({ id: 'vibecut-prg', fps: FPS, stage: STAGE, tracks: t, clips: c, transitions: [], version: 1, masterVolume: 1 })
    didInit.current = true
    if (onReady) setTimeout(onReady, 50)
    setTimeout(() => prgTLRef?.current?.fitToWindow(), 100)
    } catch(e) { console.error('[prg] init error:', e) }
  }, [engine, isInterview])

  const didAutoBuild = useRef(false)
  const [narrationMeta, setNarrationMeta] = useState(null)
  const [narrLoaded, setNarrLoaded] = useState(false)
  useEffect(() => {
    if (!taskId || isInterview) { setNarrLoaded(true); return }
    fetch(`/narration.json?task=${taskId}`)
      .then(r => r.json())
      .then(d => setNarrationMeta(d?.segments ? d : null))
      .catch(() => setNarrationMeta(null))
      .finally(() => setNarrLoaded(true))
  }, [taskId, isInterview])

  useEffect(() => {
    if (!proxyManifest?.proxies?.length || !didInit.current || didAutoBuild.current) return
    if (project?.vibe_timeline) return
    // 等 narration 加载完成再铺轨（否则旁白轨缺失）
    if (!narrLoaded) return

    try {
      let picks = {}
      let source = 'segments'
      let segDurations = null

      // 优先：有 storyboard.json 时，用分镜脚本铺轨（全局分镜，按段类型分层）
      if (storyboard?.segments?.length) {
        const built = buildPicksFromStoryboard(storyboard)
        picks = built.picks
        source = 'storyboard'
        // 音频为骨架：narration 段用音频真实时长，dialogue 段用画面估算时长
        segDurations = { ...built.segDurMap }
        if (narrationMeta?.segments) {
          for (const ns of narrationMeta.segments) {
            const sid = ns.seg_id ?? ns.index
            const dur = (ns.end || 0) - (ns.start || 0)
            if (sid != null && dur > 0) segDurations[sid] = dur
          }
        }
      } else if (segments?.length) {
        if (isInterview) {
          const hasSubClips = segments.some(s => s.sub_clips?.length > 0)
          if (hasSubClips) {
            let idx = 0
            for (const seg of segments) {
              for (const sc of (seg.sub_clips || [])) {
                if (sc.decision !== 'KEEP') continue
                const ep = seg.episode_marker?.episode || seg.video_episode || 1
                const key = `${seg.seg_id ?? 0}_${idx++}`
                picks[key] = { main: [{ ep, sourceStartSec: sc.start, sourceEndSec: sc.end }] }
              }
            }
          } else {
            const sorted = [...segments].sort((a, b) => (a.seg_id ?? 0) - (b.seg_id ?? 0))
            sorted.forEach(s => {
              const ep = s.episode_marker?.episode || s.video_episode || 1
              const startSec = s.source_start ?? 0
              const endSec = s.source_end ?? (startSec + 5)
              if (startSec <= 0 && endSec <= 0) return
              picks[`${s.seg_id ?? 0}_0`] = { main: [{ ep, sourceStartSec: startSec, sourceEndSec: endSec }] }
            })
          }
        } else {
          const sorted = [...segments].sort((a, b) => (a.seg_id ?? 0) - (b.seg_id ?? 0))
          sorted.forEach(s => {
            const ep = s.video_episode || s.episode_marker?.episode
            const startSec = s.source_start
            const endSec = s.source_end
            if (ep && startSec != null && startSec > 0) {
              const marginStart = Math.max(0, startSec - 2)
              const marginEnd = (endSec && endSec > startSec) ? endSec + 2 : startSec + 8
              picks[`${s.seg_id ?? 0}_0`] = { main: [{ ep, sourceStartSec: marginStart, sourceEndSec: marginEnd }] }
            }
          })
        }
      }

      if (Object.keys(picks).length === 0) return

      const narrDurations = {}
      if (!isInterview && narrationMeta?.segments) {
        for (const ns of narrationMeta.segments) {
          const sid = ns.seg_id ?? ns.index
          const dur = (ns.end || 0) - (ns.start || 0)
          if (sid != null && dur > 0) narrDurations[sid] = dur
        }
      }

      const mode = isInterview ? 'interview' : 'drama'
      const { project: elahProject, mediaList } = buildProjectFromProxyPicks(
        picks, proxyManifest, [], { mode, narrDurations, segDurations, taskName: taskId }
      )

      engine.loadProject(elahProject)
      const store = useMediaLibraryStore.getState()
      const order = []
      for (const m of mediaList) {
        if (!store.assets[m.assetId]) store.addAsset(m)
        order.push(m.assetId)
      }
      saveTimelineCache(elahProject, { assets: { ...store.assets }, order }, 'vibe')
      didAutoBuild.current = true
      if (onReady) setTimeout(onReady, 50)
      setTimeout(() => prgTLRef?.current?.fitToWindow(), 100)
      console.log(`[prg] 🎬 ${isInterview ? 'Interview' : 'Drama'} 自动建轨(${source}): ${Object.keys(picks).length} segments → 时间轴`)
    } catch (e) { console.error('[prg] auto-build error:', e) }
  }, [isInterview, didInit.current, segments, storyboard, proxyManifest, narrationMeta, narrLoaded, project?.vibe_timeline])

  const didPlaceholders = useRef(false)
  useEffect(() => {
    if (!didInit.current || !proxyManifest?.proxies?.length || didPlaceholders.current) return
    try {
      const phSrc = `/proxies/${proxyManifest.proxies[0].file}`
      const prj = engine.getProject()
      const skipNames = new Set(['补充镜头', '旁白 TTS'])
      for (const track of prj.tracks) {
        if (track.name?.startsWith('源')) continue
        if (skipNames.has(track.name)) continue
        const clips = prj.clips[track.id] || []
        if (clips.length === 0) {
          engine.addClip({ type: track.kind, trackId: track.id, name: '·', src: phSrc, startFrame: 0, durationFrames: 1, sourceStartFrame: 0, sourceDurationFrames: 1, volume: 0, opacity: 0.001 })
        }
      }
      didPlaceholders.current = true
    } catch(e) { console.error('[prg] placeholder error:', e) }
  }, [proxyManifest])

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
  const { project, addPick, invalidateTimeline } = useProject()
  const prgTLRef = useRef(null)
  const demuxRef = useRef(null)
  const [rebuildKey, setRebuildKey] = useState(0)  // 递增强制重挂 ProgramLoader，重新铺轨

  const [scriptW, setScriptW] = useState(380)
  const [rightW, setRightW] = useState(460)
  const [scriptCollapsed, setScriptCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [bottomPct, setTimelinePct] = useState(28)
  const [cover, setCover] = useState('')

  const [segments, setSegments] = useState([])
  const [projectType, setProjectType] = useState('drama')
  const [storyboard, setStoryboard] = useState(null)
  const [sbLoading, setSbLoading] = useState(false)
  const [sbError, setSbError] = useState(null)
  const [curSid, setCurSid] = useState(null)
  const [curHighlight, setCurHighlight] = useState('')  // 当前台词文本
  const [curNarration, setCurNarration] = useState('')   // 当前解说词文本
  const [storyTrigger, setStoryTrigger] = useState(0)     // 每次策划分镜递增
  const [proxyManifest, setProxyManifest] = useState(null)
  const [prgReady, setPrgReady] = useState(false)
  const prgCurrentFrame = usePlaybackStore(s => s.currentFrame)

  if (!demuxRef.current) { try { demuxRef.current = createDefaultDemuxerFactory() } catch(e) { console.warn('[vibe] demux:', e) } }

  useEffect(() => { fetchProxyManifest().then(setProxyManifest) }, [])
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
      if (d.project_type) setProjectType(d.project_type)
      setCover(d.cover || '')
      window.__vibe_segments = d.segments || []
      window.__vibe_cover = d.cover || ''
      if (d.segments?.length && curSid == null) setCurSid(d.segments[0].seg_id)
    }).catch(() => {})
  }, [taskId])

  // 加载全局分镜脚本（扣子/WorkBuddy 导入）
  useEffect(() => {
    if (!taskId) return
    setSbLoading(true)
    setSbError(null)
    fetch(`/storyboard.json?task=${taskId}`)
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json() })
      .then(d => {
        if (d?.segments?.length) setStoryboard(d)
        else setStoryboard(null)
      })
      .catch(() => { setStoryboard(null); setSbError('分镜脚本未导入') })
      .finally(() => setSbLoading(false))
  }, [taskId])

  // v3: 台词点击 → ASR 精确定位 (直接 seek 源素材)
  const handleDialogueClick = useCallback((sid) => {
    setCurSid(sid)
    const seg = segments.find(s => s.seg_id === sid)
    if (seg) {
      setCurHighlight(seg.highlight_text || '')
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

  // v3: 解说段点击 → 策划分镜
  const handleStoryboard = useCallback((sid) => {
    setCurSid(sid)
    if (sid === -1) {
      setCurNarration(cover || '')
    } else {
      const seg = segments.find(s => s.seg_id === sid)
      setCurNarration(seg?.narration_text || seg?.highlight_text || '')
    }
    setStoryTrigger(t => t + 1)
  }, [segments, cover])

  // 添加到节目引擎
  const handleAddToProgram = useCallback((ep, inFrames, outFrames, trackType = 'main') => {
    const engine = programEngineRef.current
    if (!engine) return
    const proxy = proxyUrlForEpisode(ep, proxyManifest)
    if (!proxy) return

    const sf = inFrames ?? 0; const of = outFrames ?? (sf + secondsToFrames(5, FPS))
    const df = of - sf
    const prj = engine.getProject()
    const isSupp = trackType === 'supp'
    const vidTrackName = isSupp ? '补充镜头' : '原声主镜头'
    const audTrackName = isSupp ? null : '原声主镜头 音频'
    const prgVid = prj.tracks.find(t => t.name === vidTrackName)
    const prgAud = audTrackName ? prj.tracks.find(t => t.name === audTrackName) : null
    if (!prgVid) return

    const existingClips = prj.clips[prgVid.id] || []
    const insertFrame = existingClips.reduce((max, c) => Math.max(max, (c.startFrame || 0) + (c.durationFrames || 0)), 0)

    engine.batch(() => {
      for (const [tid, tClips] of Object.entries(prj.clips)) {
        for (const c of tClips) { if (c.name === '·') engine.removeClip(c.id, tid) }
      }
      const v = engine.addClip({ type: 'video', trackId: prgVid.id, name: `S${curSid ?? '?'} EP${ep}${isSupp ? ' 补' : ''}`, src: proxy, startFrame: insertFrame, durationFrames: df, sourceStartFrame: sf, sourceDurationFrames: df, volume: isSupp ? 0 : 1, opacity: 1 })
      engine.updateClip(v.id, prgVid.id, { sourceStartFrame: sf, sourceDurationFrames: df })
      let a = null
      if (prgAud) {
        a = engine.addClip({ type: 'audio', trackId: prgAud.id, name: `S${curSid ?? '?'} EP${ep}`, src: proxy, startFrame: insertFrame, durationFrames: df, sourceStartFrame: sf, sourceDurationFrames: df, volume: 1 })
        engine.updateClip(a.id, prgAud.id, { sourceStartFrame: sf, sourceDurationFrames: df })
        linkClipPair(v.id, a.id)
      }
    }, 'src→prg')

    if (curSid != null) {
      addPick(curSid, '0', trackType, { ep, sourceStartSec: sf / FPS, sourceEndSec: of / FPS })
    }
  }, [proxyManifest, curSid, addPick])

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

  // v3: 分镜序列上下文 — 整段解说词
  const storyCtx = { sid: curSid, narration: curNarration, taskId, segments, cover, trigger: storyTrigger }
  const leftW = scriptCollapsed ? 0 : scriptW
  const rightPanelW = rightCollapsed ? 0 : rightW

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <EditorProvider fps={FPS} defaultTrackHeight={36} stage={STAGE}>
        <ProgramLoader key={rebuildKey} prgTLRef={prgTLRef} proxyManifest={proxyManifest} onReady={() => setPrgReady(true)} segments={segments} taskId={taskId} storyboard={storyboard} projectType={projectType} />
        <ClipLinker />

        <div className="elah-root" style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          {/* ── 左：脚本 + 预览 + 时间轴 ── */}
          <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', flex: `${100 - bottomPct}%`, minHeight: 0, overflow: 'hidden' }}>
              <div style={{ width: leftW, flexShrink: 0, overflow: 'hidden', transition: 'width 0.15s' }}>
                {!scriptCollapsed && (
                  <div className="h-full flex flex-col">
                    <div className="flex items-center justify-between px-3 py-2 border-b border-border/50 shrink-0" style={{ minHeight: 32 }}>
                      <span className="text-xs font-medium text-foreground">分镜大纲</span>
                      <button onClick={() => setScriptCollapsed(true)} className="text-muted-foreground hover:text-foreground shrink-0">◀</button>
                    </div>
                    <StoryboardOutline storyboard={storyboard} loading={sbLoading} error={sbError} />
                  </div>
                )}
              </div>
              {scriptCollapsed ? <div style={{ width: 4, flexShrink: 0, cursor: 'col-resize', background: T.border }} onClick={() => setScriptCollapsed(false)} title="展开" />
                : <VBar onMouseDown={dragX(() => scriptW, setScriptW, 200, 0.45)} />}
              <div style={{ flex: 1, minWidth: 200, position: 'relative', background: '#000' }}>
                {demuxRef.current && <Preview demuxerFactory={demuxRef.current} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }} />}
              </div>
            </div>
            <HBar onMouseDown={dragTimeline} />
            <div style={{ height: `${bottomPct}%`, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
              <TimelineControls timelineRef={prgTLRef} showTrackButtons={true} showRebuild={true}
                onRebuild={() => { invalidateTimeline(); setRebuildKey(k => k + 1) }} />
              <Timeline key={prgReady ? 'ready' : 'init'} ref={prgTLRef} fps={FPS} sidebarWidth={160} style={{ flex: 1, minHeight: 0, minWidth: 0 }} />
            </div>
          </div>

          {/* ── 右：分镜序列 + 源检视器 ── */}
          {rightCollapsed ? <div style={{ width: 4, flexShrink: 0, cursor: 'col-resize', background: T.border }} onClick={() => setRightCollapsed(false)} title="展开" />
            : <VBar onMouseDown={dragX(() => rightW, setRightW, 260, 0.45)} />}
          <div style={{ width: rightPanelW, flexShrink: 0, overflow: 'hidden', display: rightPanelW === 0 ? 'none' : 'flex', flexDirection: 'column', borderLeft: `1px solid ${T.border}` }}>
            <div className="flex items-center justify-between px-3 py-2 border-b border-border/50 shrink-0">
              <span className="text-xs font-medium text-foreground">分镜序列</span>
              <button onClick={() => setRightCollapsed(true)} className="text-muted-foreground hover:text-foreground">▶</button>
            </div>
            {/* 分镜序列 — 上部，高度与预览区同步 */}
            <div style={{ flex: `${100 - bottomPct}%`, minHeight: 0, overflow: 'hidden' }}>
              <StoryboardSequence
                context={storyCtx}
                proxyManifest={proxyManifest}
                onAddToProgram={handleAddToProgram}
                taskId={taskId}
              />
            </div>
            {/* 分隔条 — 拖拽同步时间线高度 */}
            <div onMouseDown={(e) => {
              e.preventDefault(); const s = bottomPct; const sy = e.clientY
              const ph = e.currentTarget.parentElement.clientHeight
              const mv = (ev) => setBottomPct(Math.max(20, Math.min(60, s + (sy - ev.clientY) / ph * 100)))
              const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up) }
              document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up)
            }} style={{ height: 5, flexShrink: 0, cursor: 'ns-resize', background: T.border, borderTop: `1px solid ${T.borderSubtle}` }}
              onMouseEnter={e => e.currentTarget.style.background = '#E11D48'}
              onMouseLeave={e => e.currentTarget.style.background = T.border} />
            {/* 源检视器 — 下部，高度与时间线同步 */}
            <div style={{ height: `${bottomPct}%`, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
              {proxyManifest && (
                <SourceInspector proxyManifest={proxyManifest} onAddToProgram={handleAddToProgram} timelineFrame={prgCurrentFrame} taskId={taskId} />
              )}
            </div>
          </div>
        </div>
      </EditorProvider>
    </div>
  )
}
