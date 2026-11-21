"""ESPN's public (unofficial) JSON. Parsers are defensive and the shapes are NOT yet verified against live
responses: run the 'Source audit' task from the Actions tab and read its report before trusting them."""
import time
from datetime import date

import requests

BASE = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}"
UA = {"User-Agent": "picks-board/0.1 (+https://github.com)"}


def _get(d, *path):
    for p in path:
        if isinstance(d, dict) and p in d:
            d = d[p]
        else:
            return None
    return d


def _num(x):
    if x is None:
        return None
    s = str(x).strip().lower().replace("+", "")
    if s in ("even", "ev", "pk", "pick"):
        return 100.0 if s in ("even", "ev") else 0.0
    s = s.lstrip("ou")
    try:
        return float(s)
    except ValueError:
        return None


def norm_status(status):
    t = (status or {}).get("type", {})
    name, state = (t.get("name") or "").upper(), (t.get("state") or "").lower()
    if t.get("completed") or name in ("STATUS_FINAL", "STATUS_FULL_TIME") or name.startswith("STATUS_FINAL"):
        return "final"
    if name == "STATUS_POSTPONED":
        return "postponed"
    if name in ("STATUS_CANCELED", "STATUS_CANCELLED"):
        return "cancelled"
    if name == "STATUS_SUSPENDED":
        return "suspended"
    if name == "STATUS_DELAYED":
        return "delayed"
    if state == "in" or name in ("STATUS_IN_PROGRESS", "STATUS_HALFTIME", "STATUS_END_PERIOD"):
        return "in_progress"
    return "scheduled"


def parse_odds(odds_list, home_abbr=None, away_abbr=None):
    """Accepts the newer nested shape (moneyline/pointSpread/total) and the older flat one."""
    if not odds_list:
        return None
    o = odds_list[0]
    home_ml = _num(_get(o, "moneyline", "home", "close", "odds"))
    away_ml = _num(_get(o, "moneyline", "away", "close", "odds"))
    if home_ml is None:
        home_ml = _num(_get(o, "homeTeamOdds", "moneyLine"))
    if away_ml is None:
        away_ml = _num(_get(o, "awayTeamOdds", "moneyLine"))
    spread = _num(_get(o, "pointSpread", "home", "close", "line"))
    if spread is None and o.get("details") and home_abbr:
        parts = str(o["details"]).rsplit(" ", 1)
        if len(parts) == 2 and _num(parts[1]) is not None:
            fav, val = parts[0].strip(), _num(parts[1])
            spread = val if fav == home_abbr else -val if fav == away_abbr else None
    total = _num(o.get("overUnder"))
    over = _num(_get(o, "total", "over", "close", "odds")) or _num(o.get("overOdds"))
    under = _num(_get(o, "total", "under", "close", "odds")) or _num(o.get("underOdds"))
    if total is None:
        total = _num(_get(o, "total", "over", "close", "line"))
    if all(v is None for v in (home_ml, away_ml, spread, total)):
        return None
    return {"home_ml": home_ml, "away_ml": away_ml, "spread_home": spread, "total": total,
            "over_odds": over, "under_odds": under, "book": _get(o, "provider", "name"), "source": "espn"}


def _score(c, status):
    if status not in ("in_progress", "final"):
        return None
    try:
        return float(c.get("score"))
    except (TypeError, ValueError):
        return None


def parse_team_event(ev, sport_key):
    comp = ev["competitions"][0]
    by = {c["homeAway"]: c for c in comp["competitors"]}
    home, away = by["home"], by["away"]
    status = norm_status(comp.get("status") or ev.get("status"))
    hs, as_ = _score(home, status), _score(away, status)
    winner = None
    if status == "final" and hs is not None and as_ is not None:
        winner = "home" if hs > as_ else "away" if as_ > hs else "draw"
    rec = lambda c: _get((c.get("records") or [{}])[0], "summary")
    return {"id": f"espn:{sport_key}:{ev['id']}", "sport": sport_key, "kind": "team", "event_id": f"espn:{ev['id']}",
            "event_name": ev.get("shortName") or ev.get("name"), "start_utc": ev["date"].replace("Z", ":00Z") if len(ev["date"]) == 17 else ev["date"],
            "home": home["team"]["displayName"], "away": away["team"]["displayName"],
            "venue": _get(comp, "venue", "fullName"), "status": status, "home_score": hs, "away_score": as_,
            "winner": winner, "method": None, "home_record": rec(home), "away_record": rec(away),
            "odds": parse_odds(comp.get("odds"), home["team"].get("abbreviation"), away["team"].get("abbreviation"))}


def parse_bouts(ev, sport_key):
    """Contender Series cards come through the UFC feed; label them by event name."""
    if sport_key == "ufc" and "contender series" in (ev.get("name") or "").lower():
        sport_key = "dwcs"
    out = []
    for comp in ev.get("competitions", []):
        fighters = comp.get("competitors", [])
        if len(fighters) != 2:
            continue
        fighters = sorted(fighters, key=lambda c: c.get("order", 0))
        a, b = fighters
        status = norm_status(comp.get("status") or ev.get("status"))
        winner = "home" if a.get("winner") else "away" if b.get("winner") else None
        if status == "final" and winner is None:
            winner = "draw"
        out.append({"id": f"espn:{sport_key}:{comp['id']}", "sport": sport_key, "kind": "bout",
                    "event_id": f"espn:{ev['id']}", "event_name": ev.get("name"),
                    "start_utc": comp.get("date") or ev["date"], "home": _get(a, "athlete", "displayName") or "TBD",
                    "away": _get(b, "athlete", "displayName") or "TBD", "venue": _get(ev, "venue", "fullName"),
                    "status": status, "home_score": None, "away_score": None, "winner": winner,
                    "method": _get(comp, "status", "result", "name"), "home_record": None, "away_record": None,
                    "odds": parse_odds(comp.get("odds"))})
    return out


def parse_scoreboard(raw, sport_key, kind):
    games = []
    for ev in raw.get("events", []):
        try:
            games.extend(parse_bouts(ev, sport_key) if kind == "bout" else [parse_team_event(ev, sport_key)])
        except (KeyError, IndexError, TypeError):
            continue                          # one odd event must not sink the whole day
    return games


def parse_injuries(raw):
    out = {}
    for team in raw.get("injuries", []):
        rows = []
        for i in team.get("injuries", []):
            rows.append({"name": _get(i, "athlete", "displayName") or "Unknown",
                         "pos": _get(i, "athlete", "position", "abbreviation"), "status": i.get("status") or "Unknown"})
        out[team.get("displayName", "Unknown")] = rows
    return out


class ESPNSource:
    def __init__(self, cfg, session=None):
        self.cfg, self.http = cfg, session or requests.Session()

    def _get_json(self, url, attempts=3, timeout=20):
        last = None
        for attempt in range(attempts):
            try:
                r = self.http.get(url, headers=UA, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP {r.status_code}"
            except requests.RequestException as exc:
                last = str(exc)
            time.sleep(0.5 * (2 ** attempt))
        raise RuntimeError(f"ESPN request failed: {last} ({url})")

    def _base(self, sport_key):
        sport_key = self.cfg["sports"][sport_key].get("via", sport_key)
        sp, lg = self.cfg["sports"][sport_key]["espn"]
        return BASE.format(sport=sp, league=lg)

    def fetch_day(self, sport_key, day):
        d = day if isinstance(day, date) else date.fromisoformat(str(day))
        feed = self.cfg["sports"][sport_key].get("via", sport_key)
        raw = self._get_json(f"{self._base(feed)}/scoreboard?dates={d:%Y%m%d}&limit=300")
        return parse_scoreboard(raw, feed, self.cfg["sports"][feed]["kind"])

    def fetch_range(self, sport_key, start, end):
        """Up to a few weeks of finished games in one request (ESPN accepts dates=YYYYMMDD-YYYYMMDD)."""
        feed = self.cfg["sports"][sport_key].get("via", sport_key)
        raw = self._get_json(f"{self._base(feed)}/scoreboard?dates={start:%Y%m%d}-{end:%Y%m%d}&limit=1000", attempts=2, timeout=30)
        return parse_scoreboard(raw, feed, self.cfg["sports"][feed]["kind"])

    def fetch_injuries(self, sport_key):
        if self.cfg["sports"][sport_key]["kind"] != "team":
            return {}
        return parse_injuries(self._get_json(f"{self._base(sport_key)}/injuries"))
