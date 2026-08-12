/**
 * 配音台 v1 — AI 解说语音生成
 * 三栏：音色库 | 脚本段落 | 全局控制
 *
 * 流水线位置: 编剧台 → 配音台 → 分镜台
 * 核心: 配音师Agent (VoiceDirector) 设计配音方案 → MiMo TTS 逐段生成
 */
import { useState, useEffect, useCallback, useRef, memo } from 'react'
import { useParams } from 'react-router-dom'
import { colors, space, font, radius } from '../styles/theme'
import { flexRow, flexCol, panelHeader, panelRoot, title, subtitle, label, mono, btn, card, divider as dividerStyle } from '../styles/mixins'

const F = { xs: 13, sm: 14, md: 15, lg: 16, xl: 18, mono: font.mono }

const S = {
  border: `1px solid ${colors.border}`, borderSubtle: `1px solid ${colors.borderSubtle}`,
  bgPanel: colors.bg, bgCard: colors.bgCard, text: colors.text,
  purple: colors.purple, purpleBg: colors.purpleBg, green: colors.green,
  greenBg: colors.greenBg, greenLight: colors.greenLight,
  red: colors.red, redLight: colors.redLight, redBg: colors.redBg,
  gold: colors.gold, goldBg: colors.goldBg, blue: colors.blue, blueBg: colors.blueBg,
  textMuted: colors.textMuted, textFaint: colors.textFaint, textDim: colors.textDim,
  bgHover: colors.bgHover,
  flexRow: flexRow(), panelHeader: panelHeader(),
  headerTitle: { ...title(), fontSize: F.lg },
  headerBtn: (a) => ({ ...btn(a ? 'primary' : 'default', 'md'), fontSize: F.sm }),
  divider: (w) => dividerStyle('v', w),
}

// ═══════ 预设音色 ═══════
const PRESET_VOICES = [
  { id: 'default_zh',         label: '默认女声',   desc: '清晰自然，适合通用解说' },
  { id: 'narrator_male',      label: '沉稳男声',   desc: '低沉有力，适合悬疑/正剧' },
  { id: 'narrator_female',    label: '温柔女声',   desc: '温暖柔和，适合情感向' },
  { id: 'storyteller_male',   label: '激昂男声',   desc: '饱满有力，适合高光时刻' },
]

// ═══════ 情绪图标 ═══════
const EMOTION_ICONS = {
  suspense: '🎭', narrative: '📖', passionate: '🔥',
  analytical: '🧠', warm: '💛', humorous: '😄',
}
const EMOTION_LABELS = {
  suspense: '悬念', narrative: '叙述', passionate: '激昂',
  analytical: '分析', warm: '温暖', humorous: '幽默',
}

function tc(s) {
  if (!s && s !== 0) return '--:--'
  const m = Math.floor(s / 60), ss = Math.floor(s % 60)
  return `${m}:${String(ss).padStart(2, '0')}`
}

// ═══════════════ 子组件 ═══════════════

const Divider = memo(function Divider({ onDrag, dir = 'v' }) {
  return <div onMouseDown={onDrag}
    style={dir === 'v' ? S.divider(4) : { height: 6, cursor: 'ns-resize', background: colors.border, flexShrink: 0 }}
    onMouseEnter={e => e.currentTarget.style.background = '#E11D48'}
    onMouseLeave={e => e.currentTarget.style.background = colors.border} />
})

// ── 左侧：音色库 ──
const VoiceLibrary = memo(function VoiceLibrary({ voice, setVoice, refAudio, setRefAudio }) {
  const [refPath, setRefPath] = useState(refAudio || '')

  return (
    <div style={{ ...panelRoot(), borderLeft: 'none' }}>
      <div style={S.panelHeader}>
        <span style={S.headerTitle}>🎙️ 音色库</span>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: space.sm }}>
        <div style={{ ...label(), marginBottom: space.sm }}>预设音色</div>
        {PRESET_VOICES.map(v => (
          <div key={v.id}
            onClick={() => setVoice(v.id)}
            style={{
              ...card({ active: voice === v.id }),
              cursor: 'pointer', marginBottom: space.xs,
              transition: 'border-color 0.15s',
            }}>
            <div style={{ ...title(), fontSize: F.sm }}>{v.label}</div>
            <div style={{ ...subtitle(), fontSize: F.xs }}>{v.desc}</div>
          </div>
        ))}

        <div style={{ ...label(), marginTop: space.lg, marginBottom: space.sm }}>声音克隆</div>
        <div style={{ ...card() }}>
          <div style={{ ...subtitle(), fontSize: F.xs, marginBottom: space.xs }}>
            上传参考音频 (wav/mp3, ≤10MB)
          </div>
          <div style={S.flexRow}>
            <input
              value={refPath}
              onChange={e => { setRefPath(e.target.value); setRefAudio(e.target.value || null) }}
              placeholder="参考音频路径..."
              style={{
                flex: 1, padding: '2px 6px', fontSize: F.xs,
                background: colors.bg, color: colors.text,
                border: `1px solid ${colors.border}`, borderRadius: radius.sm, outline: 'none',
              }}
            />
          </div>
        </div>
      </div>
    </div>
  )
})

// ── 中间：脚本段落列表 ──
const SegmentList = memo(function SegmentList({ segments, ttsState, playingIdx, setPlayingIdx }) {
  const audioRefs = useRef({})
  const scrollRef = useRef(null)

  const handlePlay = useCallback((idx, path) => {
    if (playingIdx === idx) {
      // 暂停
      if (audioRefs.current[idx]) {
        audioRefs.current[idx].pause()
        audioRefs.current[idx].currentTime = 0
      }
      setPlayingIdx(null)
      return
    }
    // 停止当前
    if (audioRefs.current[playingIdx]) {
      audioRefs.current[playingIdx].pause()
      audioRefs.current[playingIdx].currentTime = 0
    }
    // 播放新的
    const url = `/tts_segments/${path.split('/').pop()}`
    const audio = new Audio(url)
    audioRefs.current[idx] = audio
    audio.onended = () => setPlayingIdx(null)
    audio.onerror = () => setPlayingIdx(null)
    audio.play().catch(() => setPlayingIdx(null))
    setPlayingIdx(idx)
  }, [playingIdx, setPlayingIdx])

  if (!segments.length) {
    return (
      <div style={{ ...panelRoot() }}>
        <div style={S.panelHeader}>
          <span style={S.headerTitle}>📝 解说脚本</span>
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ textAlign: 'center', color: colors.textFaint }}>
            <div style={{ fontSize: F.xxl, marginBottom: space.sm }}>📭</div>
            <div style={{ ...subtitle() }}>暂无脚本段落</div>
            <div style={{ ...label(), marginTop: space.xs }}>请先在编剧台生成解说脚本</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={{ ...panelRoot() }}>
      <div style={S.panelHeader}>
        <span style={S.headerTitle}>📝 解说脚本</span>
        <span style={{ ...label(), fontSize: F.xs }}>
          {Object.values(ttsState).filter(s => s.status === 'ready').length}/{segments.length} 已生成
        </span>
      </div>
      <div ref={scrollRef} style={{ flex: 1, overflow: 'auto', padding: space.sm }}>
        {segments.map((seg, i) => {
          const state = ttsState[seg.seg_id] || { status: 'pending' }
          const isReady = state.status === 'ready'
          const isPlaying = playingIdx === seg.seg_id
          const isGenerating = state.status === 'generating'

          return (
            <div key={seg.seg_id}
              style={{
                ...card({ active: isReady }),
                marginBottom: space.xs,
                opacity: isReady ? 1 : 0.7,
                transition: 'opacity 0.2s',
              }}>
              {/* 顶部：序号 + 情绪标签 + 状态 */}
              <div style={{ ...S.flexRow, marginBottom: space.xs }}>
                <span style={{
                  ...mono(), background: colors.bgHover, padding: '0 4px',
                  borderRadius: radius.sm, fontSize: F.xs,
                }}>S{seg.seg_id}</span>
                {state.emotion && (
                  <span style={{ fontSize: F.xs, color: colors.textMuted }}>
                    {EMOTION_ICONS[state.emotion] || ''} {EMOTION_LABELS[state.emotion] || state.emotion}
                  </span>
                )}
                {state.speed && state.speed !== 1.0 && (
                  <span style={{ fontSize: F.xs, color: colors.textFaint }}>{state.speed}x</span>
                )}
                <div style={{ flex: 1 }} />
                {isGenerating && <span style={{ fontSize: F.xs, color: colors.gold }}>🔄 生成中...</span>}
                {isReady && (
                  <span style={{ fontSize: F.xs, color: colors.greenLight, fontWeight: 600 }}>
                    ✅ {state.duration?.toFixed(1)}s
                  </span>
                )}
                {!isReady && !isGenerating && (
                  <span style={{ fontSize: F.xs, color: colors.textFaint }}>⏳ 待生成</span>
                )}
              </div>

              {/* 解说词文本 */}
              <div style={{
                fontSize: F.sm, color: isReady ? colors.text : colors.textDim,
                lineHeight: 1.5, marginBottom: isReady ? space.xs : 0,
                fontStyle: isReady ? 'normal' : 'italic',
              }}>
                {seg.narration_text.length > 80
                  ? seg.narration_text.slice(0, 80) + '...'
                  : seg.narration_text}
              </div>

              {/* 播放按钮 (仅已生成段) */}
              {isReady && (
                <div style={S.flexRow}>
                  <button
                    onClick={() => handlePlay(seg.seg_id, state.audioPath)}
                    style={btn(isPlaying ? 'danger' : 'success', 'xs')}>
                    {isPlaying ? '⏹ 停止' : '▶ 播放'}
                  </button>
                  {state.pause_after_ms > 0 && (
                    <span style={{ ...label(), fontSize: F.xs }}>
                      停顿 {state.pause_after_ms}ms
                    </span>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
})

// ── 右侧：全局控制 ──
const ControlPanel = memo(function ControlPanel({
  voice, speed, setSpeed, pauseMs, setPauseMs,
  generating, progress, startGeneration, segments, ttsState,
}) {
  const readyCount = Object.values(ttsState).filter(s => s.status === 'ready').length
  const allDone = readyCount === segments.length && segments.length > 0

  return (
    <div style={{ ...panelRoot(), borderRight: 'none' }}>
      <div style={S.panelHeader}>
        <span style={S.headerTitle}>⚙️ 控制台</span>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: space.sm }}>

        {/* 音色信息 */}
        <div style={{ ...card(), marginBottom: space.sm }}>
          <div style={{ ...label(), marginBottom: 2 }}>当前音色</div>
          <div style={{ ...title(), fontSize: F.md, color: colors.greenLight }}>
            {PRESET_VOICES.find(v => v.id === voice)?.label || voice}
          </div>
        </div>

        {/* 语速控制 */}
        <div style={{ ...card(), marginBottom: space.sm }}>
          <div style={{ ...S.flexRow, marginBottom: space.xs }}>
            <span style={{ ...label() }}>语速倍率</span>
            <span style={{ ...title(), fontSize: F.lg, color: colors.purple }}>{speed.toFixed(1)}x</span>
          </div>
          <input type="range" min="0.7" max="1.5" step="0.05" value={speed}
            onChange={e => setSpeed(parseFloat(e.target.value))}
            disabled={generating}
            style={{ width: '100%', accentColor: colors.purple, cursor: generating ? 'not-allowed' : 'pointer' }} />
          <div style={{ ...S.flexRow, justifyContent: 'space-between' }}>
            <span style={{ ...label(), fontSize: F.xs }}>0.7x 慢速</span>
            <span style={{ ...label(), fontSize: F.xs }}>1.5x 快速</span>
          </div>
        </div>

        {/* 段间静音 */}
        <div style={{ ...card(), marginBottom: space.sm }}>
          <div style={{ ...S.flexRow, marginBottom: space.xs }}>
            <span style={{ ...label() }}>段间静音</span>
            <span style={{ ...title(), fontSize: F.lg, color: colors.blue }}>{pauseMs}ms</span>
          </div>
          <input type="range" min="0" max="2000" step="50" value={pauseMs}
            onChange={e => setPauseMs(parseInt(e.target.value))}
            disabled={generating}
            style={{ width: '100%', accentColor: colors.blue, cursor: generating ? 'not-allowed' : 'pointer' }} />
          <div style={{ ...S.flexRow, justifyContent: 'space-between' }}>
            <span style={{ ...label(), fontSize: F.xs }}>0ms 紧接</span>
            <span style={{ ...label(), fontSize: F.xs }}>2000ms 长停</span>
          </div>
        </div>

        {/* 进度 */}
        {generating && (
          <div style={{ ...card({ active: true }), marginBottom: space.sm, borderColor: colors.gold }}>
            <div style={{ ...S.flexRow, marginBottom: space.xs }}>
              <span style={{ ...title(), fontSize: F.sm, color: colors.gold }}>🔄 生成中</span>
              <span style={{ ...label(), fontSize: F.xs }}>
                {progress.done}/{progress.total}
              </span>
            </div>
            <div style={{
              height: 4, borderRadius: 2, background: colors.bg,
              overflow: 'hidden',
            }}>
              <div style={{
                height: '100%', background: colors.gold,
                width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%`,
                transition: 'width 0.3s',
              }} />
            </div>
          </div>
        )}

        {allDone && (
          <div style={{ ...card({ active: true }), marginBottom: space.sm, borderColor: colors.green }}>
            <span style={{ ...title(), fontSize: F.sm, color: colors.greenLight }}>✅ 全部完成</span>
            <div style={{ ...label(), marginTop: 2 }}>
              {readyCount}/{segments.length} 段 · 总时长 {tc(
                Object.values(ttsState).reduce((sum, s) => sum + (s.duration || 0), 0)
              )}
            </div>
          </div>
        )}

        {/* 一键生成按钮 */}
        <button
          onClick={startGeneration}
          disabled={generating || !segments.length}
          style={{
            ...btn(generating || !segments.length ? 'disabled' : 'primary', 'md'),
            width: '100%', padding: '6px 12px', fontSize: F.md,
            marginBottom: space.sm,
          }}>
          {generating ? '🔄 生成中...' : segments.length ? '🎙️ 一键生成配音' : '📭 暂无脚本'}
        </button>

        <div style={{ ...label(), textAlign: 'center', marginTop: space.sm }}>
          配音师Agent: 脚本分析 → 配音方案 → TTS生成
        </div>
      </div>
    </div>
  )
})

// ════════════════════════════════ 主组件 ════════════════════════════════

export default function VoiceDesk() {
  const { taskId } = useParams()

  // ── 状态 ──
  const [segments, setSegments] = useState([])
  const [ttsState, setTtsState] = useState({})    // {seg_id: {status, audioPath, duration, emotion, speed, pause_after_ms}}
  const [voice, setVoice] = useState('default_zh')
  const [speed, setSpeed] = useState(1.0)
  const [pauseMs, setPauseMs] = useState(300)
  const [refAudio, setRefAudio] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [progress, setProgress] = useState({ done: 0, total: 0 })
  const [playingIdx, setPlayingIdx] = useState(null)
  const [genLog, setGenLog] = useState([])          // SSE 日志
  const [loaded, setLoaded] = useState(false)

  // ── 加载 segments ──
  useEffect(() => {
    if (!taskId) return
    setLoaded(false)
    fetch(`/segments.json?task=${taskId}`)
      .then(r => r.json())
      .then(data => {
        const segs = (data.segments || []).filter(s => (s.narration_text || '').trim())
        setSegments(segs)
        // 检查是否有已生成的 TTS
        if (data.audio_verified && segs.length > 0 && segs[0].audio_duration) {
          const restored = {}
          segs.forEach(s => {
            if (s.audio_duration) {
              restored[s.seg_id] = {
                status: 'ready',
                audioPath: s.audio_path || `tts_segments/narr_${String(s.seg_id).padStart(3, '0')}.wav`,
                duration: s.audio_duration,
                emotion: s.audio_emotion || '',
              }
            }
          })
          if (Object.keys(restored).length > 0) {
            setTtsState(restored)
          }
        }
        setLoaded(true)
      })
      .catch(err => {
        console.error('加载脚本失败', err)
        setLoaded(true)
      })
  }, [taskId])

  // ── SSE 流式生成 ──
  const startGeneration = useCallback(async () => {
    if (generating || !segments.length) return

    setGenerating(true)
    setProgress({ done: 0, total: segments.length })
    setGenLog([])

    try {
      const resp = await fetch('/voiceover/generate_stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: taskId, voice, speed, pause_ms: pauseMs,
          ref_audio_path: refAudio || undefined,
        }),
      })

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let event = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            event = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))

              if (event === 'progress') {
                setGenLog(prev => [...prev, { ...data, _ts: Date.now() }])

                if (data.step === 'segment_done') {
                  const segId = data.seg_id
                  const idx = data.index
                  setTtsState(prev => ({
                    ...prev,
                    [segId]: {
                      status: 'ready',
                      audioPath: `tts_segments/narr_${String(idx).padStart(3, '0')}.wav`,
                      duration: data.duration,
                      emotion: data._emotion || '',
                      speed: data._speed || speed,
                      pause_after_ms: data._pause || pauseMs,
                    },
                  }))
                  setProgress({ done: data.done, total: data.total })
                }

                if (data.step === 'segment_start') {
                  const segId = data.seg_id
                  setTtsState(prev => ({
                    ...prev,
                    [segId]: {
                      ...prev[segId],
                      status: 'generating',
                      emotion: data.emotion || '',
                      speed: data.speed || speed,
                      pause_after_ms: data._pause || pauseMs,
                    },
                  }))
                }
              } else if (event === 'complete') {
                setGenLog(prev => [...prev, { step: 'complete', msg: '✅ 配音完成', _ts: Date.now() }])
                setProgress({ done: segments.length, total: segments.length })
              } else if (event === 'error') {
                setGenLog(prev => [...prev, { step: 'error', msg: `❌ ${data.error}`, _ts: Date.now() }])
              }
            } catch {}
          }
        }
      }
    } catch (err) {
      console.error('SSE 生成失败', err)
      setGenLog(prev => [...prev, { step: 'error', msg: `❌ 连接异常: ${err.message}`, _ts: Date.now() }])
    } finally {
      setGenerating(false)
    }
  }, [generating, segments, taskId, voice, speed, pauseMs, refAudio])

  // ── 面板宽度 ──
  const [leftW, setLeftW] = useState(220)
  const [rightW, setRightW] = useState(260)

  return (
    <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
      {/* 音色库 */}
      <div style={{ width: leftW, flexShrink: 0 }}>
        <VoiceLibrary voice={voice} setVoice={setVoice} refAudio={refAudio} setRefAudio={setRefAudio} />
      </div>

      <Divider onDrag={e => {
        const startX = e.clientX, startW = leftW
        const onMove = ev => setLeftW(Math.max(180, Math.min(350, startW + ev.clientX - startX)))
        const onUp = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
        window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp)
      }} />

      {/* 脚本段落 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {!loaded ? (
          <div style={{ ...panelRoot(), alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ color: colors.textFaint }}>加载中...</span>
          </div>
        ) : (
          <SegmentList segments={segments} ttsState={ttsState}
            playingIdx={playingIdx} setPlayingIdx={setPlayingIdx} />
        )}
      </div>

      <Divider onDrag={e => {
        const startX = e.clientX, startW = rightW
        const onMove = ev => setRightW(Math.max(200, Math.min(380, startW - ev.clientX + startX)))
        const onUp = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
        window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp)
      }} />

      {/* 控制台 */}
      <div style={{ width: rightW, flexShrink: 0 }}>
        <ControlPanel
          voice={voice} speed={speed} setSpeed={setSpeed}
          pauseMs={pauseMs} setPauseMs={setPauseMs}
          generating={generating} progress={progress}
          startGeneration={startGeneration}
          segments={segments} ttsState={ttsState}
        />
      </div>

      {/* 底部进度日志 (可选折叠) */}
      {genLog.length > 0 && (
        <div style={{
          position: 'fixed', bottom: 8, right: 12, width: 320, maxHeight: 200,
          overflow: 'auto', background: colors.bgCard, border: `1px solid ${colors.border}`,
          borderRadius: radius.lg, padding: space.sm, zIndex: 50, opacity: 0.9,
        }}>
          <div style={{ ...S.flexRow, marginBottom: space.xs }}>
            <span style={{ ...label(), fontSize: F.xs }}>配音师日志</span>
            <div style={{ flex: 1 }} />
            <button onClick={() => setGenLog([])} style={btn('ghost', 'xs')}>✕</button>
          </div>
          {genLog.slice(-20).map((l, i) => (
            <div key={i} style={{
              fontSize: F.xs, color: l.step === 'error' ? colors.redLight :
                l.step === 'complete' ? colors.greenLight : colors.textMuted,
              padding: '1px 0', fontFamily: l.step === 'error' ? F.mono : undefined,
            }}>
              {l.msg || l.step}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
