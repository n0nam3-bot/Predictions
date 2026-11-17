import json
from datetime import date
from pathlib import Path

import requests

import setup_check
import source_audit
from fake_turso import WRITE, FakeTurso

FX = Path(__file__).resolve().parent.parent / "fixtures"


class Resp:
    def __init__(self, status, body=b"{}"):
        self.status_code, self.content = status, body if isinstance(body, bytes) else json.dumps(body).encode()

    def json(self):
        return json.loads(self.content)


class Session:
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, timeout=0):
        self.calls.append(url)
        if "basketball/nba/scoreboard" in url:
            return Resp(200, (FX / "espn_nba_scoreboard.json").read_bytes())
        if "mma/ufc/scoreboard" in url:
            return Resp(200, (FX / "espn_ufc_scoreboard.json").read_bytes())
        if "stats.nba.com" in url:
            raise requests.ConnectTimeout("blocked")
        if "statsapi.mlb.com" in url:
            return Resp(200, {"dates": [{"games": [1, 2, 3]}]})
        if "/injuries" in url and "basketball" in url:
            return Resp(200, (FX / "espn_injuries.json").read_bytes())
        if "dwcs" in url:
            return Resp(404)
        return Resp(200, {"scoreboard": {"games": []}, "gameWeek": [], "properties": {"gridId": "OKX"}, "hourly": {"time": [1]}, "events": []})


def test_audit_reports_ok_fail_and_parse_mismatch(tmp_path):
    rc = source_audit.main(Session(), date(2026, 11, 15), tmp_path)
    assert rc == 0
    report = (tmp_path / "report.md").read_text()
    assert "| ESPN scoreboard nba | ok | 200 |" in report and "3 parsed, 2 with odds, 2 with moneyline" in report
    assert "| ESPN scoreboard ufc | ok |" in report and "3 parsed" in report
    assert "| stats.nba.com (often blocks cloud IPs) | FAIL | - |" in report and "blocked" in report
    assert "ESPN DWCS slug 'dwcs' | FAIL" in report
    assert "MLB Stats API schedule | ok | 200 | " in report and "3 games" in report
    assert (tmp_path / "ESPN_scoreboard_nba.txt").exists()


def test_audit_flags_events_that_do_not_parse(tmp_path):
    class Odd(Session):
        def get(self, url, headers=None, timeout=0):
            if "football/nfl/scoreboard" in url:
                return Resp(200, {"events": [{"id": "1", "weird": True}]})
            return super().get(url, headers, timeout)

    source_audit.main(Odd(), date(2026, 11, 15), tmp_path)
    assert "| ESPN scoreboard nfl | check |" in (tmp_path / "report.md").read_text()


def test_setup_check_missing_then_complete():
    rows, ok = setup_check.check({"GITHUB_REPOSITORY": "n0nam3-bot/Predictions"})
    assert not ok and [r[1] for r in rows[:2]] == ["MISSING", "MISSING"]
    assert "https://github.com/n0nam3-bot/Predictions/settings/secrets/actions/new" in rows[0][2]
    text0 = setup_check.render(rows, ok, {"GITHUB_REPOSITORY": "n0nam3-bot/Predictions"})
    assert "aistudio.google.com/apikey" in text0 and "the-odds-api.com" in text0
    fake = FakeTurso()
    try:
        env = {"TURSO_URL": fake.url, "TURSO_WRITE_TOKEN": WRITE, "GEMINI_API_KEY": "k", "INBOX_PAT_SET": "true",
               "SITE_URL": "https://picks.example.vercel.app"}
        from datetime import datetime, timedelta, timezone
        from picks import store as _store
        w = _store.TursoStore(fake.url, WRITE)
        _store.migrate(w)
        stamp = lambda m: (datetime.now(timezone.utc) - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows, ok = setup_check.check(env, lambda url, timeout: Resp(200, {"ok": True, "commit": "abcdef123", "db": "ok"}))
        assert not ok and {r[0]: r for r in rows}["Scheduler (tick)"][1] == "MISSING"           # never ticked
        w.x("INSERT INTO heartbeat (kind, at_utc) VALUES ('tick', ?)", (stamp(3),))
        rows, ok = setup_check.check(env, lambda url, timeout: Resp(200, {"ok": True, "commit": "abcdef123", "db": "ok"}))
        d = {r[0]: r for r in rows}
        assert ok and d["Database reachable, schema applied"][1] == "ok" and "abcdef1" in d["Vercel site reachable"][2]
        assert d["Free LLM key (optional)"][2] == "GEMINI_API_KEY"
        w.x("INSERT INTO heartbeat (kind, at_utc) VALUES ('tick', ?)", (stamp(300),))
        w.x("DELETE FROM heartbeat WHERE at_utc > ?", (stamp(100),))
        rows, ok = setup_check.check(env, lambda url, timeout: Resp(200, {"ok": True, "commit": "abcdef123", "db": "ok"}))
        sched = {r[0]: r for r in rows}["Scheduler (tick)"]
        assert not ok and "RELIABLE_CLOCK" in sched[2]                                              # stale tick explained
        rows, ok = setup_check.check({**env, "TURSO_WRITE_TOKEN": "wrong"})
        assert not ok
        text = setup_check.render(rows, ok)
        assert "MISSING" in text
    finally:
        fake.close()
