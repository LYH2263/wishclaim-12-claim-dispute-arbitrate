<template>
  <div class="wall">
    <h1 class="serif">愿望墙</h1>
    <p class="tag">无顶栏 · 瀑布流 · 点卡片认领</p>
    <div class="masonry">
      <article v-for="w in rows" :key="w.id" class="card" @click="$router.push('/wishes/'+w.id)">
        <h3>{{ w.title || '（无标题）' }}</h3>
        <p>{{ w.note }}</p>
        <span v-if="w.dispute" class="tag dispute">
          争议中 · {{ w.dispute.challenger }} 挑战 {{ w.dispute.original_claimer }} · 截止剩 {{ left(w.dispute.deadline_at, tick) }}
        </span>
        <span v-else-if="w.status === 'claimed'" class="tag">
          claimed · {{ w.claimer }} · 剩 {{ left(w.expires_at, tick) }}
        </span>
        <span v-else class="tag">{{ w.status }} · {{ w.data_quality }}</span>
      </article>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { left } from '../fmt'
const rows = ref([])
const tick = ref(Date.now())
let timer
onMounted(async () => {
  rows.value = await api('/wishes')
  timer = setInterval(() => { tick.value = Date.now() }, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>
