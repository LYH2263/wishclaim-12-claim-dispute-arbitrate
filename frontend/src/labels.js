export const STATUS = {
  open: '待认领',
  claimed: '已锁定',
  released: '已释放',
  fulfilled: '已核销',
  disputed: '争议中',
}

export const ROLE = {
  respondent: '原认领人',
  challenger: '挑战者',
}

export const VERDICT = {
  open: '争议中',
  won: '胜诉',
  lost: '败诉',
}

export const RULE_LABELS = {
  mutex: '互斥认领',
  ttl: '认领超时',
  fulfill: '核销',
  dispute_window: '争议时限',
  dispute_exclusive: '争议独占',
  ruling_ttl_reset: '裁决重置 TTL',
  loser_lockout: '败诉锁定',
  timeout_keeps: '超时原判',
  claimer_change: '禁止私换认领人',
}
