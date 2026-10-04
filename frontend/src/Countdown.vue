<template>
  <span class="countdown" :class="{ warn }">{{ prefix }}{{ cd.text }}</span>
</template>
<script setup>
import { useCountdown } from './useCountdown'

const props = defineProps({
  iso: { type: String, default: null },
  prefix: { type: String, default: '' },
  warn: { type: Boolean, default: false },
})
const cd = useCountdown(() => props.iso)
</script>
