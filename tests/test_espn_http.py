"""A real HTTP round trip against a local stand-in for ESPN that behaves the way production did on 2026-11-23:
one request per day works for every league, a date range works for MLB but answers HTTP 400 for NBA (as it does for
NFL and NHL), preseason games carry season type 1, and now and then a request fails with HTTP 503 and must be retried."""
import json
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from picks import config, pipeline, ratings, store
from picks.sources import espn
from picks.timing import iso
from test_pipeline import T0

CFG = config.load()
REGULAR_SEASON_STARTS = date(2026, 10, 21)


def events(league, d):
    n, season_type = (3, 1) if league == "nba" and d < REGULAR_SEASON_STARTS else (3, 2)
    out = []
    for i in range(n):
        home, away = f"{league.upper()} Team {(d.toordinal() + i) % 8}", f"{league.upper()} Team {(d.toordinal() + i + 3) % 8}"
        out.append({"id": f"{league}-{d:%Y%m%d}-{i}", "date": f"{d.isoformat()}T{18 + i:02d}:00Z", "name": f"{away} at {home}",
                    "shortName": "A @ H", "season": {"year": 2026, "type": season_type},
                    "competitions": [{"status": {"type": {"name": "STATUS_FINAL", "state": "post", "completed": True}},
                                      "competitors": [{"homeAway": "home", "score": str(100 + (d.toordinal() + i) % 7), "team": {"displayName": home, "abbreviation": "H"}},
                                                      {"homeAway": "away", "score": "95", "team": {"displayName": away, "abbreviation": "A"}}]}]})
    return out


class Handler(BaseHTTPRequestHandler):
    calls = {"n": 0, "range_400": 0, "503": 0}
    lock = threading.Lock()

    def log_message(self, *a):
        pass

    def reply(self, code, body=None):
        data = json.dumps(body or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        league = u.path.strip("/").split("/")[5]
        raw = parse_qs(u.query)["dates"][0]
        with self.lock:
            Handler.calls["n"] += 1
            hiccup = Handler.calls["n"] % 11 == 0
            if hiccup:
                Handler.calls["503"] += 1
        if hiccup:
            return self.reply(503)
        if "-" in raw:
            if league == "nba":
                with self.lock:
                    Handler.calls["range_400"] += 1
                return self.reply(400)
            a, b = (datetime.strptime(x, "%Y%m%d").date() for x in raw.split("-"))
            return self.reply(200, {"events": [e for k in range((b - a).days + 1) for e in events(league, a + timedelta(days=k))]})
        return self.reply(200, {"events": events(league, datetime.strptime(raw, "%Y%m%d").date())})


@pytest.fixture
def espn_standin(monkeypatch):
    Handler.calls = {"n": 0, "range_400": 0, "503": 0}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(espn, "BASE", f"http://127.0.0.1:{srv.server_address[1]}/apis/site/v2/sports/{{sport}}/{{league}}")
    monkeypatch.setattr(espn.time, "sleep", lambda s: None)                                       # no real back-off in a test
    yield srv
    srv.shutdown()
    srv.server_close()


def test_history_loads_over_real_http_when_espn_refuses_date_ranges(espn_standin):
    s = store.SqliteStore()
    store.migrate(s)
    quiet = lambda *a, **k: None
    out = pipeline.run_backfill(s, espn.ESPNSource(CFG), CFG, T0, days=45, budget_minutes=10, log=quiet)
    assert out["note"] == "Complete." and out["partial"] is False
    assert out["by_sport"]["nba"]["mode"] == "day" and out["by_sport"]["mlb"]["mode"] == "range"
    assert out["by_sport"]["nba"]["failed"] == 0 and out["by_sport"]["nba"]["loaded"] == out["by_sport"]["nba"]["chunks"] == 2
    assert Handler.calls["range_400"] >= 1 and Handler.calls["503"] >= 1                           # the refusal and the hiccups really happened
    nba = s.q("SELECT start_utc FROM games WHERE sport = 'nba' AND status = 'final'")
    assert len(nba) == 3 * 25 and min(r["start_utc"] for r in nba) >= "2026-10-21"                  # Oct 1-20 was preseason: ignored
    assert len(s.q("SELECT * FROM games WHERE sport = 'mlb'")) == 3 * 45
    r = ratings.build(s, "nba", CFG, iso(T0))
    assert all(r.games[f"NBA Team {i}"] >= CFG["model"]["min_rated_games"] for i in range(8))        # every team can now be rated
    again = pipeline.run_backfill(s, espn.ESPNSource(CFG), CFG, T0, days=45, budget_minutes=10, log=quiet)
    assert again["chunks_already_done"] >= 1 and len(s.q("SELECT * FROM games WHERE sport = 'nba'")) == 75   # resumable, no duplicates
