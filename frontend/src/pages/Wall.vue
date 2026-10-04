<template>
  <div class="wall">
    <h1 class="serif">愿望墙</h1>
    <p class="tag">无顶栏 · 瀑布流 · 点卡片认领</p>
    <div class="masonry">
      <article v-for="w in rows" :key="w.id" class="card" @click="$router.push('/wishes/'+w.id)">
        <h3>{{ w.title || '（无标题）' }}</h3>
        <p>{{ w.note }}</p>
        <span class="badge" :class="'b-'+w.status">{{ STATUS[w.status] || w.status }}</span>
        <p class="tag">认领人 {{ w.claimer || '—' }}</p>
        <div v-if="w.dispute && w.dispute.status === 'open'" class="banner">
          <strong>争议中</strong>
          <div class="tag">原认领人 {{ w.dispute.respondent }} vs 挑战者 {{ w.dispute.challenger }}</div>
          <Countdown :iso="w.dispute.expires_at" prefix="争议截止 " warn />
        </div>
        <Countdown v-else-if="w.status === 'claimed'" :iso="w.expires_at" prefix="认领剩余 " />
      </article>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
import { usePoll } from '../usePoll'
import { STATUS } from '../labels'
import Countdown from '../Countdown.vue'

const rows = ref([])
async function load() { rows.value = await api('/wishes') }
onMounted(load)
usePoll(load)
</script>
