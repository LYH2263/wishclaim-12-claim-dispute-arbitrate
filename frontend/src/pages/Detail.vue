<template>
  <div class="wall">
    <h1 class="serif">{{ w.title }}</h1>
    <p>{{ w.note }}</p>
    <p class="tag">状态 {{ w.status }} · 认领人 {{ w.claimer || '—' }}<template v-if="w.status==='claimed'"> · 剩 {{ left(w.expires_at, tick) }}</template></p>
    <p v-if="err" class="err">{{ err }}</p>

    <section v-if="w.dispute" class="panel dispute-panel">
      <h3 class="serif">争议中</h3>
      <p>{{ w.dispute.challenger }} 挑战 {{ w.dispute.original_claimer }} 的认领 · 截止剩 {{ left(w.dispute.deadline_at, tick) }}</p>
      <p class="tag">截止未裁决将自动维持原认领人，挑战者记败诉；争议中任何人不得直接认领。</p>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <select v-model="winner">
          <option :value="w.dispute.original_claimer">{{ w.dispute.original_claimer }}（原认领人）</option>
          <option :value="w.dispute.challenger">{{ w.dispute.challenger }}（挑战者）</option>
        </select>
        <button class="ghost" @click="preview">裁决预览</button>
        <button @click="confirm">确认裁决</button>
      </div>
      <div v-if="pv" class="panel">
        <p>预览：胜者 {{ pv.winner }} · 败者 {{ pv.loser }}</p>
        <p class="tag">确认后 {{ pv.winner }} 成为唯一认领人，认领期重开满额（截止 {{ pv.expires_at_after }}）；{{ pv.loser }} 记败诉且释放前不得再认领。预览不落库。</p>
      </div>
    </section>

    <input v-model="claimer" placeholder="你的名字" />
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button v-if="!w.dispute" @click="claim">认领锁定</button>
      <button v-if="!w.dispute && w.status==='claimed' && w.claimer && w.claimer!==claimer" class="ghost" @click="openDispute">发起争议</button>
      <button class="ghost" @click="release">释放</button>
      <button class="ghost" @click="fulfill">核销完成</button>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { left } from '../fmt'
const props = defineProps({ id: String })
const w = ref({})
const claimer = ref('访客')
const winner = ref('')
const pv = ref(null)
const err = ref('')
const tick = ref(Date.now())
let timer
async function load() {
  w.value = await api('/wishes/' + props.id)
  if (w.value.dispute) winner.value = w.value.dispute.challenger
  pv.value = null
}
async function claim() {
  err.value=''; try { await api('/wishes/'+props.id+'/claim',{method:'POST',body:JSON.stringify({claimer:claimer.value})}); await load() } catch(e){ err.value=e.message }
}
async function release() {
  err.value=''; try { await api('/wishes/'+props.id+'/release',{method:'POST',body:'{}'}); await load() } catch(e){ err.value=e.message }
}
async function fulfill() {
  err.value=''; try { await api('/wishes/'+props.id+'/fulfill',{method:'POST',body:'{}'}); await load() } catch(e){ err.value=e.message }
}
async function openDispute() {
  err.value=''; try { await api('/wishes/'+props.id+'/disputes',{method:'POST',body:JSON.stringify({challenger:claimer.value})}); await load() } catch(e){ err.value=e.message }
}
async function preview() {
  err.value=''; try { pv.value = await api('/disputes/'+w.value.dispute.id+'/preview?winner='+encodeURIComponent(winner.value)) } catch(e){ err.value=e.message }
}
async function confirm() {
  err.value=''; try { await api('/disputes/'+w.value.dispute.id+'/adjudicate',{method:'POST',body:JSON.stringify({winner:winner.value})}); await load() } catch(e){ err.value=e.message }
}
onMounted(async () => {
  await load()
  timer = setInterval(() => { tick.value = Date.now() }, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>
