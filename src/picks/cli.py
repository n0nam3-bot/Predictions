"""python -m picks.cli <command>   (set PYTHONPATH=src)

migrate | schedule | tick | grade | ledger | verify | backfill | demo
--now ISO   simulate the clock (used by the 'simulate_now' workflow input)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, ledger, llm, pipeline, store
from .sources.espn import ESPNSource
from .timing import iso, parse_utc

ROOT = Path(__file__).resolve().parent.parent.parent


def summary(text):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as fh:
            fh.write(text + "\n")


def run_ledger(st, cfg, now):
    day = pipeline.et_day(now, cfg)
    written = []
    for d in (day - timedelta(days=1), day):
        p = ledger.export_day(st, d, ROOT / "data" / "ledger", cfg["timezone"])
        if p:
            written.append(p.name)
    problems = ledger.verify_chain(st) + ledger.verify_against_ledger(st, ROOT / "data" / "ledger")
    pipeline.put_snapshot(st, "ledger_check", {"ok": not problems, "checked_utc": iso(now), "problems": problems[:20]}, now)
    return {"written": written, "problems": problems}


def main(argv=None, source=None, env=None):
    ap = argparse.ArgumentParser(prog="picks", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["migrate", "schedule", "tick", "grade", "ledger", "verify", "backfill", "demo"])
    ap.add_argument("--now", default="")
    ap.add_argument("--days", type=int, default=45)
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
        chain = llm.Chain(st, cfg, now, env)
        env_ = os.environ if env is None else env
        odds = None
        if env_.get("ODDS_API_KEY"):
            from .sources.oddsapi import OddsAPISource
            odds = OddsAPISource(env_["ODDS_API_KEY"], st, now)
        out = pipeline.run_tick(st, source, cfg, now, chain if chain.available() else None, odds)
    elif args.cmd == "backfill":
        out = pipeline.run_backfill(st, source, cfg, now, args.days)
    elif args.cmd == "grade":
        out = pipeline.run_grade(st, source, cfg, now)
    elif args.cmd == "ledger":
        out = run_ledger(st, cfg, now)
    else:
        problems = ledger.verify_chain(st) + ledger.verify_against_ledger(st, ROOT / "data" / "ledger")
        out = {"problems": problems}
    print(json.dumps(out))
    summary(f"`{args.cmd}` at {iso(now)}: `{json.dumps(out)}`")
    return 1 if out.get("problems") else 0


if __name__ == "__main__":
    sys.exit(main())
