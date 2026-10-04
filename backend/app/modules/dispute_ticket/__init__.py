"""争议单：发起、查询、到期扫尾。

争议单是对同一愿望认领权的唯一异议凭证；无争议单不得变更 claimer。
到期扫尾拍板：截止未裁决 → 自动维持原认领人（auto_keep_original），挑战者记败诉；
愿望在争议期间被释放/核销/易主 → 争议作废（moot），无胜负。
"""
from datetime import datetime, timedelta

from app.engines.claim_lock import parse_ts

OPEN = "open"
ADJUDICATED = "adjudicated"
EXPIRED = "expired"

CONFIRMED = "confirmed"                # 手动确认裁决
AUTO_KEEP_ORIGINAL = "auto_keep_original"  # 拍板：截止未裁决自动维持原认领人
MOOT = "moot"                          # 愿望已释放/核销/易主，争议作废

class DisputeError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)

def deadline_for(now: datetime, dispute_ttl_seconds: int) -> str:
    return (now + timedelta(seconds=dispute_ttl_seconds)).isoformat()

def get_dispute(c, did: int):
    return c.execute("SELECT * FROM disputes WHERE id=?", (did,)).fetchone()

def open_dispute_for(c, wish_id: int):
    return c.execute(
        "SELECT * FROM disputes WHERE wish_id=? AND status=? ORDER BY id DESC LIMIT 1",
        (wish_id, OPEN)).fetchone()

def open_disputes_map(c) -> dict:
    return {r["wish_id"]: r for r in c.execute("SELECT * FROM disputes WHERE status=?", (OPEN,))}

def create_dispute(c, wish, challenger: str, now: datetime, dispute_ttl_seconds: int) -> int:
    """对已认领愿望开争议单；返回新单 id。wish 为 wishes 行。"""
    if not challenger:
        raise DisputeError("challenger_required")
    if wish["status"] != "claimed" or not wish["claimer"]:
        raise DisputeError("not_claimed")
    if challenger == wish["claimer"]:
        raise DisputeError("self_dispute")
    if open_dispute_for(c, wish["id"]):
        raise DisputeError("already_disputed")
    cur = c.execute(
        "INSERT INTO disputes(wish_id,original_claimer,challenger,status,resolution,created_at,deadline_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (wish["id"], wish["claimer"], challenger, OPEN, None,
         now.isoformat(), deadline_for(now, dispute_ttl_seconds)))
    return cur.lastrowid

def _close(c, did: int, status: str, resolution: str, now: datetime,
           winner: str | None, loser: str | None):
    c.execute(
        "UPDATE disputes SET status=?, resolution=?, decided_at=?, winner=?, loser=? WHERE id=?",
        (status, resolution, now.isoformat(), winner, loser, did))

def sweep_disputes(c, now: datetime) -> list[int]:
    """到期扫尾：截止未裁决 → 自动维持原认领人，挑战者记败诉；愿望易主/释放 → 作废。"""
    closed = []
    for d in c.execute("SELECT * FROM disputes WHERE status=?", (OPEN,)).fetchall():
        w = c.execute("SELECT * FROM wishes WHERE id=?", (d["wish_id"],)).fetchone()
        held = w and w["status"] == "claimed" and w["claimer"] == d["original_claimer"]
        if not held:
            _close(c, d["id"], EXPIRED, MOOT, now, None, None)
            closed.append(d["id"])
        elif parse_ts(d["deadline_at"]) <= now:
            _close(c, d["id"], EXPIRED, AUTO_KEEP_ORIGINAL, now,
                   d["original_claimer"], d["challenger"])
            closed.append(d["id"])
    return closed
