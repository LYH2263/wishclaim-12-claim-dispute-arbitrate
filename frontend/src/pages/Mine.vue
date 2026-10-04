<template>
  <div class="wall">
    <h1 class="serif">我的认领</h1>
    <input v-model="identity" placeholder="认领人名" />
    <article v-for="w in rows" :key="w.id" class="card">
      <h3>{{ w.title }}</h3>
      <span class="badge" :class="'b-'+w.status">{{ STATUS[w.status] || w.status }}</span>
      <div class="tag">认领人 {{ w.claimer || '—' }}</div>
      <Countdown v-if="w.dispute && w.dispute.status === 'open'" :iso="w.dispute.expires_at" prefix="争议截止 " warn />
      <Countdown v-else-if="w.status === 'claimed'" :iso="w.expires_at" prefix="认领剩余 " />
      <div v-if="w.my_roles && w.my_roles.length" style="margin-top:6px">
        <span v-for="r in w.my_roles" :key="r.dispute_id"
              class="chip" :class="r.verdict === 'won' ? 'chip-won' : ('chip-' + r.verdict)">
          {{ VERDICT[r.verdict] }}·{{ ROLE[r.role] }}<template v-if="r.auto">（超时自动）</template>
        </span>
      </div>
    </article>
  </div>
</template>
<script setup>
import { ref, watch, onMounted } from 'vue'
import { api } from '../api'
import { identity } from '../identity'
import { usePoll } from '../usePoll'
import { STATUS, ROLE, VERDICT } from '../labels'
import Countdown from '../Countdown.vue'

const rows = ref([])
async function load() {
  rows.value = await api('/mine?claimer=' + encodeURIComponent(identity.value))
}
watch(identity, load)
onMounted(load)
usePoll(load)
</script>
