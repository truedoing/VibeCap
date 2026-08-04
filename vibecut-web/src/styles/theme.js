/**
 * VibeCut Design Tokens
 * 统一色彩、间距、字体、边框规范，消除硬编码
 */
export const colors = {
  // 背景层级
  bg:          '#121722',
  bgCard:      '#1A1F2B',
  bgHover:     'rgba(255,255,255,0.04)',
  bgActive:    'rgba(255,255,255,0.06)',

  // 文字
  text:        '#e5e7eb',
  textDim:     '#d1d5db',
  textMuted:   '#9ca3af',
  textFaint:   '#6b7280',
  textDisabled:'#4b5563',
  textInverse: '#374151',

  // 品牌/功能色
  purple:      '#a78bfa',
  purpleBg:    'rgba(139,92,246,0.08)',
  purpleBorder:'rgba(139,92,246,0.15)',
  green:       '#22c55e',
  greenLight:  '#4ade80',
  greenBg:     'rgba(34,197,94,0.12)',
  greenBgLight:'rgba(34,197,94,0.06)',
  red:         '#ef4444',
  redLight:    '#f87171',
  redBg:       'rgba(239,68,68,0.08)',
  gold:        '#fbbf24',
  goldBg:      'rgba(251,191,36,0.1)',
  blue:        '#60a5fa',
  blueBg:      'rgba(96,165,250,0.06)',

  // 边框
  border:      '#232938',
  borderSubtle:'#1A1F2B',
  borderHover: '#E11D48',
}

export const space = {
  xs:  2,
  sm:  4,
  md:  6,
  lg:  8,
  xl:  10,
  xxl: 16,
}

export const font = {
  xs:   11,
  sm:   12,
  md:   13,
  lg:   14,
  xl:   16,
  xxl:  18,
  mono: '"SF Mono", "Fira Code", monospace',
}

export const radius = {
  sm: 3,
  md: 4,
  lg: 6,
}

export const panel = {
  headerHeight: 32,
  border: `1px solid ${colors.border}`,
}
