"""争议单模块：dispute ticket persistence and lifecycle SQL.

No FastAPI dependency; callers own the connection/transaction.
"""
from datetime import datetime, timedelta

from app.engines import dispute_lock as dl

_DDL = """
CREATE TABLE IF NOT EXISTS disputes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wish_id INTEGER NOT NULL,
  respondent TEXT NOT NULL,
  challenger TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  winner TEXT,
  arbiter TEXT,
  arbiter_note TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  ruled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_disputes_wish ON disputes(wish_id);
CREATE INDEX IF NOT EXISTS idx_disputes_sweep ON disputes(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_disputes_respondent ON disputes(respondent);
CREATE INDEX IF NOT EXISTS idx_disputes_challenger ON disputes(challenger);
CREATE UNIQUE INDEX IF NOT EXISTS idx_disputes_one_open_per_wish
  ON disputes(wish_id) WHERE status='open';
"""


def ensure_schema(c) -> None:
    """Idempotent DDL + wishes column migration (safe on existing volumes)."""
    c.executescript(_DDL)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(wishes)")}
    if "active_dispute_id" not in cols:
        c.execute("ALTER TABLE wishes ADD COLUMN active_dispute_id INTEGER")


def create(c, wish_id: int, respondent: str, challenger: str,
           now: datetime, dispute_ttl_seconds: int) -> dict:
    respondent = respondent.strip()
    challenger = challenger.strip()
    cur = c.execute(
        "INSERT INTO disputes(wish_id,respondent,challenger,status,created_at,expires_at)"
        " VALUES (?,?,?,?,?,?)",
        (wish_id, respondent, challenger, dl.OPEN,
         now.isoformat(), (now + timedelta(seconds=dispute_ttl_seconds)).isoformat()),
    )
    return get(c, cur.lastrowid)


def get(c, dispute_id: int) -> dict | None:
    r = c.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
    return dict(r) if r else None


def active_for_wish(c, wish_id: int) -> dict | None:
    """The ticket currently bound to the wish's claim cycle (may be closed)."""
    r = c.execute(
        "SELECT d.* FROM wishes w JOIN disputes d ON w.active_dispute_id = d.id "
        "WHERE w.id=?",
        (wish_id,),
    ).fetchone()
    return dict(r) if r else None


def list_party(c, name: str) -> list[dict]:
    rows = c.execute(
        "SELECT * FROM disputes WHERE respondent=? OR challenger=? ORDER BY id",
        (name, name),
    ).fetchall()
    return [dict(r) for r in rows]


def list_open_due(c, now: datetime) -> list[dict]:
    """Open tickets past deadline whose wish is still in the disputed state."""
    rows = c.execute(
        "SELECT d.* FROM disputes d JOIN wishes w ON w.active_dispute_id = d.id "
        "WHERE d.status='open' AND d.expires_at <= ? AND w.status='disputed' "
        "ORDER BY d.id",
        (now.isoformat(),),
    ).fetchall()
    return [dict(r) for r in rows]


def apply_ruling(c, updates: dict) -> int:
    """Guarded ticket update; returns rows changed (0 means it lost the race)."""
    d = updates["dispute"]
    cur = c.execute(
        "UPDATE disputes SET status=?, winner=?, ruled_at=?, arbiter=?, arbiter_note=? "
        "WHERE id=? AND status='open'",
        (d["status"], d["winner"], d["ruled_at"], d["arbiter"], d["arbiter_note"], d["id"]),
    )
    return cur.rowcount


def apply_wish(c, updates: dict) -> int:
    w = updates["wish"]
    cur = c.execute(
        "UPDATE wishes SET status=?, claimer=?, claimed_at=?, expires_at=?, "
        "active_dispute_id=? WHERE id=? AND status='disputed' AND active_dispute_id=?",
        (w["status"], w["claimer"], w["claimed_at"], w["expires_at"],
         w["active_dispute_id"], w["id"], w["active_dispute_id"]),
    )
    return cur.rowcount
