import sqlite3
from datetime import date

import pytest

from picks import ledger, store
from fake_turso import READ, WRITE, FakeTurso


def sample(i=1, **kw):
    base = {"id": f"g{i}", "game_id": f"g{i}", "sport": "nba", "start_utc": "2026-11-15T00:30:00Z",
            "published_utc": "2026-11-15T00:00:00Z", "tag": "ON_TIME", "verdict": "PLAY", "market": "ML",
            "selection": "home", "line": None, "odds": -110.0, "fair_odds": -125.0, "model_prob": 0.55,
            "market_prob": 0.52, "edge": 0.03, "units": 1, "confidence": 5, "top_pick": 0,
            "rank_score": 0.1, "coverage": 0.9, "payload_json": "{}"}
    return {**base, **kw}


@pytest.fixture(params=["sqlite", "turso"])
def db(request):
    if request.param == "sqlite":
        s = store.SqliteStore()
        store.migrate(s)
        yield s
    else:
        fake = FakeTurso()
        s = store.TursoStore(fake.url, WRITE)
        store.migrate(s)
        s.fake = fake
        yield s
        fake.close()


def test_migrate_is_repeatable(db):
    store.migrate(db)
    names = {r["name"] for r in db.q("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"games", "picks", "grades", "snapshots", "odds_snapshots", "quota", "heartbeat"} <= names


def test_values_roundtrip(db):
    db.x("INSERT INTO snapshots (key, json, updated_utc) VALUES (?, ?, ?)", ("k", "{\"a\": 1}", "t"))
    assert db.q("SELECT * FROM snapshots WHERE key = ?", ("k",)) == [{"key": "k", "json": "{\"a\": 1}", "updated_utc": "t"}]
    db.x("INSERT INTO quota (key, used, cap, updated_utc) VALUES (?, ?, ?, ?)", ("q", 3, 500, "t"))
    assert db.q("SELECT used, cap FROM quota")[0] == {"used": 3, "cap": 500}
    assert db.q("SELECT NULL AS n, 1.5 AS f")[0] == {"n": None, "f": 1.5}


def test_pick_chain_is_insert_only_and_verifiable(db):
    a = ledger.insert_pick(db, sample(1))
    b = ledger.insert_pick(db, sample(2, odds=+120.0))
    assert a["prev_hash"] == ledger.GENESIS and b["prev_hash"] == a["hash"]
    assert ledger.insert_pick(db, sample(1)) is None            # one pick per game
    assert ledger.verify_chain(db) == []
    with pytest.raises((sqlite3.Error, store.StoreError), match="insert-only"):
        db.x("UPDATE picks SET odds = -300 WHERE id = 'g1'")
    with pytest.raises((sqlite3.Error, store.StoreError), match="insert-only"):
        db.x("DELETE FROM picks WHERE id = 'g1'")


def test_chain_detects_tampering(db):
    ledger.insert_pick(db, sample(1))
    ledger.insert_pick(db, sample(2))
    # an attacker with raw access drops the trigger and edits a row
    db.x("DROP TRIGGER picks_no_update")
    db.x("UPDATE picks SET odds = -300 WHERE id = 'g1'")
    errs = ledger.verify_chain(db)
    assert errs and "g1" not in errs[0] and "seq 1" in errs[0]


def test_grade_is_final_but_pending_review_can_change(db):
    db.x("INSERT INTO grades (pick_id, grade, graded_utc) VALUES ('g1', 'PENDING_REVIEW', 't')")
    db.x("UPDATE grades SET grade = 'W' WHERE pick_id = 'g1'")
    with pytest.raises((sqlite3.Error, store.StoreError), match="cannot change"):
        db.x("UPDATE grades SET grade = 'L' WHERE pick_id = 'g1'")


def test_ledger_export_and_verify(db, tmp_path):
    ledger.insert_pick(db, sample(1))
    db.x("INSERT INTO grades (pick_id, grade, reason, graded_utc) VALUES ('g1', 'W', 'x', '2026-11-15T05:00:00Z')")
    path = ledger.export_day(db, date(2026, 11, 14), tmp_path)        # published 00:00Z = Nov 14 7pm ET
    assert path.name == "2026-11-14.ndjson" and len(path.read_text().splitlines()) == 1
    assert ledger.export_day(db, date(2026, 11, 15), tmp_path).read_text().count("grade") >= 1
    assert ledger.verify_against_ledger(db, tmp_path) == []
    (tmp_path / "2026-11-14.ndjson").write_text(path.read_text().replace('"odds":-110.0', '"odds":-300.0'))
    assert ledger.verify_against_ledger(db, tmp_path) == []           # odds are inside the hash input only
    text = path.read_text().replace(db.q("SELECT hash FROM picks")[0]["hash"], "f" * 64)
    (tmp_path / "2026-11-14.ndjson").write_text(text)
    assert "differs" in ledger.verify_against_ledger(db, tmp_path)[0]
    assert ledger.export_day(db, date(2026, 1, 1), tmp_path) is None


def test_turso_read_token_cannot_write():
    fake = FakeTurso()
    try:
        w = store.TursoStore(fake.url, WRITE)
        store.migrate(w)
        r = store.TursoStore(fake.url, READ)
        assert r.q("SELECT 1 AS one") == [{"one": 1}]
        with pytest.raises(store.StoreError, match="read-only"):
            r.x("INSERT INTO snapshots (key, json, updated_utc) VALUES ('a','b','c')")
        bad = store.TursoStore(fake.url, "nope")
        with pytest.raises(store.StoreError):
            bad.q("SELECT 1")
    finally:
        fake.close()


def test_connect_picks_backend():
    assert store.connect({}) is None
    assert store.connect({"PICKS_DB": ":memory:"}).kind == "sqlite"
    s = store.connect({"TURSO_URL": "libsql://x-y.turso.io", "TURSO_WRITE_TOKEN": "t"})
    assert s.kind == "turso" and s.endpoint == "https://x-y.turso.io/v2/pipeline"
    ro = store.connect({"TURSO_URL": "https://x.turso.io", "TURSO_READ_TOKEN": "r", "TURSO_WRITE_TOKEN": "w"}, write=False)
    assert ro.headers["Authorization"] == "Bearer r"


def test_connect_strips_quotes_and_whitespace():
    s = store.connect({"TURSO_URL": ' "libsql://x-y.turso.io"\n', "TURSO_WRITE_TOKEN": " 'tok' \n"})
    assert s.endpoint == "https://x-y.turso.io/v2/pipeline" and s.headers["Authorization"] == "Bearer tok"
