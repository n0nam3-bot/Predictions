"""Win-loss-void records from graded PLAY picks. Everything is rebuildable from rows."""
from collections import OrderedDict
from datetime import timedelta
from zoneinfo import ZoneInfo

from .market import profit_units
from .timing import parse_utc

GRADES = ("W", "L", "V")


def et_date(start_utc, tz="America/New_York"):
    return parse_utc(start_utc).astimezone(ZoneInfo(tz)).date()


def _blank():
    return {"w": 0, "l": 0, "v": 0, "pending": 0, "win_pct": None, "units": 0.0, "roi": None}


def _add(bucket, row):
    g = row.get("grade")
    if g in GRADES:
        bucket[g.lower()] += 1
        if g == "W":
            bucket["units"] += profit_units(row["odds"], row.get("units", 1))
        elif g == "L":
            bucket["units"] -= row.get("units", 1)
        if g in ("W", "L"):
            bucket["risked"] = bucket.get("risked", 0) + row.get("units", 1)
    else:
        bucket["pending"] += 1


def _finish(bucket):
    decided = bucket["w"] + bucket["l"]
    bucket["win_pct"] = round(100 * bucket["w"] / decided, 1) if decided else None
    risked = bucket.pop("risked", 0)
    bucket["roi"] = round(100 * bucket["units"] / risked, 1) if risked else None
    bucket["units"] = round(bucket["units"], 2)
    return bucket


def build_records(rows, now, tz="America/New_York", history_days=30):
    """rows: dicts with verdict, sport, grade, odds, units, top_pick, start_utc."""
    plays = [r for r in rows if r.get("verdict") == "PLAY"]
    today = parse_utc(now).astimezone(ZoneInfo(tz)).date()
    overall, today_b, top = _blank(), _blank(), _blank()
    by_sport = OrderedDict()
    daily = {}
    for r in sorted(plays, key=lambda r: r["start_utc"]):
        _add(overall, r)
        _add(by_sport.setdefault(r["sport"], _blank()), r)
        if r.get("top_pick"):
            _add(top, r)
        d = et_date(r["start_utc"], tz)
        if d == today:
            _add(today_b, r)
        day = daily.setdefault(d, {"w": 0, "l": 0, "v": 0, "pending": 0})
        key = r["grade"].lower() if r.get("grade") in GRADES else "pending"
        day[key] += 1
    history = []
    for i in range(history_days - 1, -1, -1):
        d = today - timedelta(days=i)
        history.append({"date": d.isoformat(), **daily.get(d, {"w": 0, "l": 0, "v": 0, "pending": 0})})
    decided = [r["grade"] for r in sorted(plays, key=lambda r: r["start_utc"]) if r.get("grade") in ("W", "L")]
    streak = None
    if decided:
        last, n = decided[-1], 0
        for g in reversed(decided):
            if g != last:
                break
            n += 1
        streak = f"{last}{n}"
    return {"today": _finish(today_b), "overall": _finish(overall), "top_picks": _finish(top),
            "by_sport": {k: _finish(v) for k, v in by_sport.items()},
            "history": history, "streak": streak}
