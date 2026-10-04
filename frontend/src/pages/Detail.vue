<template>
  <div class="wall">
    <h1 class="serif">{{ w.title || '（无标题）' }}</h1>
    <p>{{ w.note }}</p>
    <p>
      <span class="badge" :class="'b-'+w.status">{{ STATUS[w.status] || w.status }}</span>
      <span class="tag" style="margin-left:8px">认领人 {{ w.claimer || '—' }}</span>
    </p>
    <Countdown v-if="openDispute" :iso="openDispute.expires_at" prefix="争议截止 " warn />
    <Countdown v-else-if="w.status === 'claimed'" :iso="w.expires_at" prefix="认领剩余 " />
    <p v-if="err" class="err">{{ err }}</p>

    <input v-model="identity" placeholder="你的名字" />

    <!-- active dispute: arbitration panel -->
    <div v-if="openDispute" class="banner">
      <strong>争议处理中</strong>
      <p class="tag">原认领人 {{ openDispute.respondent }} ｜ 挑战者 {{ openDispute.challenger }}</p>
      <p class="tag">逾期未裁决将自动判原认领人（{{ openDispute.respondent }}）胜诉，认领期限重新满额起算</p>
      <button class="ghost" @click="fetchPreview">获取裁决预览</button>
      <div v-if="preview">
        <div v-for="role in ['respondent','challenger']" :key="role"
             class="outcome" :class="{ selected: picked === role }"
             @click="picked = role">
          <strong>{{ ROLE[role] }}（{{ preview.outcomes[role].winner_name }}）胜诉</strong>
          <div class="tag">败方：{{ preview.outcomes[role].loser_name }}</div>
          <div class="tag">裁决后认领人：{{ preview.outcomes[role].claimer_after }}</div>
          <div class="tag">新到期时刻：{{ fmt(preview.outcomes[role].expires_at_after) }}（满额重开）</div>
        </div>
        <p class="tag">预览不改变当前认领人；到期时刻以实际裁决时刻重新计时</p>
        <input v-model="arbiter" placeholder="裁决者名字（任何人可裁决，将记录在案）" />
        <input v-model="note" placeholder="裁决备注（可选）" />
        <button :disabled="!picked" @click="confirmRule">确认裁决：{{ picked ? ROLE[picked] + '胜诉' : '请先选择胜方' }}</button>
      </div>
    </div>

    <!-- closed dispute: verdict banner -->
    <div v-else-if="closedDispute" class="banner closed">
      <strong>{{ closedDispute.winner_name }} 胜诉</strong>
      <span class="tag">（{{ closedDispute.kind === 'auto' ? '超时自动裁决' : '仲裁人 ' + closedDispute.arbiter }}）</span>
      <p v-if="iLost" class="err">你在本单争议中败诉，该认领释放前不能再次认领</p>
    </div>

    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
      <button :disabled="!!openDispute" @click="claim">认领锁定</button>
      <button class="ghost" :disabled="!!openDispute" @click="release">释放</button>
      <button class="ghost" :disabled="!!openDispute" @click="fulfill">核销完成</button>
      <button class="ghost" v-if="canDispute" @click="openDisputeAction">发起争议</button>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { identity } from '../identity'
import { usePoll } from '../usePoll'
import { STATUS, ROLE } from '../labels'
import Countdown from '../Countdown.vue'

const props = defineProps({ id: String })
const w = ref({})
const err = ref('')
const arbiter = ref(identity.value)
const note = ref('')
const preview = ref(null)
const picked = ref(null)

const openDispute = computed(() =>
  w.value.dispute && w.value.dispute.status === 'open' ? w.value.dispute : null)
const closedDispute = computed(() =>
  w.value.dispute && w.value.dispute.status !== 'open' ? w.value.dispute : null)
const canDispute = computed(() =>
  w.value.status === 'claimed' && !w.value.dispute
  && identity.value.trim() && identity.value.trim() !== (w.value.claimer || '').trim())
const iLost = computed(() =>
  closedDispute.value && closedDispute.value.loser_name === identity.value.trim())

function fmt(iso) { return iso ? iso.replace('T', ' ').replace('+00:00', ' UTC') : '—' }

async function load() {
  w.value = await api('/wishes/' + props.id)
  arbiter.value = arbiter.value || identity.value
}
async function act(path, body) {
  err.value = ''
  try { await api(path, { method: 'POST', body: JSON.stringify(body) }); await load() }
  catch (e) { err.value = e.message }
}
function claim() { act('/wishes/' + props.id + '/claim', { claimer: identity.value }) }
function release() { act('/wishes/' + props.id + '/release', {}) }
function fulfill() { act('/wishes/' + props.id + '/fulfill', {}) }
async function openDisputeAction() {
  preview.value = null; picked.value = null
  await act('/wishes/' + props.id + '/dispute', { challenger: identity.value })
}
async function fetchPreview() {
  err.value = ''
  try {
    preview.value = await api('/wishes/' + props.id + '/dispute/preview')
    if (!picked.value) picked.value = null
  } catch (e) { err.value = e.message }
}
async function confirmRule() {
  err.value = ''
  try {
    await api('/disputes/' + openDispute.value.id + '/rule', {
      method: 'POST',
      body: JSON.stringify({ winner: picked.value, arbiter: arbiter.value, arbiter_note: note.value || null }),
    })
    preview.value = null; picked.value = null; note.value = ''
    await load()
  } catch (e) { err.value = e.message }
}

onMounted(load)
usePoll(load)
</script>
