"""Plain-language status of every connection, written to the 'integrations' snapshot after each run."""
import json
from datetime import timedelta

from . import __version__
from .timing import iso, parse_utc

LLM = [("gemini", "Gemini", "GEMINI_API_KEY"), ("mistral", "Mistral", "MISTRAL_API_KEY"),
       ("cloudflare", "Cloudflare Workers AI", "CLOUDFLARE_AI"), ("openrouter", "OpenRouter", "OPENROUTER_API_KEY")]


def _snap(store, key, default):
    rows = store.q("SELECT json FROM snapshots WHERE key = ?", (key,))
    return json.loads(rows[0]["json"]) if rows else default


def _ago(now, iso_s):
    m = int((now - parse_utc(iso_s)).total_seconds() // 60)
    return f"{m} min ago" if m < 120 else f"{m // 60} h ago"


def _cooling(cool, name, now):
    """' Cooling down: model (back in 4 min).' for the provider's models that are on a cooldown."""
    t, out = iso(now), []
    for k, v in sorted(cool.items()):
        if k.startswith(name + "/") and v.get("until", "") > t:
            mins = max(1, round((parse_utc(v["until"]) - parse_utc(now)).total_seconds() / 60))
            out.append(f"{k.split('/', 1)[1]} (back in {mins} min)" if mins < 120 else f"{k.split('/', 1)[1]} (back in {mins // 60} h)")
    return (" Cooling down: " + ", ".join(out) + ".") if out else ""


def compute(store, cfg, now, env):
    now = parse_utc(now)
    items = []

    def add(group, name, state, detail):
        items.append({"group": group, "name": name, "state": state, "detail": detail})

    # --- updates
    last = store.q("SELECT MAX(at_utc) AS m FROM heartbeat WHERE kind = 'tick'")[0]["m"]
    if not last:
        add("Updates", "Updater", "bad", "Has never run. Run the Pipeline workflow with task tick, then set up the outside timer.")
    else:
        age = (now - parse_utc(last)).total_seconds() / 60
        add("Updates", "Updater", "ok" if age <= 15 else "warn" if age <= 60 else "bad",
            f"Last ran {_ago(now, last)}." + ("" if age <= 15 else " It should run every 5 minutes: check the outside timer."))
    pub = store.q("SELECT MAX(published_utc) AS m FROM picks")[0]["m"]
    add("Updates", "Last pick posted", "ok" if pub else "idle", _ago(now, pub) if pub else "No pick posted yet.")

    # --- odds
    lo, hi = iso(now - timedelta(hours=1)), iso(now + timedelta(hours=36))
    rows = store.q("SELECT odds_json FROM games WHERE kind = 'team' AND status = 'scheduled' AND start_utc BETWEEN ? AND ?", (lo, hi))
    with_ml = sum(1 for r in rows if r["odds_json"] and json.loads(r["odds_json"]).get("home_ml") is not None)
    key = (env.get("ODDS_API_KEY") or "").strip()
    if not rows:
        add("Odds", "ESPN odds", "idle", "No upcoming team games to check.")
    elif key and with_ml < len(rows):
        add("Odds", "ESPN odds", "ok" if with_ml else "warn",
            f"{with_ml} of {len(rows)} upcoming games have a moneyline. The Odds API fills in the rest when they come due.")
    else:
        add("Odds", "ESPN odds", "ok" if with_ml == len(rows) else "warn" if with_ml else "bad",
            f"{with_ml} of {len(rows)} upcoming games have a moneyline." + ("" if with_ml else " Add the ODDS_API_KEY secret for a fallback."))
    used = store.q("SELECT used, cap FROM quota WHERE key = ?", (f"oddsapi:{iso(now)[:7]}",))
    sources = _snap(store, "sources", {})
    odds_err = [f"{k.split(':')[1]}: {v['detail']}" for k, v in sources.items() if k.startswith("odds:") and not v["ok"]]
    if not key:
        add("Odds", "The Odds API", "off", "Not set up. Only needed if ESPN has no odds. Add the GitHub secret ODDS_API_KEY.")
    elif odds_err:
        add("Odds", "The Odds API", "bad", "Key is set but the last call failed: " + "; ".join(odds_err)[:140])
    elif not used:
        miss = len(rows) - with_ml
        add("Odds", "The Odds API", "idle", "Key is set. " + (f"{miss} upcoming games have no ESPN odds; they are filled from here when they come due." if miss else "Not needed so far because ESPN supplies the odds."))
    else:
        add("Odds", "The Odds API", "ok", f"Working. {used[0]['used']} of {used[0]['cap']} credits used this month.")

    # --- AI text
    st = _snap(store, "llm_status", {})
    cool = _snap(store, "llm_cooldown", {})
    today = iso(now)[:10]
    quota = {r["key"].split(":")[1]: r for r in store.q("SELECT * FROM quota WHERE key LIKE ?", (f"llm:%:{today}",))}
    working = []
    for name, label, envkey in LLM:
        val = (env.get(envkey) or "").strip()
        info, q = st.get(name, {}), quota.get(name)
        cap = cfg.get("llm", {}).get(name, {}).get("daily_cap", 0)
        if not val:
            add("AI text", label, "off", f"Not set up. Add the GitHub secret {envkey}.")
        elif name == "cloudflare" and ":" not in val:
            add("AI text", label, "bad", "The value must look like ACCOUNT_ID:API_TOKEN.")
        elif info.get("error_utc") and info["error_utc"] >= info.get("ok_utc", ""):
            conf = cfg.get("llm", {}).get(name, {})
            many = len(conf.get("models") or []) > 1 or conf.get("discover")
            add("AI text", label, "bad", f"Last call failed: {info['error'][:120]}.{_cooling(cool, name, now)} "
                + ("It switches models by itself. If it says 404, a model name in config.yaml is out of date." if many
                   else "If it says 404, the model name in config.yaml is out of date."))
        elif info.get("ok_utc"):
            working.append(label)
            add("AI text", label, "ok", f"Working. {q['used'] if q else 0} of {cap} calls today, last success {_ago(now, info['ok_utc'])}"
                + (f" ({info['ok_model']})" if info.get("ok_model") else "") + f".{_cooling(cool, name, now)}")
        else:
            add("AI text", label, "idle", "Key is set. Not called yet: it is used when a pick is posted.")
    add("AI text", "Analysis text comes from", "ok" if working else "idle", working[0] if working else "The built-in template (no AI provider has succeeded yet).")

    # --- data
    live = {sp for sp, spec in cfg["sports"].items() if "via" not in spec}          # ignore feeds we no longer fetch
    feeds = {k: v for k, v in sources.items() if k.startswith("scoreboard:") and k.split(":")[1] in live}
    inj = {k: v for k, v in sources.items() if k.startswith("injuries:") and k.split(":")[1] in live}
    for label, grp in (("Game feeds", feeds), ("Injury feeds", inj)):
        if not grp:
            add("Data", label, "idle", "Not fetched yet.")
        else:
            bad = [k.split(":")[1] + " (" + v["detail"][:60] + ")" for k, v in grp.items() if not v["ok"]]
            add("Data", label, "ok" if not bad else "bad", f"{len(grp) - len(bad)} of {len(grp)} working." + (" Failing: " + "; ".join(bad) if bad else ""))
    counts = {r["sport"]: r["n"] for r in store.q("SELECT sport, COUNT(*) AS n FROM games WHERE status = 'final' GROUP BY sport")}
    rated = [f"{s.upper()} {counts.get(s, 0)}" for s in cfg["model"]["elo"]]
    need = cfg["model"].get("min_history", {})
    thin = [s for s, n in need.items() if counts.get(s, 0) < n]
    add("Data", "Finished games stored", "warn" if thin else "ok" if counts else "idle",
        ", ".join(rated) + (f". Too few for ratings in {', '.join(x.upper() for x in thin)}: the updater loads more history by itself, or run the backfill task." if thin else "."))
    bf = {k.split(":")[1]: v for k, v in sources.items() if k.startswith("backfill:") and k.split(":")[1] in live}
    complete = _snap(store, "backfill_complete", None)
    badbf = [f"{k.upper()}: {v['detail']}" for k, v in bf.items() if not v["ok"]]
    okbf = [f"{k.upper()}: {v['detail']}" for k, v in bf.items() if v["ok"]]
    if complete:
        add("Data", "History load", "ok" if not badbf else "bad",
            f"Complete as of {_ago(now, complete['at'])} ({complete['days']} days)." + (" Problems: " + "; ".join(badbf)[:400] if badbf else ""))
    elif bf or _snap(store, "backfill_done", []):
        if badbf:
            add("Data", "History load", "bad", ("Problems: " + "; ".join(badbf) + (". Fine: " + "; ".join(okbf) if okbf else ""))[:500])
        else:
            add("Data", "History load", "warn", "In progress. " + ("; ".join(okbf)[:400] or f"{len(_snap(store, 'backfill_done', []))} chunks loaded") + ". It continues on every update.")
    else:
        add("Data", "History load", "idle", "Not started. It starts by itself on the next update, or run the backfill task.")
    bt = _snap(store, "backtest", {})
    done = {k: v for k, v in bt.items() if v.get("games")}
    add("Data", "Rating check", "ok" if done else "idle",
        "; ".join(f"{k.upper()} {v['accuracy'] * 100:.1f}% of {v['games']} winners (naive log loss {v['baseline_log_loss']}, ours {v['log_loss']})" for k, v in done.items()) if done else "Not run yet. Run the backfill task.")

    # --- system
    ledger = _snap(store, "ledger_check", {})
    add("System", "Ledger", "ok" if ledger.get("ok") else "bad" if ledger.get("ok") is False else "idle",
        "Clean." if ledger.get("ok") else "; ".join(ledger.get("problems", []))[:140] if ledger.get("ok") is False else "Not checked yet (runs daily).")
    n = store.q("SELECT (SELECT COUNT(*) FROM games) AS g, (SELECT COUNT(*) FROM picks) AS p")[0]
    add("System", "Database", "ok", f"Connected. {n['g']} games and {n['p']} picks stored.")
    add("System", "Pipeline version", "info", __version__)
    return {"version": __version__, "generated_utc": iso(now), "items": items}


def write(store, cfg, now, env):
    out = compute(store, cfg, now, env)
    store.x("INSERT INTO snapshots (key, json, updated_utc) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
            "json = excluded.json, updated_utc = excluded.updated_utc", ("integrations", json.dumps(out), iso(now)))
    return out
