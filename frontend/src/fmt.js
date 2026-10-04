export function left(ts, now = Date.now()) {
  if (!ts) return ''
  const s = Math.max(0, Math.floor((new Date(ts).getTime() - now) / 1000))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${ss}s`
  return `${ss}s`
}
