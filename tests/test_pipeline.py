import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from picks import config, ledger, market, model, pipeline, ratings, store
from test_engine import seed_ratings
from picks.timing import iso

CFG = config.load()
T0 = datetime(2026, 11, 15, 22, 0, tzinfo=timezone.utc)


class Src:
    """Serves whatever games the test sets; records fetches."""

    def __init__(self, games=None, injuries=None):
        self.games, self.injuries, self.fetches = games or [], injuries or {}, []

    def fetch_day(self, sport, day):
        self.fetches.append((sport, str(day)))
        return [dict(g) for g in self.games if g["sport"] == sport]

    def fetch_injuries(self, sport):
        return self.injuries.get(sport, {})


def game(gid, start, sport="nba", home="Harbor City Anglers", away="Lakeview Herons", **kw):
    base = {"id": gid, "sport": sport, "kind": "team", "event_id": gid, "event_name": "x", "start_utc": iso(start),
            "home": home, "away": away, "venue": "v", "status": "scheduled", "home_score": None, "away_score": None,
            "winner": None, "method": None, "home_record": None, "away_record": None,
            "odds": {"home_ml": -110, "away_ml": -110, "book": "Demo", "source": "demo"}}
    return {**base, **kw}


@pytest.fixture
def s():
    st = store.SqliteStore()
    store.migrate(st)
    return st


def test_tick_publishes_at_t30_once_and_never_after_start(s):
    start = T0 + timedelta(hours=2)
    src = Src([game("g1", start)])
    pipeline.run_schedule(s, src, CFG, T0)
    assert pipeline.run_tick(s, src, CFG, start - timedelta(minutes=60))["published"] == 0
    assert pipeline.run_tick(s, src, CFG, start - timedelta(minutes=31))["published"] == 0
    r = pipeline.run_tick(s, src, CFG, start - timedelta(minutes=30))
    assert r["published"] == 1 and r["late"] == 0
    p = s.q("SELECT * FROM picks")[0]
    assert p["tag"] == "ON_TIME" and p["published_utc"] == iso(start - timedelta(minutes=30))
    assert pipeline.run_tick(s, src, CFG, start - timedelta(minutes=26))["published"] == 0     # idempotent
    assert len(s.q("SELECT * FROM picks")) == 1


def test_late_tick_is_tagged_and_missed_game_is_excluded(s):
    start = T0 + timedelta(hours=2)
    src = Src([game("g1", start), game("g2", start + timedelta(minutes=1), home="Ridge Bears", away="Iron Coast Smiths")])
    pipeline.run_schedule(s, src, CFG, T0)
    r = pipeline.run_tick(s, src, CFG, start - timedelta(minutes=8))
    assert r["published"] == 2 and r["late"] == 2
    assert {p["tag"] for p in s.q("SELECT tag FROM picks")} == {"LATE"}
    src2 = Src([game("g3", start + timedelta(hours=1), home="Ridge Bears", away="Lakeview Herons")])
    pipeline.run_schedule(s, src2, CFG, T0)
    r = pipeline.run_tick(s, src2, CFG, start + timedelta(hours=1, minutes=2))
    assert r["published"] == 0 and r["missed"] == 1
    assert s.q("SELECT missed FROM games WHERE id='g3'")[0]["missed"] == 1
    assert pipeline.run_tick(s, src2, CFG, start + timedelta(hours=2))["missed"] == 0
    latest = pipeline.get_snapshot(s, "latest")
    assert [g["missed"] for g in latest["games"] if g["id"] == "g3"] == [True]


def test_postponed_game_is_not_published(s):
    start = T0 + timedelta(hours=2)
    src = Src([game("g1", start, status="postponed")])
    pipeline.run_schedule(s, src, CFG, T0)
    assert pipeline.run_tick(s, src, CFG, start - timedelta(minutes=30))["published"] == 0


def test_mma_card_publishes_whole_card_at_t95_of_first_bout(s):
    first = T0 + timedelta(hours=5)
    bouts = [game(f"b{i}", first + timedelta(hours=i), sport="ufc", home=f"A{i} Fighter", away=f"B{i} Fighter",
                  kind="bout", event_id="E1", event_name="Demo Card", odds=None) for i in range(4)]
    src = Src(bouts)
    pipeline.run_schedule(s, src, CFG, T0)
    assert pipeline.run_tick(s, src, CFG, first - timedelta(minutes=100))["published"] == 0
    assert pipeline.run_tick(s, src, CFG, first - timedelta(minutes=93))["published"] == 4
    assert {p["verdict"] for p in s.q("SELECT verdict FROM picks")} == {"PASS"}                 # no market -> PASS
    latest = pipeline.get_snapshot(s, "latest")
    assert all(g["pick"]["verdict"] == "PASS" for g in latest["games"])


def test_never_plays_without_injury_data(s):
    start = T0 + timedelta(hours=2)
    src = Src([game("g1", start)])
    seed_ratings(s)
    pipeline.run_schedule(s, src, CFG, T0)
    pipeline.run_tick(s, src, CFG, start - timedelta(minutes=30))
    p = s.q("SELECT * FROM picks")[0]
    assert p["verdict"] == "PASS" and p["coverage"] == 0.8 < CFG["thresholds"]["play_min_coverage"]     # everything but injuries


def strong_cfg():
    c = deepcopy(CFG)
    c["model"]["anchor_shrink"] = 1.0
    return c


def odds_for(s, home, away, start, edge):
    """Quote a price whose no-vig home probability sits `edge` below what the rating model will say."""
    rat = ratings.build(s, "nba", CFG, iso(start))
    p = rat.p_home(home, away) - edge
    return {"home_ml": market.prob_to_american(p), "away_ml": market.prob_to_american(1 - p), "book": "Demo", "source": "demo"}


def play_setup(s, edge=0.05):
    start = T0 + timedelta(hours=3)
    seed_ratings(s, "Harbor City Anglers", "Lakeview Herons")
    inj = {"nba": {"Harbor City Anglers": [], "Lakeview Herons": [{"name": "Sam Rook", "pos": "G", "status": "Out"}]}}
    g = game("g1", start, odds=odds_for(s, "Harbor City Anglers", "Lakeview Herons", start, edge))
    return start, g, inj


def test_full_flow_play_top_pick_grade_and_records(s):
    cfg = strong_cfg()
    start, g, inj = play_setup(s)
    src = Src([g], inj)
    pipeline.run_schedule(s, src, cfg, T0)
    r = pipeline.run_tick(s, src, cfg, start - timedelta(minutes=30))
    p = s.q("SELECT * FROM picks")[0]
    assert r["published"] == 1 and p["verdict"] == "PLAY", p["payload_json"]
    assert p["selection"] == "home" and p["units"] >= 1 and p["coverage"] == 1.0
    payload = json.loads(p["payload_json"])
    assert payload["narrative_source"] == "template" and payload["validator_problems"] == []
    assert payload["lean_name"] == "Harbor City Anglers" and "Elo" in payload["narrative"]["matchup"]
    src.games = [dict(g, status="final", winner="home", home_score=110, away_score=99)]
    assert pipeline.run_grade(s, src, cfg, start + timedelta(hours=4))["graded"] == 1
    gr = s.q("SELECT * FROM grades")[0]
    assert gr["grade"] == "W" and gr["profit_units"] == pytest.approx(market.profit_units(p["odds"], p["units"]), abs=1e-3)
    latest = pipeline.get_snapshot(s, "latest")
    assert latest["records"]["overall"]["w"] == 1 and latest["games"][0]["grade"]["grade"] == "W"
    assert latest["games"][0]["pick"]["selection_name"] == "Harbor City Anglers"
    assert ledger.verify_chain(s) == []
    assert pipeline.run_grade(s, src, cfg, start + timedelta(hours=5))["graded"] == 0


def test_pass_rows_still_name_the_lean(s):
    start, g, inj = play_setup(s, edge=0.005)
    src = Src([g], inj)
    pipeline.run_schedule(s, src, CFG, T0)
    pipeline.run_tick(s, src, CFG, start - timedelta(minutes=30))
    row = pipeline.get_snapshot(s, "latest")["games"][0]["pick"]
    assert row["verdict"] == "PASS" and row["lean_name"] == "Harbor City Anglers" and row["headline"] == "Pass"
    assert row["model_prob"] is not None and row["market_prob"] is not None
    text = "\n".join(row["narrative"][k] for k in ("market", "matchup", "context", "projection", "risk") if k in row["narrative"])
    assert "fighter" not in text.lower() and "striking" not in text.lower()


def test_voids_for_cancelled_after_pick(s):
    cfg = strong_cfg()
    start, g, inj = play_setup(s)
    src = Src([g], inj)
    pipeline.run_schedule(s, src, cfg, T0)
    pipeline.run_tick(s, src, cfg, start - timedelta(minutes=30))
    assert s.q("SELECT verdict FROM picks")[0]["verdict"] == "PLAY"
    src.games = [dict(g, status="cancelled")]
    pipeline.run_grade(s, src, cfg, start + timedelta(hours=1))
    assert s.q("SELECT grade FROM grades")[0]["grade"] == "V"
    assert pipeline.get_snapshot(s, "latest")["records"]["overall"]["v"] == 1


def test_source_failure_is_recorded_not_raised(s):
    class Boom(Src):
        def fetch_day(self, sport, day):
            raise RuntimeError("ESPN request failed: HTTP 503")

    pipeline.run_schedule(s, Boom(), CFG, T0)
    h = pipeline.get_snapshot(s, "health")
    assert h["sources"]["scoreboard:nba"]["ok"] is False and "503" in h["sources"]["scoreboard:nba"]["detail"]


def test_odds_snapshots_only_when_changed_and_pregame(s):
    start = T0 + timedelta(hours=3)
    g = game("g1", start)
    pipeline.upsert_game(s, g, T0)
    pipeline.upsert_game(s, g, T0 + timedelta(minutes=5))
    assert len(s.q("SELECT * FROM odds_snapshots")) == 1
    pipeline.upsert_game(s, dict(g, odds={**g["odds"], "home_ml": -120}), T0 + timedelta(minutes=10))
    assert len(s.q("SELECT * FROM odds_snapshots")) == 2
    pipeline.upsert_game(s, dict(g, odds={**g["odds"], "home_ml": -150}), start + timedelta(minutes=10))
    assert len(s.q("SELECT * FROM odds_snapshots")) == 2


def test_schedule_never_requests_the_feedless_dwcs_and_grading_maps_it_to_ufc(s):
    src = Src([])
    pipeline.run_schedule(s, src, CFG, T0)
    assert "dwcs" not in {f[0] for f in src.fetches} and "ufc" in {f[0] for f in src.fetches}
    src.fetches.clear()
    pipeline.refresh_days(s, src, CFG, T0, {("dwcs", T0.date())})
    assert [f[0] for f in src.fetches] == ["ufc"]
