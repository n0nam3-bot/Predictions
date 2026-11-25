"""On 2026-11-23 the Status panel showed ESPN answering the 30-day date-range request with HTTP 400 for NFL, NBA
and NHL (MLB's worked), so history never loaded and no team had the 8 games needed for a rating. The history
load now falls back to one request per day, the call the schedule task already makes."""
from datetime import date, timedelta

from picks import config, pipeline, ratings, status, store
from picks.sources import espn
from picks.timing import iso
from test_pipeline import Src, T0, game

CFG = config.load()
quiet = lambda *a, **k: None


def mem():
    st = store.SqliteStore()
    store.migrate(st)
    return st


class NoRangeSrc(Src):
    """Refuses date ranges for the sports in `refuse` (as ESPN does for NFL, NBA, NHL) and serves one day at a time."""

    def __init__(self, games, refuse=("nba",), bad_days=(), all_bad=()):
        super().__init__(games)
        self.refuse, self.bad_days, self.all_bad = set(refuse), set(bad_days), set(all_bad)
        self.ranges, self.days = [], []

    def fetch_range(self, sport, start, end):
        self.ranges.append((sport, str(start), str(end)))
        if sport in self.refuse:
            raise RuntimeError("ESPN request failed: HTTP 400 (basketball/nba/scoreboard?dates=20260328-20260426&limit=1000)")
        return [dict(g) for g in self.games if g["sport"] == sport]

    def fetch_days(self, sport, days):
        games, problems = [], []
        for d in days:
            self.days.append((sport, str(d)))
            if sport in self.all_bad or str(d) in self.bad_days:
                problems.append(f"{d}: ESPN request failed: HTTP 400")
            else:
                games += [dict(g) for g in self.games if g["sport"] == sport and g["start_utc"].startswith(str(d))]
        return games, problems


def finals(n, sport="nba", first_back=2):
    return [game(f"p{i}", T0 - timedelta(days=first_back + i), sport=sport, status="final", winner="home",
                 home_score=100, away_score=90) for i in range(n)]


def items(s):
    return {i["name"]: i for i in status.compute(s, CFG, T0, {})["items"]}


def test_chunks_are_30_days_newest_first():
    got = pipeline.backfill_chunks(date(2026, 11, 15), 100)
    assert [(str(a), str(b)) for a, b in got] == [("2026-10-16", "2026-11-14"), ("2026-09-16", "2026-10-15"),
                                                  ("2026-08-17", "2026-09-15"), ("2026-08-07", "2026-08-16")]


def test_range_refused_falls_back_to_day_by_day_and_completes():
    s = mem()
    src = NoRangeSrc(finals(40), refuse={"nba"})
    out = pipeline.run_backfill(s, src, CFG, T0, days=60, log=quiet)
    assert len(s.q("SELECT * FROM games WHERE sport = 'nba'")) == 40
    nba = out["by_sport"]["nba"]
    assert nba["mode"] == "day" and nba["failed"] == 0 and nba["loaded"] == nba["chunks"] == 2
    assert [r for r in src.ranges if r[0] == "nba"] == [("nba", "2026-10-16", "2026-11-14")]       # asked for a range once, then stopped
    assert pipeline.get_snapshot(s, "backfill_complete")["days"] == 60 and out["note"] == "Complete."
    note = pipeline.get_snapshot(s, "sources")["backfill:nba"]
    assert note["ok"] and "day by day" in note["detail"] and "2 of 2 chunks" in note["detail"]


def test_a_failed_day_keeps_its_chunk_open_and_the_next_run_finishes_it():
    s = mem()
    src = NoRangeSrc(finals(40), refuse={"nba"}, bad_days={"2026-10-20"})
    out = pipeline.run_backfill(s, src, CFG, T0, days=60, log=quiet)
    nba = out["by_sport"]["nba"]
    assert nba["failed"] == 1 and nba["loaded"] == 1 and "2026-10-20" in nba["first_problem"]
    assert pipeline.get_snapshot(s, "backfill_complete") is None and "Some chunks failed (nba)" in out["note"]
    assert len(s.q("SELECT * FROM games WHERE sport = 'nba'")) == 39                              # every good day of the chunk was still stored
    d = items(s)
    assert d["History load"]["state"] == "bad"
    assert "NBA" in d["History load"]["detail"] and "2026-10-20" in d["History load"]["detail"] and "HTTP 400" in d["History load"]["detail"]
    src.bad_days.clear()
    out2 = pipeline.run_backfill(s, src, CFG, T0, days=60, log=quiet)
    assert out2["by_sport"]["nba"]["failed"] == 0 and pipeline.get_snapshot(s, "backfill_complete")
    assert len(s.q("SELECT * FROM games WHERE sport = 'nba'")) == 40


def test_a_sport_whose_every_day_fails_is_dropped_for_the_run_and_the_others_continue():
    s = mem()
    src = NoRangeSrc(finals(10, sport="mlb"), refuse={"nba", "nhl"}, all_bad={"nba"})
    out = pipeline.run_backfill(s, src, CFG, T0, days=90, log=quiet)
    assert len([d for d in src.days if d[0] == "nba"]) == 30                                      # one chunk tried, then it gave up on NBA
    assert out["by_sport"]["nba"]["failed"] == 1 and out["by_sport"]["nba"]["loaded"] == 0
    assert out["by_sport"]["nhl"]["failed"] == 0
    assert out["by_sport"]["mlb"]["loaded"] == out["by_sport"]["mlb"]["chunks"]
    assert len(s.q("SELECT * FROM games WHERE sport = 'mlb'")) == 10


def test_history_loaded_day_by_day_gives_every_team_enough_games_for_a_rating():
    s = mem()
    teams = [f"Team {c}" for c in "ABCDEFGHIJ"]
    games = [game(f"h{n}", T0 - timedelta(days=2 + n // 4, minutes=n), home=teams[n % 10], away=teams[(n * 3 + 1) % 10],
                  status="final", winner="home", home_score=100 + n % 7, away_score=95, odds=None) for n in range(160)]
    pipeline.run_backfill(s, NoRangeSrc(games, refuse={"nba"}), CFG, T0, days=60, log=quiet)
    r = ratings.build(s, "nba", CFG, iso(T0))
    assert r.n_games == 160 and all(r.games[t] >= CFG["model"]["min_rated_games"] for t in teams)


def test_status_shows_progress_while_history_loads_then_complete():
    s = mem()
    src = NoRangeSrc(finals(5), refuse=())
    pipeline.run_backfill(s, src, CFG, T0, days=60, budget_minutes=0, log=quiet)                    # no time: stops after noting the first sport
    d = items(s)["History load"]
    assert d["state"] == "warn" and d["detail"].startswith("In progress.") and "chunks loaded" in d["detail"]
    pipeline.run_backfill(s, src, CFG, T0, days=60, log=quiet)
    d = items(s)["History load"]
    assert d["state"] == "ok" and d["detail"].startswith("Complete as of")


class Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


def event(day, season_type=2, eid=None):
    return {"id": eid or day, "date": f"{day[:4]}-{day[4:6]}-{day[6:8]}T00:30Z", "name": "A at B", "shortName": "A @ B",
            "season": {"year": 2026, "type": season_type},
            "competitions": [{"status": {"type": {"name": "STATUS_FINAL", "state": "post", "completed": True}},
                              "competitors": [{"homeAway": "home", "score": "101", "team": {"displayName": "B", "abbreviation": "B"}},
                                              {"homeAway": "away", "score": "99", "team": {"displayName": "A", "abbreviation": "A"}}]}]}


class Session:
    def __init__(self, bad=("20261110",)):
        self.urls, self.bad = [], bad

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        if any(f"dates={b}" in url for b in self.bad):
            return Resp(400, {})
        return Resp(200, {"events": [event(url.split("dates=")[1][:8])]})


def test_fetch_days_collects_problems_in_a_short_readable_form(monkeypatch):
    monkeypatch.setattr(espn.time, "sleep", lambda s: None)
    sess = Session()
    games, problems = espn.ESPNSource(CFG, session=sess).fetch_days("nba", [date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)])
    assert [g["id"] for g in games] == ["espn:nba:20261109", "espn:nba:20261111"]                   # order kept
    assert len(problems) == 1 and problems[0].startswith("2026-11-10: ESPN request failed: HTTP 400 (basketball/nba/scoreboard?dates=20261110")
    assert "https://" not in problems[0]
    assert sum("dates=20261110" in u for u in sess.urls) == 3                                      # the bad day was retried, the others were not
    assert all("limit=300" in u for u in sess.urls)                                                # the call the schedule task already makes


def test_preseason_and_offseason_games_are_ignored_but_unlabelled_ones_are_kept():
    raw = {"events": [event("20261005", 1, "1"), event("20261025", 2, "2"), event("20260712", 4, "3"),
                      event("20260420", 3, "4"), {**event("20261101", 2, "5"), "season": {}},
                      {**event("20261102", 2, "6"), "season": {"slug": "preseason"}}, {k: v for k, v in event("20261103", 2, "7").items() if k != "season"}]}
    assert [g["id"] for g in espn.parse_scoreboard(raw, "nba", "team")] == ["espn:nba:2", "espn:nba:4", "espn:nba:5", "espn:nba:7"]
