/**
 * VibeCut Style Mixins
 * 可复用的样式工厂函数，接受参数返回 style object
 */
import { colors, space, font, radius } from './theme'

// ── 布局 ──
export const flexRow = (opts = {}) => ({
  display: 'flex', alignItems: 'center', gap: opts.gap ?? space.sm, ...opts.extra
})
export const flexCol = (opts = {}) => ({
  display: 'flex', flexDirection: 'column', gap: opts.gap ?? space.sm, ...opts.extra
})
export const flexCenter = { display: 'flex', alignItems: 'center', justifyContent: 'center' }

// ── 面板 ──
export const panelHeader = (opts = {}) => ({
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  padding: `${space.sm}px ${space.lg}px`,
  borderBottom: `1px solid ${colors.border}`,
  flexShrink: 0, minHeight: 32, gap: space.sm, ...opts.extra
})
export const panelBody = (opts = {}) => ({
  flex: 1, overflow: 'auto', padding: `${space.xs}px 0`, ...opts.extra
})
export const panelRoot = (opts = {}) => ({
  display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, overflow: 'hidden',
  borderLeft: `1px solid ${colors.border}`, ...opts.extra
})

// ── 文本 ──
export const title = (opts = {}) => ({
  fontSize: font.lg, fontWeight: 600, color: colors.text, ...opts.extra
})
export const subtitle = (opts = {}) => ({
  fontSize: font.sm, color: colors.textMuted, ...opts.extra
})
export const label = (opts = {}) => ({
  fontSize: font.xs, color: colors.textFaint, ...opts.extra
})
export const mono = (opts = {}) => ({
  fontFamily: font.mono, fontSize: font.xs, color: colors.textFaint, ...opts.extra
})

// ── 按钮 ──
export const btn = (variant = 'default', size = 'sm') => {
  const base = { border: 'none', cursor: 'pointer', fontWeight: 500, borderRadius: radius.sm }
  const sizes = { xs: { padding: '1px 4px', fontSize: font.xs }, sm: { padding: '2px 6px', fontSize: font.sm }, md: { padding: '3px 10px', fontSize: font.sm } }
  const variants = {
    default:  { background: colors.bgHover, color: colors.textMuted },
    primary:  { background: colors.purpleBg, color: colors.purple },
    success:  { background: colors.greenBg, color: colors.greenLight },
    danger:   { background: colors.redBg, color: colors.redLight },
    ghost:    { background: 'transparent', color: colors.textMuted },
    disabled: { background: 'rgba(255,255,255,0.03)', color: colors.textFaint, cursor: 'not-allowed' },
  }
  return { ...base, ...sizes[size], ...variants[variant] }
}

// ── 输入 ──
export const input = (opts = {}) => ({
  width: '100%', padding: '3px 6px', fontSize: font.sm, fontWeight: 600,
  background: colors.bgCard, color: colors.text,
  border: `1px solid ${opts.active ? colors.purple : colors.border}`,
  borderRadius: radius.md, outline: 'none', ...opts.extra
})
export const select = (opts = {}) => ({
  padding: '1px 3px', fontSize: font.xs, background: colors.bgCard,
  color: colors.textMuted, border: `1px solid ${colors.border}`,
  borderRadius: radius.sm, outline: 'none', cursor: 'pointer', ...opts.extra
})
export const textarea = (opts = {}) => ({
  width: '100%', minHeight: 40, padding: space.sm, fontSize: font.sm,
  fontFamily: font.mono, resize: 'vertical',
  background: colors.bgCard, color: colors.text,
  border: `1px solid ${colors.border}`, borderRadius: radius.md, outline: 'none', ...opts.extra
})

// ── 卡片 ──
export const card = (opts = {}) => ({
  padding: space.sm, borderRadius: radius.lg, background: colors.bgCard,
  border: `1px solid ${opts.active ? colors.blue : colors.border}`,
  ...opts.extra
})

// ── 分隔条 ──
export const divider = (dir = 'v', size = 4) => ({
  width: dir === 'v' ? size : undefined,
  height: dir === 'h' ? size : undefined,
  cursor: dir === 'v' ? 'col-resize' : 'ns-resize',
  background: colors.border, flexShrink: 0,
})

// ── 标签色 ──
export const importanceColor = (v) => {
  if (v >= 5) return { bg: 'rgba(239,68,68,0.15)', border: colors.red, label: '金句' }
  if (v >= 4) return { bg: 'rgba(34,197,94,0.12)', border: colors.green, label: '核心' }
  if (v >= 3) return { bg: 'rgba(59,130,246,0.10)', border: colors.blue, label: '可留' }
  if (v >= 2) return { bg: 'rgba(156,163,175,0.08)', border: colors.textFaint, label: '过渡' }
  return { bg: 'rgba(156,163,175,0.04)', border: colors.textDisabled, label: '冗余' }
}
