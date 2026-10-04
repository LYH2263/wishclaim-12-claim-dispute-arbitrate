import { onMounted, onUnmounted } from 'vue'

// Poll a loader on an interval. The page still does its own immediate
// onMounted(load); this only covers third-party changes and deadline sweeps.
export function usePoll(fn, ms = 15000) {
  let timer = null
  onMounted(() => { timer = setInterval(fn, ms) })
  onUnmounted(() => clearInterval(timer))
}
