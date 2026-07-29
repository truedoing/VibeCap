import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useProject } from '../context/ProjectContext'

import '@elah/editor/styles.css'
import {
  EditorProvider,
  Preview,
  Timeline,
  createDefaultDemuxerFactory,
  useTracksStore,
  usePlaybackStore,
  usePlaybackEngine,
  useSelectionStore,
  useTimelineEngine,
  useMediaLibrary,
  useMediaLibraryStore,
  splitClipAtPlayhead,
  framesToTimecode,
  generateId,
  secondsToFrames,
} from '@elah/editor'

// ═══════════════════════════════════════════════
// 移植自 playground/react/src/components/theme.ts
// ═══════════════════════════════════════════════
const theme = {
  bgPrimary: '#06070A',
  bgSecondary: '#0D1017',
  bgPanel: '#121722',
  bgElevated: '#171D2B',
  bgTimeline: '#0A0D14',
  border: '#232938',
  borderSubtle: '#1A1F2B',
  textPrimary: '#F3F4F6',
  textSecondary: '#A7AFBF',
  textMuted: '#6B7280',
  accent: '#E11D48',
  accentHover: '#FB7185',
  accentGlow: 'rgba(225, 29, 72, 0.35)',
  success: '#22C55E',
  warning: '#F59E0B',
  info: '#3B82F6',
  purple: '#7C3AED',
  clipVideo: '#2563EB',
  clipAudio: '#16A34A',
  clipText: '#9333EA',
  playhead: '#FF2D55',
  fontSans: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  fontMono: 'ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace',
}

const btnBase = {
  padding: '6px 12px',
  background: theme.bgElevated,
  color: theme.textSecondary,
  border: `1px solid ${theme.border}`,
  borderRadius: 6,
  fontSize: 12,
  cursor: 'pointer',
  fontFamily: theme.fontSans,
  transition: 'background 0.15s, border-color 0.15s, color 0.15s',
}

const btnDisabled = (disabled) =>
  disabled
    ? { ...btnBase, background: theme.bgPanel, color: theme.textMuted, cursor: 'not-allowed', opacity: 0.6 }
    : btnBase

const divider = {
  width: 1,
  height: 18,
  background: theme.border,
  flexShrink: 0,
  margin: '0 8px',
}

// ═══════════════════════════════════════════════
// VIBECAP 数据接入层
// ═══════════════════════════════════════════════
const FPS = 25
const STAGE = { width: 1920, height: 1080 }
function thumbnailUrl(filePath) {
  if (!filePath) return undefined
  const base = filePath.replace(/\.(mp4|mov|webm|avi|mkv)$/i, '')
  return `/clips/${base}.jpg`
}

// 视频/音频 clip 联动映射：clipId → partnerClipId（双向）
const linkedPairs = new Map()

function linkClipPair(videoClipId, audioClipId) {
  linkedPairs.set(videoClipId, audioClipId)
  linkedPairs.set(audioClipId, videoClipId)
}

function unlinkClipPair(clipId) {
  const partner = linkedPairs.get(clipId)
  if (partner) {
    linkedPairs.delete(partner)
    linkedPairs.delete(clipId)
  }
}

function buildProjectFromPicks(picks) {
  const tracks = []
  const clips = {}
  const mediaList = []

  // 5 轨 ID
  const mainVideoId = generateId()   // 原声主镜头轨（画面）
  const mainAudioId = generateId()   // 原声主镜头音轨（音频）
  const mainMutedId = generateId()   // 解说主镜头轨（静音画面）
  const suppId = generateId()        // 补充轨（静音）
  const narrId = generateId()        // 旁白音轨

  const mainVideoClips = []
  const mainAudioClips = []
  const mainMutedClips = []
  const suppClips = []
  const narrClips = []

  const NARR_DURATIONS = { 0: 26, 1: 24, 2: 12, 3: 5, 4: 15, 5: 56, 6: 18, 7: 18, 8: 45 }

  const entries = Object.entries(picks).sort((a, b) => {
    const [sa] = a[0].split('_').map(Number)
    const [sb] = b[0].split('_').map(Number)
    return sa - sb
  })

  // 第1遍: 统计每段高亮阶段（main 总时长）
  const segHighlight = {}
  for (const [key, p] of entries) {
    const [sidStr] = key.split('_')
    const sid = parseInt(sidStr)
    if (!segHighlight[sid]) segHighlight[sid] = 0
    if (p.main?.length) {
      p.main.forEach(m => {
        if (m.file) segHighlight[sid] += m.duration || (m.end - m.start) || 3
      })
    }
  }

  // 计算每段偏移: highlight + narration
  // 解说阶段需要同时容纳静音 main clip（时长=hl）和旁白音频（时长=narr），
  // 因此取 max(hl, narr)，防止静音 main clip 越过段边界与下一段重叠
  const segOffsets = {}
  let cursor = 0
  for (let sid = 0; sid <= 8; sid++) {
    segOffsets[sid] = cursor
    const hl = segHighlight[sid] || 0
    const narr = NARR_DURATIONS[sid] || 0
    cursor += hl + Math.max(hl, narr)
  }

  // 第2遍: 放置 clip
  // 同一段可能有多个 entry（如 0_0, 0_1, 0_D），cursor 需要跨 entry 延续
  // segOffsets / segHighlight 是秒，必须转成帧再用于 startFrame
  const segCursors = {}  // { sid: { audioFrames, mutedFrames, suppFrames } }
  for (const [key, p] of entries) {
    const [sidStr, seqStr] = key.split('_')
    const sid = parseInt(sidStr)
    const segStart = secondsToFrames(segOffsets[sid] || 0, FPS)
    const hlDur = secondsToFrames(segHighlight[sid] || 0, FPS)
    const narrStart = segStart + hlDur

    // 初始化本段 cursor（首次遇到该段时）
    if (!segCursors[sid]) {
      segCursors[sid] = { audioFrames: segStart, mutedFrames: narrStart, suppFrames: narrStart }
    }
    const cur = segCursors[sid]

    // ── 原声主镜头轨: main clips 画面 + 音频（分开两条轨）──
    if (p.main?.length) {
      p.main.forEach((m, mi) => {
        const durSec = m.duration || (m.end - m.start) || 3
        if (!m.file) return
        const durFrames = secondsToFrames(durSec, FPS)
        const src = `/clips/${m.file}`
        const startF = cur.audioFrames
        // 视频轨 — 画面
        const vClipId = generateId(); const vAssetId = generateId()
        mediaList.push({ assetId: vAssetId, src, name: `S${sid} EP${m.ep} 主`, kind: 'video', durationSec: durSec, thumbnailUrl: thumbnailUrl(m.file) })
        mainVideoClips.push({ id: vClipId, trackId: mainVideoId, type: 'video', assetId: vAssetId, name: `S${sid} EP${m.ep}`, src, startFrame: startF, durationFrames: durFrames, sourceStartFrame: 0, sourceDurationFrames: durFrames, volume: 1, opacity: 1, locked: false, disabled: false })
        // 音轨 — 同源音频
        const aClipId = generateId(); const aAssetId = generateId()
        mediaList.push({ assetId: aAssetId, src, name: `S${sid} EP${m.ep} 原声`, kind: 'audio', durationSec: durSec })
        mainAudioClips.push({ id: aClipId, trackId: mainAudioId, type: 'audio', assetId: aAssetId, name: `S${sid} EP${m.ep}`, src, startFrame: startF, durationFrames: durFrames, sourceStartFrame: 0, sourceDurationFrames: durFrames, volume: 1, locked: false, disabled: false })
        // 建立联动关系：拖动视频 clip 时音频 clip 自动同步
        linkClipPair(vClipId, aClipId)
        cur.audioFrames += durFrames
      })
    }

    // ── 解说主镜头轨: 同组 main clips 静音（解说期背景画面）──
    if (p.main?.length) {
      p.main.forEach((m) => {
        const durSec = m.duration || (m.end - m.start) || 3
        if (!m.file) return
        const durFrames = secondsToFrames(durSec, FPS)
        const src = `/clips/${m.file}`
        const clipId = generateId(); const assetId = generateId()
        mediaList.push({ assetId, src, name: `S${sid} EP${m.ep} 主(解)`, kind: 'video', durationSec: durSec, thumbnailUrl: thumbnailUrl(m.file) })
        mainMutedClips.push({ id: clipId, trackId: mainMutedId, type: 'video', assetId, name: `S${sid} EP${m.ep}`, src, startFrame: cur.mutedFrames, durationFrames: durFrames, sourceStartFrame: 0, sourceDurationFrames: durFrames, volume: 0, opacity: 1, locked: false, disabled: false })
        cur.mutedFrames += durFrames
      })
    }

    // ── 补充轨: supp clips 静音 ──
    if (p.supp?.length) {
      p.supp.forEach((s, si) => {
        const durSec = s.duration || (s.end - s.start) || 2
        if (!s.file) return
        const durFrames = secondsToFrames(durSec, FPS)
        const src = `/clips/${s.file}`
        const clipId = generateId(); const assetId = generateId()
        mediaList.push({ assetId, src, name: `S${sid} EP${s.ep} 补`, kind: 'video', durationSec: durSec, thumbnailUrl: thumbnailUrl(s.file) })
        suppClips.push({ id: clipId, trackId: suppId, type: 'video', assetId, name: `S${sid} EP${s.ep}`, src, startFrame: cur.suppFrames, durationFrames: durFrames, sourceStartFrame: 0, sourceDurationFrames: durFrames, volume: 0, opacity: 1, locked: false, disabled: false })
        cur.suppFrames += durFrames
      })
    }
  }

  // ── 旁白音轨 ──
  for (let sid = 0; sid <= 8; sid++) {
    const dur = NARR_DURATIONS[sid]
    if (!dur) continue
    const segStart = secondsToFrames(segOffsets[sid] || 0, FPS)
    const hlDur = secondsToFrames(segHighlight[sid] || 0, FPS)
    const narrStart = segStart + hlDur
    const src = `tts_segments/narr_${String(sid).padStart(3, '0')}.wav`
    const durFrames = secondsToFrames(dur, FPS)
    const clipId = generateId(); const assetId = generateId()
    mediaList.push({ assetId, src, name: `解说 seg_${sid}`, kind: 'audio', durationSec: dur })
    narrClips.push({ id: clipId, trackId: narrId, type: 'audio', assetId, name: `解说 seg_${sid}`, src, startFrame: narrStart, durationFrames: durFrames, sourceStartFrame: 0, sourceDurationFrames: durFrames, volume: 1, locked: false, disabled: false })
  }

  // ── 组装轨道 ──
  if (suppClips.length > 0) {
    tracks.push({ id: suppId, name: '补充镜头', kind: 'video', order: 0, height: 44, locked: false, disabled: false, muted: true, solo: false })
    clips[suppId] = suppClips
  }
  if (mainMutedClips.length > 0) {
    tracks.push({ id: mainMutedId, name: '解说主镜头 (静音)', kind: 'video', order: 1, height: 44, locked: false, disabled: false, muted: true, solo: false })
    clips[mainMutedId] = mainMutedClips
  }
  if (mainVideoClips.length > 0) {
    tracks.push({ id: mainVideoId, name: '原声主镜头', kind: 'video', order: 2, height: 52, locked: false, disabled: false, muted: false, solo: false, volume: 1 })
    clips[mainVideoId] = mainVideoClips
  }
  if (mainAudioClips.length > 0) {
    tracks.push({ id: mainAudioId, name: '原声主镜头 音频', kind: 'audio', order: 0, height: 44, locked: false, disabled: false, muted: false, solo: false })
    clips[mainAudioId] = mainAudioClips
  }
  if (narrClips.length > 0) {
    tracks.push({ id: narrId, name: '旁白 TTS', kind: 'audio', order: 1, height: 44, locked: false, disabled: false, muted: false, solo: false })
    clips[narrId] = narrClips
  }

  const totalFrames = cursor * FPS
  return { project: { id: 'vibecap-timeline', fps: FPS, stage: STAGE, tracks, clips, transitions: [], version: 1, masterVolume: 1 }, mediaList }
}
const ZOOM_MIN = 0.02
const ZOOM_MAX = 50
const zoomToSlider = (z) => (Math.log(z) - Math.log(ZOOM_MIN)) / (Math.log(ZOOM_MAX) - Math.log(ZOOM_MIN))
const sliderToZoom = (s) => Math.exp(Math.log(ZOOM_MIN) + s * (Math.log(ZOOM_MAX) - Math.log(ZOOM_MIN)))

// ── TimelineControls（官方代码，几乎不改） ──
const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2]

const TimelineControls = memo(function TimelineControls({ timelineRef }) {
  const engine = useTimelineEngine()
  const playback = usePlaybackEngine()
  const { invalidateTimeline } = useProject()
  const isPlaying = usePlaybackStore((s) => s.isPlaying)
  const togglePlayPause = usePlaybackStore((s) => s.togglePlayPause)
  const zoom = usePlaybackStore((s) => s.zoom)
  const setZoom = usePlaybackStore((s) => s.setZoom)
  const totalFrames = useTracksStore((s) => s.totalFrames)
  const stage = useTracksStore((s) => s.stage)
  const hasSelection = useSelectionStore((s) => s.selectedClipIds.size === 1)
  const timecodeRef = useRef(null)

  // 原声主镜头静音开关（控制音频轨，直接从 engine 读）
  const mainMuted = (() => {
    const track = engine.getProject().tracks.find(t => t.name === '原声主镜头 音频')
    return track?.muted ?? false
  })()
  const toggleMainMute = useCallback(() => {
    const track = engine.getProject().tracks.find(t => t.name === '原声主镜头 音频')
    if (!track) return
    engine.updateTrack(track.id, { muted: !track.muted })
  }, [engine])

  useEffect(() => {
    return usePlaybackStore.subscribe((state) => {
      if (timecodeRef.current) {
        const dur = Math.max(totalFrames, 1)
        timecodeRef.current.textContent =
          `${framesToTimecode(state.currentFrame, FPS)} / ${framesToTimecode(dur, FPS)}`
      }
    })
  }, [totalFrames])

  useEffect(() => {
    if (timecodeRef.current) {
      const frame = usePlaybackStore.getState().currentFrame
      const dur = Math.max(totalFrames, 1)
      timecodeRef.current.textContent =
        `${framesToTimecode(frame, FPS)} / ${framesToTimecode(dur, FPS)}`
    }
  }, [totalFrames])

  const splitAtPlayhead = useCallback(() => {
    const result = splitClipAtPlayhead(engine)
    if (!result.ok) console.warn('[vibecap] split failed:', result.reason)
  }, [engine])

  const aspectActive = (w, h) => Math.abs(stage.width / stage.height - w / h) < 0.001
  const aspectBtn = (active) => ({ ...btnDisabled(false), minWidth: 44, padding: '5px 10px', ...(active ? { background: 'rgba(225, 29, 72, 0.12)', border: `1px solid ${theme.accent}`, color: theme.accentHover, boxShadow: `0 0 10px rgba(225, 29, 72, 0.35)` } : {}) })

  const playBtnStyle = {
    ...btnDisabled(false),
    minWidth: 36,
    padding: '5px 12px',
    ...(isPlaying ? { background: 'rgba(34, 197, 94, 0.12)', border: `1px solid ${theme.success}`, color: theme.success } : {}),
  }

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr auto 1fr',
        alignItems: 'center',
        height: 40,
        padding: '0 16px',
        background: theme.bgSecondary,
        borderTop: `1px solid ${theme.border}`,
        flexShrink: 0,
      }}
    >
      {/* 左侧：轨道操作 + Split */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <button type="button" className="elah-toolbar-btn" style={btnDisabled(false)} onClick={() => {
          // Elah addTrack('video') 限制只能有一条视频轨，改用直接写入
          const track = { id: generateId(), name: '视频轨', kind: 'video', order: engine.getProject().tracks.length, height: 44, locked: false, disabled: false, muted: false, solo: false }
          engine.getProject().tracks.push(track)
          engine.getProject().clips[track.id] = []
          engine.loadProject(engine.getProject())
        }} title="添加视频轨道">
          ＋ 视频轨
        </button>
        <button type="button" className="elah-toolbar-btn" style={btnDisabled(false)} onClick={() => engine.addTrack('audio', { name: '音频轨' })} title="添加音频轨道">
          ＋ 音频轨
        </button>
        <div style={{ width: 1, height: 18, background: theme.border, flexShrink: 0, margin: '0 4px' }} />
        <button type="button" className="elah-toolbar-btn" style={btnDisabled(!hasSelection)} disabled={!hasSelection} onClick={splitAtPlayhead} title="在播放头处分割 (S)">
          ✂ Split
        </button>
        <button type="button" className="elah-toolbar-btn"
          style={mainMuted ? { ...btnDisabled(false), background: 'rgba(225, 29, 72, 0.12)', border: `1px solid ${theme.accent}`, color: theme.accentHover } : btnDisabled(false)}
          onClick={toggleMainMute} title={mainMuted ? '原声已静音，点击恢复' : '原声播放中，点击静音'}>
          {mainMuted ? '🔇 原声' : '🔊 原声'}
        </button>
        <button type="button" className="elah-toolbar-btn" style={btnDisabled(false)}
          onClick={() => invalidateTimeline()}
          title="从原始数据重建时间线">
          🔄 刷新
        </button>
      </div>

      {/* 中间：播放 + 时间码 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button type="button" className="elah-toolbar-btn" style={playBtnStyle} onClick={togglePlayPause} title="Play / Pause (Space)">
          {isPlaying ? '⏸' : '▶'}
        </button>
        <select
          value={playback.playbackRate}
          onChange={(e) => playback.setPlaybackRate(Number(e.target.value))}
          style={{
            ...btnBase, fontSize: 11, padding: '4px 6px', cursor: 'pointer',
            fontFamily: theme.fontMono, minWidth: 56, textAlign: 'center',
            appearance: 'none', WebkitAppearance: 'none',
          }}
          title="播放速度"
        >
          {SPEEDS.map(s => (
            <option key={s} value={s}>{s}x</option>
          ))}
        </select>
        <span ref={timecodeRef} style={{ fontSize: 11, color: theme.textSecondary, fontFamily: theme.fontMono, minWidth: 172, letterSpacing: '0.02em' }}>
          00:00:00:00 / 00:00:00:00
        </span>
      </div>

      {/* 右侧：zoom + aspect */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}>
        <span style={{ fontSize: 11, color: theme.textMuted }}>Zoom</span>
        <input type="range" className="elah-range" min={0} max={1} step={0.001} value={zoomToSlider(zoom)} onChange={(e) => setZoom(sliderToZoom(Number(e.target.value)))} style={{ width: 96 }} />
        <span style={{ fontSize: 11, color: theme.textMuted, fontFamily: theme.fontMono, minWidth: 56 }}>
          {zoom < 1 ? zoom.toFixed(2) : zoom.toFixed(1)} px/f
        </span>
        <button type="button" className="elah-toolbar-btn" style={btnDisabled(false)} onClick={() => timelineRef.current?.fitToWindow()} title="Zoom to fit timeline">
          Fit
        </button>

        <div style={{ width: 1, height: 18, background: theme.border, flexShrink: 0, margin: '0 8px' }} />

        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <button type="button" className="elah-toolbar-btn" style={aspectBtn(aspectActive(1920, 1080))} onClick={() => engine.setStage(1920, 1080)}>16:9</button>
          <button type="button" className="elah-toolbar-btn" style={aspectBtn(aspectActive(1080, 1920))} onClick={() => engine.setStage(1080, 1920)}>9:16</button>
          <button type="button" className="elah-toolbar-btn" style={aspectBtn(aspectActive(1080, 1080))} onClick={() => engine.setStage(1080, 1080)}>1:1</button>
        </div>

      </div>
    </div>
  )
})

// ── 素材面板（Video/Audio 切换 Tab） ──
function MediaTabs() {
  const [tab, setTab] = useState('video')
  const { assets } = useMediaLibrary()
  const videoAssets = useMemo(() => assets.filter(a => a.kind === 'video'), [assets])
  const audioAssets = useMemo(() => assets.filter(a => a.kind === 'audio'), [assets])
  const list = tab === 'video' ? videoAssets : audioAssets

  return (
    <div className="flex flex-col h-full bg-transparent">
      {/* Tab 切换 */}
      <div className="flex border-b border-ed-border shrink-0">
        {[
          ['video', '视频', videoAssets.length],
          ['audio', '音频', audioAssets.length],
        ].map(([key, label, count]) => (
          <button key={key} onClick={() => setTab(key)}
            style={{
              flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
              padding: '8px 0', fontSize: 11, fontWeight: 500, cursor: 'pointer',
              border: 'none', background: tab === key ? theme.bgElevated : 'transparent',
              color: tab === key ? theme.textPrimary : theme.textMuted,
              borderBottom: tab === key ? `2px solid ${theme.accent}` : '2px solid transparent',
              marginBottom: -1, transition: 'all 0.15s',
            }}
          >
            {label}
            <span style={{ fontSize: 10, color: theme.textMuted }}>{count}</span>
          </button>
        ))}
      </div>

      {/* 素材列表（仿 AssetPanel 卡片样式） */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {list.length === 0 ? (
          <div className="p-4 text-center text-[11px] text-ed-text-muted">暂无素材</div>
        ) : (
          list.map(asset => (
            <div key={asset.id} draggable
              className="flex items-center gap-[10px] px-[10px] py-2 cursor-grab select-none bg-ed-card border-b border-ed-border-subtle hover:bg-ed-bg-elevated transition-all duration-150"
              onDragStart={(e) => {
                e.dataTransfer.setData('application/x-elah-media', JSON.stringify({ kind: 'media-asset', assetId: asset.id }))
              }}
            >
              <div className="relative shrink-0 bg-ed-bg rounded-sm border border-ed-border-subtle overflow-hidden flex items-center justify-center" style={{ width: 52, height: 52 }}>
                {asset.thumbnailUrl ? (
                  <img src={asset.thumbnailUrl} alt="" draggable={false} className="w-full h-full object-cover" />
                ) : asset.kind === 'audio' ? (
                  <img src="/audio-wave.svg" alt="" draggable={false} className="w-full h-full object-cover" />
                ) : (
                  <span className="text-xl text-ed-text-muted">▶</span>
                )}
              </div>
              <div className="flex flex-col gap-[3px] min-w-0">
                <span className="text-[11px] text-ed-text overflow-hidden text-ellipsis whitespace-nowrap">{asset.name}</span>
                <div className="flex items-center gap-[6px]">
                  <span className="text-[8px] font-bold tracking-[0.06em] px-[5px] py-[2px] rounded-sm"
                    style={{ color: 'var(--elah-tag-video-fg)', background: 'var(--elah-tag-video-bg)' }}>
                    {asset.kind === 'video' ? 'VIDEO' : 'AUDIO'}
                  </span>
                  <span className="text-[10px] text-ed-text-muted font-mono">{asset.durationSec.toFixed(0)}s</span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ── 视频/音频 clip 联动同步（类似剪映"链接"功能）──
// 直接 patch engine 方法，batch 合并双方操作为一次 undo
function installLinkedClips(engine) {
  const origUpdateClip = engine.updateClip.bind(engine)
  const origMoveClip = engine.moveClip.bind(engine)
  const origTrimClip = engine.trimClip.bind(engine)
  const origRemoveClip = engine.removeClip.bind(engine)
  const origSplitClip = engine.splitClip.bind(engine)
  const origPreviewClip = engine.previewClip.bind(engine)

  const SYNC_KEYS = ['startFrame', 'durationFrames', 'sourceStartFrame', 'sourceDurationFrames']

  function partnerOf(clipId) {
    const pid = linkedPairs.get(clipId)
    if (!pid) return null
    const info = engine.findClip(pid)
    if (!info) { linkedPairs.delete(clipId); return null }
    return { id: pid, trackId: info.trackId }
  }

  // moveClip — 拖动 clip 换位置
  engine.moveClip = function (clipId, fromTrackId, toTrackId, startFrame) {
    const p = partnerOf(clipId)
    if (!p) return origMoveClip(clipId, fromTrackId, toTrackId, startFrame)
    engine.batch(() => {
      origMoveClip(clipId, fromTrackId, toTrackId, startFrame)
      origMoveClip(p.id, p.trackId, p.trackId, startFrame)
    })
  }

  // trimClip — 拖拽 clip 边缘裁剪
  engine.trimClip = function (clipId, trackId, startFrame, durationFrames) {
    const p = partnerOf(clipId)
    if (!p) return origTrimClip(clipId, trackId, startFrame, durationFrames)
    engine.batch(() => {
      origTrimClip(clipId, trackId, startFrame, durationFrames)
      origTrimClip(p.id, p.trackId, startFrame, durationFrames)
    })
  }

  // previewClip — 拖动过程中的实时预览（拖动时调用此方法，不是 moveClip）
  engine.previewClip = function (clipId, trackId, updates) {
    origPreviewClip(clipId, trackId, updates)
    const p = partnerOf(clipId)
    if (p) {
      const sync = {}
      for (const k of SYNC_KEYS) { if (k in updates) sync[k] = updates[k] }
      if (Object.keys(sync).length > 0) origPreviewClip(p.id, p.trackId, sync)
    }
  }

  // updateClip — 通用属性更新（属性面板修改等）
  engine.updateClip = function (clipId, trackId, updates) {
    const p = partnerOf(clipId)
    if (!p) return origUpdateClip(clipId, trackId, updates)
    const sync = {}
    for (const k of SYNC_KEYS) { if (k in updates) sync[k] = updates[k] }
    if (Object.keys(sync).length === 0) return origUpdateClip(clipId, trackId, updates)
    engine.batch(() => {
      origUpdateClip(clipId, trackId, updates)
      origUpdateClip(p.id, p.trackId, sync)
    })
  }

  // removeClip — 删除
  engine.removeClip = function (clipId, trackId) {
    const p = partnerOf(clipId)
    if (!p) return origRemoveClip(clipId, trackId)
    engine.batch(() => {
      origRemoveClip(clipId, trackId)
      origRemoveClip(p.id, p.trackId)
    })
    unlinkClipPair(clipId)
  }

  // splitClip — 分割（Split 按钮 / 快捷键）
  engine.splitClip = function (clipId, trackId, atFrame) {
    const p = partnerOf(clipId)
    if (!p) return origSplitClip(clipId, trackId, atFrame)
    let vR = null, aR = null
    engine.batch(() => {
      vR = origSplitClip(clipId, trackId, atFrame)
      aR = origSplitClip(p.id, p.trackId, atFrame)
    })
    if (vR && aR) {
      unlinkClipPair(clipId); unlinkClipPair(p.id)
      linkClipPair(vR[0], aR[0]); linkClipPair(vR[1], aR[1])
    }
    return vR
  }
}

function ClipLinker() {
  const engine = useTimelineEngine()
  const installed = useRef(false)

  useEffect(() => {
    if (installed.current) return
    installed.current = true
    installLinkedClips(engine)
  }, [engine])

  return null
}

// ── 数据持久化（加载 + 自动保存，使用统一 ProjectContext） ──
function DataLoader({ timelineRef }) {
  const engine = useTimelineEngine()
  const { project: vibeProject, saveTimelineCache } = useProject()
  const didLoad = useRef(false)
  const saveTimer = useRef(null)

  // 加载：从统一 project 读取 picks 和缓存
  // 当 timeline 被清空（用户点刷新或 picks 变更）时自动重建
  useEffect(() => {
    if (didLoad.current && vibeProject.timeline) return
    const picks = vibeProject.picks || {}
    const hasCache = vibeProject.timeline && vibeProject.mediaCache

    if (hasCache) {
      // 有缓存 → 恢复时间线编辑
      engine.loadProject(vibeProject.timeline)
      const { assets, order } = vibeProject.mediaCache
      const store = useMediaLibraryStore.getState()
      for (const id of order) {
        if (assets[id] && !store.assets[id]) store.addAsset(assets[id])
      }
    } else {
      // 无缓存 → 从 picks 重建
      linkedPairs.clear()  // 清除旧联动映射
      // 清除旧素材（每次用 getState() 取最新 state，避免 zustand 快照过期）
      for (const id of [...useMediaLibraryStore.getState().order]) {
        useMediaLibraryStore.getState().removeAsset(id)
      }

      if (Object.keys(picks).length > 0) {
        const { project: elahProject, mediaList } = buildProjectFromPicks(picks)
        engine.loadProject(elahProject)
        // 添加素材：每次用 getState() 做重复检查，防止 StrictMode 双重挂载时
        // 缓存的 store 快照残留上一次挂载的数据导致全部 skip
        for (const item of mediaList) {
          const curAssets = useMediaLibraryStore.getState().assets
          if (curAssets[item.assetId]) continue
          useMediaLibraryStore.getState().addAsset({
            id: item.assetId, kind: item.kind, name: item.name, src: item.src,
            durationSec: item.durationSec ?? 3, width: 1920, height: 1080,
            byteSize: 0, lastModified: Date.now(), addedAt: Date.now(),
            thumbnailUrl: item.thumbnailUrl,
            waveform: item.waveform,
          })
        }
      } else {
        // picks 为空 → 清空
        engine.loadProject({ id: 'vibecap-empty', fps: FPS, stage: STAGE, tracks: [], clips: {}, transitions: [], version: 1 })
        for (const id of [...useMediaLibraryStore.getState().order]) {
          useMediaLibraryStore.getState().removeAsset(id)
        }
      }
    }
    didLoad.current = true
    // 时间线数据加载完成后自动缩放至适配窗口
    setTimeout(() => timelineRef?.current?.fitToWindow(), 100)
  }, [engine, vibeProject.picks, vibeProject.timeline])

  // 自动保存
  useEffect(() => {
    const save = () => {
      clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(() => {
        const elahProject = engine.getProject()
        const mediaState = useMediaLibraryStore.getState()
        saveTimelineCache(elahProject, { assets: mediaState.assets, order: mediaState.order })
      }, 300)
    }
    engine.on('change', save)
    engine.on('history:change', save)
    return () => {
      engine.off('change', save)
      engine.off('history:change', save)
      clearTimeout(saveTimer.current)
    }
  }, [engine, saveTimelineCache])

  return null
}

// ═══════════════════════════════════════════════
// 主组件 — 移植自官方 ProductionEditor，仅改数据入口
// ═══════════════════════════════════════════════
export default function TimelinePage() {
  const timelineRef = useRef(null)
  const demuxerFactoryRef = useRef(null)
  const [timelineHeight, setTimelineHeight] = useState(280)
  const dragRef = useRef(null)

  if (!demuxerFactoryRef.current) {
    try { demuxerFactoryRef.current = createDefaultDemuxerFactory() } catch (e) { console.warn('[VIBECAP] mediabunny init failed:', e) }
  }

  // 拖拽调整时间线高度
  const startHRef = useRef(280)
  const onDragStart = useCallback((e) => {
    e.preventDefault()
    startHRef.current = timelineHeight
    const startY = e.clientY
    const onMove = (ev) => {
      setTimelineHeight(Math.max(120, Math.min(600, startHRef.current + (startY - ev.clientY))))
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [])

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <EditorProvider fps={FPS} defaultTrackHeight={36} stage={STAGE}>
        <DataLoader timelineRef={timelineRef} />
        <ClipLinker />
        <div className="elah-root" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
          <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
            {/* 左侧栏 */}
            <div style={{
              display: 'flex', flexDirection: 'column',
              width: 220, flexShrink: 0,
              borderRight: `1px solid ${theme.border}`,
              background: theme.bgPanel,
              minHeight: 0, overflow: 'hidden',
            }}>
              <MediaTabs />
            </div>

            {/* 中央区域：Preview + 拖拽条 + Timeline */}
            <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
              {/* Preview — 自动填充剩余空间 */}
              <div style={{ flex: 1, minHeight: 0, position: 'relative', background: '#000' }}>
                {demuxerFactoryRef.current && (
                  <Preview demuxerFactory={demuxerFactoryRef.current} style={{ width: '100%', height: '100%' }} />
                )}
              </div>

              {/* 拖拽手柄 */}
              <div
                ref={dragRef}
                onMouseDown={onDragStart}
                style={{
                  height: 6, cursor: 'ns-resize',
                  background: theme.border,
                  borderTop: `1px solid ${theme.borderSubtle}`,
                  borderBottom: `1px solid ${theme.borderSubtle}`,
                  flexShrink: 0,
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = theme.accent}
                onMouseLeave={e => e.currentTarget.style.background = theme.border}
              />

              {/* TimelineControls + Timeline */}
              <div style={{ height: timelineHeight, flexShrink: 0, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <TimelineControls timelineRef={timelineRef} />
                <Timeline ref={timelineRef} fps={FPS} sidebarWidth={160} style={{ flex: 1, minHeight: 0, minWidth: 0 }} />
              </div>
            </div>
          </div>
        </div>
      </div>
      </EditorProvider>
    </div>
  )
}
