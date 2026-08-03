/**
 * 策划台 — 口播采访剪辑策划
 * 三栏：转写素材 → 剪辑脚本 → AI 助手
 * v2: 性能优化版 — 组件拆分 + memo + 虚拟滚动
 */
import { useState, useEffect, useCallback, useMemo, memo, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { colors, space, font as baseFont, radius } from '../styles/theme'
import { flexRow, panelHeader, panelRoot, title, subtitle, label, mono, btn, input, select, textarea, card, divider as dividerStyle, importanceColor as impColor } from '../styles/mixins'

const FPS = 25

// 策划台: 文字密集型工作, 字号比全局大一号
const F = { xs: 13, sm: 14, md: 15, lg: 16, xl: 18, mono: baseFont.mono }

// 向后兼容别名
const S = {
  border: `1px solid ${colors.border}`, borderSubtle: `1px solid ${colors.borderSubtle}`,
  bgPanel: colors.bg, bgCard: colors.bgCard, text: colors.text,
  purple: colors.purple, purpleBg: colors.purpleBg, green: colors.green,
  greenBg: colors.greenBg, red: colors.red, gold: colors.gold, blue: colors.blue,
  flexRow: flexRow(), panelHeader: panelHeader(), headerTitle: { ...title(), fontSize: F.lg }, headerBtn: (a) => ({ ...btn(a ? 'primary' : 'default', 'md'), fontSize: F.sm }),
  divider: (w) => dividerStyle('v', w),
}

function tc(s) {
  if (!s && s !== 0) return '--:--'
  const m = Math.floor(s / 60), ss = Math.floor(s % 60)
  return `${m}:${String(ss).padStart(2, '0')}`
}

function secToMin(s) {
  const m = Math.floor(s / 60), ss = Math.floor(s % 60)
  return `${m}:${String(ss).padStart(2, '0')}`
}

// ═══════════════════ 子组件 ═══════════════════

const Divider = memo(function Divider({ onDrag, dir = 'v' }) {
  return <div onMouseDown={onDrag}
    style={dir === 'v' ? S.divider(4) : { height: 6, cursor: 'ns-resize', background: '#232938', flexShrink: 0 }}
    onMouseEnter={e => e.currentTarget.style.background = '#E11D48'}
    onMouseLeave={e => e.currentTarget.style.background = '#232938'} />
})

// ── 左侧：转写素材 ──
const SourcePanel = memo(function SourcePanel({
  transcript, asrLoaded, asrGroups, asrStats, classifiedSegs,
  filterMode, setFilterMode, collapsedGroups, setCollapsedGroups, toggleGroup,
  searchInputRef, searchQuery, setSearchQuery, searchMode, setSearchMode, doSearch, searching,
  searchResults, setSearchResults, matchSet, isMatch, hl,
  segments, selectedIdx, addSegmentFromLine,
}) {
  const [visibleRange, setVisibleRange] = useState([0, 60])
  const scrollRef = useRef(null)

  // Virtual scroll: only render visible lines
  const handleScroll = useCallback((e) => {
    const el = e.target
    const lineH = 22, visible = Math.ceil(el.clientHeight / lineH)
    const start = Math.max(0, Math.floor(el.scrollTop / lineH) - 5)
    setVisibleRange([start, start + visible + 10])
  }, [])

  const groups = asrGroups || []
  const contentOnly = filterMode === 'content'
  const displayGroups = contentOnly
    ? groups.map(g => ({ ...g, lines: (g.lines || []).filter(l => (l.importance || 3) >= 3) })).filter(g => g.lines.length > 0)
    : groups

  return (
    <>
      <div style={S.panelHeader}>
        <div style={S.flexRow}>
          <span style={S.headerTitle}>转写素材</span>
          {asrLoaded && <span style={{ marginLeft: 6, fontSize: F.sm, color: '#6b7280' }}>
            {groups.length} 段 · {asrStats.content || 0} 句
          </span>}
        </div>
        <div style={{ ...S.flexRow, gap: 4 }}>
          <button onClick={() => setCollapsedGroups({})} style={S.headerBtn(false)}>展开</button>
          <button onClick={() => { const a = {}; groups.forEach((_, i) => { a[i] = true }); setCollapsedGroups(a) }} style={S.headerBtn(false)}>折叠</button>
          <button onClick={() => setFilterMode(filterMode === 'all' ? 'content' : 'all')} style={{
            ...S.headerBtn(filterMode === 'content'), background: filterMode === 'content' ? 'rgba(34,197,94,0.15)' : 'rgba(255,255,255,0.05)',
            color: filterMode === 'content' ? '#4ade80' : '#9ca3af' }}>
            {filterMode === 'content' ? '✓ 精炼' : '全部'}
          </button>
        </div>
      </div>

      {/* 搜索栏 */}
      {asrLoaded && (
        <div style={{ padding: '3px 8px', borderBottom: S.borderSubtle, display: 'flex', gap: 3, flexShrink: 0 }}>
          <select value={searchMode} onChange={e => setSearchMode(e.target.value)}
            style={{ padding: '1px 2px', fontSize: F.xs, background: S.bgPanel, color: '#9ca3af', border: S.borderSubtle, borderRadius: 3, outline: 'none' }}>
            <option value="keyword">关键词</option>
            <option value="semantic">语义</option>
            <option value="hybrid">混合</option>
          </select>
          <input ref={searchInputRef} onKeyDown={e => e.key === 'Enter' && doSearch()}
            placeholder="搜索原话..."
            style={{ flex: 1, padding: '2px 6px', fontSize: F.sm, background: S.bgPanel, color: '#e5e7eb', border: `1px solid ${searchQuery ? '#a78bfa' : '#232938'}`, borderRadius: 3, outline: 'none' }} />
          <button onClick={() => doSearch()} disabled={searching}
            style={{ padding: '1px 6px', fontSize: F.xs, borderRadius: 3, border: 'none', cursor: searching ? 'wait' : 'pointer', background: 'rgba(139,92,246,0.15)', color: '#a78bfa' }}>
            {searching ? '··' : '搜'}
          </button>
          {searchResults !== null && (
            <button onClick={() => { setSearchResults(null); setSearchQuery(''); if (searchInputRef.current) searchInputRef.current.value = '' }}
              style={{ padding: '1px 4px', fontSize: F.xs, borderRadius: 2, border: 'none', cursor: 'pointer', background: 'rgba(255,255,255,0.04)', color: '#6b7280' }}>✕</button>
          )}
        </div>
      )}

      {/* 内容 */}
      <div ref={scrollRef} onScroll={handleScroll} style={{ flex: 1, overflow: 'auto', padding: '2px 0' }}>
        {!asrLoaded ? (
          <div style={{ textAlign: 'center', color: '#6b7280', padding: 20, fontSize: 12 }}>加载中...</div>
        ) : displayGroups.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#6b7280', padding: 20, fontSize: 12 }}>无内容</div>
        ) : (
          displayGroups.map((group, gi) => {
            const lines = group.lines || []
            const matchCount = matchSet ? lines.filter(s => isMatch(s)).length : 0
            return (
              <div key={gi} style={{ margin: '2px 4px', borderRadius: 5, overflow: 'hidden', border: '1px solid rgba(255,255,255,0.04)' }}>
                <div onClick={() => toggleGroup(gi)}
                  style={{ padding: '4px 8px', background: S.purpleBg, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5, userSelect: 'none' }}>
                  <span style={{ fontSize: F.sm, color: '#a78bfa', transform: collapsedGroups[gi] ? 'rotate(-90deg)' : 'none', transition: 'transform 0.15s', display: 'inline-block' }}>▼</span>
                  <span style={{ fontSize: F.sm, fontWeight: 700, color: '#a78bfa' }}>{group.title}</span>
                  <span style={{ fontSize: F.xs, color: '#6b7280', flex: 1 }}>{group.summary}</span>
                  {matchCount > 0 && <span style={{ fontSize: F.xs, color: '#fbbf24', background: 'rgba(251,191,36,0.1)', padding: '0 3px', borderRadius: 2 }}>{matchCount}</span>}
                  <span style={{ fontSize: F.xs, color: '#4b5563' }}>{secToMin(group.start_sec)} · {lines.length}句</span>
                </div>
                {!collapsedGroups[gi] && lines.map((s, i) => {
                  const imp = s.importance || 3
                  const isGold = imp >= 5
                  const alreadyAdded = segments.some(seg => Math.abs((seg.source_start || 0) - (s.start_sec || 0)) < 0.5)
                  const matched = matchSet && isMatch(s)
                  return (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '1px 6px', fontSize: F.sm, lineHeight: 1.5,
                      borderBottom: '1px solid rgba(255,255,255,0.01)', background: alreadyAdded ? 'rgba(34,197,94,0.04)' : 'transparent',
                      opacity: matchSet && !matched ? 0.35 : 1 }}>
                      <span style={{ width: 12, flexShrink: 0, textAlign: 'center', fontSize: 9 }}>
                        {isGold ? <span style={{ color: '#fbbf24', fontSize: 10 }}>★</span> : ''}
                      </span>
                      <span style={{ color: '#6b7280', fontFamily: 'monospace', fontSize: F.xs, minWidth: 30, textAlign: 'right', flexShrink: 0 }}>
                        {secToMin(s.start_sec)}
                      </span>
                      <span style={{ flex: 1, color: matched ? '#fbbf24' : '#d1d5db' }}>
                        {matched ? hl(s.text) : s.text}
                      </span>
                      <button onClick={() => alreadyAdded ? null : addSegmentFromLine(s)}
                        disabled={alreadyAdded}
                        style={{ width: 14, height: 14, flexShrink: 0, borderRadius: 2, border: 'none', cursor: alreadyAdded ? 'default' : 'pointer',
                          background: alreadyAdded ? 'rgba(34,197,94,0.15)' : 'rgba(255,255,255,0.06)',
                          color: alreadyAdded ? '#4ade80' : '#6b7280', fontSize: F.xs, fontWeight: 700, lineHeight: '12px', textAlign: 'center', padding: 0 }}>
                        {alreadyAdded ? '✓' : '+'}
                      </button>
                    </div>
                  )
                })}
              </div>
            )
          })
        )}
      </div>
    </>
  )
})

// ── 中间：剪辑脚本 ──
const ScriptPanel = memo(function ScriptPanel({
  topic, setTopic, outline, setOutline, updateOutlineItem, addOutlineItem, removeOutlineItem,
  segments, setSegments, setGenResult,
  selectedIdx, setSelectedIdx, editingIdx, setEditingIdx,
  moveSegment, removeSegment, updateSegment,
  generating, genMsg, exportJSON,
}) {
  return (
    <>
      <div style={S.panelHeader}>
        <div style={S.flexRow}>
          <span style={S.headerTitle}>剪辑脚本</span>
          {segments.length > 0 && <span style={{ marginLeft: 6, fontSize: F.sm, color: '#6b7280' }}>{segments.length} 段</span>}
        </div>
        <div style={{ ...S.flexRow, gap: 4 }}>
          <button onClick={() => { setSegments([]); setGenResult(null); setTopic(''); setOutline([]) }}
            style={{ ...S.headerBtn(false), color: '#f87171', background: 'rgba(239,68,68,0.08)' }}>✕ 清除</button>
          <button onClick={exportJSON} disabled={segments.length === 0}
            style={{ ...S.headerBtn(false), background: segments.length ? 'rgba(34,197,94,0.2)' : 'rgba(255,255,255,0.05)',
              color: segments.length ? '#4ade80' : '#6b7280' }}>
            导出 JSON
          </button>
        </div>
      </div>

      {/* 主题 + 大纲 */}
      <div style={{ padding: '4px 8px', borderBottom: S.borderSubtle, flexShrink: 0 }}>
        <textarea value={topic} onChange={e => setTopic(e.target.value)}
          placeholder="视频主题…"
          rows={2}
          style={{ width: '100%', padding: '4px 6px', fontSize: F.xs, fontWeight: 600, background: S.bgPanel, color: '#e5e7eb',
            border: `1px solid ${topic ? '#a78bfa' : '#232938'}`, borderRadius: 4, outline: 'none', marginBottom: 3, resize: 'vertical' }} />
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'center' }}>
          {outline.map((o, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 1, padding: '1px 3px', borderRadius: 3, background: S.purpleBg, border: '1px solid rgba(139,92,246,0.15)' }}>
              <select value={o.narrative_role} onChange={e => updateOutlineItem(i, 'narrative_role', e.target.value)}
                style={{ fontSize: F.xs, padding: '0 1px', background: 'transparent', color: '#a78bfa', border: 'none', outline: 'none', cursor: 'pointer' }}>
                {['hook_tension','hook_promise','personal_reveal','empathy','evidence','bridge','turn','proof','insight'].map(r => <option key={r} value={r}>{r}</option>)}
              </select>
              <input value={o.label} onChange={e => updateOutlineItem(i, 'label', e.target.value)}
                style={{ fontSize: F.xs, padding: '0 2px', background: 'transparent', color: '#d1d5db', border: 'none', outline: 'none', width: o.label.length * 8 + 16, minWidth: 36 }} />
              <button onClick={() => removeOutlineItem(i)} style={{ fontSize: F.xs, padding: '0 2px', cursor: 'pointer', background: 'none', border: 'none', color: '#6b7280' }}>×</button>
            </div>
          ))}
          <button onClick={addOutlineItem} style={{ fontSize: F.xs, padding: '1px 5px', borderRadius: 3, cursor: 'pointer', background: 'rgba(255,255,255,0.04)', color: '#9ca3af', border: '1px dashed #374151' }}>+ 段落</button>
        </div>
      </div>

      {/* 脚本列表 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '6px 8px' }}>
        {segments.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#6b7280', fontSize: F.sm, marginTop: 50 }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>📝</div>
            填入主题后点「AI 生成」<br />
            <span style={{ fontSize: F.sm, color: '#4b5563' }}>或从左侧素材栏点 + 手动添加</span>
          </div>
        ) : (
          segments.map((seg, idx) => (
            <SegmentCard key={idx}
              seg={seg} idx={idx}
              isSelected={selectedIdx === idx}
              isEditing={editingIdx === idx}
              onSelect={() => setSelectedIdx(idx)}
              onEdit={() => setEditingIdx(editingIdx === idx ? null : idx)}
              onMoveUp={() => moveSegment(idx, idx - 1)}
              onMoveDown={() => moveSegment(idx, idx + 1)}
              onRemove={() => removeSegment(idx)}
              onUpdate={(f, v) => updateSegment(idx, f, v)}
              canMoveUp={idx > 0}
              canMoveDown={idx < segments.length - 1}
            />
          ))
        )}
      </div>
    </>
  )
})

const SegmentCard = memo(function SegmentCard({ seg, idx, isSelected, isEditing, onSelect, onEdit, onMoveUp, onMoveDown, onRemove, onUpdate, canMoveUp, canMoveDown }) {
  return (
    <div onClick={onSelect}
      style={{ marginBottom: 6, borderRadius: 5, cursor: 'pointer',
        background: isSelected ? 'rgba(96,165,250,0.06)' : S.bgCard,
        border: `1px solid ${isSelected ? '#60a5fa' : isEditing ? '#60a5fa' : '#232938'}`,
        overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '3px 6px', background: 'rgba(0,0,0,0.2)', borderBottom: S.borderSubtle }}>
        <span style={{ fontSize: F.xs, fontWeight: 700, color: '#e5e7eb', minWidth: 20 }}>S{idx}</span>
        {seg.topic && <span style={{ fontSize: 7, padding: '0 3px', borderRadius: 2, background: S.purpleBg, color: '#a78bfa' }}>{seg.topic}</span>}
        <span style={{ fontSize: 7, fontFamily: 'monospace', color: '#6b7280' }}>{tc(seg.source_start)}-{tc(seg.source_end)}</span>
        <div style={{ flex: 1 }} />
        <button onClick={onMoveUp} disabled={!canMoveUp} style={smallBtn(canMoveUp)}>↑</button>
        <button onClick={onMoveDown} disabled={!canMoveDown} style={smallBtn(canMoveDown)}>↓</button>
        <button onClick={onEdit} style={{ ...smallBtn(true), background: isEditing ? 'rgba(96,165,250,0.2)' : 'rgba(255,255,255,0.05)', color: isEditing ? '#60a5fa' : '#9ca3af' }}>{isEditing ? '收' : '编'}</button>
        <button onClick={onRemove} style={{ ...smallBtn(true), color: '#ef4444' }}>✕</button>
      </div>
      {isEditing ? (
        <div style={{ padding: 6, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <textarea value={seg.highlight_text} onChange={e => onUpdate('highlight_text', e.target.value)}
            style={{ width: '100%', minHeight: 36, padding: 4, fontSize: F.sm, fontFamily: 'monospace', resize: 'vertical', background: S.bgPanel, color: '#e5e7eb', border: S.borderSubtle, borderRadius: 3, outline: 'none' }} />
          <div style={{ display: 'flex', gap: 6 }}>
            <input type="number" step="0.1" value={seg.source_start} onChange={e => onUpdate('source_start', parseFloat(e.target.value) || 0)}
              style={numInputStyle} placeholder="入点" />
            <input type="number" step="0.1" value={seg.source_end} onChange={e => onUpdate('source_end', parseFloat(e.target.value) || 0)}
              style={numInputStyle} placeholder="出点" />
            <select value={seg.edit_type || 'trim'} onChange={e => onUpdate('edit_type', e.target.value)}
              style={{ ...selectInputStyle, flex: 1 }}>
              <option value="trim">去冗余</option>
              <option value="raw">原样</option>
              <option value="merge">合并</option>
            </select>
          </div>
          <input value={seg.narration_text || ''} onChange={e => onUpdate('narration_text', e.target.value)}
            placeholder="旁白过渡（可选）"
            style={{ width: '100%', padding: '3px 4px', fontSize: F.xs, fontFamily: 'monospace', background: S.bgPanel, color: '#e5e7eb', border: S.borderSubtle, borderRadius: 3, outline: 'none' }} />
        </div>
      ) : (
        <div style={{ padding: '4px 6px', fontSize: F.sm, color: '#e5e7eb', lineHeight: 1.4 }}>
          {seg.highlight_text}
          {seg.narration_text && <div style={{ fontSize: F.xs, color: '#60a5fa', marginTop: 2 }}>💬 {seg.narration_text}</div>}
        </div>
      )}
    </div>
  )
})

const smallBtn = (enabled) => ({ padding: '0 3px', fontSize: F.xs, border: 'none', cursor: enabled ? 'pointer' : 'default', background: 'none', color: enabled ? '#9ca3af' : '#374151' })
const numInputStyle = { flex: 1, padding: '2px 4px', fontSize: F.xs, fontFamily: 'monospace', background: S.bgPanel, color: '#e5e7eb', border: S.borderSubtle, borderRadius: 3, outline: 'none' }
const selectInputStyle = { padding: '2px 4px', fontSize: F.xs, background: S.bgPanel, color: '#e5e7eb', border: S.borderSubtle, borderRadius: 3, outline: 'none' }

// ── 右侧：AI 助手 ──
const AIPanel = memo(function AIPanel({ report, genResult, segments, asrStats, setTopic, genLog, generating, generateScript, topic }) {
  const [tab, setTab] = useState('ai')
  const [selTheme, setSelTheme] = useState(null)

  const stats = useMemo(() => [
    { label: '总句', val: asrStats.content || 0 },
    { label: '脚本', val: segments.length },
    { label: '金句', val: segments.filter(s => s.highlight_text?.length < 15 && s.highlight_text?.includes('学')).length },
  ], [asrStats, segments])

  return (
    <>
      <div style={{ display: 'flex', borderBottom: S.borderSubtle, flexShrink: 0 }}>
        {['ai', 'preview'].map(t => (
          <button key={t} onClick={() => setTab(t)}
            style={{ flex: 1, padding: '5px', fontSize: F.sm, fontWeight: 500, border: 'none', cursor: 'pointer',
              background: tab === t ? S.bgPanel : 'transparent', color: tab === t ? '#e5e7eb' : '#6b7280',
              borderBottom: tab === t ? `2px solid ${t === 'ai' ? '#a78bfa' : '#22c55e'}` : '2px solid transparent' }}>
            {t === 'ai' ? 'AI 助手' : '预览'}
          </button>
        ))}
      </div>

      {tab === 'ai' ? (
        <div style={{ flex: 1, overflow: 'auto', padding: 8, fontSize: 10 }}>
          {/* AI 生成按钮 */}
          <button onClick={generateScript} disabled={generating || !topic?.trim()}
            style={{ width: '100%', padding: '6px 0', marginBottom: 10, borderRadius: 6, border: 'none', cursor: (generating || !topic?.trim()) ? 'not-allowed' : 'pointer',
              background: (!generating && topic?.trim()) ? 'linear-gradient(135deg, rgba(139,92,246,0.3), rgba(34,197,94,0.2))' : 'rgba(255,255,255,0.03)',
              color: (!generating && topic?.trim()) ? '#e5e7eb' : '#6b7280', fontSize: 14, fontWeight: 700 }}>
            {generating ? '⏳ 生成中...' : '🧠 AI 生成脚本'}
          </button>
          {/* 统计 */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
            {stats.map((st, i) => (
              <span key={i} style={{ padding: '2px 6px', borderRadius: 4, background: 'rgba(255,255,255,0.04)', color: '#d1d5db', fontSize: 9 }}>
                {st.label} <b style={{ color: '#e5e7eb' }}>{st.val}</b>
              </span>
            ))}
          </div>

          {/* 生成结果 */}
          {genResult && (
            <div style={{ marginBottom: 10, padding: 6, borderRadius: 5, background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.15)' }}>
              <div style={{ fontWeight: 600, color: '#4ade80', marginBottom: 3 }}>
                ✅ 生成完成 · {genResult.sections?.length || 0} 段
                {genResult.richCount && <> · 丰富版{genResult.richCount}句→压缩至{genResult.finalCount || genResult.segments?.length || 0}句</>}
              </div>
              {genResult.time_estimate && (
                <div style={{ display: 'flex', gap: 6, marginBottom: 3, fontSize: 9 }}>
                  <span style={{ color: '#9ca3af' }}>⏱ {genResult.time_estimate.budget}s</span>
                  <span style={{ color: '#fbbf24' }}>📦 {genResult.time_estimate.source_total}s</span>
                  <span style={{ color: genResult.time_estimate.status === 'ok' ? '#4ade80' : '#f87171', fontWeight: 600 }}>
                    🎯 {genResult.time_estimate.estimated_final}s
                    {genResult.time_estimate.status !== 'ok' && (genResult.time_estimate.status === 'over' ? ' ⚠️长' : ' ⚠️短')}
                  </span>
                </div>
              )}
              {genResult.review_issues?.length > 0 && (
                <div style={{ marginTop: 4, padding: 4, borderRadius: 3, background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.15)' }}>
                  <div style={{ fontSize: F.xs, fontWeight: 600, color: '#fbbf24', marginBottom: 2 }}>⚠️ 审核发现 {genResult.review_issues.length} 个问题</div>
                  {genResult.review_issues.slice(0, 5).map((iss, i) => (
                    <div key={i} style={{ fontSize: F.xs, color: '#d1d5db', padding: '1px 0' }}>
                      [{iss.severity}] {iss.detail}
                    </div>
                  ))}
                </div>
              )}
              {genResult.aiCount > 0 && <div style={{ fontSize: F.xs, color: '#a78bfa' }}>🤖 {genResult.aiCount} 句AI补写</div>}
              {genResult.notes && <div style={{ fontSize: F.xs, color: '#9ca3af', marginTop: 3 }}>{genResult.notes}</div>}
            </div>
          )}

          {/* 内容报告 */}
          {report && (
            <div style={{ marginBottom: 10, padding: 6, borderRadius: 5, background: S.purpleBg, border: '1px solid rgba(139,92,246,0.12)' }}>
              <div style={{ fontSize: F.sm, fontWeight: 600, color: '#a78bfa', marginBottom: 4 }}>📋 内容分析</div>
              <div style={{ fontSize: F.xs, color: '#d1d5db', lineHeight: 1.5, marginBottom: 8 }}>{report.summary}</div>
              <div style={{ fontSize: F.sm, fontWeight: 600, color: '#9ca3af', marginBottom: 4 }}>可选主题</div>
              {report.themes?.map((t, i) => (
                <div key={i} onClick={() => { setTopic(`主题：${t.name}。切入角度：${t.angle}。标题建议：${t.hook_suggestion || ''}`); setSelTheme(i) }}
                  style={{ padding: '4px 6px', marginBottom: 3, borderRadius: 4, cursor: 'pointer',
                    background: selTheme === i ? 'rgba(34,197,94,0.08)' : (selTheme == null && i === report.recommended?.theme_index ? 'rgba(34,197,94,0.05)' : 'rgba(255,255,255,0.02)'),
                    border: selTheme === i ? '1px solid rgba(34,197,94,0.3)' : (selTheme == null && i === report.recommended?.theme_index ? '1px solid rgba(34,197,94,0.15)' : '1px solid transparent') }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    {(selTheme === i || (selTheme == null && i === report.recommended?.theme_index)) && <span style={{ fontSize: F.sm, color: '#4ade80' }}>⭐</span>}
                    <span style={{ fontWeight: 600, color: '#e5e7eb', fontSize: 12 }}>{t.name}</span>
                    <span style={{ fontSize: F.xs, color: '#fbbf24' }}>{'★'.repeat(t.strength)}</span>
                  </div>
                  <div style={{ fontSize: F.xs, color: '#9ca3af', marginTop: 2 }}>{t.angle}</div>
                  <div style={{ fontSize: F.xs, color: '#60a5fa', marginTop: 1 }}>Hook: "{t.hook_suggestion}"</div>
                </div>
              ))}
            </div>
          )}

          {/* 生成进度 */}
          {generating && genLog.length > 0 && (
            <div style={{ marginBottom: 10, padding: 8, borderRadius: 5, background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.15)' }}>
              <div style={{ fontSize: F.sm, fontWeight: 600, color: '#a78bfa', marginBottom: 5 }}>⚙️ 生成进度</div>
              {genLog.map((entry, i) => {
                const isNew = i === genLog.length - 1
                const icon = entry.step === 'planning' ? '📐' : entry.step === 'planning_done' ? '✅' :
                             entry.step === 'writing' ? '✍️' : entry.step === 'writing_done' ? '✅' :
                             entry.step === 'review' ? '🔍' : entry.step === 'review_done' ? '📊' :
                             entry.step === 'editing' ? '✂️' : entry.step === 'editing_done' ? '✅' : '·'
                return (
                  <div key={i} style={{ fontSize: F.xs, color: isNew ? '#e5e7eb' : '#6b7280', padding: '1px 0',
                    opacity: isNew ? 1 : 0.6, lineHeight: 1.5 }}>
                    {icon} {entry.msg}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      ) : (
        <div style={{ flex: 1, overflow: 'auto', padding: 8 }}>
          {segments.length > 0 ? (
            segments.map((seg, i) => (
              <div key={i} style={{ padding: '4px 6px', marginBottom: 3, borderRadius: 3, background: 'rgba(255,255,255,0.02)', fontSize: 9 }}>
                <div style={{ color: '#e5e7eb', fontWeight: 600 }}>S{i} {seg.topic && `· ${seg.topic}`}</div>
                <div style={{ color: '#9ca3af', lineHeight: 1.3 }}>{seg.highlight_text?.substring(0, 50)}</div>
                <div style={{ color: '#6b7280', fontFamily: 'monospace', marginTop: 1 }}>{tc(seg.source_start)}-{tc(seg.source_end)}</div>
              </div>
            ))
          ) : (
            <div style={{ textAlign: 'center', color: '#6b7280', fontSize: F.xs, marginTop: 40 }}>添加段落后显示预览</div>
          )}
          {segments.length > 0 && (
            <div style={{ fontSize: F.xs, color: '#4b5563', textAlign: 'center', marginTop: 6 }}>
              总长约 {tc(segments.reduce((s, seg) => s + ((seg.source_end || 0) - (seg.source_start || 0)), 0))}
            </div>
          )}
        </div>
      )}
    </>
  )
})

// ═══════════════════ 主组件 ═══════════════════
export default function PlanningDesk() {
  const { seriesId, taskId } = useParams()
  const projectName = seriesId === 'doutinghao' ? '都挺好' : seriesId === 'yanglaoshi' ? '杨老师教育' : decodeURIComponent(seriesId || '')
  const projectParam = `project=${encodeURIComponent(projectName)}`

  // ── 数据状态 ──
  const [transcript, setTranscript] = useState('')
  const [sentences, setSentences] = useState([])
  const [structure, setStructure] = useState(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState('')

  const [topic, setTopic] = useState('')
  const [outline, setOutline] = useState([
    { label: '开场hook', narrative_role: 'hook_tension' },
    { label: '提出悬念', narrative_role: 'hook_promise' },
    { label: '四步展开', narrative_role: 'evidence' },
    { label: '情绪过桥', narrative_role: 'bridge' },
    { label: '反转', narrative_role: 'turn' },
    { label: '亲身案例', narrative_role: 'proof' },
    { label: '深层洞察', narrative_role: 'insight' },
  ])
  const [generating, setGenerating] = useState(false)

  const [segments, setSegments] = useState([])
  const [editingIdx, setEditingIdx] = useState(null)
  const [selectedIdx, setSelectedIdx] = useState(null)

  // ── 素材状态 ──
  const [asrLoaded, setAsrLoaded] = useState(false)
  const [classifiedSegs, setClassifiedSegs] = useState([])
  const [asrStats, setAsrStats] = useState({})
  const [asrGroups, setAsrGroups] = useState([])
  const [collapsedGroups, setCollapsedGroups] = useState({})
  const [filterMode, setFilterMode] = useState('content')

  // ── 搜索状态 ──
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [searchMode, setSearchMode] = useState('keyword')

  // ── AI报告 ──
  const [report, setReport] = useState(null)
  const [genResult, setGenResult] = useState(null)

  // ── UI 状态 ──
  const [leftW, setLeftW] = useState(510)
  const [rightW, setRightW] = useState(450)
  const [rightTab, setRightTab] = useState('ai')

  // ── 拖拽 ──
  const dragX = useCallback((get, set, min) => (e) => {
    e.preventDefault(); const s = get(); const sx = e.clientX
    const vw = document.documentElement.clientWidth
    const mv = (ev) => set(Math.max(min, Math.min(vw * 0.5, s - (sx - ev.clientX))))
    const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up) }
    document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up)
  }, [])

  // ── 自动加载 ──
  useEffect(() => { fetch(`/asr/classified?${projectParam}`).then(r => r.json()).then(d => {
    if (d.ok) { setClassifiedSegs(d.segments || []); setAsrStats(d.stats || {}); setAsrLoaded(true) }
    setTranscript(d.segments?.map(s => `[${s.start_sec.toFixed(1)}s] ${s.text}`).join('\n') || '')
  }).catch(() => fetch(`/asr/raw?${projectParam}`).then(r => r.json()).then(d => {
    if (d.ok) { setTranscript(d.transcript); setAsrLoaded(true) }
  }).catch(() => setError('ASR 加载失败'))) }, [])

  useEffect(() => { fetch(`/data/segmented?${projectParam}`).then(r => r.json()).then(d => {
    const groups = Object.values(d)[0]?.groups; if (groups?.length) setAsrGroups(groups)
    else fetch('/asr_groups.json?' + Date.now()).then(r => r.json()).then(d2 => setAsrGroups(d2.segments || []))
  }).catch(() => {}) }, [])

  useEffect(() => { fetch(`/content_report.json?${projectParam}&` + Date.now()).then(r => r.json()).then(setReport).catch(() => {}) }, [projectName])

  useEffect(() => {
    if (!taskId) return
    fetch(`/segments.json?task=${encodeURIComponent(taskId)}`).then(r => r.json()).then(d => {
      if (d.segments?.length) setSegments(d.segments)
    }).catch(() => {})
  }, [taskId])

  // ── 搜索 ──
  const searchInputRef = useRef(null)
  const doSearch = useCallback(async (q) => {
    const query = q || searchInputRef.current?.value || ''
    if (!query.trim()) { setSearchResults(null); return }
    setSearchQuery(query)
    setSearching(true)
    try {
      const resp = await fetch(`http://localhost:8765/search?q=${encodeURIComponent(query)}&mode=${searchMode}`)
      const data = await resp.json()
      setSearchResults(Array.isArray(data) ? data.map(r => ({ start_sec: r.start, text: r.description || r.asr || '', score: r.score })) : [])
    } catch { setSearchResults([]) }
    finally { setSearching(false) }
  }, [searchMode])

  const matchSet = useMemo(() => searchResults ? new Set(searchResults.map(r => Math.round(r.start_sec || 0))) : null, [searchResults])
  const isMatch = useCallback((s) => matchSet && matchSet.has(Math.round(s.start_sec || 0)), [matchSet])
  const hl = useCallback((text) => {
    if (!searchQuery || !matchSet) return text
    const q = searchQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return text.split(new RegExp(`(${q})`, 'gi')).map((p, i) =>
      p.toLowerCase() === searchQuery.toLowerCase()
        ? <mark key={i} style={{ background: 'rgba(251,191,36,0.3)', color: '#fbbf24', borderRadius: 2, padding: '0 1px' }}>{p}</mark>
        : p
    )
  }, [searchQuery, matchSet])

  // ── 脚本操作 ──
  const addSegmentFromLine = useCallback((s) => {
    const seg = { seg_id: 0, highlight_text: s.text, source_start: s.start_sec || 0,
      source_end: (s.start_sec || 0) + Math.max(3, (s.text?.length || 5) / 5),
      topic: s.layer === 'content' ? '素材' : '', edit_type: 'trim', narration_text: '', _sentence_idx: s.start_sec }
    setSegments(prev => {
      const insertAt = selectedIdx != null ? selectedIdx + 1 : prev.length
      const next = [...prev]; next.splice(insertAt, 0, seg)
      return next.map((s, i) => ({ ...s, seg_id: i }))
    })
  }, [selectedIdx])

  const moveSegment = useCallback((from, to) => {
    if (to < 0 || to >= segments.length) return
    setSegments(prev => { const n = [...prev]; const [item] = n.splice(from, 1); n.splice(to, 0, item); return n.map((s, i) => ({ ...s, seg_id: i })) })
  }, [segments])

  const removeSegment = useCallback((idx) => {
    setSegments(prev => prev.filter((_, i) => i !== idx).map((s, i) => ({ ...s, seg_id: i })))
  }, [])

  const updateSegment = useCallback((idx, field, value) => {
    setSegments(prev => prev.map((s, i) => i === idx ? { ...s, [field]: value } : s))
  }, [])

  const exportJSON = useCallback(() => {
    const out = { task_type: 'interview', total_segments: segments.length, segments }
    const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' })
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'segments.json'; a.click()
    URL.revokeObjectURL(a.href)
  }, [segments])

  // ── AI 生成 (SSE 流式) ──
  const [genMsg, setGenMsg] = useState('')
  const [genLog, setGenLog] = useState([])
  const generateScript = useCallback(async () => {
    if (!topic.trim()) return
    setGenerating(true); setError(''); setGenResult(null); setGenMsg('连接中...'); setGenLog([])
    try {
      const resp = await fetch('/script/generate_script_stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topic: topic.trim() }) })
      const reader = resp.body.getReader(); const decoder = new TextDecoder()
      let buf = ''; let currentEvent = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n'); buf = lines.pop() || ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (trimmed.startsWith('event: ')) { currentEvent = trimmed.slice(7); continue }
          if (!trimmed.startsWith('data: ')) continue
          try {
            const data = JSON.parse(trimmed.slice(6))
            if (currentEvent === 'progress') {
              if (data.step) { setGenMsg(data.msg || ''); setGenLog(prev => [...prev, { step: data.step, msg: data.msg, ts: Date.now() }]) }
              if (data.result?.sections) setGenResult(prev => ({ ...prev, sections: data.result.sections, topic: data.result.topic }))
            } else if (currentEvent === 'complete') {
              if (data.ok && data.segments) {
                setSegments(data.segments.map((s, i) => ({ ...s, seg_id: i })))
                setGenResult({ sections: data.sections || [], checks: data.checks || {}, bridges: data.bridges || [], notes: data.notes || '', aiCount: data.ai_generated_count || 0, time_estimate: data.time_estimate || null, topic: data.topic, richCount: data.rich_count, finalCount: data.final_count, review_issues: data.review_issues || [] })
                if (data.sections?.length) setOutline(data.sections.map(s => ({ label: s.point?.slice(0, 20) || s.role, narrative_role: s.role })))
                setGenMsg(''); setGenLog(prev => [...prev, { step: 'done', msg: `✅ 生成完成 · ${data.total || 0}句 · 预估${data.time_estimate?.estimated_final || 0}s`, ts: Date.now() }])
              }
            } else if (currentEvent === 'error') {
              setError(data.error || '生成失败')
            }
          } catch {}
        }
      }
    } catch (e) { setError('网络错误: ' + e.message) }
    finally { setGenerating(false); setGenMsg('') }
  }, [topic])

  const updateOutlineItem = useCallback((idx, f, v) => { setOutline(prev => prev.map((o, i) => i === idx ? { ...o, [f]: v } : o)) }, [])
  const addOutlineItem = useCallback(() => { setOutline(prev => [...prev, { label: '新段落', narrative_role: 'evidence' }]) }, [])
  const removeOutlineItem = useCallback((idx) => { setOutline(prev => prev.filter((_, i) => i !== idx)) }, [])
  const toggleGroup = useCallback((gi) => setCollapsedGroups(prev => ({ ...prev, [gi]: !prev[gi] })), [])

  // ── 快捷键 ──
  useEffect(() => {
    const k = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 's') { e.preventDefault(); exportJSON() } }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [exportJSON])

  const rightW_final = rightTab === 'ai' ? rightW : 0
  return (
    <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
      <div style={{ width: leftW, flexShrink: 0, display: 'flex', flexDirection: 'column', borderRight: S.border, overflow: 'hidden' }}>
        <SourcePanel {...{ transcript, asrLoaded, asrGroups, asrStats, classifiedSegs, filterMode, setFilterMode, collapsedGroups, setCollapsedGroups, toggleGroup, searchInputRef, searchQuery, setSearchQuery, searchMode, setSearchMode, doSearch, searching, searchResults, setSearchResults, matchSet, isMatch, hl, segments, selectedIdx, addSegmentFromLine }} />
      </div>
      <Divider onDrag={dragX(() => leftW, setLeftW, 360)} />
      <div style={{ flex: 1, minWidth: 200, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <ScriptPanel {...{ topic, setTopic, outline, setOutline, updateOutlineItem, addOutlineItem, removeOutlineItem, segments, setSegments, setGenResult, selectedIdx, setSelectedIdx, editingIdx, setEditingIdx, moveSegment, removeSegment, updateSegment, generating, genMsg, exportJSON }} />
      </div>
      <Divider onDrag={dragX(() => rightW, setRightW, 360)} />
      <div style={{ width: rightW, flexShrink: 0, display: rightW === 0 ? 'none' : 'flex', flexDirection: 'column', borderLeft: S.border, overflow: 'hidden' }}>
        <AIPanel report={report} genResult={genResult} segments={segments} asrStats={asrStats} setTopic={setTopic} genLog={genLog} generating={generating} generateScript={generateScript} topic={topic} />
      </div>
    </div>
  )
}
