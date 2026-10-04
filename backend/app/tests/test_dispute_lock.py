from datetime import datetime, timedelta, timezone

import pytest

from app.engines import dispute_lock as dl

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _ticket(status=dl.OPEN, winner=None, expires_at=None, **kw):
    d = {
        "id": 1, "wish_id": 7,
        "respondent": "alice", "challenger": "bob",
        "status": status, "winner": winner,
        "arbiter": None if status == dl.OPEN else "carol",
        "arbiter_note": None,
        "created_at": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (expires_at or (NOW + timedelta(hours=1))).isoformat(),
        "ruled_at": None if status == dl.OPEN else NOW.isoformat(),
    }
    d.update(kw)
    return d


def test_party_roles_and_verdict_helpers():
    assert dl.party_name(_ticket(), dl.RESPONDENT) == "alice"
    assert dl.party_name(_ticket(), dl.CHALLENGER) == "bob"
    assert dl.other_role(dl.RESPONDENT) == dl.CHALLENGER
    assert dl.winner_role(_ticket()) is None
    assert dl.loser_of(_ticket()) is None
    ruled = _ticket(status=dl.RULED, winner=dl.CHALLENGER)
    assert dl.winner_role(ruled) == dl.CHALLENGER
    assert dl.loser_of(ruled) == dl.RESPONDENT
    timed = _ticket(status=dl.TIMEOUT, winner=dl.RESPONDENT)
    assert dl.loser_of(timed) == dl.CHALLENGER


def test_dispute_allowed_branches():
    ok = dl.dispute_allowed("claimed", None, "alice", "bob")
    assert ok == {"ok": True, "reason": ""}
    assert dl.dispute_allowed("claimed", None, "alice", "alice ")["reason"] == "cannot_dispute_own"
    assert dl.dispute_allowed("open", None, None, "bob")["reason"] == "not_claimed"
    assert dl.dispute_allowed("fulfilled", None, None, "bob")["reason"] == "not_claimed"
    assert dl.dispute_allowed("claimed", dl.OPEN, "alice", "bob")["reason"] == "already_in_dispute"
    assert dl.dispute_allowed("claimed", dl.RULED, "alice", "bob")["reason"] == "already_adjudicated"
    assert dl.dispute_allowed("claimed", dl.TIMEOUT, "alice", "bob")["reason"] == "already_adjudicated"
    assert dl.dispute_allowed("claimed", None, "alice", "  ")["reason"] == "challenger_required"


def test_ruling_permitted_boundary():
    assert dl.ruling_permitted(_ticket(expires_at=NOW + timedelta(seconds=1)), NOW)["ok"] is True
    # now == expires_at counts as deadline passed (matches claim_lock <= semantics)
    r = dl.ruling_permitted(_ticket(expires_at=NOW), NOW)
    assert r == {"ok": False, "reason": "dispute_deadline_passed"}
    assert dl.ruling_permitted(_ticket(status=dl.RULED, winner=dl.RESPONDENT), NOW)["reason"] == "dispute_closed"


def test_preview_ruling_both_outcomes_and_no_mutation():
    d = _ticket()
    snap = dict(d)
    out = dl.preview_ruling(d, NOW, 3600)
    assert set(out.keys()) == {dl.RESPONDENT, dl.CHALLENGER}
    r = out[dl.RESPONDENT]
    assert r["winner"] == "respondent" and r["loser"] == "challenger"
    assert r["winner_name"] == "alice" and r["loser_name"] == "bob"
    assert r["status_after"] == "claimed" and r["claimer_after"] == "alice"
    ch = out[dl.CHALLENGER]
    assert ch["claimer_after"] == "bob" and ch["loser_name"] == "alice"
    assert r["claimed_at_after"] == NOW.isoformat()
    assert r["expires_at_after"] == (NOW + timedelta(seconds=3600)).isoformat()
    assert d == snap  # input untouched, ticket still open


def test_rule_updates_full_ttl_reset_for_either_winner():
    stale = _ticket(expires_at=NOW - timedelta(hours=5))
    for role, name in ((dl.RESPONDENT, "alice"), (dl.CHALLENGER, "bob")):
        u = dl.rule_updates(stale, role, NOW, 86400, "carol")
        assert u["dispute"]["status"] == dl.RULED and u["dispute"]["winner"] == role
        w = u["wish"]
        assert w["status"] == "claimed" and w["claimer"] == name
        assert w["claimed_at"] == NOW.isoformat()
        assert w["expires_at"] == (NOW + timedelta(seconds=86400)).isoformat()
        assert w["active_dispute_id"] == stale["id"]
    with pytest.raises(ValueError):
        dl.rule_updates(_ticket(status=dl.RULED, winner=dl.RESPONDENT), dl.RESPONDENT, NOW, 10, "c")
    with pytest.raises(ValueError):
        dl.rule_updates(_ticket(), "someone_else", NOW, 10, "c")


def test_timeout_due_and_updates():
    assert dl.timeout_due(_ticket(expires_at=NOW + timedelta(seconds=1)), NOW) is False
    assert dl.timeout_due(_ticket(expires_at=NOW), NOW) is True
    with pytest.raises(ValueError):
        dl.timeout_updates(_ticket(expires_at=NOW + timedelta(seconds=1)), NOW, 100)
    u = dl.timeout_updates(_ticket(expires_at=NOW - timedelta(seconds=1)), NOW, 86400)
    assert u["dispute"]["status"] == dl.TIMEOUT
    assert u["dispute"]["winner"] == dl.RESPONDENT
    assert u["dispute"]["arbiter"] == dl.AUTO_ARBITER
    assert u["wish"]["claimer"] == "alice"
    assert u["wish"]["expires_at"] == (NOW + timedelta(seconds=86400)).isoformat()


def test_ban_reason():
    assert dl.ban_reason(None, "bob") is None
    assert dl.ban_reason(_ticket(), "alice") == "in_dispute"
    ruled = _ticket(status=dl.RULED, winner=dl.CHALLENGER)  # alice lost
    assert dl.ban_reason(ruled, "alice") == "lost_dispute_lock"
    assert dl.ban_reason(ruled, "alice ") == "lost_dispute_lock"
    assert dl.ban_reason(ruled, "bob") is None       # winner
    assert dl.ban_reason(ruled, "carol") is None     # third party
