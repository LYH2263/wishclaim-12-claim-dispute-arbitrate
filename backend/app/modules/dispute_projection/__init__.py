"""投影：把 wishes + disputes 投影为墙卡、详情、「我的认领」视图；败诉禁认判定。

败诉禁认：争议已裁决（含到期自动维持原认领人）且胜者仍持有该愿望时，
败者不得再 claim/再争议该行；愿望释放（含 TTL 自动释放）后禁令自动解除。
"""
from datetime import datetime

from app.engines.claim_lock import parse_ts
from app.modules.dispute_ticket import ADJUDICATED, EXPIRED, OPEN

RESOLVED = (ADJUDICATED, EXPIRED)

def seconds_left(ts: str | None, now: datetime) -> int | None:
    if not ts:
        return None
    return max(0, int((parse_ts(ts) - now).total_seconds()))

def dispute_view(d, now: datetime) -> dict:
    return {
        "id": d["id"],
        "wish_id": d["wish_id"],
        "status": d["status"],
        "resolution": d["resolution"],
        "original_claimer": d["original_claimer"],
        "challenger": d["challenger"],
        "deadline_at": d["deadline_at"],
        "deadline_left_s": seconds_left(d["deadline_at"], now) if d["status"] == OPEN else None,
        "winner": d["winner"],
        "loser": d["loser"],
        "decided_at": d["decided_at"],
    }

def wish_view(w, open_dispute, now: datetime) -> dict:
    """墙卡/详情投影：争议中挂 dispute 视图，认领中带统一倒计时字段。"""
    out = dict(w)
    out["dispute"] = dispute_view(open_dispute, now) if open_dispute else None
    out["claim_left_s"] = seconds_left(w["expires_at"], now) if w["status"] == "claimed" else None
    return out

def active_ban(c, wish_id: int, person: str):
    """返回生效中的败诉禁认单；无则 None。胜者仍持有 → 禁令生效，直至释放。"""
    w = c.execute("SELECT * FROM wishes WHERE id=?", (wish_id,)).fetchone()
    if not w or w["status"] != "claimed" or not w["claimer"] or not person:
        return None
    return c.execute(
        "SELECT * FROM disputes WHERE wish_id=? AND loser=? AND winner=? AND status IN (?,?)"
        " ORDER BY id DESC LIMIT 1",
        (wish_id, person, w["claimer"], ADJUDICATED, EXPIRED)).fetchone()

def _role_result(d, person: str) -> tuple[str, str]:
    role = "challenger" if d["challenger"] == person else "original"
    if d["status"] == OPEN:
        return role, "pending"
    if d["winner"] is None:
        return role, "moot"
    return role, ("won" if d["winner"] == person else "lost")

def mine_view(c, person: str, now: datetime) -> dict:
    """「我的认领」投影：当前认领 + 争议记录（败诉留痕，标注是否仍被禁认）。"""
    claims = [dict(r) for r in c.execute(
        "SELECT * FROM wishes WHERE claimer=? ORDER BY id DESC", (person,))]
    disputes = []
    for d in c.execute(
            "SELECT * FROM disputes WHERE challenger=? OR original_claimer=? ORDER BY id DESC",
            (person, person)).fetchall():
        v = dispute_view(d, now)
        v["role"], v["result"] = _role_result(d, person)
        v["wish_title"] = (c.execute("SELECT title FROM wishes WHERE id=?",
                                     (d["wish_id"],)).fetchone() or {"title": "?"})["title"]
        v["ban_active"] = active_ban(c, d["wish_id"], person) is not None
        disputes.append(v)
    return {"claims": claims, "disputes": disputes}
