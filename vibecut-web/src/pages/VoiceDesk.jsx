/**
 * 配音台 v1.1 — AI 解说语音生成
 * 三栏：音色库 | 脚本段落 | 全局控制
 *
 * 流水线位置: 编剧台 → 配音台 → 分镜台
 * 核心: 配音师Agent (VoiceDirector) 设计配音方案 → MiMo TTS 逐段生成
 *
 * v1.1 新增:
 *  - 音色试听 (voicePreviewCache + previewVoice)
 *  - 单段重生成 + 段级覆盖 (segOverrides + regenerateSegment)
 *  - 文本展开/折叠 (80字符threshold)
 *  - Audio cleanup on unmount
 */
import { useState, useEffect, useCallback, useRef, memo } from 'react'
import { useParams } from 'react-router-dom'
import { colors, space, font, radius } from '../styles/theme'
import { flexRow, flexCol, panelHeader, panelRoot, title, subtitle, label, mono, btn, card, select as selectStyle, divider as dividerStyle } from '../styles/mixins'

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
const VoiceLibrary = memo(function VoiceLibrary({ voice, setVoice, refAudio, setRefAudio, onPreviewVoice, previewingVoice }) {
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
            <div style={{ ...flexRow(), justifyContent: 'space-between' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ ...title(), fontSize: F.sm }}>{v.label}</div>
                <div style={{ ...subtitle(), fontSize: F.xs }}>{v.desc}</div>
              </div>
              <button
                onClick={e => { e.stopPropagation(); onPreviewVoice(v.id) }}
                disabled={previewingVoice === v.id}
                style={{
                  ...btn(previewingVoice === v.id ? 'disabled' : 'ghost', 'xs'),
                  flexShrink: 0, marginLeft: space.xs,
                }}
                title="试听">
                {previewingVoice === v.id ? '⏳' : '🔊'}
              </button>
            </div>
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
const SegmentList = memo(function SegmentList({
  segments, ttsState, playingIdx, setPlayingIdx,
  segOverrides, setSegOverrides, onRegenerate, regeneratingSegs, generating,
}) {
  const audioRefs = useRef({})

  // Audio cleanup on unmount
  useEffect(() => {
    return () => {
      Object.values(audioRefs.current).forEach(a => {
        try { a.pause(); a.src = '' } catch {}
      })
    }
  }, [])

  // 段文本展开/折叠
  const [expandedSegs, setExpandedSegs] = useState({})

  const handlePlay = useCallback((idx, path) => {
    if (playingIdx === idx) {
      if (audioRefs.current[idx]) {
        audioRefs.current[idx].pause()
        audioRefs.current[idx].currentTime = 0
      }
      setPlayingIdx(null)
      return
    }
    if (audioRefs.current[playingIdx]) {
      audioRefs.current[playingIdx].pause()
      audioRefs.current[playingIdx].currentTime = 0
    }
    const url = `/tts_segments/${path.split('/').pop()}?t=${Date.now()}`
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
      <div style={{ flex: 1, overflow: 'auto', padding: space.sm }}>
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

              {/* 解说词文本 (可展开/折叠) */}
              <div style={{
                fontSize: F.sm, color: isReady ? colors.text : colors.textDim,
                lineHeight: 1.5, marginBottom: space.xs,
                fontStyle: isReady ? 'normal' : 'italic',
              }}>
                {(() => {
                  const LIMIT = 80
                  const tooLong = seg.narration_text.length > LIMIT
                  const showFull = expandedSegs[seg.seg_id]
                  if (tooLong && !showFull) return seg.narration_text.slice(0, LIMIT) + '...'
                  return seg.narration_text
                })()}
              </div>
              {seg.narration_text.length > 80 && (
                <button
                  onClick={() => setExpandedSegs(prev => ({ ...prev, [seg.seg_id]: !prev[seg.seg_id] }))}
                  style={{ ...btn('ghost', 'xs'), marginBottom: space.xs, fontSize: F.xs, color: colors.blue }}>
                  {expandedSegs[seg.seg_id] ? '收起 ▲' : '展开全文 ▼'}
                </button>
              )}

              {/* ── 覆盖参数 (collapsible) ── */}
              {(state.status === 'pending' || isReady) && (
                <details style={{ marginTop: space.xs }}>
                  <summary style={{
                    ...label(), fontSize: F.xs, cursor: 'pointer',
                    color: segOverrides[seg.seg_id] ? colors.blue : colors.textFaint,
                  }}>
                    {segOverrides[seg.seg_id] ? '⚙️ 已覆盖' : '⚙️ 覆盖参数'}
                  </summary>
                  <div style={{ ...flexCol({ gap: 2 }), marginTop: space.xs }}>
                    <div style={flexRow({ gap: 2 })}>
                      <span style={{ ...label(), fontSize: F.xs, width: 32, flexShrink: 0 }}>音色</span>
                      <select
                        value={segOverrides[seg.seg_id]?.voice || ''}
                        onChange={e => {
                          const v = e.target.value
                          setSegOverrides(prev => {
                            const cur = { ...(prev[seg.seg_id] || {}) }
                            if (v) cur.voice = v; else delete cur.voice
                            if (!Object.keys(cur).length) { const n = { ...prev }; delete n[seg.seg_id]; return n }
                            return { ...prev, [seg.seg_id]: cur }
                          })
                        }}
                        style={{
                          flex: 1, background: colors.bg, color: colors.text, border: `1px solid ${colors.border}`,
                          borderRadius: radius.sm, padding: '1px 4px', fontSize: F.xs,
                        }}>
                        <option value="">默认</option>
                        {PRESET_VOICES.map(v => (
                          <option key={v.id} value={v.id}>{v.label}</option>
                        ))}
                      </select>
                    </div>
                    <div style={flexRow({ gap: 2 })}>
                      <span style={{ ...label(), fontSize: F.xs, width: 32, flexShrink: 0 }}>情绪</span>
                      <select
                        value={segOverrides[seg.seg_id]?.emotion || ''}
                        onChange={e => {
                          const em = e.target.value
                          setSegOverrides(prev => {
                            const cur = { ...(prev[seg.seg_id] || {}) }
                            if (em) cur.emotion = em; else delete cur.emotion
                            if (!Object.keys(cur).length) { const n = { ...prev }; delete n[seg.seg_id]; return n }
                            return { ...prev, [seg.seg_id]: cur }
                          })
                        }}
                        style={{
                          flex: 1, background: colors.bg, color: colors.text, border: `1px solid ${colors.border}`,
                          borderRadius: radius.sm, padding: '1px 4px', fontSize: F.xs,
                        }}>
                        <option value="">配音师自动</option>
                        {Object.entries(EMOTION_LABELS).map(([key, label]) => (
                          <option key={key} value={key}>{EMOTION_ICONS[key]} {label}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                </details>
              )}

              {/* ── 播放 + 重生成按钮 ── */}
              {(isReady || isGenerating) && (
                <div style={{ ...S.flexRow, marginTop: space.xs }}>
                  {isReady && (
                    <button
                      onClick={() => handlePlay(seg.seg_id, state.audioPath)}
                      style={btn(isPlaying ? 'danger' : 'success', 'xs')}>
                      {isPlaying ? '⏹ 停止' : '▶ 播放'}
                    </button>
                  )}
                  {isReady && (
                    <button
                      onClick={() => onRegenerate(seg.seg_id)}
                      disabled={generating || regeneratingSegs.has(seg.seg_id)}
                      style={btn(generating || regeneratingSegs.has(seg.seg_id) ? 'disabled' : 'ghost', 'xs')}>
                      {regeneratingSegs.has(seg.seg_id) ? '🔄 重生成中...' : '🔄 重生成'}
                    </button>
                  )}
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
  importAudioPath, setImportAudioPath, importAudio, importing,
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

        {/* ── 音频导入 (主入口) ── */}
        <div style={{ ...card({ active: true }), marginBottom: space.sm, borderColor: colors.blue }}>
          <div style={{ ...title(), fontSize: F.sm, color: colors.blue, marginBottom: space.xs }}>
            📥 导入配音音频
          </div>
          <div style={{ ...subtitle(), fontSize: F.xs, marginBottom: space.sm }}>
            在别的机器生成整段解说音频后，填路径导入。本机自动 ASR 对齐 + 切分。
          </div>
          <input
            value={importAudioPath}
            onChange={e => setImportAudioPath(e.target.value)}
            placeholder="音频路径，如 /path/to/解说音频.wav"
            disabled={importing}
            style={{
              width: '100%', padding: '4px 8px', fontSize: F.xs,
              background: colors.bg, color: colors.text,
              border: `1px solid ${colors.border}`, borderRadius: radius.sm,
              outline: 'none', marginBottom: space.sm, boxSizing: 'border-box',
            }}
          />
          <button
            onClick={importAudio}
            disabled={importing || !importAudioPath.trim()}
            style={{
              ...btn(importing || !importAudioPath.trim() ? 'disabled' : 'primary', 'md'),
              width: '100%', padding: '6px 12px', fontSize: F.md,
            }}>
            {importing ? '🔄 导入中...' : '📥 开始导入'}
          </button>
        </div>

        {/* 一键生成按钮 (降级为次要) */}
        <button
          onClick={startGeneration}
          disabled={generating || !segments.length}
          title="需在别的机器生成后导入，本机仅作 fallback"
          style={{
            ...btn(generating || !segments.length ? 'disabled' : 'ghost', 'md'),
            width: '100%', padding: '6px 12px', fontSize: F.sm,
            marginBottom: space.sm,
          }}>
          {generating ? '🔄 生成中...' : segments.length ? '🎙️ 本机生成 (慢)' : '📭 暂无脚本'}
        </button>

        <div style={{ ...label(), textAlign: 'center', marginTop: space.sm }}>
          导入: 音频 → ASR对齐 → 切分 → 逐段播放
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

  // ── v1.1 新增: 段级覆盖 + 单段重生成 + 音色试听 ──
  const [segOverrides, setSegOverrides] = useState({})
  // {seg_id: {voice?, emotion?, speed?, pauseMs?}}
  const [regeneratingSegs, setRegeneratingSegs] = useState(new Set())
  const voicePreviewCache = useRef({})
  const [previewingVoice, setPreviewingVoice] = useState(null)

  // ── v1.2 新增: 音频导入 ──
  const [importAudioPath, setImportAudioPath] = useState('')
  const [importing, setImporting] = useState(false)

  // 音色试听
  const previewVoice = useCallback(async (voiceId) => {
    if (previewingVoice === voiceId) return

    if (voicePreviewCache.current[voiceId]) {
      const audio = new Audio(voicePreviewCache.current[voiceId] + '&_t=' + Date.now())
      audio.play().catch(() => {})
      return
    }

    setPreviewingVoice(voiceId)
    try {
      const resp = await fetch('/voiceover/preview_voice', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: taskId, voice: voiceId }),
      })
      const data = await resp.json()
      if (data.ok) {
        const url = `/tts_segments/_voice_sample_${voiceId}.wav?task=${taskId}`
        voicePreviewCache.current[voiceId] = url
        const audio = new Audio(url)
        audio.play().catch(() => {})
      }
    } catch (err) {
      console.error('Preview failed:', err)
    } finally {
      setPreviewingVoice(null)
    }
  }, [previewingVoice, taskId])

  // ── 加载 segments (可复用) ──
  const reloadSegments = useCallback(() => {
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

  useEffect(() => {
    reloadSegments()
  }, [reloadSegments])

  // ── 音频导入 SSE ──
  const importAudio = useCallback(async () => {
    if (importing || !importAudioPath.trim()) return
    setImporting(true)
    setGenLog([])

    try {
      const resp = await fetch('/voiceover/import_audio', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: taskId, audio_path: importAudioPath.trim() }),
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
              } else if (event === 'complete') {
                setGenLog(prev => [...prev, { step: 'complete', msg: '✅ 导入完成', _ts: Date.now() }])
              } else if (event === 'error') {
                setGenLog(prev => [...prev, { step: 'error', msg: `❌ ${data.error}`, _ts: Date.now() }])
              }
            } catch {}
          }
        }
      }
    } catch (err) {
      console.error('导入失败', err)
      setGenLog(prev => [...prev, { step: 'error', msg: `❌ 连接异常: ${err.message}`, _ts: Date.now() }])
    } finally {
      setImporting(false)
      // 导入完成刷新 segments + ttsState (触发恢复逻辑)
      reloadSegments()
    }
  }, [importing, importAudioPath, taskId, reloadSegments])

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
          seg_overrides: Object.keys(segOverrides).length > 0 ? segOverrides : undefined,
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
  }, [generating, segments, taskId, voice, speed, pauseMs, refAudio, segOverrides])

  // ── v1.1: 单段重生成 SSE ──
  const regenerateSegment = useCallback(async (segId) => {
    if (regeneratingSegs.has(segId) || generating) return

    setRegeneratingSegs(prev => new Set(prev).add(segId))

    const overrides = segOverrides[segId] || {}
    const body = { task: taskId, seg_id: segId }
    if (overrides.voice) body.voice = overrides.voice
    if (overrides.emotion) body.emotion = overrides.emotion
    if (overrides.speed != null) body.speed = overrides.speed
    if (overrides.pauseMs != null) body.pause_ms = overrides.pauseMs

    try {
      const resp = await fetch('/voiceover/regenerate_segment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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
              if (event === 'progress' && data.step === 'segment_start') {
                setTtsState(prev => ({
                  ...prev,
                  [segId]: {
                    ...prev[segId],
                    status: 'generating',
                    emotion: data.emotion || prev[segId]?.emotion,
                  },
                }))
              }
              if (event === 'progress' && data.step === 'segment_done') {
                setTtsState(prev => ({
                  ...prev,
                  [segId]: {
                    status: 'ready',
                    audioPath: `tts_segments/narr_${String(data.index).padStart(3, '0')}.wav`,
                    duration: data.duration,
                    emotion: data.emotion || prev[segId]?.emotion,
                    speed: data.speed || prev[segId]?.speed,
                    pause_after_ms: prev[segId]?.pause_after_ms || 300,
                  },
                }))
              }
              if (event === 'complete') {
                setGenLog(prev => [...prev, {
                  step: 'regenerate_done',
                  msg: `✅ S${segId} 重生成完成 · ${data.duration?.toFixed(1)}s`,
                  _ts: Date.now()
                }])
              }
              if (event === 'error') {
                setGenLog(prev => [...prev, {
                  step: 'error',
                  msg: `❌ S${segId}: ${data.error}`,
                  _ts: Date.now()
                }])
                // Roll back status
                setTtsState(prev => {
                  const cur = prev[segId]
                  return {
                    ...prev,
                    [segId]: {
                      ...cur,
                      status: cur?.audioPath ? 'ready' : 'pending',
                    },
                  }
                })
              }
            } catch {}
          }
        }
      }
    } catch (err) {
      console.error('Regenerate SSE failed', err)
      setGenLog(prev => [...prev, {
        step: 'error',
        msg: `❌ S${segId} 重生成连接异常: ${err.message}`,
        _ts: Date.now()
      }])
      setTtsState(prev => {
        const cur = prev[segId]
        return {
          ...prev,
          [segId]: {
            ...cur,
            status: cur?.audioPath ? 'ready' : 'pending',
          },
        }
      })
    } finally {
      setRegeneratingSegs(prev => {
        const next = new Set(prev)
        next.delete(segId)
        return next
      })
    }
  }, [regeneratingSegs, generating, segOverrides, taskId])

  // ── 面板宽度 ──
  const [leftW, setLeftW] = useState(220)
  const [rightW, setRightW] = useState(260)

  return (
    <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
      {/* 音色库 */}
      <div style={{ width: leftW, flexShrink: 0 }}>
        <VoiceLibrary voice={voice} setVoice={setVoice} refAudio={refAudio} setRefAudio={setRefAudio}
          onPreviewVoice={previewVoice} previewingVoice={previewingVoice} />
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
            playingIdx={playingIdx} setPlayingIdx={setPlayingIdx}
            segOverrides={segOverrides} setSegOverrides={setSegOverrides}
            onRegenerate={regenerateSegment}
            regeneratingSegs={regeneratingSegs}
            generating={generating} />
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
          importAudioPath={importAudioPath} setImportAudioPath={setImportAudioPath}
          importAudio={importAudio} importing={importing}
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
