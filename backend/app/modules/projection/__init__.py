"""投影模块：read models merging wishes with their bound dispute ticket.

Wall/detail use the ACTIVE-bound ticket (wishes.active_dispute_id); the Mine
model scans ALL tickets where the name is a party, so verdict history survives
claimer changes and releases.
"""
from app.engines.claim_lock import parse_ts
from app.engines import dispute_lock as dl

_DISPUTE_COLS = (
    "d.id AS d_id", "d.wish_id AS d_wish_id", "d.respondent AS d_respondent",
    "d.challenger AS d_challenger", "d.status AS d_status", "d.winner AS d_winner",
    "d.arbiter AS d_arbiter", "d.arbiter_note AS d_arbiter_note",
    "d.created_at AS d_created_at", "d.expires_at AS d_expires_at",
    "d.ruled_at AS d_ruled_at",
)


def dispute_json(d: dict | None, now=None) -> dict | None:
    if not d:
        return None
    winner = dl.winner_role(d)
    loser = dl.loser_of(d)
    return {
        "id": d["id"],
        "wish_id": d["wish_id"],
        "status": d["status"],
        "respondent": d["respondent"],
        "challenger": d["challenger"],
        "winner": winner,
        "loser": loser,
        "winner_name": dl.party_name(d, winner) if winner else None,
        "loser_name": dl.party_name(d, loser) if loser else None,
        "created_at": d["created_at"],
        "expires_at": d["expires_at"],
        "ruled_at": d["ruled_at"],
        "arbiter": d["arbiter"],
        "arbiter_note": d.get("arbiter_note"),
        "deadline_passed": bool(now and d["status"] == dl.OPEN
                                and parse_ts(d["expires_at"]) <= now),
        "kind": "auto" if d["status"] == dl.TIMEOUT
                else ("manual" if d["status"] == dl.RULED else None),
    }


def _row_to_view(r, now=None) -> dict:
    w = {k: r[k] for k in r.keys() if not k.startswith("d_")}
    if r["d_id"] is None:
        w["dispute"] = None
        return w
    d = {
        "id": r["d_id"], "wish_id": r["d_wish_id"], "respondent": r["d_respondent"],
        "challenger": r["d_challenger"], "status": r["d_status"],
        "winner": r["d_winner"], "arbiter": r["d_arbiter"],
        "arbiter_note": r["d_arbiter_note"], "created_at": r["d_created_at"],
        "expires_at": r["d_expires_at"], "ruled_at": r["d_ruled_at"],
    }
    w["dispute"] = dispute_json(d, now)
    return w


_SELECT = (
    "SELECT w.*, " + ", ".join(_DISPUTE_COLS)
    + " FROM wishes w LEFT JOIN disputes d ON w.active_dispute_id = d.id"
)


def wish_view(c, wish_id: int, now=None) -> dict | None:
    r = c.execute(_SELECT + " WHERE w.id=?", (wish_id,)).fetchone()
    return _row_to_view(r, now) if r else None


def list_wall(c, now=None) -> list[dict]:
    rows = c.execute(_SELECT + " ORDER BY w.id DESC").fetchall()
    return [_row_to_view(r, now) for r in rows]


def mine_records(c, name: str, now=None) -> list[dict]:
    """Wishes currently held by name, plus every ticket naming the person.

    Each record gains relation (claimer|party|both) and my_roles, a list of
    {dispute_id, role, verdict: open|won|lost, auto, at}.
    """
    rows = c.execute(
        "SELECT w.*, t.id AS t_id, t.respondent AS t_respondent, "
        "t.challenger AS t_challenger, t.status AS t_status, t.winner AS t_winner, "
        "t.ruled_at AS t_ruled_at "
        "FROM wishes w LEFT JOIN disputes t ON t.wish_id = w.id "
        "WHERE w.claimer=? OR t.respondent=? OR t.challenger=? ORDER BY w.id DESC, t.id",
        (name, name, name),
    ).fetchall()

    by_id: dict[int, dict] = {}
    for r in rows:
        wid = r["id"]
        rec = by_id.get(wid)
        if rec is None:
            rec = {k: r[k] for k in r.keys() if not k.startswith("t_")}
            rec["dispute"] = None  # filled below from the active binding
            rec["my_roles"] = []
            by_id[wid] = rec
        if r["t_id"] is None:
            continue
        if r["t_respondent"] != name and r["t_challenger"] != name:
            continue  # other-cycle tickets surfaced via the claimer match
        role = dl.RESPONDENT if r["t_respondent"] == name else dl.CHALLENGER
        if r["t_status"] == dl.OPEN:
            verdict, at = "open", None
        else:
            won = r["t_winner"] == role
            verdict = "won" if won else "lost"
            at = r["t_ruled_at"]
        rec["my_roles"].append({
            "dispute_id": r["t_id"],
            "role": role,
            "verdict": verdict,
            "auto": r["t_status"] == dl.TIMEOUT,
            "at": at,
        })

    # attach the active-bound ticket view (independent of the party join above)
    for wid, rec in by_id.items():
        d = c.execute(
            "SELECT * FROM disputes WHERE id=(SELECT active_dispute_id FROM wishes WHERE id=?)",
            (wid,),
        ).fetchone()
        rec["dispute"] = dispute_json(dict(d), now) if d else None
        am_claimer = rec.get("claimer") == name
        am_party = bool(rec["my_roles"])
        rec["relation"] = "both" if am_claimer and am_party else (
            "claimer" if am_claimer else "party")
    return list(by_id.values())
