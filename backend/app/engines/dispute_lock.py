"""Pure decision logic for wish disputes (no DB access).

Mirrors app/engines/claim_lock.py: deterministic, frozen-clock testable.
A dispute binds one claim cycle: respondent (original claimer snapshot) vs
challenger. A ruling always grants the winner a FULL fresh claim TTL.
"""
from datetime import datetime, timedelta

from app.engines.claim_lock import parse_ts

RESPONDENT = "respondent"
CHALLENGER = "challenger"
ROLES = (RESPONDENT, CHALLENGER)

# dispute status
OPEN = "open"
RULED = "ruled"
TIMEOUT = "timeout"

AUTO_ARBITER = "system:auto-timeout"


def party_name(d: dict, role: str) -> str:
    """Display name of a party; respondent is the snapshot captured at filing."""
    return d[role]


def other_role(role: str) -> str:
    return CHALLENGER if role == RESPONDENT else RESPONDENT


def winner_role(d: dict) -> str | None:
    """None while the ticket is open; otherwise respondent|challenger."""
    if d.get("status") == OPEN:
        return None
    return d.get("winner")


def loser_of(d: dict) -> str | None:
    """Role of the losing party, or None while open."""
    w = winner_role(d)
    return None if w is None else other_role(w)


def dispute_allowed(status: str, binding_status: str | None,
                    claimer: str | None, challenger: str | None) -> dict:
    """Whether a fresh dispute may be filed against a claimed wish.

    binding_status is the active-bound ticket status (None/ open/ ruled/ timeout).
    """
    name = (challenger or "").strip()
    if not name:
        return {"ok": False, "reason": "challenger_required"}
    # binding checks first: a wish under an open ticket is already 'disputed',
    # and a closed ticket binds a 'claimed' cycle that must not be re-litigated
    if binding_status == OPEN:
        return {"ok": False, "reason": "already_in_dispute"}
    if binding_status in (RULED, TIMEOUT):
        return {"ok": False, "reason": "already_adjudicated"}
    if status != "claimed":
        return {"ok": False, "reason": "not_claimed"}
    if claimer and name == claimer.strip():
        return {"ok": False, "reason": "cannot_dispute_own"}
    return {"ok": True, "reason": ""}


def ruling_permitted(d: dict, now: datetime) -> dict:
    """Manual ruling is allowed only on an open ticket before its deadline."""
    if d.get("status") != OPEN:
        return {"ok": False, "reason": "dispute_closed"}
    if d.get("expires_at") and parse_ts(d["expires_at"]) <= now:
        return {"ok": False, "reason": "dispute_deadline_passed"}
    return {"ok": True, "reason": ""}


def _one_outcome(d: dict, winner: str, now: datetime, ttl_seconds: int) -> dict:
    loser = other_role(winner)
    winner_name = d[winner]
    loser_name = d[loser]
    return {
        "winner": winner,
        "loser": loser,
        "winner_name": winner_name,
        "loser_name": loser_name,
        "status_after": "claimed",
        "claimer_after": winner_name,
        "claimed_at_after": now.isoformat(),
        "expires_at_after": (now + timedelta(seconds=ttl_seconds)).isoformat(),
    }


def preview_ruling(d: dict, now: datetime, claim_ttl_seconds: int) -> dict:
    """Both possible outcomes. Pure: never writes and never mutates d."""
    return {
        RESPONDENT: _one_outcome(d, RESPONDENT, now, claim_ttl_seconds),
        CHALLENGER: _one_outcome(d, CHALLENGER, now, claim_ttl_seconds),
    }


def rule_updates(d: dict, winner: str, now: datetime, claim_ttl_seconds: int,
                 arbiter: str, arbiter_note: str | None = None) -> dict:
    """Atomic patch sets for a confirmed manual ruling (full TTL reset)."""
    if winner not in ROLES:
        raise ValueError("invalid winner role")
    if d.get("status") != OPEN:
        raise ValueError("dispute is not open")
    return {
        "dispute": {
            "id": d["id"],
            "status": RULED,
            "winner": winner,
            "ruled_at": now.isoformat(),
            "arbiter": arbiter,
            "arbiter_note": arbiter_note,
        },
        "wish": {
            "id": d["wish_id"],
            "status": "claimed",
            "claimer": d[winner],
            "claimed_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=claim_ttl_seconds)).isoformat(),
            "active_dispute_id": d["id"],
        },
    }


def timeout_due(d: dict, now: datetime) -> bool:
    return (
        d.get("status") == OPEN
        and bool(d.get("expires_at"))
        and parse_ts(d["expires_at"]) <= now
    )


def timeout_updates(d: dict, now: datetime, claim_ttl_seconds: int) -> dict:
    """Deadline passed with no ruling: original claimer wins; TTL resets too."""
    if not timeout_due(d, now):
        raise ValueError("dispute not due for timeout")
    return {
        "dispute": {
            "id": d["id"],
            "status": "timeout",
            "winner": RESPONDENT,
            "ruled_at": now.isoformat(),
            "arbiter": AUTO_ARBITER,
            "arbiter_note": None,
        },
        "wish": {
            "id": d["wish_id"],
            "status": "claimed",
            "claimer": d[RESPONDENT],
            "claimed_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=claim_ttl_seconds)).isoformat(),
            "active_dispute_id": d["id"],
        },
    }


def ban_reason(binding: dict | None, requester: str) -> str | None:
    """Claim-time rejection caused by the wish's active-bound dispute.

    open binding  -> in_dispute for everyone
    closed binding -> lost_dispute_lock for the loser (until release clears it)
    """
    if not binding:
        return None
    status = binding.get("status")
    if status == OPEN:
        return "in_dispute"
    if status in (RULED, TIMEOUT):
        loser_role = loser_of(binding)
        if loser_role and requester and requester.strip() == binding[loser_role]:
            return "lost_dispute_lock"
    return None
