import { ref, computed } from 'vue'

function pad(n) { return String(n).padStart(2, '0') }

function format(ms) {
  if (ms <= 0) return '已截止'
  const s = Math.floor(ms / 1000)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (d > 0) return `${d}天${pad(h)}时${pad(m)}分`
  if (h > 0) return `${pad(h)}:${pad(m)}:${pad(sec)}`
  return `${pad(m)}:${pad(sec)}`
}

// One shared 1s ticker for every countdown on the page (wall has many cards).
const tick = ref(Date.now())
let started = false
function ensureTicker() {
  if (!started && typeof window !== 'undefined') {
    started = true
    setInterval(() => { tick.value = Date.now() }, 1000)
  }
}

// Live countdown to an ISO timestamp. getTarget may be a getter/ref so the
// display switches automatically between claim and dispute deadlines.
export function useCountdown(getTarget) {
  ensureTicker()
  const target = computed(() => {
    const iso = typeof getTarget === 'function' ? getTarget() : getTarget
    return iso ? Date.parse(iso) : NaN
  })
  const text = computed(() => {
    tick.value // subscribe
    return Number.isNaN(target.value) ? '' : format(target.value - Date.now())
  })
  const expired = computed(() => {
    tick.value
    return !Number.isNaN(target.value) && target.value <= Date.now()
  })
  return { text, expired }
}
