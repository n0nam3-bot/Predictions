from datetime import timedelta

from picks import cli, config, pipeline, store
from picks.sources import oddsapi
from test_pipeline import Src, T0, game

CFG = config.load()
RAW = [{"id": "x", "commence_time": "2026-11-15T23:05:00Z", "home_team": "Harbor City Anglers", "away_team": "Lakeview Herons",
        "bookmakers": [{"key": "other", "title": "Other", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Harbor City Anglers", "price": -300}, {"name": "Lakeview Herons", "price": 250}]}]},
                       {"key": "draftkings", "title": "DraftKings", "markets": [{"key": "h2h", "outcomes": [
                           {"name": "Lakeview Herons", "price": 135}, {"name": "Harbor City Anglers", "price": -155}]}]}]}]


class Http:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def get(self, url, timeout=0, params=None):
        self.calls.append((url, params))

        class R:
            status_code = self.status

            def json(s):
                return RAW
        return R()


def mem():
    s = store.SqliteStore()
    store.migrate(s)
    return s


def test_parse_prefers_known_book_and_orients_by_team_name():
    ev = oddsapi.parse_events(RAW)
    assert ev[0]["book"] == "DraftKings" and (ev[0]["home_ml"], ev[0]["away_ml"]) == (-155, 135)
    assert oddsapi.parse_events({"message": "bad key"}) == []


def test_match_handles_flipped_orientation_and_time_window():
    ev = oddsapi.parse_events(RAW)
    g = {"home": "Lakeview Herons", "away": "Harbor City Anglers", "start_utc": "2026-11-15T23:30:00Z"}
    assert oddsapi.match(g, ev)["home_ml"] == 135
    assert oddsapi.match({**g, "start_utc": "2026-11-17T00:00:00Z"}, ev) is None
    assert oddsapi.match({**g, "home": "Someone Else"}, ev) is None


def test_budget_and_throttle():
    s, http = mem(), Http()
    src = oddsapi.OddsAPISource("k", s, T0, http)
    assert src.fetch("nba") and len(http.calls) == 1 and http.calls[0][1]["markets"] == "h2h"
    assert src.fetch("nba") == [] and len(http.calls) == 1                         # throttled for 20 minutes
    later = oddsapi.OddsAPISource("k", s, T0 + timedelta(minutes=30), http)
    assert later.fetch("nba") and len(http.calls) == 2
    s.x("UPDATE quota SET used = 430 WHERE key LIKE 'oddsapi:%'")
    assert oddsapi.OddsAPISource("k", s, T0 + timedelta(hours=2), http).fetch("nba") == []        # past 85% of 500
    assert oddsapi.OddsAPISource("", s, T0, http).fetch("nba") == [] and oddsapi.OddsAPISource("k", s, T0, http).fetch("golf") == []


def test_tick_fills_missing_moneyline_from_fallback():
    s = mem()
    start = T0 + timedelta(hours=1)
    g = game("g1", start, odds=None)
    src = Src([g])
    pipeline.run_schedule(s, src, CFG, T0)
    raw = [{**RAW[0], "commence_time": start.strftime("%Y-%m-%dT%H:%M:%SZ")}]
    http = Http()
    http.get = lambda url, timeout=0, params=None: type("R", (), {"status_code": 200, "json": lambda self: raw})()
    odds = oddsapi.OddsAPISource("k", s, start - timedelta(minutes=30), http)
    pipeline.run_tick(s, src, CFG, start - timedelta(minutes=30), None, odds)
    row = s.q("SELECT odds_json FROM games WHERE id='g1'")[0]
    assert "the-odds-api" in row["odds_json"]
    assert len(s.q("SELECT * FROM odds_snapshots WHERE game_id='g1'")) == 1
    p = s.q("SELECT payload_json FROM picks")[0]["payload_json"]
    assert "no moneyline" not in p


def test_backfill_loads_history_and_latest_reports_date_range():
    s = mem()
    start = T0 - timedelta(days=10)
    src = Src([game("old1", start, status="final", winner="home", home_score=100, away_score=90)])
    out = pipeline.run_backfill(s, src, CFG, T0, days=20)
    assert out["games_upserted"] >= 1
    latest = pipeline.get_snapshot(s, "latest")
    assert latest["date_range"]["min"] == "2026-11-05" and latest["date_range"]["max"] == "2026-11-05"
    assert ("nba", "2026-11-05") in src.fetches or any(f[0] == "nba" for f in src.fetches)


def test_cli_backfill_runs(tmp_path):
    env = {"PICKS_DB": str(tmp_path / "p.db")}
    assert cli.main(["backfill", "--days", "2", "--now", T0.isoformat()], source=Src([]), env=env) == 0


class RangeSrc(Src):
    def __init__(self, games):
        super().__init__(games)
        self.ranges = []

    def fetch_range(self, sport, start, end):
        self.ranges.append((sport, str(start), str(end)))
        return [dict(g) for g in self.games if g["sport"] == sport]


def test_backfill_uses_30_day_ranges_and_bulk_inserts():
    s = mem()
    past = [game(f"p{i}", T0 - timedelta(days=5 + i), status="final", winner="home", home_score=100, away_score=90) for i in range(130)]
    src = RangeSrc(past)
    out = pipeline.run_backfill(s, src, CFG, T0, days=100)
    nba = [r for r in src.ranges if r[0] == "nba"]
    assert len(nba) == 4 and nba[0][2] == "2026-11-14" and nba[-1][1] == "2026-08-07"        # 30+30+30+10 days back from yesterday
    assert "dwcs" not in {r[0] for r in src.ranges}
    assert len(s.q("SELECT * FROM games")) == 130 and out["games_upserted"] >= 130
    assert s.q("SELECT COUNT(*) AS n FROM odds_snapshots")[0]["n"] == 0                       # past games get no odds snapshots


def test_backtest_reports_walk_forward_accuracy():
    from picks import backtest
    s = mem()
    teams = [f"T{i}" for i in range(6)]
    strength = {t: i for i, t in enumerate(teams)}                                          # T5 beats T0 reliably
    n = 0
    for rnd in range(14):
        for i, h in enumerate(teams):
            a = teams[(i + 1 + rnd) % 6]
            if a == h:
                continue
            n += 1
            hs, as_ = (100 + strength[h] * 3, 100 + strength[a] * 3)
            pipeline.upsert_game(s, game(f"b{n}", T0 - timedelta(days=60 - n // 3, minutes=n), status="final", home=h, away=a,
                                         winner="home" if hs > as_ else "away", home_score=hs, away_score=as_, odds=None), T0)
    out = backtest.run(s, CFG)["nba"]
    assert out["games"] > 20 and out["accuracy"] > 0.7 and out["log_loss"] < out["baseline_log_loss"]
    assert backtest.run(s, CFG)["nhl"] == {"games": 0}


def test_backfill_stops_at_its_time_budget_and_resumes():
    s = mem()
    src = RangeSrc([game("p1", T0 - timedelta(days=9), status="final", winner="home", home_score=100, away_score=90)])
    first = pipeline.run_backfill(s, src, CFG, T0, days=100, budget_minutes=0, log=lambda *a, **k: None)
    assert first["partial"] is True and src.ranges == []                                  # no time at all: nothing fetched
    second = pipeline.run_backfill(s, src, CFG, T0, days=100, budget_minutes=10, log=lambda *a, **k: None)
    assert second["partial"] is False and len(src.ranges) > 0
    calls = len(src.ranges)
    third = pipeline.run_backfill(s, src, CFG, T0, days=100, budget_minutes=10, log=lambda *a, **k: None)
    assert third["chunks_already_done"] > 0 and len(src.ranges) <= calls + len(pipeline.feeds(CFG))            # finished chunks are not fetched again
