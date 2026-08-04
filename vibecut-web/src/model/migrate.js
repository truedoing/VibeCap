/**
 * picks 数据迁移工具
 * 旧格式: { ep, start, end, file, duration }  (基于提取文件)
 * 新格式: { ep, sourceStartSec, sourceEndSec }  (基于时间引用)
 */

const OLD_FILE_RE = /^clip_pick_S(\d+)_(\d+)_(main|supp)_ep(\d+)\.mp4$/

/**
 * 检测 picks 是否为旧格式（有 file 字段）
 */
export function isLegacyClipRef(ref) {
  return ref && typeof ref.file === 'string' && !ref.sourceStartSec
}

/**
 * 从旧 file 名反推时间引用
 * file 如 "clip_pick_S0_0_main_ep27.mp4"
 * 使用现有的 start/end 字段（如果有的话）
 */
export function migrateClipRef(ref) {
  if (!isLegacyClipRef(ref)) return ref

  // 优先用已有的 start/end 字段
  const sourceStartSec = ref.start ?? 0
  const sourceEndSec = ref.end ?? (sourceStartSec + (ref.duration || 3))

  return {
    ep: ref.ep,
    sourceStartSec,
    sourceEndSec,
  }
}

/**
 * 迁移整个 picks 对象
 * picks = { "0_0": { main: [ClipRef], supp: [ClipRef] }, ... }
 */
export function migratePicks(picks) {
  if (!picks || typeof picks !== 'object') return picks

  let hasLegacy = false
  for (const value of Object.values(picks)) {
    if (!value || typeof value !== 'object') continue
    for (const type of ['main', 'supp']) {
      if (Array.isArray(value[type])) {
        if (value[type].some(isLegacyClipRef)) hasLegacy = true
      }
    }
  }

  if (!hasLegacy) return picks

  const migrated = {}
  for (const [key, value] of Object.entries(picks)) {
    if (!value || typeof value !== 'object') {
      migrated[key] = value
      continue
    }
    const migratedValue = {}
    for (const type of ['main', 'supp']) {
      if (Array.isArray(value[type])) {
        migratedValue[type] = value[type].map(migrateClipRef)
      }
    }
    migrated[key] = { ...value, ...migratedValue }
  }
  return migrated
}

/**
 * 检测 picks 是否全部使用新格式
 */
export function isProxyFormat(picks) {
  if (!picks || typeof picks !== 'object') return false
  for (const value of Object.values(picks)) {
    if (!value || typeof value !== 'object') continue
    for (const type of ['main', 'supp']) {
      if (Array.isArray(value[type]) && value[type].length > 0) {
        // 只要有一个新格式的 clip，就认为是 proxy 格式
        if (value[type].some(r => r.sourceStartSec !== undefined)) return true
        // 如果没有任何 sourceStartSec，检查是否也没有 file 字段
        if (value[type].some(r => !r.file)) return true
      }
    }
  }
  return false
}
