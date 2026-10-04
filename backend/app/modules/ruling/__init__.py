"""裁决写锁模块：atomic write transactions for dispute filing and rulings.

All multi-statement mutations go through BEGIN IMMEDIATE here so check-then-act
races (duplicate disputes, ruling vs. timeout) are impossible to interleave.
Pure decisions live in app/engines/dispute_lock.py.
"""
from contextlib import contextmanager

from app.db import connect
from app.engines import dispute_lock as dl
from app.modules import dispute as tickets


class DisputeError(Exception):
    def __init__(self, status_code: int, reason: str):
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason


@contextmanager
def tx():
    """sqlite3 defaults to a deferred transaction; switch to autocommit mode
    (isolation_level=None) so we can issue an explicit BEGIN IMMEDIATE."""
    c = connect()
    c.isolation_level = None
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def file_atomic(wish_id: int, challenger: str, now, dispute_ttl_seconds: int) -> dict:
    """Create a dispute ticket and flip the wish into disputed in one txn."""
    challenger = (challenger or "").strip()
    with tx() as c:
        r = c.execute("SELECT * FROM wishes WHERE id=?", (wish_id,)).fetchone()
        if not r:
            raise DisputeError(404, "not found")
        w = dict(r)
        binding = tickets.active_for_wish(c, wish_id)
        allowed = dl.dispute_allowed(
            w["status"], binding["status"] if binding else None,
            w["claimer"], challenger)
        if not allowed["ok"]:
            code = 400 if allowed["reason"] in (
                "not_claimed", "cannot_dispute_own", "challenger_required") else 409
            raise DisputeError(code, allowed["reason"])
        t = tickets.create(c, wish_id, w["claimer"], challenger, now, dispute_ttl_seconds)
        cur = c.execute(
            "UPDATE wishes SET status='disputed', active_dispute_id=? WHERE id=? "
            "AND status='claimed' AND active_dispute_id IS NULL",
            (t["id"], wish_id))
        if cur.rowcount != 1:
            raise DisputeError(409, "already_in_dispute")
        return t


def sweep_timeouts(c, now, claim_ttl_seconds: int) -> list[dict]:
    """Auto-rule every due dispute in favor of the original claimer.

    Usable inside an open BEGIN IMMEDIATE transaction or the request's own
    connection. A timeout is a ruling, so the claim TTL resets in full.
    """
    applied = []
    for d in tickets.list_open_due(c, now):
        updates = dl.timeout_updates(d, now, claim_ttl_seconds)
        if tickets.apply_ruling(c, updates) != 1:
            continue
        if tickets.apply_wish(c, updates) != 1:
            raise DisputeError(500, "wish_dispute_binding_lost")
        applied.append(updates)
    return applied


def rule_atomic(dispute_id: int, winner: str, arbiter: str,
                arbiter_note: str | None, now, claim_ttl_seconds: int) -> dict:
    """Confirm a manual ruling. Timeout sweep runs INSIDE this transaction so a
    deadline expiry can never be overwritten by a late manual ruling."""
    arbiter = (arbiter or "").strip()
    if not arbiter:
        raise DisputeError(400, "arbiter_required")
    if winner not in dl.ROLES:
        raise DisputeError(422, "invalid_winner")
    with tx() as c:
        sweep_timeouts(c, now, claim_ttl_seconds)
        d = tickets.get(c, dispute_id)
        if not d:
            raise DisputeError(404, "dispute_not_found")
        permitted = dl.ruling_permitted(d, now)
        if not permitted["ok"]:
            raise DisputeError(409, "dispute_closed")
        try:
            updates = dl.rule_updates(d, winner, now, claim_ttl_seconds,
                                      arbiter, arbiter_note)
        except ValueError:
            raise DisputeError(409, "dispute_closed")
        if tickets.apply_ruling(c, updates) != 1:
            raise DisputeError(409, "dispute_closed")
        if tickets.apply_wish(c, updates) != 1:
            raise DisputeError(500, "wish_dispute_binding_lost")
        return updates
