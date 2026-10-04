"""裁决：预览（不落库）+ 确认（条件更新写锁，单事务生效）。

expires_at 拍板：重开满额（restart_full）——无论胜者是原认领人还是挑战者，
确认裁决后 expires_at = 裁决时刻 + 完整 ttl_seconds，墙卡/详情/规则倒计时同源。
无争议单（或单已关闭）直接改 claimer 一律拒绝。
"""
from datetime import datetime, timedelta

from app.modules.dispute_ticket import (
    ADJUDICATED, CONFIRMED, OPEN, DisputeError, get_dispute,
)

TTL_POLICY = "restart_full"  # 重开满额
LOSER_EFFECT = "lost_record_and_banned_until_release"  # 败诉记录 + 释放前禁认

def _parties(dispute, winner: str) -> tuple[str, str]:
    pair = [dispute["original_claimer"], dispute["challenger"]]
    if winner not in pair:
        raise DisputeError("winner_not_party")
    loser = pair[0] if winner == pair[1] else pair[1]
    return winner, loser

def preview_verdict(dispute, winner: str, now: datetime, ttl_seconds: int) -> dict:
    """裁决预览：给出胜者与败者结果，不改 claimer、不写库。"""
    if dispute is None:
        raise DisputeError("no_dispute_ticket")
    if dispute["status"] != OPEN:
        raise DisputeError("dispute_closed")
    winner, loser = _parties(dispute, winner)
    return {
        "dispute_id": dispute["id"],
        "winner": winner,
        "loser": loser,
        "claimer_after": winner,
        "expires_at_after": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        "ttl_policy": TTL_POLICY,
        "loser_effect": LOSER_EFFECT,
        "changes_claimer_now": False,
    }

def adjudicate(c, dispute_id: int, winner: str, now: datetime, ttl_seconds: int) -> dict:
    """确认裁决：CAS 写锁翻单，胜者成为唯一 claimer，expires_at 重开满额。"""
    dispute = get_dispute(c, dispute_id)
    if dispute is None:
        raise DisputeError("no_dispute_ticket")
    if dispute["status"] != OPEN:
        raise DisputeError("dispute_closed")
    winner, loser = _parties(dispute, winner)
    wish = c.execute("SELECT * FROM wishes WHERE id=?", (dispute["wish_id"],)).fetchone()
    if not wish or wish["status"] != "claimed" or wish["claimer"] != dispute["original_claimer"]:
        raise DisputeError("dispute_moot")
    # 写锁：仅当单仍为 open 才翻单；并发/重复确认只有一方生效
    cur = c.execute(
        "UPDATE disputes SET status=?, resolution=?, decided_at=?, winner=?, loser=?"
        " WHERE id=? AND status=?",
        (ADJUDICATED, CONFIRMED, now.isoformat(), winner, loser, dispute_id, OPEN))
    if cur.rowcount == 0:
        raise DisputeError("dispute_closed")
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    c.execute(
        "UPDATE wishes SET status='claimed', claimer=?, claimed_at=?, expires_at=? WHERE id=?",
        (winner, now.isoformat(), expires_at, dispute["wish_id"]))
    return {
        "dispute_id": dispute_id,
        "wish_id": dispute["wish_id"],
        "winner": winner,
        "loser": loser,
        "claimer": winner,
        "expires_at": expires_at,
        "ttl_policy": TTL_POLICY,
        "loser_effect": LOSER_EFFECT,
    }
