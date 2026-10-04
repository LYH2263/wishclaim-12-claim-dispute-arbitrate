import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point DATA_DIR at a fresh temp dir before every test (db_path() reads the
    env var per connect(), so no import reload is needed)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app import seed
    seed.init_db()
    yield
