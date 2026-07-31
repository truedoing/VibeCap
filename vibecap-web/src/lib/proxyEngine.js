/**
 * 代理视频解析引擎
 * 管理代理文件 URL 和源视频时间引用的转换
 */

const FPS = 25

/**
 * 获取代理视频 URL
 */
export function proxyUrlForEpisode(ep, manifest) {
  if (!manifest?.proxies) return null
  const proxy = manifest.proxies.find(p => p.ep === ep)
  return proxy ? `/proxies/${proxy.file}` : null
}

/**
 * 获取代理视频信息
 */
export function proxyInfoForEpisode(ep, manifest) {
  if (!manifest?.proxies) return null
  return manifest.proxies.find(p => p.ep === ep) || null
}

/**
 * 从 ClipRef 计算出 Elah clip 所需的参数
 * 返回 { src, sourceStartFrame, sourceDurationFrames, durationSec }
 */
export function resolveClipSource(ref, fps = FPS) {
  const sourceStartSec = ref.sourceStartSec ?? ref.start ?? 0
  const sourceEndSec = ref.sourceEndSec ?? ref.end ?? (sourceStartSec + (ref.duration || 3))
  const sourceStartFrame = secondsToFrames(sourceStartSec, fps)
  const sourceDurationFrames = secondsToFrames(sourceEndSec - sourceStartSec, fps)

  return {
    sourceStartFrame,
    sourceDurationFrames,
    durationSec: sourceEndSec - sourceStartSec,
    sourceStartSec,
    sourceEndSec,
  }
}

/**
 * 秒 → 帧（Elah 使用整数帧）
 */
export function secondsToFrames(sec, fps = FPS) {
  return Math.round(sec * fps)
}

/**
 * 帧 → 秒
 */
export function framesToSeconds(frames, fps = FPS) {
  return frames / fps
}

/**
 * 加载代理 manifest
 */
export async function fetchProxyManifest() {
  try {
    const resp = await fetch(`/proxies/manifest?_t=${Date.now()}`)
    return await resp.json()
  } catch {
    return { drama: '', proxies: [] }
  }
}
