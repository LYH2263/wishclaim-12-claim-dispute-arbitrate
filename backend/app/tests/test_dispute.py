import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.seed import init_schema
from app.modules import dispute_ticket as ticket
from app.modules import dispute_verdict as verdict
from app.modules import dispute_projection as proj

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
TTL = 3600        # 认领满额 1h
DTTL = 1800       # 争议截止 30m

def fresh():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_schema(c)
    return c

def add_wish(c, status="claimed", claimer="alice", expires_at=None):
    exp = expires_at if expires_at is not None else (NOW + timedelta(hours=1)).isoformat()
    cur = c.execute(
        "INSERT INTO wishes(title,note,status,claimer,claimed_at,expires_at,data_quality)"
        " VALUES ('t','',?,?,?,?,'clean')",
        (status, claimer, NOW.isoformat() if claimer else None, exp if claimer else None))
    return cur.lastrowid

def wish(c, wid):
    return c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()

def make_dispute(c, wid, challenger="bob", at=NOW):
    did = ticket.create_dispute(c, wish(c, wid), challenger, at, DTTL)
    return ticket.get_dispute(c, did)

def test_create_dispute_records_parties_and_deadline():
    c = fresh(); wid = add_wish(c)
    d = make_dispute(c, wid)
    assert d["original_claimer"] == "alice" and d["challenger"] == "bob"
    assert d["status"] == ticket.OPEN
    assert d["deadline_at"] == (NOW + timedelta(seconds=DTTL)).isoformat()

def test_create_dispute_requires_claimed_wish():
    c = fresh(); wid = add_wish(c, status="open", claimer=None)
    with pytest.raises(ticket.DisputeError) as e:
        ticket.create_dispute(c, wish(c, wid), "bob", NOW, DTTL)
    assert e.value.reason == "not_claimed"

def test_create_dispute_rejects_self_and_duplicate():
    c = fresh(); wid = add_wish(c)
    with pytest.raises(ticket.DisputeError) as e:
        ticket.create_dispute(c, wish(c, wid), "alice", NOW, DTTL)
    assert e.value.reason == "self_dispute"
    make_dispute(c, wid)
    with pytest.raises(ticket.DisputeError) as e:
        ticket.create_dispute(c, wish(c, wid), "carol", NOW, DTTL)
    assert e.value.reason == "already_disputed"

def test_preview_gives_outcome_without_writing():
    c = fresh(); wid = add_wish(c)
    d = make_dispute(c, wid)
    p = verdict.preview_verdict(d, "bob", NOW, TTL)
    assert p["winner"] == "bob" and p["loser"] == "alice"
    assert p["claimer_after"] == "bob"
    assert p["expires_at_after"] == (NOW + timedelta(seconds=TTL)).isoformat()
    assert p["ttl_policy"] == "restart_full" and p["changes_claimer_now"] is False
    assert ticket.get_dispute(c, d["id"])["status"] == ticket.OPEN
    assert wish(c, wid)["claimer"] == "alice"  # 预览不改 claimer

def test_adjudicate_challenger_wins_restart_full_ttl():
    c = fresh(); wid = add_wish(c)
    old_exp = wish(c, wid)["expires_at"]
    d = make_dispute(c, wid)
    later = NOW + timedelta(minutes=10)
    r = verdict.adjudicate(c, d["id"], "bob", later, TTL)
    w = wish(c, wid)
    assert w["claimer"] == "bob" and w["status"] == "claimed"
    assert w["expires_at"] == (later + timedelta(seconds=TTL)).isoformat()  # 重开满额
    assert w["expires_at"] != old_exp
    d2 = ticket.get_dispute(c, d["id"])
    assert d2["status"] == ticket.ADJUDICATED and d2["resolution"] == ticket.CONFIRMED
    assert d2["winner"] == "bob" and d2["loser"] == "alice" and r["loser"] == "alice"

def test_adjudicate_original_wins_also_restart_full():
    c = fresh(); wid = add_wish(c)
    d = make_dispute(c, wid)
    r = verdict.adjudicate(c, d["id"], "alice", NOW, TTL)
    assert r["claimer"] == "alice"
    assert wish(c, wid)["expires_at"] == (NOW + timedelta(seconds=TTL)).isoformat()

def test_no_ticket_no_claimer_change():
    c = fresh()
    with pytest.raises(ticket.DisputeError) as e:
        verdict.adjudicate(c, 999, "bob", NOW, TTL)
    assert e.value.reason == "no_dispute_ticket"

def test_write_lock_rejects_second_confirm():
    c = fresh(); wid = add_wish(c)
    d = make_dispute(c, wid)
    verdict.adjudicate(c, d["id"], "bob", NOW, TTL)
    with pytest.raises(ticket.DisputeError) as e:
        verdict.adjudicate(c, d["id"], "alice", NOW, TTL)
    assert e.value.reason == "dispute_closed"
    assert wish(c, wid)["claimer"] == "bob"  # 首次确认为准

def test_adjudicate_rejects_non_party_winner():
    c = fresh(); wid = add_wish(c)
    d = make_dispute(c, wid)
    with pytest.raises(ticket.DisputeError) as e:
        verdict.adjudicate(c, d["id"], "mallory", NOW, TTL)
    assert e.value.reason == "winner_not_party"

def test_sweep_auto_keeps_original_after_deadline():
    c = fresh(); wid = add_wish(c)
    d = make_dispute(c, wid, at=NOW - timedelta(seconds=2 * DTTL))  # 截止已过
    closed = ticket.sweep_disputes(c, NOW)
    assert closed == [d["id"]]
    d2 = ticket.get_dispute(c, d["id"])
    assert d2["status"] == ticket.EXPIRED and d2["resolution"] == ticket.AUTO_KEEP_ORIGINAL
    assert d2["winner"] == "alice" and d2["loser"] == "bob"  # 自动维持原认领人
    assert wish(c, wid)["claimer"] == "alice"  # 愿望本体不动

def test_sweep_moot_when_wish_no_longer_held():
    c = fresh(); wid = add_wish(c)
    d = make_dispute(c, wid)
    c.execute("UPDATE wishes SET status='released', claimer=NULL WHERE id=?", (wid,))
    ticket.sweep_disputes(c, NOW)
    d2 = ticket.get_dispute(c, d["id"])
    assert d2["resolution"] == ticket.MOOT and d2["winner"] is None and d2["loser"] is None

def test_loser_banned_until_release():
    c = fresh(); wid = add_wish(c)
    d = make_dispute(c, wid)
    verdict.adjudicate(c, d["id"], "bob", NOW, TTL)
    assert proj.active_ban(c, wid, "alice") is not None   # 败者禁认
    assert proj.active_ban(c, wid, "bob") is None         # 胜者不受限
    c.execute("UPDATE wishes SET status='released', claimer=NULL WHERE id=?", (wid,))
    assert proj.active_ban(c, wid, "alice") is None       # 释放后解禁

def test_mine_view_keeps_lost_record():
    c = fresh(); wid = add_wish(c)
    d = make_dispute(c, wid)
    verdict.adjudicate(c, d["id"], "bob", NOW, TTL)
    mine_alice = proj.mine_view(c, "alice", NOW)
    assert mine_alice["claims"] == []
    rec = [x for x in mine_alice["disputes"] if x["id"] == d["id"]][0]
    assert rec["result"] == "lost" and rec["role"] == "original" and rec["ban_active"] is True
    mine_bob = proj.mine_view(c, "bob", NOW)
    assert mine_bob["claims"][0]["id"] == wid
    assert mine_bob["disputes"][0]["result"] == "won"
