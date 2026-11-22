"""python -m picks.cli <command>   (set PYTHONPATH=src)

migrate | schedule | tick | grade | ledger | verify | backfill | backtest | demo
--now ISO   simulate the clock (used by the 'simulate_now' workflow input)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import backtest, config, ledger, llm, pipeline, status, store
from .sources.espn import ESPNSource
from .timing import iso, parse_utc

ROOT = Path(__file__).resolve().parent.parent.parent


def ledger_dir(env=None):
    """Where the daily audit files live. Tests point PICKS_LEDGER_DIR somewhere private."""
    env = os.environ if env is None else env
    return Path(env.get("PICKS_LEDGER_DIR") or ROOT / "data" / "ledger")


def summary(text):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as fh:
            fh.write(text + "\n")


def run_ledger(st, cfg, now, env=None):
    day = pipeline.et_day(now, cfg)
    written = []
    for d in (day - timedelta(days=1), day):
        p = ledger.export_day(st, d, ledger_dir(env), cfg["timezone"])
        if p:
            written.append(p.name)
    problems = ledger.verify_chain(st) + ledger.verify_against_ledger(st, ledger_dir(env))
    pipeline.put_snapshot(st, "ledger_check", {"ok": not problems, "checked_utc": iso(now), "problems": problems[:20]}, now)
    return {"written": written, "problems": problems}


def last_run(st, kind):
    row = st.q("SELECT MAX(at_utc) AS m FROM heartbeat WHERE kind = ?", (kind,))
    return parse_utc(row[0]["m"]) if row and row[0]["m"] else None


def housekeeping(st, source, cfg, now):
    """GitHub cron is unreliable. If only `tick` is being triggered (for example by an external timer),
    refresh the schedule every 3 hours and grade every 40 minutes from inside the tick."""
    ran = []
    ls, lg = last_run(st, "schedule"), last_run(st, "grade")
    if ls is None or (now - ls) > timedelta(hours=3):
        pipeline.run_schedule(st, source, cfg, now)
        ran.append("schedule")
    return ran, (lg is None or (now - lg) > timedelta(minutes=40))


def history_thin(st, cfg):
    counts = {r["sport"]: r["n"] for r in st.q("SELECT sport, COUNT(*) AS n FROM games WHERE status = 'final' GROUP BY sport")}
    return any(counts.get(s, 0) < need for s, need in cfg["model"].get("min_history", {}).items())


def maybe_backfill(st, source, cfg, now):
    """Ratings need history. If it is thin, load a few minutes' worth per tick until it is complete (resumable)."""
    done = pipeline.get_snapshot(st, "backfill_complete", None)
    if done and (now - parse_utc(done["at"])) < timedelta(hours=24):
        return False
    last = last_run(st, "backfill")
    if not history_thin(st, cfg) or (last and (now - last) < timedelta(minutes=20)):
        return False
    pipeline.run_backfill(st, source, cfg, now, days=240, budget_minutes=3)
    pipeline.put_snapshot(st, "backtest", backtest.run(st, cfg), now)
    return True


def main(argv=None, source=None, env=None):
    ap = argparse.ArgumentParser(prog="picks", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["migrate", "schedule", "tick", "grade", "ledger", "verify", "backfill", "backtest", "demo"])
    ap.add_argument("--now", default="")
    ap.add_argument("--days", type=int, default=240)
    ap.add_argument("--budget", type=int, default=10, help="backfill time budget in minutes")
    ap.add_argument("--out", default=str(ROOT / "site" / "demo" / "latest.json"))
    args = ap.parse_args(argv)
    cfg = config.load()
    now = parse_utc(args.now) if args.now else datetime.now(timezone.utc)
    if args.cmd == "demo":
        latest = __import__("picks.demo", fromlist=["x"]).write(args.out)
        print(f"wrote {args.out}: {len(latest['games'])} games")
        return 0
    st = store.connect(env)
    if st is None:
        print("::notice::Database not configured (TURSO_URL and TURSO_WRITE_TOKEN missing). Nothing to do yet.")
        summary("Database not configured yet. Follow docs/SETUP_PHONE.md.")
        return 0
    n = store.migrate(st)
    if args.cmd == "migrate":
        print(f"schema ok ({n} statements)")
        return 0
    source = source or ESPNSource(cfg)
    if args.cmd == "schedule":
        out = pipeline.run_schedule(st, source, cfg, now)
    elif args.cmd == "tick":
        ran, grade_due = housekeeping(st, source, cfg, now)
        chain = llm.Chain(st, cfg, now, env)
        env_ = os.environ if env is None else env
        odds = None
        if env_.get("ODDS_API_KEY"):
            from .sources.oddsapi import OddsAPISource
            odds = OddsAPISource(env_["ODDS_API_KEY"], st, now)
        out = pipeline.run_tick(st, source, cfg, now, chain if chain.available() else None, odds)
        if grade_due:
            pipeline.run_grade(st, source, cfg, now)
            ran.append("grade")
        if maybe_backfill(st, source, cfg, now):
            ran.append("backfill")
        out["also_ran"] = ran
    elif args.cmd == "backfill":
        out = pipeline.run_backfill(st, source, cfg, now, args.days, args.budget)
        out["backtest"] = backtest.run(st, cfg)
        pipeline.put_snapshot(st, "backtest", out["backtest"], now)
        pipeline.build_snapshots(st, cfg, now)
    elif args.cmd == "backtest":
        out = backtest.run(st, cfg)
        pipeline.put_snapshot(st, "backtest", out, now)
        pipeline.build_snapshots(st, cfg, now)
    elif args.cmd == "grade":
        out = pipeline.run_grade(st, source, cfg, now)
    elif args.cmd == "ledger":
        out = run_ledger(st, cfg, now, env)
    else:
        problems = ledger.verify_chain(st) + ledger.verify_against_ledger(st, ledger_dir(env))
        out = {"problems": problems}
    if args.cmd in ("tick", "schedule", "grade", "backfill", "backtest", "ledger"):
        status.write(st, cfg, now, os.environ if env is None else env)
        pipeline.build_snapshots(st, cfg, now)
    print(json.dumps(out))
    summary(f"`{args.cmd}` at {iso(now)}: `{json.dumps(out)}`")
    return 1 if out.get("problems") else 0


if __name__ == "__main__":
    sys.exit(main())
