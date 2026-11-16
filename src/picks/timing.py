"""When is a game due? Pure functions so a simulated clock can test every edge."""
from datetime import datetime, timedelta, timezone

WAIT, DUE, LATE, MISSED, PUBLISHED = "WAIT", "DUE", "LATE", "MISSED", "PUBLISHED"


def parse_utc(s):
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(dt):
    return parse_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(kind, start_utc, now, published, cfg):
    """kind: 'team' or 'mma'. start_utc: scheduled start (first bout for MMA)."""
    if published:
        return PUBLISHED
    start, now = parse_utc(start_utc), parse_utc(now)
    if now >= start:
        return MISSED
    t = cfg["timing"][kind]
    minutes_left = (start - now).total_seconds() / 60
    if minutes_left > t["due_minutes"]:
        return WAIT
    if minutes_left < t["late_after_minutes"] and kind == "team":
        return LATE
    if minutes_left < t["late_after_minutes"] and kind == "mma":
        return LATE
    return DUE


def publish_target(kind, start_utc):
    """The moment the analysis is meant to go out (T-30 team, T-90 MMA card)."""
    minutes = 30 if kind == "team" else 90
    return parse_utc(start_utc) - timedelta(minutes=minutes)


def due_items(games, now, published_ids, cfg):
    """Group games into publishable items.

    Team games are individual items. MMA bouts are grouped per card (event_id) and the card
    is judged by its earliest bout. Returns [(state, kind, item_id, [games])] for DUE/LATE/MISSED.
    """
    items = []
    cards = {}
    for g in games:
        if g["kind"] == "team":
            state = classify("team", g["start_utc"], now, g["id"] in published_ids, cfg)
            if state in (DUE, LATE, MISSED):
                items.append((state, "team", g["id"], [g]))
        else:
            cards.setdefault(g["event_id"] or g["id"], []).append(g)
    for card_id, bouts in cards.items():
        first = min(parse_utc(b["start_utc"]) for b in bouts)
        pending = [b for b in bouts if b["id"] not in published_ids]
        if not pending:
            continue
        state = classify("mma", first, now, False, cfg)
        if state in (DUE, LATE, MISSED):
            items.append((state, "mma", card_id, sorted(pending, key=lambda b: b["start_utc"])))
    return items
