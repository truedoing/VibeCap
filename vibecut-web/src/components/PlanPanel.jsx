/**
 * 方案全文面板 — 编辑台左侧（drama 模式）
 * 展示「除脚本正文（narration_text/highlight_text）以外」的完整方案：
 *   论点/洞察详解 / 装置 / 金句 / 论证链 / 情绪曲线 / 解说-原声占比 /
 *   名场面 function 分布 / 剧集分布 / 节奏流 / 备选标题 / 制作方向 / 结构
 * 图表全部手写 SVG + 内联 style，零额外依赖。
 */
import { useMemo } from 'react'
import { colors, font as baseFont } from '../styles/theme'
import { flexRow, panelHeader, title, btn } from '../styles/mixins'

// 脚本台: 文字密集型, 字号比全局大一号（与 ScriptDesk 一致）
const F = { xs: 13, sm: 14, md: 15, lg: 16, xl: 18, mono: baseFont.mono }

const S = {
  border: `1px solid ${colors.border}`, borderSubtle: `1px solid ${colors.borderSubtle}`,
  bgPanel: colors.bg, bgCard: colors.bgCard, text: colors.text,
  purple: colors.purple, purpleBg: colors.purpleBg, green: colors.green,
  greenBg: colors.greenBg, red: colors.red, gold: colors.gold, blue: colors.blue,
  flexRow: flexRow(), panelHeader: panelHeader(), headerTitle: { ...title(), fontSize: F.lg },
  headerBtn: (a) => ({ ...btn(a ? 'primary' : 'default', 'md'), fontSize: F.sm }),
}

// 名场面 function → 颜色
const FUNCTION_COLORS = {
  '锚定': '#fbbf24',  // gold
  '举证': '#4ade80',  // green
  '引爆': '#f87171',  // red
  '爆点': '#fb923c',  // orange
  '钉人': '#60a5fa',  // blue
  '对冲': '#f472b6',  // pink
  '喘息': '#94a3b8',  // slate
}
const FUNCTION_FALLBACK = '#6b7280'

const CARD = {
  padding: '8px', borderRadius: 6, marginBottom: 10,
  background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)',
}
const CARD_LABEL = { fontSize: F.xs, fontWeight: 600, color: '#9ca3af', marginBottom: 4 }

function funcColor(f) { return FUNCTION_COLORS[f] || FUNCTION_FALLBACK }

// ── 字段归一化：兼容外部导入（meta 全量）与 AI V2（theme=论点字符串）两种语义 ──
function normalizePlan(meta) {
  const m = meta || {}
  const themeIsList = Array.isArray(m.theme)
  const themeArr = themeIsList ? m.theme : (m.theme ? [m.theme] : [])
  return {
    script_id: m.script_id || '',
    title: m.title || '',
    series: m.series || '',
    type: m.type || '',
    arc_episodes: m.arc_episodes || '',
    estimated_duration: m.estimated_duration || '',
    insight: m.core_insight || (typeof m.theme === 'string' ? m.theme : ''),
    insight_detail: m.core_insight_detail || '',
    tags: themeIsList ? themeArr : [],
    device: m.device || '',
    golden_quotes: Array.isArray(m.golden_quotes) ? m.golden_quotes : [],
    argument_chain: Array.isArray(m.argument_chain) ? m.argument_chain : [],
    emotion_curve: m.emotion_curve || {},
    alternate_titles: Array.isArray(m.alternate_titles) ? m.alternate_titles : [],
    production_notes: m.production_notes || {},
    rhythm_check: m.rhythm_check || {},
  }
}

// ── 手写 SVG: Donut（解说 vs 原声占比） ──
function Donut({ a, b, aLabel, bLabel, aColor, bColor, centerText }) {
  const total = a + b
  const R = 30, C = 2 * Math.PI * R
  const aFrac = total ? a / total : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <svg width={80} height={80} viewBox="0 0 80 80" style={{ flexShrink: 0 }}>
        <circle cx={40} cy={40} r={R} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={10} />
        <circle cx={40} cy={40} r={R} fill="none" stroke={aColor} strokeWidth={10}
          strokeDasharray={`${aFrac * C} ${C}`} strokeLinecap="butt"
          transform="rotate(-90 40 40)" />
        <circle cx={40} cy={40} r={R} fill="none" stroke={bColor} strokeWidth={10}
          strokeDasharray={`${(1 - aFrac) * C} ${C}`} strokeDashoffset={-aFrac * C} strokeLinecap="butt"
          transform="rotate(-90 40 40)" />
        <text x={40} y={38} textAnchor="middle" fill={colors.text} fontSize={14} fontWeight={700}>{centerText}</text>
        <text x={40} y={53} textAnchor="middle" fill={colors.textFaint} fontSize={9}>原声占比</text>
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: F.xs, color: colors.textDim }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: aColor, display: 'inline-block' }} />
          {aLabel} <span style={{ color: colors.textFaint, fontFamily: 'monospace' }}>{a}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: F.xs, color: colors.textDim }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: bColor, display: 'inline-block' }} />
          {bLabel} <span style={{ color: colors.textFaint, fontFamily: 'monospace' }}>{b}</span>
        </div>
      </div>
    </div>
  )
}

// ── 手写 SVG: 横向分布条（function / 剧集） ──
function BarRow({ items, colorOf }) {
  if (!items.length) return null
  const max = Math.max(...items.map(([, n]) => n), 1)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {items.map(([label, n]) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: F.xs }}>
          <span style={{ width: 34, flexShrink: 0, color: colors.textMuted, textAlign: 'right', fontFamily: 'monospace' }}>{label}</span>
          <div style={{ flex: 1, height: 10, background: 'rgba(255,255,255,0.04)', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ width: `${(n / max) * 100}%`, height: '100%', background: colorOf ? colorOf(label) : colors.purple, borderRadius: 2 }} />
          </div>
          <span style={{ width: 18, flexShrink: 0, color: colors.textFaint, fontFamily: 'monospace' }}>{n}</span>
        </div>
      ))}
    </div>
  )
}

// ── 节奏流：每段一格，narration=紫 / dialogue=绿（标 function 首字） ──
function FlowStrip({ segments }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
      {segments.map((s, i) => {
        const isDia = !!s.highlight_text
        const bg = isDia ? funcColor(s.function) : colors.purple
        const label = isDia ? (s.function || '对').slice(0, 1) : ''
        return (
          <div key={i} title={`S${i} ${isDia ? '原声 · ' + (s.function || '') : '解说'}`}
            style={{
              width: 16, height: 16, borderRadius: 2, background: bg,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 9, fontWeight: 700, color: '#0b0e14', flexShrink: 0,
              opacity: isDia ? 1 : 0.55,
            }}>
            {label}
          </div>
        )
      })}
    </div>
  )
}

// ── 手写 SVG: 情绪强度折线（key_peaks） ──
function EmotionCurve({ curve }) {
  const peaks = Array.isArray(curve?.key_peaks) ? curve.key_peaks : []
  const desc = curve?.description || ''
  if (!peaks.length) return null
  const W = 300, H = 72, PAD = 12
  const maxInt = Math.max(...peaks.map(p => p.intensity || 0), 5)
  const maxSeg = Math.max(...peaks.map(p => p.segment || 0), 1)
  const x = (seg) => PAD + (seg / maxSeg) * (W - PAD * 2)
  const y = (int) => H - PAD - (int / maxInt) * (H - PAD * 2)
  const pts = peaks.map(p => `${x(p.segment)},${y(p.intensity)}`).join(' ')
  const labels = peaks.filter(p => p.label)
  return (
    <div>
      {desc && <div style={{ fontSize: F.xs, color: colors.textFaint, lineHeight: 1.5, marginBottom: 6 }}>{desc}</div>}
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
        {/* 网格 */}
        {[1, 3, 5].map(g => (
          <line key={g} x1={PAD} y1={y(g)} x2={W - PAD} y2={y(g)} stroke="rgba(255,255,255,0.05)" strokeWidth={1} />
        ))}
        {/* 折线 + 面积 */}
        <polyline points={pts} fill="none" stroke={colors.gold} strokeWidth={2} strokeLinejoin="round" />
        {peaks.map(p => (
          <g key={p.segment}>
            <circle cx={x(p.segment)} cy={y(p.intensity)} r={3} fill={colors.gold} />
            <text x={x(p.segment)} y={y(p.intensity) - 7} textAnchor="middle" fontSize={8} fill={colors.textMuted}>{p.intensity}</text>
          </g>
        ))}
      </svg>
      {/* 峰值图例 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
        {labels.map(p => (
          <span key={p.segment} style={{ fontSize: 10, padding: '1px 5px', borderRadius: 2, background: 'rgba(251,191,36,0.08)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.15)' }}>
            S{p.segment} {p.label}
          </span>
        ))}
      </div>
    </div>
  )
}

// ── 论证链：纵向流程 ──
function ArgumentChain({ chain }) {
  if (!chain.length) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {chain.map((step, i) => (
        <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'stretch' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 18, flexShrink: 0 }}>
            <div style={{ width: 14, height: 14, borderRadius: 7, background: colors.purple, color: '#0b0e14', fontSize: 9, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 1 }}>
              {i + 1}
            </div>
            {i < chain.length - 1 && <div style={{ flex: 1, width: 1, background: 'rgba(139,92,246,0.3)' }} />}
          </div>
          <div style={{ fontSize: F.xs, color: colors.textDim, lineHeight: 1.5, padding: '1px 0 6px 0' }}>{step}</div>
        </div>
      ))}
    </div>
  )
}

// ── 金句列表 ──
function GoldenQuotes({ quotes }) {
  if (!quotes.length) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {quotes.map((q, i) => (
        <div key={i} style={{ fontSize: F.xs, lineHeight: 1.5 }}>
          <span style={{ color: colors.gold, fontFamily: 'monospace', fontSize: 11 }}>S{q.seq} </span>
          <span style={{ color: colors.textDim }}>“{q.text}”</span>
          {q.type && (
            <span style={{ marginLeft: 5, fontSize: 10, padding: '0 4px', borderRadius: 2, background: 'rgba(251,191,36,0.1)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.15)', whiteSpace: 'nowrap' }}>{q.type}</span>
          )}
        </div>
      ))}
    </div>
  )
}

// ── 左侧面板：方案全文 ──
export default function DramaSourcePanel({ projectName, segments, scriptMeta, onCollapse }) {
  const plan = normalizePlan(scriptMeta)

  const stats = useMemo(() => {
    let narration = 0, dialogue = 0, chars = 0
    const funcs = {}, eps = {}
    for (const s of segments || []) {
      if (s.highlight_text) dialogue++; else narration++
      chars += (s.narration_text || '').length
      if (s.function) funcs[s.function] = (funcs[s.function] || 0) + 1
      const ep = s.episode_marker?.episode ?? s.video_episode
      if (ep != null && ep !== '') eps[ep] = (eps[ep] || 0) + 1
    }
    const total = (segments || []).length
    return {
      total, narration, dialogue, chars,
      ratio: total ? Math.round((dialogue / total) * 100) : 0,
      funcs: Object.entries(funcs),
      eps: Object.entries(eps).sort((a, b) => Number(a[0]) - Number(b[0])),
    }
  }, [segments])

  const rc = plan.rhythm_check
  const rcStruct = rc.structure || {}
  const pn = plan.production_notes

  const isEmpty = !plan.title && !plan.insight && !plan.device && plan.tags.length === 0 && stats.total === 0

  return (
    <>
      <div style={S.panelHeader}>
        <div style={S.flexRow}>
          <span style={S.headerTitle}>📋 方案全文</span>
          <span style={{ marginLeft: 6, fontSize: F.xs, color: '#6b7280' }}>
            {projectName} · {stats.total}段
          </span>
        </div>
        <div style={{ ...S.flexRow, gap: 4 }}>
          <button onClick={onCollapse} style={{ ...S.headerBtn(false), fontSize: 11, padding: '1px 6px' }} title="折叠">◀</button>
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '10px', borderBottom: S.borderSubtle }}>
        {isEmpty ? (
          <p style={{ fontSize: F.xs, color: '#6b7280', lineHeight: 1.6, margin: 0 }}>
            暂无方案内容。文案由外部工具（扣子 / WorkBuddy）或 AI 编剧生成，导入 / 生成后这里展示完整方案。
          </p>
        ) : (
          <>
            {/* 1. 标题 + 元信息 */}
            {plan.title && (
              <div style={{ marginBottom: 10 }}>
                <div style={{ fontSize: F.sm, fontWeight: 700, color: '#e5e7eb', lineHeight: 1.4 }}>{plan.title}</div>
                {(plan.series || plan.type || plan.arc_episodes || plan.estimated_duration) && (
                  <div style={{ fontSize: F.xs, color: '#9ca3af', marginTop: 2 }}>
                    {[plan.series, plan.type, plan.arc_episodes ? `EP${plan.arc_episodes}` : '', plan.estimated_duration].filter(Boolean).join(' · ')}
                  </div>
                )}
              </div>
            )}

            {/* 2. 论点 / 核心洞察 */}
            {plan.insight && (
              <div style={{ ...CARD, background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.15)' }}>
                <div style={{ ...CARD_LABEL, color: '#a78bfa' }}>💡 论点 / 核心洞察</div>
                <div style={{ fontSize: F.xs, color: '#d1d5db', lineHeight: 1.6 }}>{plan.insight}</div>
                {plan.insight_detail && (
                  <div style={{ fontSize: F.xs, color: '#9ca3af', lineHeight: 1.6, marginTop: 6, paddingTop: 6, borderTop: '1px solid rgba(139,92,246,0.12)' }}>
                    {plan.insight_detail}
                  </div>
                )}
              </div>
            )}

            {/* 3. 叙事装置 */}
            {plan.device && (
              <div style={{ ...CARD, background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.14)' }}>
                <div style={{ ...CARD_LABEL, color: '#fbbf24' }}>🎭 叙事装置</div>
                <div style={{ fontSize: F.xs, color: '#d1d5db', lineHeight: 1.6 }}>{plan.device}</div>
              </div>
            )}

            {/* 4. 主题标签 */}
            {plan.tags.length > 0 && (
              <div style={{ marginBottom: 10 }}>
                <div style={CARD_LABEL}>主题</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {plan.tags.map((t, i) => (
                    <span key={i} style={{ fontSize: F.xs, padding: '2px 6px', borderRadius: 3, background: S.purpleBg, color: '#a78bfa', border: '1px solid rgba(139,92,246,0.15)' }}>{t}</span>
                  ))}
                </div>
              </div>
            )}

            {/* 5. KPI 统计行 */}
            {stats.total > 0 && (
              <div style={{ ...CARD, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {[
                  ['总段数', stats.total, colors.text],
                  ['解说', stats.narration, colors.purple],
                  ['原声', stats.dialogue, colors.greenLight],
                  ['总字数', stats.chars, colors.textDim],
                  ['原声占比', `${stats.ratio}%`, colors.gold],
                ].map(([k, v, c]) => (
                  <div key={k} style={{ flex: '1 0 40%', minWidth: 70 }}>
                    <div style={{ fontSize: F.xs, color: colors.textFaint }}>{k}</div>
                    <div style={{ fontSize: F.md, fontWeight: 700, color: c, fontFamily: 'monospace' }}>{v}</div>
                  </div>
                ))}
              </div>
            )}

            {/* 6. 情绪曲线（外部工具产物，最该画图） */}
            {plan.emotion_curve?.key_peaks?.length > 0 && (
              <div style={CARD}>
                <div style={CARD_LABEL}>📈 情绪曲线</div>
                <EmotionCurve curve={plan.emotion_curve} />
              </div>
            )}

            {/* 7. 解说 vs 原声 Donut */}
            {stats.total > 0 && (
              <div style={CARD}>
                <div style={CARD_LABEL}>解说 / 原声结构</div>
                <Donut a={stats.narration} b={stats.dialogue} aLabel="解说" bLabel="原声"
                  aColor={colors.purple} bColor={colors.greenLight} centerText={`${stats.ratio}%`} />
              </div>
            )}

            {/* 8. 名场面 function 分布 */}
            {stats.funcs.length > 0 && (
              <div style={CARD}>
                <div style={CARD_LABEL}>名场面 function 分布</div>
                <BarRow items={stats.funcs} colorOf={funcColor} />
              </div>
            )}

            {/* 9. 剧集分布 */}
            {stats.eps.length > 0 && (
              <div style={CARD}>
                <div style={CARD_LABEL}>剧集分布</div>
                <BarRow items={stats.eps.map(([e, n]) => [`EP${e}`, n])} />
              </div>
            )}

            {/* 10. 节奏流 */}
            {stats.total > 0 && (
              <div style={CARD}>
                <div style={CARD_LABEL}>节奏流 <span style={{ color: colors.textFaint, fontWeight: 400 }}>（紫=解说 · 彩=原声 function）</span></div>
                <FlowStrip segments={segments} />
              </div>
            )}

            {/* 11. 论证链 */}
            {plan.argument_chain.length > 0 && (
              <div style={CARD}>
                <div style={CARD_LABEL}>🔗 论证链</div>
                <ArgumentChain chain={plan.argument_chain} />
              </div>
            )}

            {/* 12. 金句 */}
            {plan.golden_quotes.length > 0 && (
              <div style={CARD}>
                <div style={CARD_LABEL}>✨ 金句（{plan.golden_quotes.length}）</div>
                <GoldenQuotes quotes={plan.golden_quotes} />
              </div>
            )}

            {/* 13. 备选标题 */}
            {plan.alternate_titles.length > 0 && (
              <div style={CARD}>
                <div style={CARD_LABEL}>备选标题</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {plan.alternate_titles.map((t, i) => (
                    <div key={i} style={{ fontSize: F.xs, color: colors.textDim, lineHeight: 1.5 }}>
                      <span style={{ color: colors.textFaint, fontFamily: 'monospace', marginRight: 4 }}>{i + 1}.</span>{t}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 14. 制作方向 */}
            {(pn.voice_direction || pn.visual_direction) && (
              <div style={CARD}>
                <div style={CARD_LABEL}>🎬 制作方向</div>
                {pn.voice_direction && (
                  <div style={{ marginBottom: 6 }}>
                    <div style={{ fontSize: 11, color: colors.textFaint, fontWeight: 600, marginBottom: 2 }}>配音</div>
                    <div style={{ fontSize: F.xs, color: colors.textDim, lineHeight: 1.6 }}>{pn.voice_direction}</div>
                  </div>
                )}
                {pn.visual_direction && (
                  <div>
                    <div style={{ fontSize: 11, color: colors.textFaint, fontWeight: 600, marginBottom: 2 }}>画面</div>
                    <div style={{ fontSize: F.xs, color: colors.textDim, lineHeight: 1.6 }}>{pn.visual_direction}</div>
                  </div>
                )}
              </div>
            )}

            {/* 15. 结构文本（外部导入产物） */}
            {Object.keys(rc).length > 0 && (
              <div style={CARD}>
                <div style={CARD_LABEL}>节奏检查</div>
                {rc.dialogue_ratio && <div style={{ fontSize: F.xs, color: '#d1d5db' }}>原声占比：{rc.dialogue_ratio}</div>}
                {rc.total_segments && <div style={{ fontSize: F.xs, color: '#d1d5db' }}>总段数：{rc.total_segments}</div>}
                {rc.max_consecutive_narration && <div style={{ fontSize: F.xs, color: '#d1d5db' }}>最长连续解说：{rc.max_consecutive_narration} 段</div>}
                {Object.keys(rcStruct).length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    {Object.entries(rcStruct).map(([k, v]) => (
                      <div key={k} style={{ fontSize: F.xs, color: '#9ca3af', lineHeight: 1.5 }}>
                        <span style={{ color: '#6b7280' }}>{k}：</span>{v}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}
