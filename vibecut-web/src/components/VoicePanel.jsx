/**
 * 配音面板 — 编辑台右侧
 * 轻量配音：选音色 → 逐段生成 / 一键全部 → 试听
 * 复用后端 /voiceover/generate_stream（全量）+ /voiceover/regenerate_segment（单段）。
 * 产物契约：narr_{seg_id:03d}.wav + segments.json 反写 audio_duration/audio_path（分镜台消费）。
 */
import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { colors, font as baseFont } from '../styles/theme'
import { flexRow, panelHeader, panelRoot, title, btn, card, select as selectStyle, label } from '../styles/mixins'

const F = { xs: 13, sm: 14, md: 15, lg: 16, xl: 18, mono: baseFont.mono }

const S = {
  border: `1px solid ${colors.border}`, borderSubtle: `1px solid ${colors.borderSubtle}`,
  bgPanel: colors.bg, bgCard: colors.bgCard, text: colors.text,
  purple: colors.purple, purpleBg: colors.purpleBg, green: colors.green,
  greenBg: colors.greenBg, greenLight: colors.greenLight,
  red: colors.red, gold: colors.gold, blue: colors.blue,
  textMuted: colors.textMuted, textFaint: colors.textFaint, textDim: colors.textDim,
  flexRow: flexRow(), panelHeader: panelHeader(),
  headerTitle: { ...title(), fontSize: F.lg },
  headerBtn: (a) => ({ ...btn(a ? 'primary' : 'default', 'md'), fontSize: F.sm }),
}

// 预设音色（与后端 tts_engine.PRESET_VOICES 保持一致）
const PRESET_VOICES = [
  { id: '冰糖', label: '冰糖 · 活泼少女' },
  { id: '茉莉', label: '茉莉 · 知性女声' },
  { id: '苏打', label: '苏打 · 阳光少年' },
  { id: '白桦', label: '白桦 · 成熟男声' },
]

function audioUrl(path, taskId) {
  const name = (path || '').split('/').pop()
  return `/tts_segments/${name}?task=${encodeURIComponent(taskId)}&t=${Date.now()}`
}

export default function VoicePanel({ taskId, segments }) {
  const [voice, setVoice] = useState('白桦')

  // 只配音有 narration_text 的段（原声/dialogue 段跳过）
  const narrSegs = useMemo(() => (segments || []).filter(s => (s.narration_text || '').trim()), [segments])

  // 初始 ttsState：从 segments 的 audio_duration/audio_path 恢复
  const initialTts = useMemo(() => {
    const m = {}
    for (const s of narrSegs) {
      const sid = s.seg_id
      const path = s.audio_path || `tts_segments/narr_${String(sid).padStart(3, '0')}.wav`
      if (s.audio_duration) {
        m[sid] = { status: 'ready', audioPath: path, duration: s.audio_duration }
      } else {
        m[sid] = { status: 'pending', audioPath: path, duration: null }
      }
    }
    return m
  }, [narrSegs])

  const [ttsState, setTtsState] = useState(initialTts)
  const [generating, setGenerating] = useState(false)        // 全量生成中
  const [regeneratingSegs, setRegeneratingSegs] = useState(new Set())
  const [progress, setProgress] = useState({ done: 0, total: 0 })
  const [playingIdx, setPlayingIdx] = useState(null)
  const audioRefs = useRef({})

  // 当 segments 变化时（如重新导入/编辑），刷新 ttsState
  useEffect(() => { setTtsState(initialTts) }, [initialTts])

  // unmount 清理 audio
  useEffect(() => () => {
    Object.values(audioRefs.current).forEach(a => { try { a.pause(); a.src = '' } catch {} })
  }, [])

  const handlePlay = useCallback((sid, path) => {
    if (playingIdx === sid) {
      if (audioRefs.current[sid]) { audioRefs.current[sid].pause(); audioRefs.current[sid].currentTime = 0 }
      setPlayingIdx(null)
      return
    }
    if (audioRefs.current[playingIdx]) { audioRefs.current[playingIdx].pause(); audioRefs.current[playingIdx].currentTime = 0 }
    const audio = new Audio(audioUrl(path, taskId))
    audioRefs.current[sid] = audio
    audio.onended = () => setPlayingIdx(null)
    audio.onerror = () => setPlayingIdx(null)
    audio.play().catch(() => setPlayingIdx(null))
    setPlayingIdx(sid)
  }, [playingIdx, taskId])

  // 单段生成（复用 /voiceover/regenerate_segment，跳过配音师）
  const generateOne = useCallback(async (sid) => {
    if (generating || regeneratingSegs.has(sid)) return
    setRegeneratingSegs(prev => new Set(prev).add(sid))
    setTtsState(prev => ({ ...prev, [sid]: { ...prev[sid], status: 'generating' } }))
    try {
      const resp = await fetch('/voiceover/regenerate_segment', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: taskId, seg_id: sid, voice }),
      })
      const reader = resp.body.getReader(); const decoder = new TextDecoder()
      let buf = ''; let ev = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n'); buf = lines.pop() || ''
        for (const line of lines) {
          const t = line.trim()
          if (t.startsWith('event: ')) { ev = t.slice(7); continue }
          if (!t.startsWith('data: ')) continue
          try {
            const d = JSON.parse(t.slice(6))
            if (ev === 'progress' && d.step === 'segment_done') {
              setTtsState(prev => ({ ...prev, [sid]: { status: 'ready', audioPath: d.audio_path || `tts_segments/narr_${String(sid).padStart(3, '0')}.wav`, duration: d.duration } }))
            } else if (ev === 'error') {
              setTtsState(prev => ({ ...prev, [sid]: { ...prev[sid], status: prev[sid]?.duration ? 'ready' : 'pending' } }))
            }
          } catch {}
        }
      }
    } catch {
      setTtsState(prev => ({ ...prev, [sid]: { ...prev[sid], status: prev[sid]?.duration ? 'ready' : 'pending' } }))
    } finally {
      setRegeneratingSegs(prev => { const n = new Set(prev); n.delete(sid); return n })
    }
  }, [taskId, voice, generating, regeneratingSegs])

  // 一键生成全部（复用 /voiceover/generate_stream）
  const generateAll = useCallback(async () => {
    if (generating || !narrSegs.length) return
    setGenerating(true)
    setProgress({ done: 0, total: narrSegs.length })
    // 标记所有待生成段
    setTtsState(prev => {
      const n = { ...prev }
      for (const s of narrSegs) if (!n[s.seg_id]?.duration) n[s.seg_id] = { ...n[s.seg_id], status: 'generating' }
      return n
    })
    try {
      const resp = await fetch('/voiceover/generate_stream', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: taskId, voice, speed: 1.0, pause_ms: 300 }),
      })
      const reader = resp.body.getReader(); const decoder = new TextDecoder()
      let buf = ''; let ev = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n'); buf = lines.pop() || ''
        for (const line of lines) {
          const t = line.trim()
          if (t.startsWith('event: ')) { ev = t.slice(7); continue }
          if (!t.startsWith('data: ')) continue
          try {
            const d = JSON.parse(t.slice(6))
            if (ev === 'progress' && d.step === 'segment_start' && d.seg_id != null) {
              setTtsState(prev => ({ ...prev, [d.seg_id]: { ...prev[d.seg_id], status: 'generating' } }))
            } else if (ev === 'progress' && d.step === 'segment_done' && d.seg_id != null) {
              setTtsState(prev => ({ ...prev, [d.seg_id]: { status: 'ready', audioPath: `tts_segments/narr_${String(d.seg_id).padStart(3, '0')}.wav`, duration: d.duration } }))
              setProgress({ done: d.done, total: d.total })
            }
          } catch {}
        }
      }
    } catch {}
    finally { setGenerating(false) }
  }, [generating, narrSegs, taskId, voice])

  const readyCount = Object.values(ttsState).filter(s => s.status === 'ready').length
  const totalDuration = Object.values(ttsState).reduce((sum, s) => sum + (s.duration || 0), 0)

  return (
    <div style={{ ...panelRoot(), borderRight: 'none' }}>
      <div style={S.panelHeader}>
        <span style={S.headerTitle}>🎙️ 配音</span>
        <span style={{ fontSize: F.xs, color: colors.textFaint }}>{readyCount}/{narrSegs.length} 已生成</span>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 8 }}>
        {/* 音色选择 */}
        <div style={{ ...card(), marginBottom: 8 }}>
          <div style={{ ...label(), marginBottom: 4 }}>音色</div>
          <select value={voice} onChange={e => setVoice(e.target.value)}
            style={{ ...selectStyle(), width: '100%', padding: '4px 6px', fontSize: F.xs }}>
            {PRESET_VOICES.map(v => <option key={v.id} value={v.id}>{v.label}</option>)}
          </select>
        </div>

        {/* 一键全部 */}
        <button onClick={generateAll} disabled={generating || !narrSegs.length}
          style={{ ...S.headerBtn(generating || !narrSegs.length ? false : true), width: '100%', marginBottom: 8 }}>
          {generating ? `🔄 生成中 ${progress.done}/${progress.total}` : '🎙️ 一键生成全部'}
        </button>

        {/* 段落列表 */}
        {narrSegs.length === 0 ? (
          <div style={{ textAlign: 'center', color: colors.textFaint, fontSize: F.xs, padding: 20 }}>
            暂无可配音段（无 narration_text）
          </div>
        ) : (
          narrSegs.map(s => {
            const sid = s.seg_id
            const st = ttsState[sid] || { status: 'pending', audioPath: `tts_segments/narr_${String(sid).padStart(3, '0')}.wav` }
            const isReady = st.status === 'ready'
            const isGenerating = st.status === 'generating'
            const isPlaying = playingIdx === sid
            return (
              <div key={sid} style={{ ...card({ active: isReady }), marginBottom: 6, opacity: isReady ? 1 : 0.75 }}>
                <div style={{ ...S.flexRow, marginBottom: 4 }}>
                  <span style={{ fontSize: F.xs, fontFamily: 'monospace', color: colors.textFaint, background: colors.bgHover, padding: '0 4px', borderRadius: 3 }}>S{sid}</span>
                  {isGenerating && <span style={{ fontSize: F.xs, color: colors.gold }}>🔄 生成中</span>}
                  {isReady && <span style={{ fontSize: F.xs, color: colors.greenLight, fontWeight: 600 }}>✅ {st.duration?.toFixed(1)}s</span>}
                  {!isReady && !isGenerating && <span style={{ fontSize: F.xs, color: colors.textFaint }}>⏳ 待生成</span>}
                </div>
                <div style={{ fontSize: F.xs, color: isReady ? colors.textDim : colors.textFaint, lineHeight: 1.5, marginBottom: 6 }}>
                  {s.narration_text.length > 60 ? s.narration_text.slice(0, 60) + '…' : s.narration_text}
                </div>
                <div style={{ ...S.flexRow }}>
                  {isReady && (
                    <button onClick={() => handlePlay(sid, st.audioPath)}
                      style={btn(isPlaying ? 'danger' : 'success', 'xs')}>
                      {isPlaying ? '⏹ 停止' : '▶ 播放'}
                    </button>
                  )}
                  <button onClick={() => generateOne(sid)}
                    disabled={generating || regeneratingSegs.has(sid)}
                    style={btn(generating || regeneratingSegs.has(sid) ? 'disabled' : 'ghost', 'xs')}>
                    {regeneratingSegs.has(sid) ? '🔄…' : isReady ? '🔄 重生成' : '🎙 生成'}
                  </button>
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* 底部合计 */}
      {narrSegs.length > 0 && (
        <div style={{ padding: '6px 8px', borderTop: S.borderSubtle, fontSize: F.xs, color: colors.textFaint }}>
          总时长 {totalDuration.toFixed(1)}s · {narrSegs.length} 段
        </div>
      )}
    </div>
  )
}
