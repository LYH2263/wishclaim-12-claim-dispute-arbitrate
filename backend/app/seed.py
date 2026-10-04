from datetime import datetime, timedelta, timezone

from app.db import connect
from app.modules import dispute as dispute_module


def init_db():
    c = connect()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS wishes(
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, note TEXT, status TEXT,
      claimer TEXT, claimed_at TEXT, expires_at TEXT, data_quality TEXT
    );
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    """)
    dispute_module.ensure_schema(c)
    c.commit()
    if c.execute("SELECT COUNT(*) c FROM wishes").fetchone()["c"] == 0:
        n = datetime.now(timezone.utc)
        c.executemany(
            "INSERT INTO wishes(title,note,status,claimer,claimed_at,expires_at,data_quality) VALUES (?,?,?,?,?,?,?)",
            [
                ("机械键盘", "红轴", "open", None, None, None, "clean"),
                ("围巾", "羊毛", "open", None, None, None, "clean"),
                ("脏愿望-空标题", "", "open", None, None, None, "dirty"),
                ("过期锁样例", "应被TTL释放", "claimed", "ghost", "2020-01-01T00:00:00+00:00",
                 "2020-01-01T01:00:00+00:00", "dirty"),
                ("待争议样例", "等待第二位挑战者", "claimed", "alice",
                 n.isoformat(), (n + timedelta(seconds=86400)).isoformat(), "clean"),
            ],
        )
        c.execute("INSERT INTO settings(key,value) VALUES ('ttl_seconds','86400')")
        c.execute("INSERT INTO settings(key,value) VALUES ('wall_title','暖粉愿望墙')")
        c.commit()
    # Idempotent upsert outside the seed block so existing volumes get it too.
    c.execute(
        "INSERT INTO settings(key,value) SELECT 'dispute_ttl_seconds','86400' "
        "WHERE NOT EXISTS (SELECT 1 FROM settings WHERE key='dispute_ttl_seconds')")
    c.commit()
    c.close()
