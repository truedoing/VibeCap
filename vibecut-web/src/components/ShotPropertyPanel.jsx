/**
 * 属性面板 — 分镜台右上角（原分镜序列位置）
 * 根据选中元素显示属性详情。当前支持：分镜大纲里选中的镜头 → 显示对应 VLM 场景信息。
 *
 * 数据流：shot(分镜脚本) → resolveShotSource 解析 ep+入点秒 → GET /vlm/lookup 命中 VLM 段。
 */
import { useState, useEffect, useMemo } from 'react'
import { colors } from '../styles/theme'
import { resolveShotSource } from '../lib/storyboardUtils'

/* shot_type 色标（与 StoryboardOutline 一致） */
const SHOT_TYPE_STYLE = {
  main:         { label: '主镜头', color: colors.purple },
  establishing: { label: '建立',   color: colors.blue },
  reaction:     { label: '反应',   color: colors.gold },
  insert:       { label: '插入',   color: colors.green },
  cutaway:      { label: '切离',   color: colors.textMuted },
  emphasis:     { label: '强调',   color: colors.red },
  transition:   { label: '转场',   color: colors.textFaint },
}

/* 一行 label→value */
function Field({ label, children }) {
  return (
    <div className="flex gap-2 py-0.5 text-[12px] leading-snug">
      <span className="shrink-0 text-textFaint" style={{ width: 64 }}>{label}</span>
      <span className="flex-1 min-w-0 text-foreground/85 break-words">{children ?? '—'}</span>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="border-b border-border/50 px-3 py-2">
      <div className="text-[11px] font-medium text-textMuted mb-1">{title}</div>
      {children}
    </div>
  )
}

export default function ShotPropertyPanel({ shot, sourceFileToEp }) {
  const src = useMemo(() => (shot ? resolveShotSource(shot, sourceFileToEp || {}) : null), [shot, sourceFileToEp])
  const [vlm, setVlm] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!src) { setVlm(null); setError(null); return }
    let alive = true
    setLoading(true); setError(null); setVlm(null)
    fetch(`/vlm/lookup?ep=${src.ep}&sec=${src.startSec}`)
      .then(r => r.json())
      .then(d => { if (!alive) return; if (d.ok) setVlm(d.scene); else setError(d.error || '无匹配') })
      .catch(e => { if (alive) setError(String(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [src?.ep, src?.startSec])

  if (!shot) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-textFaint px-4 text-center leading-relaxed">
        在左侧分镜大纲点选一个镜头，<br />这里显示该镜头对应的 VLM 详情
      </div>
    )
  }

  const st = SHOT_TYPE_STYLE[shot.shot_type] || SHOT_TYPE_STYLE.cutaway

  return (
    <div className="h-full overflow-y-auto custom-scrollbar">
      {/* 镜头信息（分镜脚本） */}
      <Section title="镜头">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded"
            style={{ color: st.color, background: `${st.color}22` }}>{st.label}</span>
          <span className="text-[12px] font-mono text-foreground">{shot.shot_id}</span>
          <span className="text-[10px] font-mono text-textFaint ml-auto">{shot.in_point ?? '无源'}{shot.duration_sec != null ? ` · ${shot.duration_sec}s` : ''}</span>
        </div>
        <Field label="画面描述">{shot.description}</Field>
        <Field label="运镜">{shot.camera}</Field>
        <Field label="作用">{shot.role}</Field>
        {shot.transition_in && <Field label="转场入">{shot.transition_in}</Field>}
        {shot.source_file && <Field label="源文件">{shot.source_file}</Field>}
      </Section>

      {/* VLM 详情 */}
      {!src ? (
        <Section title="VLM 详情">
          <div className="text-[12px] text-textFaint">无源画面（黑屏/转场），无对应 VLM 段</div>
        </Section>
      ) : loading ? (
        <Section title="VLM 详情">
          <div className="text-[12px] text-textFaint">查询中…</div>
        </Section>
      ) : error ? (
        <Section title="VLM 详情">
          <div className="text-[12px] text-redLight">{error}</div>
        </Section>
      ) : vlm ? (
        <Section title={`VLM 详情 · EP${vlm.ep} 场景${vlm.scene_id}`}>
          <Field label="时间范围">{vlm.start}s – {vlm.end}s</Field>
          <Field label="VLM 画面">{vlm.visual_summary}</Field>
          <Field label="景别">{vlm.shot_size}</Field>
          <Field label="构图">{vlm.composition}</Field>
          <Field label="机位">{vlm.angle}</Field>
          <Field label="情绪">{vlm.emotional_tone}</Field>
          <Field label="强度">{vlm.intensity}</Field>
          <Field label="光线">{vlm.lighting}</Field>
          <Field label="动作">{Array.isArray(vlm.actions) ? vlm.actions.join('、') : vlm.actions}</Field>
          <Field label="人物">{Array.isArray(vlm.characters) ? vlm.characters.join('、') : vlm.characters}</Field>
          <Field label="地点">{vlm.location}</Field>
          <Field label="事件">{vlm.event}</Field>
          <Field label="场记情绪">{vlm.mood}</Field>
        </Section>
      ) : null}
    </div>
  )
}
