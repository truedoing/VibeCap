/**
 * 配音面板 — 编辑台右侧
 * 选中段模式：直接操作中间选中的脚本段（不重复列文本），保留「一键生成全部」。
 * 音色：内置预设 + 全局克隆音色（浏览器上传参考音频创建）。
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

function audioUrl(path, taskId) {
  const name = (path || '').split('/').pop()
  return `/tts_segments/${name}?task=${encodeURIComponent(taskId)}&t=${Date.now()}`
}

function fmtTime(s) {
  if (s == null || !isFinite(s)) return '0:00'
  const m = Math.floor(s / 60), ss = Math.floor(s % 60)
  return `${m}:${String(ss).padStart(2, '0')}`
}

const VOICE_PREF_KEY = 'vibecut-voice-prefs'

// 从 localStorage 恢复音色/语速偏好
function loadVoicePrefs() {
  try {
    const raw = localStorage.getItem(VOICE_PREF_KEY)
    if (raw) return JSON.parse(raw)
  } catch {}
  return {}
}

export default function VoicePanel({ taskId, segments, selectedIdx }) {
  const [prefs] = useState(loadVoicePrefs)
  const [voice, setVoice] = useState(prefs.voice || '白桦')
  const [speed, setSpeed] = useState(prefs.speed ?? 1.2)  // 语速倍率，默认 1.2x（原 1.0 太慢）

  // 音色列表（后端 /voiceover/voices：预设 + 克隆）
  const [voices, setVoices] = useState([])
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [refText, setRefText] = useState('')
  const [refFile, setRefFile] = useState(null)
  const [creating, setCreating] = useState(false)
  const [createMsg, setCreateMsg] = useState('')

  // 只配音有 narration_text 的段（原声/dialogue 段跳过）
  const narrSegs = useMemo(() => (segments || []).filter(s => (s.narration_text || '').trim()), [segments])

  // 当前选中段（按 seg_id 定位；selectedIdx 是数组下标）
  const selectedSeg = useMemo(() => {
    if (selectedIdx == null) return null
    const seg = segments?.[selectedIdx]
    if (!seg || !(seg.narration_text || '').trim()) return null
    return seg
  }, [segments, selectedIdx])

  // 初始 ttsState：从 segments 的 audio_duration/audio_path 恢复
  const initialTts = useMemo(() => {
    const m = {}
    for (const s of narrSegs) {
      const sid = s.seg_id
      const path = s.audio_path || `tts_segments/narr_${String(sid).padStart(3, '0')}.wav`
      m[sid] = s.audio_duration
        ? { status: 'ready', audioPath: path, duration: s.audio_duration }
        : { status: 'pending', audioPath: path, duration: null }
    }
    return m
  }, [narrSegs])

  const [ttsState, setTtsState] = useState(initialTts)
  const [generating, setGenerating] = useState(false)        // 全量生成中
  const generatingRef = useRef(false)  // 同步锁：防连点产生并发流（进度/文件会打架）
  const [regeneratingSegs, setRegeneratingSegs] = useState(new Set())
  const [progress, setProgress] = useState({ current: 0, total: 0 })  // current = 正在生成的段序号(1-based)
  const [playing, setPlaying] = useState(false)
  const [curTime, setCurTime] = useState(0)  // 当前播放进度（秒）
  const audioRef = useRef(null)

  // 加载音色列表
  useEffect(() => {
    fetch('/voiceover/voices')
      .then(r => r.json())
      .then(d => { if (d.ok && Array.isArray(d.voices)) setVoices(d.voices) })
      .catch(() => {})
  }, [])

  // 持久化音色/语速偏好
  useEffect(() => {
    try { localStorage.setItem(VOICE_PREF_KEY, JSON.stringify({ voice, speed })) } catch {}
  }, [voice, speed])

  useEffect(() => { setTtsState(initialTts) }, [initialTts])

  // 切换选中段时，停止当前播放并复位进度
  useEffect(() => {
    if (audioRef.current) { try { audioRef.current.pause() } catch {} }
    setPlaying(false)
    setCurTime(0)
  }, [selectedSeg?.seg_id])

  useEffect(() => () => { if (audioRef.current) { try { audioRef.current.pause() } catch {} } }, [])

  // 当前选中段的状态
  const selState = selectedSeg ? (ttsState[selectedSeg.seg_id] || { status: 'pending', audioPath: `tts_segments/narr_${String(selectedSeg.seg_id).padStart(3, '0')}.wav` }) : null

  const handlePlay = useCallback(() => {
    if (!selectedSeg || !selState || selState.status !== 'ready') return
    if (playing) {
      if (audioRef.current) audioRef.current.pause()
      setPlaying(false)
      return
    }
    const audio = new Audio(audioUrl(selState.audioPath, taskId))
    audioRef.current = audio
    audio.ontimeupdate = () => setCurTime(audio.currentTime)
    audio.onended = () => { setPlaying(false); setCurTime(0) }
    audio.onerror = () => setPlaying(false)
    audio.play().catch(() => setPlaying(false))
    setPlaying(true)
  }, [selectedSeg, selState, playing, taskId])

  // 跳转进度
  const handleSeek = useCallback((sec) => {
    if (audioRef.current) {
      audioRef.current.currentTime = sec
      setCurTime(sec)
    }
  }, [])

  // 单段生成
  const generateOne = useCallback(async () => {
    if (!selectedSeg) return
    const sid = selectedSeg.seg_id
    if (generatingRef.current || generating || regeneratingSegs.has(sid)) return
    setRegeneratingSegs(prev => new Set(prev).add(sid))
    setTtsState(prev => ({ ...prev, [sid]: { ...prev[sid], status: 'generating' } }))
    try {
      const resp = await fetch('/voiceover/regenerate_segment', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: taskId, seg_id: sid, voice, speed }),
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
  }, [selectedSeg, taskId, voice, speed, generating, regeneratingSegs])

  // 一键生成全部
  const generateAll = useCallback(async () => {
    if (generatingRef.current || !narrSegs.length) return
    generatingRef.current = true
    setGenerating(true)
    setProgress({ current: 1, total: narrSegs.length })
    setTtsState(prev => {
      const n = { ...prev }
      for (const s of narrSegs) if (!n[s.seg_id]?.duration) n[s.seg_id] = { ...n[s.seg_id], status: 'generating' }
      return n
    })
    try {
      const resp = await fetch('/voiceover/generate_stream', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: taskId, voice, speed, pause_ms: 300 }),
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
              // 当前段开始 → 按钮显示"正在生成第 N 段"（避免冻结在 done=N-1）
              setProgress(prev => ({ current: (d.index ?? 0) + 1, total: d.total ?? prev.total }))
              setTtsState(prev => ({ ...prev, [d.seg_id]: { ...prev[d.seg_id], status: 'generating' } }))
            } else if (ev === 'progress' && d.step === 'segment_done' && d.seg_id != null) {
              setTtsState(prev => ({ ...prev, [d.seg_id]: { status: 'ready', audioPath: `tts_segments/narr_${String(d.seg_id).padStart(3, '0')}.wav`, duration: d.duration } }))
              setProgress(prev => ({ ...prev, total: d.total ?? prev.total }))
            }
          } catch {}
        }
      }
    } catch {}
    finally { generatingRef.current = false; setGenerating(false) }
  }, [narrSegs, taskId, voice, speed])

  // 新建克隆音色
  const createVoice = useCallback(async () => {
    if (!newName.trim() || !refFile) { setCreateMsg('请填音色名并选择参考音频'); return }
    setCreating(true); setCreateMsg('')
    try {
      const fd = new FormData()
      fd.append('name', newName.trim())
      fd.append('ref_text', refText.trim())
      fd.append('audio', refFile)
      const resp = await fetch('/voiceover/create_voice', { method: 'POST', body: fd })
      const d = await resp.json()
      if (d.ok) {
        setCreateMsg(`✅ 已创建「${d.voice?.name}」`)
        setNewName(''); setRefText(''); setRefFile(null)
        setShowCreate(false)
        // 刷新音色列表 + 选中新音色
        const v = await fetch('/voiceover/voices').then(r => r.json())
        if (v.ok) setVoices(v.voices)
        setVoice(d.voice?.name || newName.trim())
      } else {
        setCreateMsg(`❌ ${d.error || '创建失败'}`)
      }
    } catch (e) {
      setCreateMsg(`❌ ${e.message}`)
    } finally {
      setCreating(false)
    }
  }, [newName, refText, refFile])

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
          <div style={{ ...S.flexRow, justifyContent: 'space-between' }}>
            <div style={{ ...label() }}>音色</div>
            <button onClick={() => setShowCreate(s => !s)} style={btn('ghost', 'xs')}>
              {showCreate ? '收起' : '＋ 克隆音色'}
            </button>
          </div>
          <select value={voice} onChange={e => setVoice(e.target.value)}
            style={{ ...selectStyle(), width: '100%', padding: '4px 6px', fontSize: F.xs, marginTop: 2 }}>
            {voices.map(v => (
              <option key={v.name} value={v.name}>{v.label}{v.kind === 'clone' ? ' (克隆)' : ''}</option>
            ))}
            {voices.length === 0 && <option value="白桦">白桦 · 成熟男声</option>}
          </select>

          {/* 语速 */}
          <div style={{ ...S.flexRow, justifyContent: 'space-between', marginTop: 8 }}>
            <div style={{ ...label() }}>语速</div>
            <span style={{ fontSize: F.xs, color: colors.textMuted, fontFamily: 'monospace' }}>{speed.toFixed(1)}x</span>
          </div>
          <input type="range" min={0.8} max={1.8} step={0.1} value={speed}
            onChange={e => setSpeed(parseFloat(e.target.value))}
            style={{ width: '100%', marginTop: 2 }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: colors.textFaint }}>
            <span>0.8x 慢</span>
            <span>1.8x 快</span>
          </div>

          {/* 克隆音色表单 */}
          {showCreate && (
            <div style={{ marginTop: 8, paddingTop: 8, borderTop: S.borderSubtle }}>
              <input value={newName} onChange={e => setNewName(e.target.value)}
                placeholder="音色名（如：我的声音）"
                style={{ width: '100%', padding: '4px 6px', fontSize: F.xs, background: colors.bg, color: colors.text, border: S.border, borderRadius: 4, outline: 'none', marginBottom: 6, boxSizing: 'border-box' }} />
              <input type="file" accept=".wav,.mp3" onChange={e => setRefFile(e.target.files?.[0] || null)}
                style={{ fontSize: F.xs, color: colors.textMuted, marginBottom: 6 }} />
              <input value={refText} onChange={e => setRefText(e.target.value)}
                placeholder="参考音频对应文本（可选，克隆更准）"
                style={{ width: '100%', padding: '4px 6px', fontSize: F.xs, background: colors.bg, color: colors.text, border: S.border, borderRadius: 4, outline: 'none', marginBottom: 6, boxSizing: 'border-box' }} />
              <button onClick={createVoice} disabled={creating || !newName.trim() || !refFile}
                style={{ ...S.headerBtn(creating ? false : true), width: '100%' }}>
                {creating ? '⏳ 创建中…' : '🎤 创建克隆音色'}
              </button>
              {createMsg && <div style={{ fontSize: F.xs, color: createMsg.startsWith('✅') ? colors.greenLight : colors.redLight, marginTop: 4 }}>{createMsg}</div>}
            </div>
          )}
        </div>

        {/* 一键全部 */}
        <button onClick={generateAll} disabled={generating || !narrSegs.length}
          title={generating ? `正在配音第 ${progress.current}/${progress.total} 段（已完成 ${Object.values(ttsState).filter(s => s.status === 'ready').length} 段）` : '为所有解说段生成配音'}
          style={{ ...S.headerBtn(generating || !narrSegs.length ? false : true), width: '100%', marginBottom: 8 }}>
          {generating ? `🔄 生成中 ${progress.current}/${progress.total}` : '🎙️ 一键生成全部'}
        </button>

        {/* 选中段操作 */}
        <div style={{ ...card(), marginBottom: 8 }}>
          <div style={{ ...label(), marginBottom: 4 }}>选中段落</div>
          {!selectedSeg ? (
            <div style={{ fontSize: F.xs, color: colors.textFaint, lineHeight: 1.6 }}>
              在中间脚本区点选一段（解说段）后，这里直接操作该段生成/试听。
            </div>
          ) : (
            <>
              <div style={{ fontSize: F.xs, color: colors.textMuted, fontFamily: 'monospace', marginBottom: 4 }}>
                S{selectedSeg.seg_id}
                {selState?.status === 'ready' && <span style={{ color: colors.greenLight, marginLeft: 6 }}>✅ {selState.duration?.toFixed(1)}s</span>}
                {selState?.status === 'generating' && <span style={{ color: colors.gold, marginLeft: 6 }}>🔄 生成中</span>}
                {selState?.status === 'pending' && <span style={{ color: colors.textFaint, marginLeft: 6 }}>⏳ 待生成</span>}
              </div>

              {/* 简易播放器 */}
              {selState?.status === 'ready' && (
                <div style={{ ...card(), padding: 8, marginBottom: 4, background: colors.bg }}>
                  <div style={{ ...S.flexRow, gap: 6 }}>
                    <button onClick={handlePlay}
                      style={{ ...btn(playing ? 'danger' : 'success', 'sm'), minWidth: 34, padding: '2px 8px' }}>
                      {playing ? '⏸' : '▶'}
                    </button>
                    <span style={{ fontSize: 11, fontFamily: 'monospace', color: colors.textMuted, minWidth: 66, textAlign: 'center' }}>
                      {fmtTime(curTime)} / {fmtTime(selState.duration || 0)}
                    </span>
                  </div>
                  <input type="range" min={0} max={selState.duration || 1} step={0.1} value={curTime}
                    onChange={e => handleSeek(parseFloat(e.target.value))}
                    style={{ width: '100%', marginTop: 4 }} />
                </div>
              )}

              <div style={{ ...S.flexRow, marginTop: 2 }}>
                <button onClick={generateOne} disabled={generating || regeneratingSegs.has(selectedSeg.seg_id)}
                  style={btn(generating || regeneratingSegs.has(selectedSeg.seg_id) ? 'disabled' : 'primary', 'sm')}>
                  {regeneratingSegs.has(selectedSeg.seg_id) ? '🔄…' : selState?.status === 'ready' ? '🔄 重生成' : '🎙 生成'}
                </button>
              </div>
            </>
          )}
        </div>
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
