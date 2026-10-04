import { ref, watch } from 'vue'

// Single shared display name across Detail/Mine (identity is a free-text
// string in this app; localStorage is its only persistence).
export const identity = ref(localStorage.getItem('wc_name') || '访客')

watch(identity, v => localStorage.setItem('wc_name', (v || '').trim() || '访客'))
