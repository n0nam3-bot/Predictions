"""Fallback odds from The Odds API (free plan: 500 credits a month, one credit per sport per call here).
Used only when ESPN has no moneyline for a game that is about to be posted, and never past 85% of the month."""
import re

import requests

from ..timing import iso, parse_utc

SPORT_KEYS = {"nfl": "americanfootball_nfl", "nba": "basketball_nba", "nhl": "icehockey_nhl",
              "mlb": "baseball_mlb", "ufc": "mma_mixed_martial_arts"}
PREFERRED = ["draftkings", "fanduel", "betmgm", "caesars", "pointsbetus", "bovada"]
URL = "https://api.the-odds-api.com/v4/sports/{key}/odds"


def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def parse_events(raw):
    out = []
    for ev in raw if isinstance(raw, list) else []:
        books = {b.get("key"): b for b in ev.get("bookmakers", [])}
        ordered = [books[k] for k in PREFERRED if k in books] + [b for k, b in books.items() if k not in PREFERRED]
        for book in ordered:
            h2h = next((m for m in book.get("markets", []) if m.get("key") == "h2h"), None)
            prices = {norm(o["name"]): o["price"] for o in (h2h or {}).get("outcomes", []) if "price" in o}
            if norm(ev.get("home_team")) in prices and norm(ev.get("away_team")) in prices:
                out.append({"home": ev["home_team"], "away": ev["away_team"], "start_utc": ev["commence_time"],
                            "home_ml": float(prices[norm(ev["home_team"])]), "away_ml": float(prices[norm(ev["away_team"])]),
                            "book": book.get("title") or book.get("key")})
                break
    return out


def match(game, events, window_hours=6):
    """Return odds oriented to the game's own home/away, or None."""
    h, a = norm(game["home"]), norm(game["away"])
    for ev in events:
        eh, ea = norm(ev["home"]), norm(ev["away"])
        close = abs((parse_utc(ev["start_utc"]) - parse_utc(game["start_utc"])).total_seconds()) <= window_hours * 3600
        if not close:
            continue
        if (eh, ea) == (h, a):
            return {"home_ml": ev["home_ml"], "away_ml": ev["away_ml"], "book": ev["book"], "source": "the-odds-api"}
        if (eh, ea) == (a, h):
            return {"home_ml": ev["away_ml"], "away_ml": ev["home_ml"], "book": ev["book"], "source": "the-odds-api"}
    return None


class OddsAPISource:
    def __init__(self, key, store, now, http=None, cap=500, min_gap_minutes=20):
        self.key, self.store, self.now, self.http = key, store, parse_utc(now), http or requests
        self.cap, self.gap = cap, min_gap_minutes

    def month_key(self):
        return f"oddsapi:{iso(self.now)[:7]}"

    def used(self):
        row = self.store.q("SELECT used FROM quota WHERE key = ?", (self.month_key(),))
        return row[0]["used"] if row else 0

    def fetch(self, sport_key):
        if not self.key or sport_key not in SPORT_KEYS or self.used() >= 0.85 * self.cap:
            return []
        last = self.store.q("SELECT json FROM snapshots WHERE key = ?", (f"oddsapi_last:{sport_key}",))
        if last and (self.now - parse_utc(last[0]["json"].strip('"'))).total_seconds() < self.gap * 60:
            return []
        self.store.x("INSERT INTO quota (key, used, cap, updated_utc) VALUES (?, 1, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                     "used = used + 1, updated_utc = excluded.updated_utc", (self.month_key(), self.cap, iso(self.now)))
        self.store.x("INSERT INTO snapshots (key, json, updated_utc) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                     "json = excluded.json, updated_utc = excluded.updated_utc",
                     (f"oddsapi_last:{sport_key}", '"' + iso(self.now) + '"', iso(self.now)))
        r = self.http.get(URL.format(key=SPORT_KEYS[sport_key]), timeout=20,
                          params={"regions": "us", "markets": "h2h", "oddsFormat": "american", "apiKey": self.key})
        if r.status_code != 200:
            raise RuntimeError(f"The Odds API HTTP {r.status_code}")
        return parse_events(r.json())
