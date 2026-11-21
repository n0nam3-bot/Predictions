"""schedule -> tick -> grade -> snapshots. Every function takes the clock as an argument so it can be simulated."""
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from . import decide, facts, grading, ledger, market, model, narrative, ratings as ratings_mod, records, timing
from .timing import DUE, LATE, MISSED, iso, parse_utc

SPORT_ORDER = ["mlb", "nfl", "nba", "nhl", "ufc", "dwcs"]


def et_day(now, cfg):
    return parse_utc(now).astimezone(ZoneInfo(cfg["timezone"])).date()


def et_bounds_utc(day, cfg):
    tz = ZoneInfo(cfg["timezone"])
    from datetime import datetime
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    return iso(start), iso(start + timedelta(days=1))


def put_snapshot(store, key, obj, now):
    store.x("INSERT INTO snapshots (key, json, updated_utc) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET json = excluded.json, updated_utc = excluded.updated_utc",
            (key, json.dumps(obj, separators=(",", ":"), default=str), iso(now)))


def get_snapshot(store, key, default=None):
    rows = store.q("SELECT json FROM snapshots WHERE key = ?", (key,))
    return json.loads(rows[0]["json"]) if rows else default


def heartbeat(store, kind, now, detail=None):
    store.x("INSERT INTO heartbeat (kind, at_utc, detail) VALUES (?, ?, ?)", (kind, iso(now), detail))
    store.x("DELETE FROM heartbeat WHERE id <= (SELECT MAX(id) FROM heartbeat) - 300")


def upsert_game(store, g, now):
    store.x(
        "INSERT INTO games (id, sport, kind, event_id, event_name, start_utc, home, away, venue, status, home_score, "
        "away_score, winner, method, home_record, away_record, odds_json, updated_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET start_utc=excluded.start_utc, status=excluded.status, "
        "home_score=excluded.home_score, away_score=excluded.away_score, winner=excluded.winner, "
        "method=excluded.method, home_record=excluded.home_record, away_record=excluded.away_record, "
        "venue=excluded.venue, event_name=excluded.event_name, "
        "odds_json=COALESCE(excluded.odds_json, games.odds_json), updated_utc=excluded.updated_utc",
        (g["id"], g["sport"], g["kind"], g.get("event_id"), g.get("event_name"), g["start_utc"], g["home"], g["away"],
         g.get("venue"), g["status"], g.get("home_score"), g.get("away_score"), g.get("winner"), g.get("method"),
         g.get("home_record"), g.get("away_record"), json.dumps(g["odds"]) if g.get("odds") else None, iso(now)))
    o = g.get("odds")
    if o and g["status"] == "scheduled" and parse_utc(g["start_utc"]) > parse_utc(now):
        last = store.q("SELECT home_ml, away_ml, spread_home, total FROM odds_snapshots WHERE game_id = ? "
                       "ORDER BY taken_utc DESC, id DESC LIMIT 1", (g["id"],))
        cur = (o.get("home_ml"), o.get("away_ml"), o.get("spread_home"), o.get("total"))
        if not last or tuple(last[0].values()) != cur:
            store.x("INSERT INTO odds_snapshots (game_id, taken_utc, book, home_ml, away_ml, spread_home, total, "
                    "over_odds, under_odds) VALUES (?,?,?,?,?,?,?,?,?)",
                    (g["id"], iso(now), o.get("book"), *cur, o.get("over_odds"), o.get("under_odds")))


def _note_source(store, name, ok, detail, now):
    cur = get_snapshot(store, "sources", {})
    cur[name] = {"ok": ok, "detail": detail, "at": iso(now)}
    put_snapshot(store, "sources", cur, now)


def feeds(cfg):
    return [s for s, spec in cfg["sports"].items() if "via" not in spec]


def refresh_days(store, source, cfg, now, pairs):
    """pairs: set of (sport, date). Fetch each scoreboard once and upsert."""
    n = 0
    pairs = {(cfg["sports"][s].get("via", s), d) for s, d in pairs}
    for sport, day in sorted(pairs):
        try:
            for g in source.fetch_day(sport, day):
                upsert_game(store, g, now)
                n += 1
            _note_source(store, f"scoreboard:{sport}", True, f"{day}", now)
        except Exception as exc:
            _note_source(store, f"scoreboard:{sport}", False, str(exc)[:160], now)
    return n


def refresh_injuries(store, source, cfg, now, sports):
    for sport in sorted(sports):
        if cfg["sports"][sport]["kind"] != "team":
            continue
        try:
            data = source.fetch_injuries(sport)
            if data:
                put_snapshot(store, f"injuries:{sport}", data, now)
            _note_source(store, f"injuries:{sport}", True, "ok" if data else "empty (nothing listed, possibly off-season)", now)
        except Exception as exc:
            _note_source(store, f"injuries:{sport}", False, str(exc)[:160], now)


def run_schedule(store, source, cfg, now, back=7, fwd=2):
    heartbeat(store, "schedule", now)
    today = et_day(now, cfg)
    pairs = {(s, today + timedelta(days=d)) for s in feeds(cfg) for d in range(-back, fwd + 1)}
    n = refresh_days(store, source, cfg, now, pairs)
    refresh_injuries(store, source, cfg, now, set(feeds(cfg)))
    build_snapshots(store, cfg, now)
    return {"games_upserted": n}


UPSERT_SQL = ("INSERT INTO games (id, sport, kind, event_id, event_name, start_utc, home, away, venue, status, home_score, "
              "away_score, winner, method, home_record, away_record, odds_json, updated_utc) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
              "ON CONFLICT(id) DO UPDATE SET start_utc=excluded.start_utc, status=excluded.status, "
              "home_score=excluded.home_score, away_score=excluded.away_score, winner=excluded.winner, "
              "method=excluded.method, home_record=excluded.home_record, away_record=excluded.away_record, "
              "venue=excluded.venue, event_name=excluded.event_name, "
              "odds_json=COALESCE(excluded.odds_json, games.odds_json), updated_utc=excluded.updated_utc")


def _upsert_args(g, now):
    return (g["id"], g["sport"], g["kind"], g.get("event_id"), g.get("event_name"), g["start_utc"], g["home"], g["away"],
            g.get("venue"), g["status"], g.get("home_score"), g.get("away_score"), g.get("winner"), g.get("method"),
            g.get("home_record"), g.get("away_record"), json.dumps(g["odds"]) if g.get("odds") else None, iso(now))


def upsert_games_bulk(store, games, now, batch=60):
    """Past games only (no odds snapshots): many rows per HTTP request."""
    for i in range(0, len(games), batch):
        store.many([(UPSERT_SQL, _upsert_args(g, now)) for g in games[i:i + batch]])
    return len(games)


def run_backfill(store, source, cfg, now, days=240, budget_minutes=10, log=print):
    """Load past games in 30-day chunks, newest first. Stops cleanly when the time budget is spent and
    remembers finished chunks, so running it again continues instead of starting over."""
    import time
    started = time.monotonic()
    heartbeat(store, "backfill", now)
    today = et_day(now, cfg)
    n, skipped, partial = 0, 0, False
    done = set(get_snapshot(store, "backfill_done", []))
    if hasattr(source, "fetch_range"):
        for sport in feeds(cfg):
            end = today - timedelta(days=1)
            while end > today - timedelta(days=days):
                start = max(end - timedelta(days=29), today - timedelta(days=days))
                tag = f"{sport}:{start}:{end}"
                if tag in done and end < today - timedelta(days=3):
                    skipped += 1
                elif time.monotonic() - started > budget_minutes * 60:
                    partial = True
                    break
                else:
                    try:
                        games = source.fetch_range(sport, start, end)
                        n += upsert_games_bulk(store, games, now)
                        done.add(tag)
                        _note_source(store, f"backfill:{sport}", True, f"{start} to {end}: {len(games)} games", now)
                        log(f"backfill {sport} {start} to {end}: {len(games)} games", flush=True)
                    except Exception as exc:
                        _note_source(store, f"backfill:{sport}", False, str(exc)[:160], now)
                        log(f"backfill {sport} {start} to {end} FAILED: {str(exc)[:120]}", flush=True)
                end = start - timedelta(days=1)
            if partial:
                break
        put_snapshot(store, "backfill_done", sorted(done), now)
    else:
        pairs = {(s, today - timedelta(days=d)) for s in feeds(cfg) for d in range(1, days + 1)}
        n = refresh_days(store, source, cfg, now, pairs)
    build_snapshots(store, cfg, now)
    return {"days": days, "games_upserted": n, "chunks_already_done": skipped, "partial": partial,
            "note": "Time budget reached. Run backfill again to continue." if partial else "Complete."}


def _row_game(row, odds):
    keys = ("id", "sport", "kind", "event_id", "event_name", "start_utc", "home", "away", "venue", "status",
            "home_score", "away_score", "winner", "method", "home_record", "away_record")
    return {**{k: row[k] for k in keys}, "odds": odds}


def fill_missing_odds(store, odds_source, cfg, now, games):
    """Ask the fallback odds source only for games that still have no moneyline."""
    from .sources import oddsapi
    filled = 0
    need = {}
    for g in games:
        o = json.loads(g["odds_json"]) if g.get("odds_json") else None
        if not o or o.get("home_ml") is None or o.get("away_ml") is None:
            need.setdefault(g["sport"], []).append(g)
    for sport, rows in need.items():
        try:
            events = odds_source.fetch(sport)
        except Exception as exc:
            _note_source(store, f"odds:{sport}", False, str(exc)[:160], now)
            continue
        for g in rows:
            found = oddsapi.match(g, events)
            if found:
                upsert_game(store, _row_game(g, found), now)
                filled += 1
        if events:
            _note_source(store, f"odds:{sport}", True, f"{len(events)} events", now)
    return filled


def _candidates(store, now):
    lo, hi = iso(parse_utc(now) - timedelta(minutes=30)), iso(parse_utc(now) + timedelta(hours=4))
    teams = store.q("SELECT * FROM games WHERE kind = 'team' AND status IN ('scheduled','delayed') AND missed = 0 "
                    "AND start_utc BETWEEN ? AND ?", (lo, hi))
    ev = store.q("SELECT DISTINCT event_id FROM games WHERE kind = 'bout' AND missed = 0 AND start_utc BETWEEN ? AND ?",
                 (iso(parse_utc(now) - timedelta(hours=12)), iso(parse_utc(now) + timedelta(hours=6))))
    bouts = []
    for e in ev:
        bouts += store.q("SELECT * FROM games WHERE event_id = ? AND kind = 'bout'", (e["event_id"],))
    return teams + bouts


def publish_game(store, cfg, now, g, state, chain=None, cache=None):
    th = cfg["thresholds"]
    packet = facts.build_packet(store, g, now, cfg, cache)
    cov = facts.coverage(packet, cfg["coverage_weights"])
    m = model.project(packet, cfg)
    d = {**decide.decide(packet, m, cov, cfg), "coverage": cov}
    top = 0
    if d["verdict"] == "PLAY" and d["edge"] >= th["top_min_edge"] and cov >= th["top_min_coverage"]:
        lo, hi = et_bounds_utc(et_day(now, cfg), cfg)
        used = store.q("SELECT COUNT(*) AS c FROM picks WHERE top_pick = 1 AND published_utc >= ? AND published_utc < ?",
                       (lo, hi))[0]["c"]
        top = 1 if used < th["top_per_day"] else 0
    narr, src, problems = narrative.narrate(packet, m, d, chain)
    mk = packet["inputs"]["market"]["value"]
    payload = {"headline": narr["headline"], "narrative": {k: narr[k] for k in narrative.SECTIONS + ["thesis"]},
               "narrative_source": src, "validator_problems": problems, "reason": d["reason"],
               "adjustments": (m or {}).get("adjustments", []), "home": g["home"], "away": g["away"],
               "lean_name": g[d["selection"]] if d["selection"] in ("home", "away") else None,
               "signals": narrative.signals(packet, m),
               "event_name": g.get("event_name"), "unavailable": [u["label"] for u in packet["unavailable"]],
               "inputs": {k: {"available": v["value"] is not None, "source": v["source"], "fetched_at": v["fetched_at"],
                              "reason": v["reason"]} for k, v in packet["inputs"].items()},
               "market": {k: mk.get(k) for k in ("home_ml", "away_ml", "book", "no_vig_home", "no_vig_away")} if mk else None,
               "model": m}
    row = {"id": g["id"], "game_id": g["id"], "sport": g["sport"], "start_utc": g["start_utc"],
           "published_utc": iso(now), "tag": "LATE" if state == LATE else "ON_TIME", "verdict": d["verdict"],
           "market": d["market"], "selection": d["selection"] if d["verdict"] == "PLAY" else None, "line": None,
           "odds": d["odds"] if d["verdict"] == "PLAY" else None,
           "fair_odds": d["fair_odds"], "model_prob": d["model_prob"], "market_prob": d["market_prob"],
           "edge": d["edge"], "units": d["units"], "confidence": d["confidence"], "top_pick": top,
           "rank_score": d["rank_score"], "coverage": cov, "payload_json": json.dumps(payload, sort_keys=True, default=str)}
    saved = ledger.insert_pick(store, row)
    store.x("INSERT INTO facts (game_id, packet_json, coverage, built_utc) VALUES (?,?,?,?) "
            "ON CONFLICT(game_id) DO UPDATE SET packet_json=excluded.packet_json, coverage=excluded.coverage, "
            "built_utc=excluded.built_utc", (g["id"], json.dumps(packet, default=str), cov, iso(now)))
    return saved


def run_tick(store, source, cfg, now, chain=None, odds_source=None):
    now = parse_utc(now)
    heartbeat(store, "tick", now)
    published = {r["game_id"] for r in store.q("SELECT game_id FROM picks")}
    items = timing.due_items(_candidates(store, now), now, published, cfg)
    stats = {"published": 0, "late": 0, "missed": 0, "items": len(items)}
    rcache = ratings_mod.Cache(store, cfg)
    for state, kind, item_id, games_ in items:
        pending = [g for g in games_ if g["status"] in ("scheduled", "delayed") and parse_utc(g["start_utc"]) > now]
        if state == MISSED:
            for g in games_:
                if g["status"] in ("scheduled", "delayed"):
                    store.x("UPDATE games SET missed = 1 WHERE id = ?", (g["id"],))
                    stats["missed"] += 1
            continue
        if not pending:
            continue
        pairs = {(g["sport"], et_day(g["start_utc"], cfg)) for g in pending}
        refresh_days(store, source, cfg, now, pairs)
        refresh_injuries(store, source, cfg, now, {g["sport"] for g in pending})
        if odds_source is not None:
            fill_missing_odds(store, odds_source, cfg, now,
                              [store.q("SELECT * FROM games WHERE id = ?", (g["id"],))[0] for g in pending])
        for g in pending:
            fresh = store.q("SELECT * FROM games WHERE id = ?", (g["id"],))[0]
            if fresh["status"] not in ("scheduled", "delayed"):
                continue
            if publish_game(store, cfg, now, fresh, state, chain, rcache):
                stats["published"] += 1
                stats["late"] += state == LATE
    build_snapshots(store, cfg, now)
    return stats


def closing_odds(store, pick):
    snap = store.q("SELECT home_ml, away_ml FROM odds_snapshots WHERE game_id = ? AND taken_utc <= ? "
                   "ORDER BY taken_utc DESC, id DESC LIMIT 1", (pick["game_id"], pick["start_utc"]))
    if not snap:
        return None, None
    close = snap[0]["home_ml" if pick["selection"] == "home" else "away_ml"]
    if close is None:
        return None, None
    clv = market.american_to_implied(close) - market.american_to_implied(pick["odds"])
    return close, round(clv, 4)


def run_grade(store, source, cfg, now):
    now = parse_utc(now)
    heartbeat(store, "grade", now)
    todo = store.q("SELECT p.* FROM picks p LEFT JOIN grades g ON g.pick_id = p.id WHERE p.verdict = 'PLAY' "
                   "AND p.start_utc < ? AND (g.pick_id IS NULL OR g.grade = 'PENDING_REVIEW')", (iso(now),))
    refresh_days(store, source, cfg, now, {(p["sport"], et_day(p["start_utc"], cfg)) for p in todo})
    stats = {"graded": 0, "review": 0, "pending": 0}
    for p in todo:
        game = store.q("SELECT * FROM games WHERE id = ?", (p["game_id"],))[0]
        res = grading.grade_pick(p, game, now)
        g = res["grade"]
        if g == "PENDING":
            stats["pending"] += 1
            continue
        if g == "PENDING_REVIEW":
            stats["review"] += 1
        profit = market.profit_units(p["odds"], p["units"]) if g == "W" else -p["units"] if g == "L" else 0.0
        close, clv = closing_odds(store, p)
        store.x("INSERT INTO grades (pick_id, grade, reason, home_score, away_score, profit_units, closing_odds, clv, "
                "graded_utc, source) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(pick_id) DO UPDATE SET grade = excluded.grade, "
                "reason = excluded.reason, home_score = excluded.home_score, away_score = excluded.away_score, "
                "profit_units = excluded.profit_units, closing_odds = excluded.closing_odds, clv = excluded.clv, "
                "graded_utc = excluded.graded_utc", (p["id"], g, res["reason"], game["home_score"], game["away_score"],
                                                      round(profit, 4), close, clv, iso(now), "espn"))
        stats["graded"] += g in ("W", "L", "V")
    build_snapshots(store, cfg, now)
    return stats


def _pick_view(row, payload):
    sel = row["selection"]
    return {"verdict": row["verdict"], "tag": row["tag"], "headline": payload["headline"],
            "market": row["market"], "selection": sel,
            "selection_name": payload["home"] if sel == "home" else payload["away"] if sel == "away" else None,
            "odds": row["odds"], "fair_odds": row["fair_odds"], "model_prob": row["model_prob"],
            "market_prob": row["market_prob"], "edge": row["edge"], "units": row["units"],
            "confidence": row["confidence"], "top_pick": bool(row["top_pick"]), "coverage": row["coverage"],
            "published_utc": row["published_utc"], "narrative": payload["narrative"], "reason": payload["reason"],
            "unavailable": payload["unavailable"], "inputs": payload["inputs"],
            "narrative_source": payload["narrative_source"], "lean_name": payload.get("lean_name"), "signals": payload.get("signals", []), "hash": row["hash"][:12]}


def build_snapshots(store, cfg, now):
    now = parse_utc(now)
    rows = store.q("SELECT p.verdict, p.sport, p.odds, p.units, p.top_pick, p.start_utc, g.grade FROM picks p "
                   "LEFT JOIN grades g ON g.pick_id = p.id")
    rec = records.build_records(rows, now, cfg["timezone"])
    lo, hi = iso(now - timedelta(hours=26)), iso(now + timedelta(hours=36))
    games = store.q("SELECT * FROM games WHERE start_utc BETWEEN ? AND ? ORDER BY start_utc, id", (lo, hi))
    picks = {r["game_id"]: r for r in store.q("SELECT * FROM picks WHERE start_utc BETWEEN ? AND ?", (lo, hi))}
    grades = {r["pick_id"]: r for r in store.q("SELECT * FROM grades")}
    first_bout = {}
    for g in games:
        if g["kind"] == "bout":
            first_bout[g["event_id"]] = min(first_bout.get(g["event_id"], g["start_utc"]), g["start_utc"])
    out = []
    for g in games:
        p = picks.get(g["id"])
        kind = "team" if g["kind"] == "team" else "mma"
        anchor = first_bout.get(g["event_id"], g["start_utc"]) if kind == "mma" else g["start_utc"]
        item = {"id": g["id"], "sport": g["sport"], "kind": g["kind"], "event_name": g["event_name"],
                "start_utc": g["start_utc"], "home": g["home"], "away": g["away"], "venue": g["venue"],
                "status": g["status"], "home_score": g["home_score"], "away_score": g["away_score"],
                "winner": g["winner"], "publish_at_utc": iso(timing.publish_target(kind, anchor)), "pick": None,
                "grade": None, "missed": bool(g["missed"])}
        if p:
            item["pick"] = _pick_view(p, json.loads(p["payload_json"]))
            gr = grades.get(p["id"])
            if gr:
                item["grade"] = {k: gr[k] for k in ("grade", "reason", "profit_units", "closing_odds", "clv")}
        out.append(item)
    last_pub = store.q("SELECT MAX(published_utc) AS m FROM picks")[0]["m"]
    sources = get_snapshot(store, "sources", {})
    day = f"llm:%:{iso(now)[:10]}"
    quota = {r["key"]: {"used": r["used"], "cap": r["cap"]} for r in store.q("SELECT * FROM quota WHERE key LIKE ?", (day,))}
    health = {"generated_utc": iso(now), "last_tick_utc": (store.q("SELECT MAX(at_utc) AS m FROM heartbeat WHERE kind='tick'")[0]["m"]),
              "last_publish_utc": last_pub, "sources": sources, "quota": quota,
              "ledger": get_snapshot(store, "ledger_check", {"ok": None, "checked_utc": None, "problems": []}),
              "backtest": get_snapshot(store, "backtest", {}), "integrations": get_snapshot(store, "integrations", {}),
              "experimental": True}
    span = store.q("SELECT MIN(start_utc) AS lo, MAX(start_utc) AS hi FROM games")[0]
    date_range = {"min": str(et_day(span["lo"], cfg)) if span["lo"] else None,
                  "max": str(et_day(span["hi"], cfg)) if span["hi"] else None}
    latest = {"schema": 1, "source": "live", "date_range": date_range, "generated_utc": iso(now), "timezone": cfg["timezone"],
              "sports": SPORT_ORDER, "thresholds": {k: cfg["thresholds"][k] for k in ("play_min_edge", "play_min_coverage")}, "records": rec, "games": out, "health": health,
              "top_picks": [x["id"] for x in out if x["pick"] and x["pick"]["top_pick"]]}
    put_snapshot(store, "latest", latest, now)
    put_snapshot(store, "record", rec, now)
    put_snapshot(store, "health", health, now)
    return latest
