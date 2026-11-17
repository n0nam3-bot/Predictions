import json
from pathlib import Path

from picks import config
from picks.sources import espn

FX = Path(__file__).resolve().parent.parent / "fixtures"
CFG = config.load()


def load(name):
    return json.loads((FX / name).read_text())


def test_team_scoreboard_parses_both_odds_shapes_and_statuses():
    games = espn.parse_scoreboard(load("espn_nba_scoreboard.json"), "nba", "team")
    assert [g["status"] for g in games] == ["scheduled", "final", "postponed"]        # bad event skipped
    a, b, c = games
    assert a["id"] == "espn:nba:9001" and a["home"] == "Harbor City Anglers" and a["start_utc"] == "2026-11-16T00:30:00Z"
    assert (a["odds"]["home_ml"], a["odds"]["away_ml"], a["odds"]["spread_home"], a["odds"]["total"]) == (-160, 135, -3.5, 221.5)
    assert a["odds"]["over_odds"] == -110 and a["home_record"] == "7-3" and a["venue"] == "Harbor Arena"
    assert (b["odds"]["home_ml"], b["odds"]["away_ml"], b["odds"]["spread_home"]) == (105, -125, 1.5)   # derived from 'RID -1.5'
    assert b["winner"] == "home" and b["home_score"] == 108 and a["home_score"] is None
    assert c["odds"] is None and c["winner"] is None


def test_bouts_are_ordered_and_graded_by_winner_flag():
    bouts = espn.parse_scoreboard(load("espn_ufc_scoreboard.json"), "ufc", "bout")
    assert len(bouts) == 3 and {b["event_id"] for b in bouts} == {"espn:5001"}
    assert bouts[0]["winner"] == "home" and bouts[0]["home"] == "Tomas Reyes-Hale"
    assert (bouts[1]["home"], bouts[1]["away"]) == ("Luis Ferro", "Kenji Arai")          # sorted by 'order'
    assert bouts[1]["odds"]["home_ml"] == -180 and bouts[2]["odds"] is None


def test_injuries_and_helpers():
    inj = espn.parse_injuries(load("espn_injuries.json"))
    assert inj["Harbor City Anglers"][0] == {"name": "Sam Rook", "pos": "G", "status": "Out"} and inj["Lakeview Herons"] == []
    assert espn._num("EVEN") == 100 and espn._num("+130") == 130 and espn._num("o221.5") == 221.5 and espn._num("x") is None
    assert espn.parse_odds([]) is None and espn.parse_odds([{"provider": {"name": "x"}}]) is None


class FakeHTTP:
    def __init__(self, replies):
        self.replies, self.urls = list(replies), []

    def get(self, url, **kw):
        self.urls.append(url)
        code, body = self.replies.pop(0)

        class R:
            status_code = code

            def json(self_inner):
                return body
        return R()


def test_source_builds_urls_and_retries(monkeypatch):
    monkeypatch.setattr(espn.time, "sleep", lambda s: None)
    http = FakeHTTP([(503, None), (200, load("espn_nba_scoreboard.json"))])
    src = espn.ESPNSource(CFG, http)
    games = src.fetch_day("nba", "2026-11-15")
    assert len(games) == 3 and http.urls[0].endswith("/basketball/nba/scoreboard?dates=20261115&limit=300")
    assert espn.ESPNSource(CFG, FakeHTTP([(200, load("espn_injuries.json"))])).fetch_injuries("nba")["Lakeview Herons"] == []
    assert espn.ESPNSource(CFG, FakeHTTP([])).fetch_injuries("ufc") == {}


def test_contender_series_is_labelled_from_the_ufc_feed_and_has_no_own_endpoint():
    raw = load("espn_ufc_scoreboard.json")
    raw["events"][0]["name"] = "Dana White's Contender Series: Season 10, Week 3"
    bouts = espn.parse_scoreboard(raw, "ufc", "bout")
    assert {b["sport"] for b in bouts} == {"dwcs"} and bouts[0]["id"].startswith("espn:dwcs:")
    assert CFG["sports"]["dwcs"] == {"kind": "bout", "via": "ufc"}
    http = FakeHTTP([(200, raw)])
    games = espn.ESPNSource(CFG, http).fetch_day("dwcs", "2026-11-19")
    assert http.urls[0].endswith("/mma/ufc/scoreboard?dates=20261119&limit=300") and games[0]["sport"] == "dwcs"
