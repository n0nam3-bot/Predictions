"""Offline demo: fictional teams, a simulated day, the real pipeline. Output is clearly labelled as demo data."""
import json
import random
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, ledger, pipeline, ratings as ratings_mod, status, store
from .timing import iso, parse_utc

START = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
FINAL = datetime(2026, 11, 16, 3, 45, tzinfo=timezone.utc)
NOTE = "Demo data: fictional teams and a simulated day. These are not real picks or real results."


def amplified(cfg):
    """Demo only: let the model follow its own rating fully, so the demo day shows plays as well as passes."""
    c = deepcopy(cfg)
    c["model"]["anchor_shrink"] = 1.0
    return c


def _g(gid, sport, start, home, away, odds, result=None, **kw):
    return {"id": f"demo:{gid}", "sport": sport, "kind": "team", "event_id": f"demo:{gid}", "event_name": f"{away} at {home}",
            "start_utc": start, "home": home, "away": away, "venue": f"{home} Arena", "home_record": None, "away_record": None,
            "odds": dict(zip(("home_ml", "away_ml"), odds), book="Demo Book", source="demo") if odds else None,
            "result": result, "duration_h": 3, "method": None, **kw}


def scenario():
    g = [
        _g("n1", "nfl", "2026-11-15T18:00:00Z", "Summit Ravens", "Delta Pilots", (-120, 100), (27, 20)),
        _g("n2", "nfl", "2026-11-15T21:25:00Z", "Cobalt Falcons", "Maple Wolves", (-125, 105), (17, 24)),
        _g("h1", "nhl", "2026-11-15T23:00:00Z", "Iron Coast Skaters", "Northgate Owls", (-115, -105), (3, 2)),
        _g("h2", "nhl", "2026-11-16T00:00:00Z", "Prairie Foxes", "Glacier Kings", (-110, -110), None, cancel=True),
        _g("h3", "nhl", "2026-11-16T04:30:00Z", "Ember Bay Comets", "Redwater Pilots", (-130, 110)),
        _g("b1", "nba", "2026-11-15T23:30:00Z", "Harbor City Anglers", "Lakeview Herons", (-110, -110), (101, 96)),
        _g("b2", "nba", "2026-11-16T01:30:00Z", "Ridge Bears", "Iron Coast Smiths", (-105, -115)),
        _g("b3", "nba", "2026-11-16T03:30:00Z", "Westfield Foxes", "Pine Valley Rams", (-110, -110)),
        _g("b4", "nba", "2026-11-16T03:50:00Z", "Capital Owls", "Sunset Lions", (-150, 130)),
    ]
    first = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)
    names = [("Luis Ferro", "Kenji Arai"), ("Tomas Reyes-Hale", "Ivo Brandt"), ("Dario Okoro", "Hana Sato"),
             ("Marcus Vale", "Bruno Keane")]
    for i, (a, b) in enumerate(names):
        g.append({"id": f"demo:f{i}", "sport": "ufc", "kind": "bout", "event_id": "demo:card1", "event_name": "Demo Fight Night",
                  "start_utc": iso(first + timedelta(hours=i)), "home": a, "away": b, "venue": "Demo Apex",
                  "home_record": None, "away_record": None, "odds": ({"home_ml": -180, "away_ml": 150, "book": "Demo Book",
                  "source": "demo"} if i == 3 else None), "result": None, "duration_h": 0.5, "method": None})
    return g


# Team strength (-1 weak .. +1 strong) and days since each team last played, for rating and rest.
STRENGTH = {"Summit Ravens": 0.8, "Delta Pilots": -0.6, "Cobalt Falcons": 0.7, "Maple Wolves": -0.5,
            "Iron Coast Skaters": 0.6, "Northgate Owls": -0.4, "Prairie Foxes": 0.5, "Glacier Kings": -0.3,
            "Ember Bay Comets": 0.3, "Redwater Pilots": -0.2, "Harbor City Anglers": 0.7, "Lakeview Herons": -0.6,
            "Ridge Bears": 0.1, "Iron Coast Smiths": 0.0, "Westfield Foxes": 0.5, "Pine Valley Rams": -0.4,
            "Capital Owls": -0.5, "Sunset Lions": 0.6}
LAST_GAP = {"Delta Pilots": 4, "Summit Ravens": 7, "Maple Wolves": 7, "Cobalt Falcons": 7, "Northgate Owls": 1.1, "Iron Coast Skaters": 3,
            "Glacier Kings": 1.2, "Prairie Foxes": 3, "Lakeview Herons": 1.1, "Harbor City Anglers": 3, "Pine Valley Rams": 1.2,
            "Westfield Foxes": 3, "Sunset Lions": 1.2, "Capital Owls": 3}
# Edge each game is priced to give the model (positive = value on the home side). Small ones become passes.
TARGET_EDGE = {"n1": 0.06, "n2": 0.075, "h1": 0.07, "h2": 0.045, "h3": 0.03, "b1": 0.055, "b2": 0.004, "b3": 0.012, "b4": -0.05}
BASE = {"nfl": (24, 4), "nba": (108, 7), "nhl": (3, 1)}
SPORT_OF = {}


class FixtureSource:
    def __init__(self, games, injuries):
        self.games = {g["id"]: g for g in games}
        self.injuries = injuries
        self.now = START

    def _view(self, g):
        s = parse_utc(g["start_utc"])
        v = {k: g[k] for k in g if k not in ("result", "duration_h", "cancel", "visible_from")}
        v.update(status="scheduled", home_score=None, away_score=None, winner=None)
        if g.get("cancel") and self.now >= s - timedelta(minutes=20):
            v["status"] = "cancelled"
        elif self.now >= s + timedelta(hours=g["duration_h"]) and g.get("result"):
            hs, as_ = g["result"]
            v.update(status="final", home_score=hs, away_score=as_, winner="home" if hs > as_ else "away")
        elif self.now >= s:
            v["status"] = "in_progress"
        return v

    def fetch_day(self, sport, day):
        from zoneinfo import ZoneInfo
        out = []
        for g in self.games.values():
            if g["sport"] != sport or (g.get("visible_from") and self.now < parse_utc(g["visible_from"])):
                continue
            if parse_utc(g["start_utc"]).astimezone(ZoneInfo("America/New_York")).date().isoformat() == str(day):
                out.append(self._view(g))
        return out

    def fetch_injuries(self, sport):
        return self.injuries.get(sport, {})


def _seed_history(st, games, now, rng):
    team_sport = {}
    for g in games:
        if g["kind"] == "team":
            team_sport[g["home"]] = team_sport[g["away"]] = g["sport"]
    n = 0
    for team, sport in team_sport.items():
        base, spread = BASE[sport]
        for i in range(12):
            n += 1
            days_ago = LAST_GAP.get(team, 3) + i * 2.6
            win = rng.random() < 0.5 + 0.14 * STRENGTH.get(team, 0)
            margin = rng.randint(1, max(2, spread))
            hi, lo = base + margin, base
            home = i % 2 == 0
            hs, as_ = (hi, lo) if (win == home) else (lo, hi)
            opp = f"Past Opponent {n % 9}"
            pipeline.upsert_game(st, {"id": f"hist:{n}", "sport": sport, "kind": "team", "event_id": f"hist:{n}", "event_name": "history",
                                      "start_utc": iso(START - timedelta(days=days_ago)), "home": team if home else opp, "away": opp if home else team,
                                      "venue": None, "status": "final", "home_score": hs, "away_score": as_,
                                      "winner": "home" if hs > as_ else "away", "odds": None}, now)


def _price_games(st, games, cfg):
    """Quote each scenario game so the rating model sees the edge in TARGET_EDGE (with a normal 4% vig)."""
    from . import facts, market, model
    rcache = ratings_mod.Cache(st, cfg)
    for g in games:
        key = g["id"].split(":")[1]
        if g["kind"] != "team" or key not in TARGET_EDGE:
            continue
        probe = dict(g, odds_json=json.dumps({"home_ml": -110, "away_ml": -110}))
        pk = facts.build_packet(st, probe, START, cfg, rcache)
        rating_home = model.project(pk, cfg)["rating_home"]
        p_mkt = min(max(rating_home - TARGET_EDGE[key], 0.25), 0.75)
        g["odds"] = {"home_ml": market.prob_to_american(min(p_mkt + 0.02, 0.97)), "away_ml": market.prob_to_american(min(1 - p_mkt + 0.02, 0.97)),
                     "book": "Demo Book", "source": "demo"}


def _seed_old_record(st, cfg, rng):
    """Synthetic picks on earlier days so the 30-day strip and totals have something to show."""
    for d in range(29, 0, -1):
        for k in range(rng.choice([0, 1, 2, 3, 3, 4])):
            sport = rng.choice(["mlb", "nfl", "nba", "nhl"]) if d > 120 else rng.choice(["nfl", "nba", "nhl"])
            start = START - timedelta(days=d, hours=-(k * 2))
            pid = f"old:{d}:{k}"
            row = {"id": pid, "game_id": pid, "sport": sport, "start_utc": iso(start), "published_utc": iso(start - timedelta(minutes=31)),
                   "tag": "ON_TIME", "verdict": "PLAY", "market": "ML", "selection": "home", "line": None,
                   "odds": rng.choice([-110, -105, 105, 120]), "fair_odds": -115, "model_prob": 0.56, "market_prob": 0.52,
                   "edge": 0.04, "units": rng.choice([1, 1, 2]), "confidence": 5, "top_pick": int(rng.random() < 0.2),
                   "rank_score": 0.03, "coverage": 0.95, "payload_json": json.dumps({"headline": "demo", "narrative": {}, "home": "", "away": "",
                   "reason": None, "unavailable": [], "inputs": {}, "narrative_source": "template"})}
            ledger.insert_pick(st, row)
            grade = rng.choices(["W", "L", "V"], [54, 41, 5])[0]
            profit = 0.0
            st.x("INSERT INTO grades (pick_id, grade, reason, profit_units, graded_utc, source) VALUES (?,?,?,?,?,?)",
                 (pid, grade, "demo", profit, iso(start + timedelta(hours=4)), "demo"))


def run(cfg=None):
    cfg = amplified(cfg or config.load())
    st = store.SqliteStore()
    store.migrate(st)
    games = scenario()
    injuries = {"nfl": {}, "nhl": {}, "nba": {"Lakeview Herons": [{"name": "Sam Rook", "pos": "G", "status": "Out"}],
                                              "Pine Valley Rams": [{"name": "Eli Marsh", "pos": "F", "status": "Out"}],
                                              "Harbor City Anglers": [], "Westfield Foxes": []}}
    for sport in ("nfl", "nhl", "nba"):
        for g in games:
            if g["sport"] == sport:
                injuries[sport].setdefault(g["home"], [])
                injuries[sport].setdefault(g["away"], [])
    injuries["nfl"]["Delta Pilots"] = [{"name": "Joe Calder", "pos": "QB", "status": "Out"}]
    injuries["nhl"]["Northgate Owls"] = [{"name": "Piotr Nyl", "pos": "G", "status": "Out"}]
    _seed_history(st, games, START, random.Random(11))
    _price_games(st, games, cfg)
    src = FixtureSource(games, injuries)
    _seed_old_record(st, cfg, random.Random(7))
    t = START
    while t <= FINAL:
        src.now = t
        if (t - START) % timedelta(hours=3) == timedelta(0):
            pipeline.run_schedule(st, src, cfg, t)
        if not (datetime(2026, 11, 16, 3, 5, tzinfo=timezone.utc) <= t < FINAL):   # GitHub dropped these cron runs
            pipeline.run_tick(st, src, cfg, t)
        if t.minute % 30 == 0:
            pipeline.run_grade(st, src, cfg, t)
        t += timedelta(minutes=5)
    src.now = FINAL
    pipeline.run_grade(st, src, cfg, FINAL)
    status.write(st, cfg, FINAL, {})
    latest = pipeline.build_snapshots(st, cfg, FINAL)
    latest["source"] = "demo"
    latest["demo_note"] = NOTE
    return latest, st


def write(path):
    latest, _ = run()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(latest, indent=1))
    return latest
