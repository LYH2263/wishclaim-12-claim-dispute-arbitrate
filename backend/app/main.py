from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import seed
from app.db import connect
from app.engines.claim_lock import claim_allowed, lock_payload, release_if_expired
from app.engines import dispute_lock as dl
from app.modules import dispute as tickets
from app.modules import ruling
from app.modules import projection

app = FastAPI(title="Wishclaim", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup():
    seed.init_db()
    c = connect()
    sweep(c)
    c.commit()
    c.close()


def now(): return datetime.now(timezone.utc)


def _setting(key: str, default: int) -> int:
    c = connect()
    row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    c.close()
    return int(row["value"] if row else default)


def ttl(): return _setting("ttl_seconds", 86400)


def dispute_ttl(): return _setting("dispute_ttl_seconds", 86400)


def sweep(c):
    # 1) deadline auto-rulings keep the original claimer and reset TTL in full;
    #    resulting rows are claimed with a future expiry, so step 2 can't touch them
    ruling.sweep_timeouts(c, now(), ttl())
    # 2) ordinary claim TTL expiry releases the wish and lifts any dispute ban
    for r in c.execute("SELECT * FROM wishes WHERE status='claimed'"):
        rel = release_if_expired(r["status"], r["expires_at"], now())
        if rel:
            c.execute(
                "UPDATE wishes SET status=?, claimer=?, claimed_at=?, expires_at=?, "
                "active_dispute_id=NULL WHERE id=?",
                (rel["status"], None, None, None, r["id"]))


@app.get("/api/health")
def health(): return {"ok": True, "project": "wishclaim"}


@app.get("/api/wishes")
def list_wishes():
    c = connect(); sweep(c); c.commit()
    rows = projection.list_wall(c, now()); c.close(); return rows


@app.get("/api/wishes/{wid}")
def get_wish(wid: int):
    c = connect(); sweep(c); c.commit()
    v = projection.wish_view(c, wid, now()); c.close()
    if not v: raise HTTPException(404, "not found")
    return v


class WishIn(BaseModel):
    title: str
    note: str = ""


@app.post("/api/wishes")
def create_wish(body: WishIn):
    c = connect()
    cur = c.execute("INSERT INTO wishes(title,note,status,data_quality) VALUES (?,?,?,?)",
                    (body.title, body.note, "open", "clean"))
    c.commit(); wid = cur.lastrowid; c.close(); return {"id": wid}


class ClaimIn(BaseModel):
    claimer: str


@app.post("/api/wishes/{wid}/claim")
def claim(wid: int, body: ClaimIn):
    c = connect(); sweep(c); c.commit()
    r = c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
    if not r: c.close(); raise HTTPException(404, "not found")
    if r["status"] == "disputed":
        c.close(); raise HTTPException(409, "in_dispute")
    allowed = claim_allowed(r["status"], r["claimer"], now(), r["expires_at"])
    if not allowed["ok"]:
        if allowed["reason"] == "locked":
            binding = tickets.active_for_wish(c, wid)
            reason = dl.ban_reason(binding, body.claimer) or "locked"
            c.close(); raise HTTPException(409, reason)
        c.close(); raise HTTPException(409, allowed["reason"])
    p = lock_payload(body.claimer, now(), ttl())
    c.execute(
        "UPDATE wishes SET status=?, claimer=?, claimed_at=?, expires_at=?, "
        "active_dispute_id=NULL WHERE id=?",
        (p["status"], p["claimer"], p["claimed_at"], p["expires_at"], wid))
    c.commit(); c.close(); return p


@app.post("/api/wishes/{wid}/release")
def release(wid: int):
    c = connect()
    r = c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
    if not r: c.close(); raise HTTPException(404, "not found")
    if r["status"] == "disputed":
        c.close(); raise HTTPException(400, "in_dispute")
    if r["status"] != "claimed":
        c.close(); raise HTTPException(400, "not_claimed")
    c.execute(
        "UPDATE wishes SET status='released', claimer=NULL, claimed_at=NULL, "
        "expires_at=NULL, active_dispute_id=NULL WHERE id=?", (wid,))
    c.commit(); c.close(); return {"ok": True, "status": "released"}


@app.post("/api/wishes/{wid}/fulfill")
def fulfill(wid: int):
    c = connect()
    r = c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
    if not r: c.close(); raise HTTPException(404, "not found")
    if r["status"] == "disputed":
        c.close(); raise HTTPException(400, "in_dispute")
    if r["status"] != "claimed":
        c.close(); raise HTTPException(400, "need_claim")
    c.execute("UPDATE wishes SET status='fulfilled' WHERE id=?", (wid,))
    c.commit(); c.close(); return {"ok": True, "status": "fulfilled"}


class DisputeIn(BaseModel):
    challenger: str


@app.post("/api/wishes/{wid}/dispute")
def dispute(wid: int, body: DisputeIn):
    c = connect(); sweep(c); c.commit(); c.close()
    try:
        t = ruling.file_atomic(wid, body.challenger, now(), dispute_ttl())
    except ruling.DisputeError as e:
        raise HTTPException(e.status_code, e.reason)
    return t


@app.get("/api/wishes/{wid}/dispute/preview")
def dispute_preview(wid: int, winner: Literal["respondent", "challenger"] | None = None):
    c = connect(); sweep(c); c.commit()
    v = projection.wish_view(c, wid, now())
    if not v: c.close(); raise HTTPException(404, "not found")
    d = v["dispute"]
    if not d: c.close(); raise HTTPException(409, "no_active_dispute")
    if d["status"] != dl.OPEN: c.close(); raise HTTPException(409, "dispute_closed")
    outcomes = dl.preview_ruling(d, now(), ttl())
    c.close()
    return {
        "dispute_id": d["id"],
        "now": now().isoformat(),
        "claim_ttl_seconds": ttl(),
        "selected": winner,
        "outcomes": outcomes,
    }


class RuleIn(BaseModel):
    winner: Literal["respondent", "challenger"]
    arbiter: str
    arbiter_note: str | None = None


@app.post("/api/disputes/{did}/rule")
def rule(did: int, body: RuleIn):
    try:
        updates = ruling.rule_atomic(
            did, body.winner, body.arbiter, body.arbiter_note, now(), ttl())
    except ruling.DisputeError as e:
        raise HTTPException(e.status_code, e.reason)
    return {"dispute": updates["dispute"], "wish": updates["wish"]}


@app.get("/api/mine")
def mine(claimer: str):
    c = connect(); sweep(c); c.commit()
    rows = projection.mine_records(c, claimer, now()); c.close(); return rows


@app.get("/api/done")
def done():
    c = connect()
    rows = [dict(r) for r in c.execute("SELECT * FROM wishes WHERE status='fulfilled'")]
    c.close(); return rows


@app.get("/api/settings")
def settings():
    c = connect()
    rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}
    c.close(); return rows


@app.get("/api/rules")
def rules():
    dttl = dispute_ttl()
    return {
        "mutex": "同一愿望同时只能被一人认领",
        "ttl": "认领超时未核销则自动释放",
        "fulfill": "核销后状态变为 fulfilled",
        "dispute_window": f"争议发起后 {dttl} 秒内未裁决，系统自动判原认领人胜诉",
        "dispute_exclusive": "争议处理期间愿望处于「争议中」：第三方不能认领，释放与核销暂停",
        "ruling_ttl_reset": "裁决一经作出（含超时自动裁决），认领期限一律重置为完整 TTL，自裁决时刻起重新计时",
        "loser_lockout": "败诉方在该认领被释放（超时自动释放或手动释放）前，不能再次认领同一愿望",
        "timeout_keeps": "争议逾期未裁决，视为原认领人胜诉，认领人不变并获得完整 TTL",
        "claimer_change": "认领锁不接受直接换人：只有争议裁决（手动或超时）能变更认领人",
    }
