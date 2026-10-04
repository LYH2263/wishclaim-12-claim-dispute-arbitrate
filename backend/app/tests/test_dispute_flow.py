"""SQLite-backed flow tests. Route handlers are called directly (they are plain
functions), so no httpx/TestClient dependency is needed."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app import seed
from app.db import connect
from app.main import (
    claim, dispute, dispute_preview, rule, release, fulfill,
    list_wishes, get_wish, mine, ClaimIn, DisputeIn, RuleIn,
)

SEED_DISPUTABLE = 5  # 待争议样例: claimed by alice, future expiry
SEED_EXPIRED = 4     # 过期锁样例: claimed by ghost, 2020 expiry


def _expect(status_code, fn, *args):
    with pytest.raises(HTTPException) as ei:
        fn(*args)
    assert ei.value.status_code == status_code
    return ei.value.detail


def _backdate(dispute_id=None, wish_id=None, ts="2020-01-01T00:00:00+00:00"):
    c = connect()
    if dispute_id is not None:
        c.execute("UPDATE disputes SET expires_at=? WHERE id=?", (ts, dispute_id))
    if wish_id is not None:
        c.execute("UPDATE wishes SET expires_at=? WHERE id=?", (ts, wish_id))
    c.commit(); c.close()


def test_schema_idempotent_and_setting_backfill():
    seed.init_db()  # existing seeded db: must not duplicate or error
    seed.init_db()
    c = connect()
    cols = {r["name"] for r in c.execute("PRAGMA table_info(wishes)")}
    assert "active_dispute_id" in cols
    assert c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='disputes'").fetchone()
    assert c.execute("SELECT value FROM settings WHERE key='dispute_ttl_seconds'").fetchone()["value"] == "86400"
    c.execute("DELETE FROM settings WHERE key='dispute_ttl_seconds'"); c.commit()
    c.close()
    seed.init_db()
    c = connect()
    assert c.execute("SELECT value FROM settings WHERE key='dispute_ttl_seconds'").fetchone()["value"] == "86400"
    c.close()


def test_challenger_wins_full_lifecycle():
    t = dispute(SEED_DISPUTABLE, DisputeIn(challenger="bob"))
    assert t["status"] == "open" and t["respondent"] == "alice" and t["challenger"] == "bob"

    w = get_wish(SEED_DISPUTABLE)
    assert w["status"] == "disputed" and w["claimer"] == "alice"
    assert w["dispute"]["status"] == "open"
    # third party AND original claimer are blocked; release/fulfill suspended
    assert _expect(409, claim, SEED_DISPUTABLE, ClaimIn(claimer="carol")) == "in_dispute"
    assert _expect(409, claim, SEED_DISPUTABLE, ClaimIn(claimer="alice")) == "in_dispute"
    assert _expect(400, release, SEED_DISPUTABLE) == "in_dispute"
    assert _expect(400, fulfill, SEED_DISPUTABLE) == "in_dispute"

    # preview is read-only
    pv = dispute_preview(SEED_DISPUTABLE, "challenger")
    assert pv["selected"] == "challenger"
    assert pv["outcomes"]["challenger"]["claimer_after"] == "bob"
    assert pv["outcomes"]["respondent"]["claimer_after"] == "alice"
    w = get_wish(SEED_DISPUTABLE)
    assert w["status"] == "disputed" and w["claimer"] == "alice"

    res = rule(t["id"], RuleIn(winner="challenger", arbiter="carol"))
    assert res["wish"]["claimer"] == "bob" and res["wish"]["status"] == "claimed"
    w = get_wish(SEED_DISPUTABLE)
    assert w["claimer"] == "bob" and w["dispute"]["winner"] == "challenger"
    assert w["dispute"]["kind"] == "manual"
    exp = datetime.fromisoformat(w["expires_at"])
    assert exp > datetime.now(timezone.utc) + timedelta(hours=23)

    # loser is locked out with a specific reason; third party sees generic locked
    assert _expect(409, claim, SEED_DISPUTABLE, ClaimIn(claimer="alice")) == "lost_dispute_lock"
    assert _expect(409, claim, SEED_DISPUTABLE, ClaimIn(claimer="carol")) == "locked"

    # mine projection keeps the loss record after claimer moved
    ma = [r for r in mine("alice") if r["id"] == SEED_DISPUTABLE][0]
    role = ma["my_roles"][0]
    assert role["role"] == "respondent" and role["verdict"] == "lost"
    mb = [r for r in mine("bob") if r["id"] == SEED_DISPUTABLE][0]
    assert mb["my_roles"][0]["verdict"] == "won" and mb["relation"] == "both"

    # release lifts the ban: loser may claim again (new cycle)
    assert release(SEED_DISPUTABLE)["status"] == "released"
    p = claim(SEED_DISPUTABLE, ClaimIn(claimer="alice"))
    assert p["claimer"] == "alice" and p["status"] == "claimed"
    assert get_wish(SEED_DISPUTABLE)["active_dispute_id"] is None


def test_respondent_wins():
    t = dispute(SEED_DISPUTABLE, DisputeIn(challenger="bob"))
    res = rule(t["id"], RuleIn(winner="respondent", arbiter="carol"))
    assert res["wish"]["claimer"] == "alice"
    assert get_wish(SEED_DISPUTABLE)["status"] == "claimed"
    assert _expect(409, claim, SEED_DISPUTABLE, ClaimIn(claimer="bob")) == "lost_dispute_lock"
    assert _expect(409, claim, SEED_DISPUTABLE, ClaimIn(claimer="zoe")) == "locked"


def test_timeout_auto_keeps_original_claimer():
    t = dispute(SEED_DISPUTABLE, DisputeIn(challenger="bob"))
    _backdate(dispute_id=t["id"])
    rows = list_wishes()  # lazy sweep triggers the auto-ruling
    w = [r for r in rows if r["id"] == SEED_DISPUTABLE][0]
    assert w["status"] == "claimed" and w["claimer"] == "alice"
    assert w["dispute"]["status"] == "timeout" and w["dispute"]["kind"] == "auto"
    assert w["dispute"]["winner"] == "respondent"
    assert datetime.fromisoformat(w["expires_at"]) > datetime.now(timezone.utc) + timedelta(hours=23)
    assert _expect(409, claim, SEED_DISPUTABLE, ClaimIn(claimer="bob")) == "lost_dispute_lock"
    # closed ticket can no longer be previewed or manually ruled
    assert _expect(409, dispute_preview, SEED_DISPUTABLE) == "dispute_closed"
    assert _expect(409, rule, t["id"], RuleIn(winner="challenger", arbiter="carol")) == "dispute_closed"


def test_timeout_reset_not_released_by_claim_ttl_sweep():
    t = dispute(SEED_DISPUTABLE, DisputeIn(challenger="bob"))
    _backdate(dispute_id=t["id"], wish_id=SEED_DISPUTABLE)
    rows = list_wishes()  # timeout sweep runs before claim TTL sweep
    w = [r for r in rows if r["id"] == SEED_DISPUTABLE][0]
    assert w["status"] == "claimed" and w["claimer"] == "alice"
    assert datetime.fromisoformat(w["expires_at"]) > datetime.now(timezone.utc)


def test_dispute_rejections():
    assert _expect(400, dispute, SEED_DISPUTABLE, DisputeIn(challenger="alice")) == "cannot_dispute_own"
    assert _expect(400, dispute, SEED_DISPUTABLE, DisputeIn(challenger="  ")) == "challenger_required"
    assert _expect(400, dispute, 1, DisputeIn(challenger="bob")) == "not_claimed"
    assert _expect(400, dispute, SEED_EXPIRED, DisputeIn(challenger="bob")) == "not_claimed"
    assert _expect(404, dispute, 999, DisputeIn(challenger="bob")) == "not found"

    t = dispute(SEED_DISPUTABLE, DisputeIn(challenger="bob"))
    assert _expect(409, dispute, SEED_DISPUTABLE, DisputeIn(challenger="zoe")) == "already_in_dispute"
    rule(t["id"], RuleIn(winner="respondent", arbiter="carol"))
    assert _expect(409, dispute, SEED_DISPUTABLE, DisputeIn(challenger="zoe")) == "already_adjudicated"
    assert _expect(404, rule, 999, RuleIn(winner="respondent", arbiter="carol")) == "dispute_not_found"


def test_preview_requires_active_dispute():
    assert _expect(409, dispute_preview, 1) == "no_active_dispute"  # open wish
    assert _expect(404, dispute_preview, 999) == "not found"


def test_wall_projection_null_for_clean_wishes():
    dispute(SEED_DISPUTABLE, DisputeIn(challenger="bob"))
    rows = {r["id"]: r for r in list_wishes()}
    assert rows[SEED_DISPUTABLE]["dispute"] is not None
    assert rows[SEED_DISPUTABLE]["dispute"]["challenger"] == "bob"
    assert rows[1]["dispute"] is None


def test_fulfill_after_ruling_keeps_loser_history():
    t = dispute(SEED_DISPUTABLE, DisputeIn(challenger="bob"))
    rule(t["id"], RuleIn(winner="challenger", arbiter="carol"))
    assert fulfill(SEED_DISPUTABLE)["status"] == "fulfilled"
    assert _expect(409, claim, SEED_DISPUTABLE, ClaimIn(claimer="alice")) == "already_fulfilled"
    ma = [r for r in mine("alice") if r["id"] == SEED_DISPUTABLE][0]
    assert ma["my_roles"][0]["verdict"] == "lost"


def test_party_only_record_after_release():
    t = dispute(SEED_DISPUTABLE, DisputeIn(challenger="bob"))
    rule(t["id"], RuleIn(winner="challenger", arbiter="carol"))
    release(SEED_DISPUTABLE)  # claimer nulled, but ticket history remains
    recs = [r for r in mine("alice") if r["id"] == SEED_DISPUTABLE]
    assert recs and recs[0]["relation"] == "party"
    assert recs[0]["my_roles"][0]["verdict"] == "lost"
