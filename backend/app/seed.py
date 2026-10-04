from app.db import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS wishes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, note TEXT, status TEXT,
  claimer TEXT, claimed_at TEXT, expires_at TEXT, data_quality TEXT
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS disputes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wish_id INTEGER NOT NULL,
  original_claimer TEXT NOT NULL,
  challenger TEXT NOT NULL,
  status TEXT NOT NULL,
  resolution TEXT,
  created_at TEXT NOT NULL,
  deadline_at TEXT NOT NULL,
  decided_at TEXT,
  winner TEXT,
  loser TEXT
);
"""

DEFAULT_SETTINGS = {
    "ttl_seconds": "86400",
    "dispute_ttl_seconds": "43200",
    "wall_title": "暖粉愿望墙",
}

def init_schema(c):
    c.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (k, v))

def init_db():
    c = connect()
    init_schema(c)
    if c.execute("SELECT COUNT(*) c FROM wishes").fetchone()["c"] == 0:
        c.executemany(
            "INSERT INTO wishes(title,note,status,claimer,claimed_at,expires_at,data_quality) VALUES (?,?,?,?,?,?,?)",
            [
                ("机械键盘", "红轴", "open", None, None, None, "clean"),
                ("围巾", "羊毛", "open", None, None, None, "clean"),
                ("脏愿望-空标题", "", "open", None, None, None, "dirty"),
                ("过期锁样例", "应被TTL释放", "claimed", "ghost", "2020-01-01T00:00:00+00:00",
                 "2020-01-01T01:00:00+00:00", "dirty"),
            ],
        )
    c.commit()
    c.close()
