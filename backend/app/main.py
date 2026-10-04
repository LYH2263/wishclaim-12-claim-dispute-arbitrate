from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect
from app.engines.claim_lock import claim_allowed, lock_payload, release_if_expired
from app.modules import dispute_ticket, dispute_verdict, dispute_projection
from app.modules.dispute_ticket import DisputeError

app = FastAPI(title="Wishclaim", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

def now(): return datetime.now(timezone.utc)

def setting(c, key, default):
    row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return int(row["value"] if row else default)

def ttl():
    c = connect(); v = setting(c, "ttl_seconds", 86400); c.close(); return v

def sweep(c):
    """先扫愿望 TTL 释放，再扫争议单（截止未裁决→自动维持原认领人；易主→作废）。"""
    for r in c.execute("SELECT * FROM wishes WHERE status='claimed'"):
        rel = release_if_expired(r["status"], r["expires_at"], now())
        if rel:
            c.execute("UPDATE wishes SET status=?, claimer=?, claimed_at=?, expires_at=? WHERE id=?",
                      (rel["status"], None, None, None, r["id"]))
    dispute_ticket.sweep_disputes(c, now())

def wish_or_404(c, wid):
    r = c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
    if not r: raise HTTPException(404, "not found")
    return r

@app.get("/api/health")
def health(): return {"ok": True, "project": "wishclaim"}

@app.get("/api/wishes")
def list_wishes():
    c = connect(); sweep(c); c.commit()
    dm = dispute_ticket.open_disputes_map(c)
    rows = [dispute_projection.wish_view(r, dm.get(r["id"]), now())
            for r in c.execute("SELECT * FROM wishes ORDER BY id DESC")]
    c.close(); return rows

@app.get("/api/wishes/{wid}")
def get_wish(wid: int):
    c = connect(); sweep(c); c.commit()
    r = wish_or_404(c, wid)
    out = dispute_projection.wish_view(r, dispute_ticket.open_dispute_for(c, wid), now())
    c.close(); return out

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
    if dispute_projection.active_ban(c, wid, body.claimer):
        c.close(); raise HTTPException(409, "dispute_loser_banned")
    disputed = dispute_ticket.open_dispute_for(c, wid) is not None
    allowed = claim_allowed(r["status"], r["claimer"], now(), r["expires_at"], disputed)
    if not allowed["ok"]:
        c.close(); raise HTTPException(409, allowed["reason"])
    p = lock_payload(body.claimer, now(), ttl())
    c.execute("UPDATE wishes SET status=?, claimer=?, claimed_at=?, expires_at=? WHERE id=?",
              (p["status"], p["claimer"], p["claimed_at"], p["expires_at"], wid))
    c.commit(); c.close(); return p

@app.post("/api/wishes/{wid}/release")
def release(wid: int):
    c = connect()
    r = c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
    if not r: c.close(); raise HTTPException(404, "not found")
    if r["status"] != "claimed":
        c.close(); raise HTTPException(400, "not_claimed")
    c.execute("UPDATE wishes SET status='released', claimer=NULL, claimed_at=NULL, expires_at=NULL WHERE id=?", (wid,))
    dispute_ticket.sweep_disputes(c, now())  # 释放后未决争议作废
    c.commit(); c.close(); return {"ok": True, "status": "released"}

@app.post("/api/wishes/{wid}/fulfill")
def fulfill(wid: int):
    c = connect()
    r = c.execute("SELECT * FROM wishes WHERE id=?", (wid,)).fetchone()
    if not r: c.close(); raise HTTPException(404, "not found")
    if r["status"] != "claimed":
        c.close(); raise HTTPException(400, "need_claim")
    c.execute("UPDATE wishes SET status='fulfilled' WHERE id=?", (wid,))
    dispute_ticket.sweep_disputes(c, now())  # 核销后未决争议作废
    c.commit(); c.close(); return {"ok": True, "status": "fulfilled"}

class DisputeIn(BaseModel):
    challenger: str

@app.post("/api/wishes/{wid}/disputes")
def open_dispute(wid: int, body: DisputeIn):
    c = connect(); sweep(c); c.commit()
    r = wish_or_404(c, wid)
    try:
        if dispute_projection.active_ban(c, wid, body.challenger):
            raise DisputeError("dispute_loser_banned")
        did = dispute_ticket.create_dispute(c, r, body.challenger, now(),
                                            setting(c, "dispute_ttl_seconds", 43200))
    except DisputeError as e:
        c.close(); raise HTTPException(409, e.reason)
    c.commit()
    out = dispute_projection.dispute_view(dispute_ticket.get_dispute(c, did), now())
    c.close(); return out

@app.get("/api/disputes/{did}/preview")
def preview(did: int, winner: str):
    """裁决预览：给出胜者与败者结果，不改 claimer。"""
    c = connect(); sweep(c); c.commit()
    try:
        out = dispute_verdict.preview_verdict(
            dispute_ticket.get_dispute(c, did), winner, now(), ttl())
    except DisputeError as e:
        c.close(); raise HTTPException(409, e.reason)
    c.close(); return out

class VerdictIn(BaseModel):
    winner: str

@app.post("/api/disputes/{did}/adjudicate")
def adjudicate(did: int, body: VerdictIn):
    """确认裁决：写锁翻单，胜者成为唯一 claimer，expires_at 重开满额。"""
    c = connect(); sweep(c); c.commit()
    try:
        out = dispute_verdict.adjudicate(c, did, body.winner, now(), ttl())
    except DisputeError as e:
        c.close(); raise HTTPException(409, e.reason)
    c.commit()
    out["wish"] = dispute_projection.wish_view(
        wish_or_404(c, out["wish_id"]), None, now())
    c.close(); return out

@app.get("/api/mine")
def mine(claimer: str):
    c = connect(); sweep(c); c.commit()
    out = dispute_projection.mine_view(c, claimer, now())
    c.close(); return out

@app.get("/api/done")
def done():
    c = connect()
    rows = [dict(r) for r in c.execute("SELECT * FROM wishes WHERE status='fulfilled'")]; c.close(); return rows

@app.get("/api/settings")
def settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows

@app.get("/api/rules")
def rules():
    return {
        "mutex": "同一愿望同时只能被一人认领",
        "ttl": "认领超时未核销则自动释放",
        "fulfill": "核销后状态变为 fulfilled",
        "dispute": "已认领的愿望可被他人发起争议；争议中任何人不得直接认领，第三人不得插队",
        "dispute_deadline": "争议截止未裁决：自动维持原认领人，挑战者记败诉",
        "verdict_ttl": "裁决确认后胜者成为唯一认领人，认领期重开满额（自裁决时刻起完整 TTL），墙卡/详情倒计时同源",
        "loser": "败诉者在「我的认领」留败诉记录，该愿望释放前不得再次认领或发起争议",
        "no_ticket_no_change": "无争议单不得变更认领人；重复裁决以首次确认为准",
    }
