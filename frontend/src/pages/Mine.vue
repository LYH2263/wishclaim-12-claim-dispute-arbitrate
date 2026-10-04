<template>
  <div class="wall">
    <h1 class="serif">我的认领</h1>
    <input v-model="name" @change="load" placeholder="认领人名" />
    <article v-for="w in claims" :key="w.id" class="card">
      <h3>{{ w.title }}</h3>
      <span class="tag">{{ w.status }} · 到期 {{ w.expires_at }}</span>
    </article>
    <h2 class="serif">争议记录</h2>
    <article v-for="d in disputes" :key="d.id" class="card">
      <h3>{{ d.wish_title }}</h3>
      <span class="tag" :class="{dispute: d.result==='lost'}">
        {{ d.role === 'challenger' ? '我发起' : '我被挑战' }} · {{ label(d) }}
      </span>
      <p v-if="d.result==='lost' && d.ban_active" class="tag">败诉：该愿望释放前不得再次认领</p>
    </article>
    <p v-if="!disputes.length" class="tag">暂无争议记录</p>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const name = ref('访客')
const claims = ref([])
const disputes = ref([])
function label(d) {
  if (d.result === 'pending') return '争议中 · 截止 ' + d.deadline_at
  if (d.result === 'moot') return '已作废'
  return d.result === 'won' ? '胜诉' : '败诉'
}
async function load() {
  const r = await api('/mine?claimer=' + encodeURIComponent(name.value))
  claims.value = r.claims
  disputes.value = r.disputes
}
onMounted(load)
</script>
