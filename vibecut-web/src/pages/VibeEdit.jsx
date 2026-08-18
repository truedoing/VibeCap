/**
 * 分镜台 v3 — 段落级分镜设计
 * 双引擎：节目引擎(大预览+底部时间轴) + 分镜序列面板(右侧)
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useProject } from '../context/ProjectContext'

import '@elah/editor/styles.css'
import {
  EditorProvider, Preview, Timeline,
  createDefaultDemuxerFactory,
  useTimelineEngine,
  useTracksStore, usePlaybackStore, useMediaLibraryStore, useSelectionStore,
  secondsToFrames, generateId,
} from '@elah/editor'

import ScriptPanel from '../components/ScriptPanel'
import StoryboardOutline from '../components/StoryboardOutline'
import ShotPropertyPanel from '../components/ShotPropertyPanel'
import { colors } from '../styles/theme'
import { divider as dividerStyle } from '../styles/mixins'
import SourceInspector from '../components/SourceInspector'
import TimelineControls from '../components/TimelineControls'
import ClipLinker from '../hooks/useLinkedClips'
import { buildProjectFromProxyPicks, linkClipPair, clearLinkedPairs } from '../lib/timelineBuilder'
import { fetchProxyManifest, proxyUrlForEpisode, proxyInfoForEpisode } from '../lib/proxyEngine'
import { buildPicksFromStoryboard, buildSourceFileToEp, resolveShotSource } from '../lib/storyboardUtils'
import { migratePicks } from '../model/migrate'

const FPS = 25
const STAGE = { width: 1920, height: 1080 }
const ZOOM_MIN = 0.02
const ZOOM_MAX = 50
const ZOOM_WHEEL_FACTOR = 1.2  // 滚轮缩放倍率（对数尺度，平滑）
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
        // 缓存恢复时重建 clipRegistry（clipId → ep/秒），供「点 clip → 大纲定位」联动
        const registry = {}
        for (const clips of Object.values(vibeTimeline.clips || {})) {
          for (const c of clips) {
            if (c.type !== 'video') continue
            const m = String(c.name || '').match(/EP(\d+)/)
            if (!m) continue
            registry[c.id] = {
              ep: parseInt(m[1]),
              sourceStartSec: (c.sourceStartFrame || 0) / FPS,
              sourceEndSec: ((c.sourceStartFrame || 0) + (c.sourceDurationFrames || 0)) / FPS,
            }
          }
        }
        window.__vibe_clipRegistry = registry
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
      const { project: elahProject, mediaList, clipRegistry } = buildProjectFromProxyPicks(
        picks, proxyManifest, [], { mode, narrDurations, segDurations, taskName: taskId }
      )
      // clipRegistry: clipId → {ep, sourceStartSec, sourceEndSec}，供「点时间轴 clip → 大纲定位」反查
      window.__vibe_clipRegistry = clipRegistry

      engine.loadProject(elahProject)
      const store = useMediaLibraryStore.getState()
      const order = []
      for (const m of mediaList) {
        if (!store.assets[m.id]) store.addAsset(m)
        order.push(m.id)
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
        // 占位 clip(name='·') 不视为内容 —— 否则占位阶段就把空时间轴缓存下来，reload 恢复成只有占位、永不 auto-build
        const hasContent = Object.values(prj.clips || {}).some(arr =>
          arr.some(c => c.name !== '·' && c.src && c.src.length > 5))
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
  const [sbNewNotice, setSbNewNotice] = useState(null)  // 检测到的新分镜脚本更新时间
  const sbSigRef = useRef(null)  // 已加载 storyboard 的 _mtime（轮询基线）
  const [selectedShot, setSelectedShot] = useState(null)  // 分镜大纲里选中的镜头（属性面板消费）
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
  const loadStoryboard = useCallback(async () => {
    if (!taskId) return
    setSbLoading(true)
    setSbError(null)
    try {
      const r = await fetch(`/storyboard.json?task=${taskId}`)
      if (!r.ok) throw new Error(r.status)
      const d = await r.json()
      if (d?.segments?.length) {
        setStoryboard(d)
        sbSigRef.current = d._mtime ?? null
      } else {
        setStoryboard(null)
      }
      setSbNewNotice(null)
    } catch {
      setStoryboard(null)
      setSbError('分镜脚本未导入')
    } finally {
      setSbLoading(false)
    }
  }, [taskId])

  useEffect(() => { loadStoryboard() }, [loadStoryboard])

  // 轮询检测外部导入的新分镜脚本（只提示，不自动替换已加载数据）
  useEffect(() => {
    if (!taskId) return
    const check = async () => {
      if (sbSigRef.current == null) return  // 尚无基线，跳过
      try {
        const r = await fetch(`/storyboard.json?task=${taskId}`)
        if (!r.ok) return
        const d = await r.json()
        const sig = d?._mtime
        setSbNewNotice(sig && sig !== sbSigRef.current ? new Date(sig * 1000) : null)
      } catch {}
    }
    const timer = setInterval(check, 20000)
    return () => clearInterval(timer)
  }, [taskId])

  // 重新生成：先取最新分镜脚本，再整体重建时间线
  const reloadStoryboard = useCallback(async () => {
    await loadStoryboard()
    invalidateTimeline()
    setRebuildKey(k => k + 1)
  }, [loadStoryboard, invalidateTimeline])

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

  // 滚轮缩放：拦截 Elah 内部的线性 ±0.5（低端巨跳、高端微调），改用乘法缩放（对数尺度平滑）
  const handleTimelineWheel = useCallback((e) => {
    if (!e.ctrlKey && !e.metaKey) return  // 非缩放滚轮 → 交给默认横向滚动
    e.preventDefault()
    e.stopPropagation()  // 捕获阶段拦截，阻止 Elah 的线性缩放监听触发
    const zoom = usePlaybackStore.getState().zoom
    const factor = e.deltaY > 0 ? 1 / ZOOM_WHEEL_FACTOR : ZOOM_WHEEL_FACTOR
    const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom * factor))
    usePlaybackStore.getState().setZoom(next)
  }, [])

  // v3: 分镜序列上下文 — 整段解说词
  const storyCtx = { sid: curSid, narration: curNarration, taskId, segments, cover, trigger: storyTrigger }
  // 分镜脚本 source_files 反查（文件名 → ep），属性面板解析镜头用
  const sourceFileToEp = useMemo(() => buildSourceFileToEp(storyboard?.source_files), [storyboard])

  // 点时间轴 clip → 反查对应 shot，联动大纲选中（文案↔视频对应查看）
  const selectedClipId = useSelectionStore((s) => (s.selectedClipIds.size === 1 ? [...s.selectedClipIds][0] : null))
  useEffect(() => {
    if (!selectedClipId || !storyboard) return
    const ref = window.__vibe_clipRegistry?.[selectedClipId]
    if (!ref) return
    const { ep, sourceStartSec } = ref
    for (const seg of storyboard.segments || []) {
      for (const shot of seg.shot_sequence || []) {
        const src = resolveShotSource(shot, sourceFileToEp)
        if (src && src.ep === ep && Math.abs(src.startSec - sourceStartSec) < 1.5) {
          setSelectedShot(shot)
          return
        }
      }
    }
  }, [selectedClipId, storyboard, sourceFileToEp])

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
                    <div className="flex items-center gap-2 px-3 py-2 border-b border-border/50 shrink-0" style={{ minHeight: 32 }}>
                      <span className="text-xs font-medium text-foreground">分镜大纲</span>
                      <button onClick={reloadStoryboard} title="重新加载分镜脚本并重建时间线"
                        className="text-[10px] text-muted-foreground hover:text-foreground shrink-0 border border-border/60 rounded px-1.5 py-0.5">
                        ⟳ 重新生成
                      </button>
                      <button onClick={() => setScriptCollapsed(true)} className="text-muted-foreground hover:text-foreground shrink-0 ml-auto">◀</button>
                    </div>
                    <StoryboardOutline storyboard={storyboard} loading={sbLoading} error={sbError} notice={sbNewNotice}
                      onReload={reloadStoryboard} onSelectShot={setSelectedShot} selectedShotId={selectedShot?.shot_id} />
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
              <div onWheelCapture={handleTimelineWheel} style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                <Timeline key={prgReady ? 'ready' : 'init'} ref={prgTLRef} fps={FPS} sidebarWidth={160} style={{ flex: 1, minHeight: 0, minWidth: 0 }} />
              </div>
            </div>
          </div>

          {/* ── 右：属性面板 + 源检视器 ── */}
          {rightCollapsed ? <div style={{ width: 4, flexShrink: 0, cursor: 'col-resize', background: T.border }} onClick={() => setRightCollapsed(false)} title="展开" />
            : <VBar onMouseDown={dragX(() => rightW, setRightW, 260, 0.45)} />}
          <div style={{ width: rightPanelW, flexShrink: 0, overflow: 'hidden', display: rightPanelW === 0 ? 'none' : 'flex', flexDirection: 'column', borderLeft: `1px solid ${T.border}` }}>
            <div className="flex items-center justify-between px-3 py-2 border-b border-border/50 shrink-0">
              <span className="text-xs font-medium text-foreground">属性</span>
              <button onClick={() => setRightCollapsed(true)} className="text-muted-foreground hover:text-foreground">▶</button>
            </div>
            {/* 属性面板 — 上部，高度与预览区同步；按选中元素显示详情 */}
            <div style={{ flex: `${100 - bottomPct}%`, minHeight: 0, overflow: 'hidden' }}>
              <ShotPropertyPanel shot={selectedShot} sourceFileToEp={sourceFileToEp} />
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
