"""Build the facts packet for a game: every input with value, source, fetched_at (or a reason it is missing)."""
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from . import market
from .timing import iso, parse_utc

INPUT_META = {
    "market": ("betting market", ["odds", "line", "price", "market"]),
    "schedule_rest": ("rest and schedule", ["rest", "back-to-back", "schedule", "travel"]),
    "recent_form": ("recent form", ["form", "streak", "last five", "recent"]),
    "injuries": ("injuries", ["injur", "inactive", "questionable", "doubtful", "out for", "availability", "lineup"]),
}


def _input(value, source, fetched_at, reason=None):
    return {"value": value, "source": source, "fetched_at": fetched_at, "reason": reason}


def team_history(store, game, team, limit=6):
    rows = store.q(
        "SELECT * FROM games WHERE sport = ? AND status = 'final' AND start_utc < ? AND (home = ? OR away = ?) "
        "ORDER BY start_utc DESC LIMIT ?", (game["sport"], game["start_utc"], team, team, limit))
    return rows


def _rest(history, start):
    if not history:
        return None
    return round((parse_utc(start) - parse_utc(history[0]["start_utc"])).total_seconds() / 86400, 1)


def _form(history, team):
    w = sum(1 for g in history[:5] if g["winner"] == ("home" if g["home"] == team else "away"))
    n = min(len(history), 5)
    return {"w": w, "l": n - w, "games": n}


def build_packet(store, game, now, sources_ok=("espn",)):
    now_iso = iso(parse_utc(now))
    odds = json.loads(game["odds_json"]) if game.get("odds_json") else None
    inputs = {}
    if odds and odds.get("home_ml") is not None and odds.get("away_ml") is not None:
        ph, pa, vig = market.no_vig_two_way(odds["home_ml"], odds["away_ml"])
        first = store.q("SELECT home_ml, away_ml FROM odds_snapshots WHERE game_id = ? ORDER BY taken_utc LIMIT 1",
                        (game["id"],))
        opening = first[0] if first else None
        inputs["market"] = _input({**odds, "no_vig_home": round(ph, 4), "no_vig_away": round(pa, 4),
                                   "vig": round(vig, 4), "opening": opening}, odds.get("source", "espn"), now_iso)
    else:
        inputs["market"] = _input(None, "espn", now_iso, "no moneyline in the feed for this game")
    if game["kind"] == "team":
        hh, ah = team_history(store, game, game["home"]), team_history(store, game, game["away"])
        if hh and ah:
            hr, ar = _rest(hh, game["start_utc"]), _rest(ah, game["start_utc"])
            inputs["schedule_rest"] = _input({"home_rest_days": hr, "away_rest_days": ar,
                                              "home_back_to_back": hr is not None and hr < 1.5,
                                              "away_back_to_back": ar is not None and ar < 1.5}, "schedule history", now_iso)
            inputs["recent_form"] = _input({"home": _form(hh, game["home"]), "away": _form(ah, game["away"])},
                                           "schedule history", now_iso)
        else:
            why = "fewer than one prior game stored for each side; run the backfill"
            inputs["schedule_rest"] = _input(None, "schedule history", now_iso, why)
            inputs["recent_form"] = _input(None, "schedule history", now_iso, why)
    else:
        why = "fight-camp data (layoff, reach, finish rates) is not connected yet"
        inputs["schedule_rest"] = _input(None, "none", now_iso, why)
        inputs["recent_form"] = _input(None, "none", now_iso, why)
    inj = store.q("SELECT json FROM snapshots WHERE key = ?", (f"injuries:{game['sport']}",))
    if inj:
        data = json.loads(inj[0]["json"])
        inputs["injuries"] = _input({"home": data.get(game["home"], []), "away": data.get(game["away"], [])},
                                    "espn injuries", now_iso)
    else:
        inputs["injuries"] = _input(None, "espn", now_iso, "injury feed not connected or empty")
    unavailable = [{"key": k, "label": INPUT_META[k][0], "reason": v["reason"], "keywords": INPUT_META[k][1]}
                   for k, v in inputs.items() if v["value"] is None]
    return {"game": {"id": game["id"], "sport": game["sport"], "kind": game["kind"], "home": game["home"],
                     "away": game["away"], "start_utc": game["start_utc"], "venue": game.get("venue"),
                     "event_name": game.get("event_name")},
            "inputs": inputs, "unavailable": unavailable}


def coverage(packet, weights):
    got = sum(w for k, w in weights.items() if packet["inputs"].get(k, {}).get("value") is not None)
    return round(got / sum(weights.values()), 3)
