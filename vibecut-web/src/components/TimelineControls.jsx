/**
 * 共享的时间轴控制栏
 * 从 Timeline.jsx 提取，供 VibeEdit 和 Timeline 页面复用
 */
import { memo, useRef, useEffect, useCallback } from 'react'
import {
  useTimelineEngine, usePlaybackEngine, usePlaybackStore,
  useTracksStore, useSelectionStore,
  splitClipAtPlayhead, framesToTimecode, generateId,
} from '@elah/editor'
import { useProject } from '../context/ProjectContext'

const FPS = 25
const theme = {
  bgSecondary: '#0D1017',
  bgElevated: '#171D2B',
  border: '#232938',
  textPrimary: '#F3F4F6',
  textSecondary: '#A7AFBF',
  textMuted: '#6B7280',
  accent: '#E11D48',
  accentHover: '#FB7185',
  success: '#22C55E',
}

const btnBase = {
  padding: '6px 12px',
  background: theme.bgElevated,
  color: theme.textSecondary,
  border: `1px solid ${theme.border}`,
  borderRadius: 6,
  fontSize: 12,
  cursor: 'pointer',
  fontFamily: 'system-ui, sans-serif',
  transition: 'background 0.15s, border-color 0.15s, color 0.15s',
}

const btnDisabled = (d) => d
  ? { ...btnBase, background: '#121722', color: theme.textMuted, cursor: 'not-allowed', opacity: 0.6 }
  : btnBase

const ZOOM_MIN = 0.02
const ZOOM_MAX = 50
const zoomToSlider = (z) => (Math.log(z) - Math.log(ZOOM_MIN)) / (Math.log(ZOOM_MAX) - Math.log(ZOOM_MIN))
const sliderToZoom = (s) => Math.exp(Math.log(ZOOM_MIN) + s * (Math.log(ZOOM_MAX) - Math.log(ZOOM_MIN)))
const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2]

const TimelineControls = memo(function TimelineControls({ timelineRef, showRebuild = true, showTrackButtons = true }) {
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
    if (!result.ok) console.warn('[vibecut] split failed:', result.reason)
  }, [engine])

  const aspectActive = (w, h) => Math.abs((stage?.width || 1920) / (stage?.height || 1080) - w / h) < 0.001
  const aspectBtn = (active) => ({
    ...btnDisabled(false), minWidth: 44, padding: '5px 10px',
    ...(active ? { background: 'rgba(225,29,72,0.12)', border: `1px solid ${theme.accent}`, color: theme.accentHover } : {})
  })

  const playBtnStyle = {
    ...btnDisabled(false), minWidth: 36, padding: '5px 12px',
    ...(isPlaying ? { background: 'rgba(34,197,94,0.12)', border: `1px solid ${theme.success}`, color: theme.success } : {}),
  }

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center',
      height: 40, padding: '0 16px', background: theme.bgSecondary,
      borderTop: `1px solid ${theme.border}`, flexShrink: 0,
    }}>
      {/* 左侧 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {showTrackButtons && (
          <>
            <button type="button" className="elah-toolbar-btn" style={btnDisabled(false)} onClick={() => engine.addTrack('video', { name: '视频轨' })} title="添加视频轨道">＋ 视频轨</button>
            <button type="button" className="elah-toolbar-btn" style={btnDisabled(false)} onClick={() => engine.addTrack('audio', { name: '音频轨' })} title="添加音频轨道">＋ 音频轨</button>
            <div style={{ width: 1, height: 18, background: theme.border, flexShrink: 0, margin: '0 4px' }} />
          </>
        )}
        <button type="button" className="elah-toolbar-btn" style={btnDisabled(!hasSelection)} disabled={!hasSelection} onClick={splitAtPlayhead} title="在播放头处分割 (S)">✂ Split</button>
        <button type="button" className="elah-toolbar-btn"
          style={mainMuted ? { ...btnDisabled(false), background: 'rgba(225,29,72,0.12)', border: `1px solid ${theme.accent}`, color: theme.accentHover } : btnDisabled(false)}
          onClick={toggleMainMute}>{mainMuted ? '🔇 原声' : '🔊 原声'}</button>
        {showRebuild && (
          <button type="button" className="elah-toolbar-btn" style={btnDisabled(false)} onClick={() => invalidateTimeline()} title="重建时间线">🔄 刷新</button>
        )}
      </div>

      {/* 中间 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button type="button" className="elah-toolbar-btn" style={playBtnStyle} onClick={togglePlayPause} title="Play/Pause (Space)">{isPlaying ? '⏸' : '▶'}</button>
        <select value={playback.playbackRate} onChange={(e) => playback.setPlaybackRate(Number(e.target.value))}
          style={{ ...btnBase, fontSize: 11, padding: '4px 6px', cursor: 'pointer', fontFamily: 'monospace', minWidth: 56, textAlign: 'center', appearance: 'none', WebkitAppearance: 'none' }}>
          {SPEEDS.map(s => <option key={s} value={s}>{s}x</option>)}
        </select>
        <span ref={timecodeRef} style={{ fontSize: 11, color: theme.textSecondary, fontFamily: 'monospace', minWidth: 172 }}>00:00:00:00 / 00:00:00:00</span>
      </div>

      {/* 右侧 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end' }}>
        <span style={{ fontSize: 11, color: theme.textMuted }}>Zoom</span>
        <input type="range" className="elah-range" min={0} max={1} step={0.001} value={zoomToSlider(zoom)} onChange={(e) => setZoom(sliderToZoom(Number(e.target.value)))} style={{ width: 96 }} />
        <span style={{ fontSize: 11, color: theme.textMuted, fontFamily: 'monospace', minWidth: 56 }}>{zoom < 1 ? zoom.toFixed(2) : zoom.toFixed(1)} px/f</span>
        <button type="button" className="elah-toolbar-btn" style={btnDisabled(false)} onClick={() => timelineRef.current?.fitToWindow()} title="适应窗口">Fit</button>
        <div style={{ width: 1, height: 18, background: theme.border, flexShrink: 0, margin: '0 8px' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          {[[1920,1080,'16:9'],[1080,1920,'9:16'],[1080,1080,'1:1']].map(([w,h,label]) => (
            <button key={label} type="button" className="elah-toolbar-btn" style={aspectBtn(aspectActive(w,h))} onClick={() => engine.setStage(w,h)}>{label}</button>
          ))}
        </div>
      </div>
    </div>
  )
})

export default TimelineControls
