"""Build the facts packet for a game: every input with value, source, fetched_at (or a reason it is missing)."""
import json
from zoneinfo import ZoneInfo

from . import market, ratings as ratings_mod
from .timing import iso, parse_utc

INPUT_META = {
    "market": ("betting market", ["odds", "line", "price", "market"]),
    "ratings": ("team ratings", ["rating", "elo", "stronger", "weaker"]),
    "schedule_rest": ("rest and schedule", ["rest", "back-to-back", "days off", "schedule", "travel"]),
    "recent_form": ("recent form", ["form", "streak", "last five", "recent"]),
    "injuries": ("injuries", ["injur", "inactive", "questionable", "doubtful", "out for", "availability", "lineup"]),
}
SEVERITY = {"out": 0, "doubtful": 1, "questionable": 2, "day-to-day": 3}
LONG_TERM = ("injured reserve", "injured list", "ir", "60-day", "10-day il", "15-day il", "suspension")


def _input(value, source, fetched_at, reason=None):
    return {"value": value, "source": source, "fetched_at": fetched_at, "reason": reason}


def team_history(store, game, team, limit=8):
    return store.q("SELECT * FROM games WHERE sport = ? AND status = 'final' AND start_utc < ? AND (home = ? OR away = ?) "
                   "ORDER BY start_utc DESC LIMIT ?", (game["sport"], game["start_utc"], team, team, limit))


def _day(iso_s, tz):
    return parse_utc(iso_s).astimezone(ZoneInfo(tz)).date()


def _schedule(history, start, tz):
    gd = _day(start, tz)
    off = max(0, (gd - _day(history[0]["start_utc"], tz)).days - 1)
    week = 1 + sum(1 for h in history if (gd - _day(h["start_utc"], tz)).days <= 6)
    return {"days_off": off, "games_in_last_7_days": week}


def _form(history, team):
    results, diff = [], 0.0
    for g in history[:5]:
        home = g["home"] == team
        mine, theirs = (g["home_score"], g["away_score"]) if home else (g["away_score"], g["home_score"])
        if mine is None or theirs is None:
            won = g["winner"] == ("home" if home else "away")
            results.append({"r": "W" if won else "L", "score": None})
            continue
        results.append({"r": "W" if mine > theirs else "L" if theirs > mine else "T", "score": f"{int(mine)}-{int(theirs)}"})
        diff += mine - theirs
    w = sum(1 for r in results if r["r"] == "W")
    return {"w": w, "l": sum(1 for r in results if r["r"] == "L"), "games": len(results), "diff": round(diff, 1), "results": results}


def _injuries(raw):
    short, long_term = [], 0
    for p in raw or []:
        status = (p.get("status") or "").lower()
        if any(k in status for k in LONG_TERM):
            long_term += 1
        elif status in SEVERITY:
            short.append(p)
    short.sort(key=lambda p: SEVERITY[p["status"].lower()])
    return [{"name": p["name"], "pos": p.get("pos"), "status": p["status"]} for p in short[:6]], long_term


def build_packet(store, game, now, cfg=None, cache=None):
    from . import config
    cfg = cfg or config.load()
    tz = cfg["timezone"]
    now_iso = iso(parse_utc(now))
    odds = json.loads(game["odds_json"]) if game.get("odds_json") else None
    inputs = {}
    if odds and odds.get("home_ml") is not None and odds.get("away_ml") is not None:
        ph, pa, vig = market.no_vig_two_way(odds["home_ml"], odds["away_ml"])
        first = store.q("SELECT home_ml, away_ml FROM odds_snapshots WHERE game_id = ? ORDER BY taken_utc, id LIMIT 1", (game["id"],))
        inputs["market"] = _input({**odds, "no_vig_home": round(ph, 4), "no_vig_away": round(pa, 4), "vig": round(vig, 4),
                                   "opening": first[0] if first else None}, odds.get("source", "espn"), now_iso)
    else:
        inputs["market"] = _input(None, "espn", now_iso, "no moneyline in the feed for this game")
    if game["kind"] == "team":
        home, away = game["home"], game["away"]
        cache = cache or ratings_mod.Cache(store, cfg)
        rat = cache.get(game["sport"], game["start_utc"])
        need = cfg["model"]["min_rated_games"]
        if rat and rat.games[home] >= need and rat.games[away] >= need:
            inputs["ratings"] = _input({
                "home_elo": round(rat.elo[home]), "away_elo": round(rat.elo[away]), "elo_gap": round(abs(rat.elo[home] - rat.elo[away])),
                "home_adv": rat.home_adv, "p_home": round(rat.p_home(home, away), 4),
                "home_games": rat.games[home], "away_games": rat.games[away],
                "home_record": f"{rat.wins[home]}-{rat.losses[home]}", "away_record": f"{rat.wins[away]}-{rat.losses[away]}",
                "home_margin": round(rat.avg_margin(home), 2), "away_margin": round(rat.avg_margin(away), 2),
                "unit": ratings_mod.UNIT.get(game["sport"], "points")}, "stored final scores", now_iso)
        else:
            have = (rat.games[home], rat.games[away]) if rat else (0, 0)
            inputs["ratings"] = _input(None, "stored final scores", now_iso,
                                       f"needs {need} stored games per team (home has {have[0]}, away has {have[1]}); run the backfill task")
        hh, ah = team_history(store, game, home), team_history(store, game, away)
        if hh and ah:
            hs, as_ = _schedule(hh, game["start_utc"], tz), _schedule(ah, game["start_utc"], tz)
            inputs["schedule_rest"] = _input({"home_days_off": hs["days_off"], "away_days_off": as_["days_off"],
                                              "home_back_to_back": hs["days_off"] == 0, "away_back_to_back": as_["days_off"] == 0,
                                              "home_games_in_last_7_days": hs["games_in_last_7_days"],
                                              "away_games_in_last_7_days": as_["games_in_last_7_days"],
                                              "window_days": 7}, "stored schedule", now_iso)           # the 7 in "last 7 days" is data, so the validator allows it
            inputs["recent_form"] = _input({"home": _form(hh, home), "away": _form(ah, away)}, "stored final scores", now_iso)
        else:
            why = "no earlier games stored for one of the teams; run the backfill task"
            inputs["schedule_rest"] = _input(None, "stored schedule", now_iso, why)
            inputs["recent_form"] = _input(None, "stored final scores", now_iso, why)
    else:
        why = "fighter data (record, reach, layoff, finishing rates) is not connected yet"
        for k in ("ratings", "schedule_rest", "recent_form"):
            inputs[k] = _input(None, "none", now_iso, why)
    inj = store.q("SELECT json FROM snapshots WHERE key = ?", (f"injuries:{game['sport']}",))
    if inj and game["kind"] == "team":
        data = json.loads(inj[0]["json"])
        hl, hlt = _injuries(data.get(game["home"]))
        al, alt = _injuries(data.get(game["away"]))
        inputs["injuries"] = _input({"home": hl, "away": al, "home_long_term": hlt, "away_long_term": alt}, "espn injuries", now_iso)
    else:
        inputs["injuries"] = _input(None, "espn", now_iso, "injury feed not connected or empty")
    unavailable = [{"key": k, "label": INPUT_META[k][0], "reason": v["reason"], "keywords": INPUT_META[k][1]}
                   for k, v in inputs.items() if v["value"] is None]
    return {"game": {"id": game["id"], "sport": game["sport"], "kind": game["kind"], "home": game["home"], "away": game["away"],
                     "start_utc": game["start_utc"], "venue": game.get("venue"), "event_name": game.get("event_name")},
            "inputs": inputs, "unavailable": unavailable}


def coverage(packet, weights):
    got = sum(w for k, w in weights.items() if packet["inputs"].get(k, {}).get("value") is not None)
    return round(got / sum(weights.values()), 3)
