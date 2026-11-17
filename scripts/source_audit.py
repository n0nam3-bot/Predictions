#!/usr/bin/env python3
"""Probe every free data source from inside GitHub Actions and report what really works.

Run it from Actions (Pipeline -> task: audit) because some providers treat cloud IPs differently
from a phone or laptop. Samples are saved in audit_out/ so parsers can be fixed against real responses.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from picks import config  # noqa: E402
from picks.sources import espn  # noqa: E402

UA = {"User-Agent": "picks-board-audit/0.1 (github actions)"}


def probe(session, name, url, check=None, headers=None, sample_dir=None):
    t0 = time.time()
    info = {"name": name, "url": url, "status": None, "ms": None, "bytes": 0, "note": "", "parse_failed": False}
    try:
        r = session.get(url, headers=headers or UA, timeout=25)
        info.update(status=r.status_code, ms=int((time.time() - t0) * 1000), bytes=len(r.content))
        if r.status_code in (200, 206):
            if check:
                try:
                    info["note"] = check(r)
                except Exception as exc:                     # a shape we did not expect
                    info.update(note=f"parse error: {exc}", parse_failed=True)
            if sample_dir:
                Path(sample_dir).mkdir(parents=True, exist_ok=True)
                safe = "".join(c if c.isalnum() else "_" for c in name)
                (Path(sample_dir) / f"{safe}.txt").write_bytes(r.content[:30000])
    except requests.RequestException as exc:
        info["note"] = str(exc)[:100]
    return info


def espn_scoreboard_check(sport_key, kind):
    def check(r):
        raw = r.json()
        events = len(raw.get("events", []))
        games = espn.parse_scoreboard(raw, sport_key, kind)
        with_odds = sum(1 for g in games if g["odds"])
        with_ml = sum(1 for g in games if g["odds"] and g["odds"]["home_ml"] is not None)
        if events and not games:
            raise ValueError(f"{events} events but none parsed")
        extra = f", {sum(1 for g in games if g['sport'] == 'dwcs')} Contender Series bouts" if kind == "bout" else ""
        return f"{events} events, {len(games)} parsed, {with_odds} with odds, {with_ml} with moneyline{extra}"
    return check


def espn_injuries_check(r):
    data = espn.parse_injuries(r.json())
    return f"{len(data)} teams, {sum(len(v) for v in data.values())} injury rows"


def targets(cfg, today):
    ymd, iso_day = today.strftime("%Y%m%d"), today.isoformat()
    out = []
    for key, spec in cfg["sports"].items():
        if "via" in spec:
            continue
        sp, lg = spec["espn"]
        base = espn.BASE.format(sport=sp, league=lg)
        out.append((f"ESPN scoreboard {key}", f"{base}/scoreboard?dates={ymd}&limit=300", espn_scoreboard_check(key, spec["kind"])))
        if spec["kind"] == "team":
            out.append((f"ESPN injuries {key}", f"{base}/injuries", espn_injuries_check))
    for slug in ("dwcs", "dana-white-contender-series", "contender-series"):
        out.append((f"ESPN DWCS slug '{slug}'", f"{espn.BASE.format(sport='mma', league=slug)}/scoreboard", lambda r: f"{len(r.json().get('events', []))} events"))
    out += [
        ("MLB Stats API schedule", f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={iso_day}&hydrate=probablePitcher",
         lambda r: f"{sum(len(d['games']) for d in r.json().get('dates', []))} games"),
        ("NHL web API schedule", f"https://api-web.nhle.com/v1/schedule/{iso_day}",
         lambda r: f"{len(r.json().get('gameWeek', []))} days"),
        ("NBA cdn scoreboard", "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json",
         lambda r: f"{len(r.json().get('scoreboard', {}).get('games', []))} games"),
        ("stats.nba.com (often blocks cloud IPs)", f"https://stats.nba.com/stats/scoreboardv2?GameDate={iso_day}&LeagueID=00&DayOffset=0", None),
        ("nflverse schedule CSV (first KB)", "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv", None),
        ("UFCStats completed events", "http://ufcstats.com/statistics/events/completed", None),
        ("NWS API", "https://api.weather.gov/points/40.8448,-73.8648", lambda r: "grid " + r.json()["properties"]["gridId"]),
        ("Open-Meteo", "https://api.open-meteo.com/v1/forecast?latitude=40.84&longitude=-73.86&hourly=temperature_2m&forecast_days=1",
         lambda r: f"{len(r.json()['hourly']['time'])} hourly points"),
    ]
    return out


def verdict(r):
    if r["status"] not in (200, 206):
        return "FAIL"
    return "check" if r["parse_failed"] else "ok"


def render(results):
    lines = ["### Source audit", "", "| Source | Result | HTTP | ms | Notes |", "|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['name']} | {verdict(r)} | {r['status'] or '-'} | {r['ms'] or '-'} | {r['note']} |")
    bad = [r["name"] for r in results if verdict(r) != "ok"]
    lines += ["", f"{len(results) - len(bad)} of {len(results)} fine."]
    if bad:
        lines.append("Needs attention: " + "; ".join(bad) + ". Fix parsers against the saved samples (audit-samples artifact) before relying on them.")
    lines.append("Not probed on purpose: The Odds API (free plan is only 500 credits a month) and every LLM provider (keys are checked by setup-check).")
    return "\n".join(lines) + "\n"


def main(session=None, today=None, out_dir=None):
    cfg = config.load()
    tz = ZoneInfo(cfg["timezone"])
    today = today or datetime.now(timezone.utc).astimezone(tz).date()
    session = session or requests.Session()
    out_dir = out_dir or ROOT / "audit_out"
    results = []
    for name, url, check in targets(cfg, today):
        headers = {**UA, "Range": "bytes=0-2000"} if "csv" in name.lower() else None
        results.append(probe(session, name, url, check, headers, out_dir))
    report = render(results)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "report.md").write_text(report)
    (Path(out_dir) / "results.json").write_text(json.dumps(results, indent=1))
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report)
    return 0 if any(verdict(r) == "ok" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
