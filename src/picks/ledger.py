"""Insert-only pick ledger: a hash chain in the database plus a daily NDJSON export in git."""
import hashlib
import json
from pathlib import Path

from .records import et_date
from .timing import iso, parse_utc

GENESIS = "0" * 64
HASHED_COLUMNS = ["id", "game_id", "sport", "start_utc", "published_utc", "tag", "verdict", "market",
                  "selection", "line", "odds", "fair_odds", "model_prob", "market_prob", "edge", "units",
                  "confidence", "top_pick", "rank_score", "coverage", "payload_json"]


def _norm(obj):
    """-110 and -110.0 must hash the same (SQLite REAL columns read back as floats)."""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_norm(v) for v in obj]
    return obj


def canonical(obj):
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def row_hash(prev_hash, row):
    body = {k: row.get(k) for k in HASHED_COLUMNS}
    return hashlib.sha256((prev_hash + canonical(body)).encode("utf-8")).hexdigest()


def insert_pick(store, row):
    """Append a pick. Returns the stored row, or None if this game already has a pick."""
    if store.q("SELECT 1 FROM picks WHERE game_id = ?", (row["game_id"],)):
        return None
    last = store.q("SELECT hash FROM picks ORDER BY seq DESC LIMIT 1")
    prev = last[0]["hash"] if last else GENESIS
    full = {**row, "prev_hash": prev, "hash": row_hash(prev, row)}
    cols = HASHED_COLUMNS + ["prev_hash", "hash"]
    store.x(f"INSERT OR IGNORE INTO picks ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [full.get(c) for c in cols])
    saved = store.q("SELECT * FROM picks WHERE game_id = ?", (row["game_id"],))
    return saved[0] if saved and saved[0]["hash"] == full["hash"] else None


def verify_chain(store):
    errors, prev = [], GENESIS
    for r in store.q("SELECT * FROM picks ORDER BY seq"):
        if r["prev_hash"] != prev:
            errors.append(f"seq {r['seq']}: prev_hash does not match the previous row")
        if r["hash"] != row_hash(r["prev_hash"], r):
            errors.append(f"seq {r['seq']}: content does not match its hash")
        prev = r["hash"]
    return errors


def ledger_lines(store, day, tz="America/New_York"):
    lines = []
    for r in store.q("SELECT * FROM picks ORDER BY seq"):
        if et_date(r["published_utc"], tz) == day:
            lines.append({"type": "pick", **{k: r[k] for k in HASHED_COLUMNS}, "prev_hash": r["prev_hash"],
                          "hash": r["hash"]})
    for g in store.q("SELECT * FROM grades WHERE grade IN ('W','L','V') ORDER BY pick_id"):
        if et_date(g["graded_utc"], tz) == day:
            lines.append({"type": "grade", **g})
    return lines


def export_day(store, day, out_dir, tz="America/New_York"):
    lines = ledger_lines(store, day, tz)
    if not lines:
        return None
    path = Path(out_dir) / f"{day.isoformat()}.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(x) + "\n" for x in lines))
    return path


def verify_against_ledger(store, ledger_dir):
    """Every ledger line must match the database. Returns a list of problems."""
    problems = []
    picks = {r["id"]: r for r in store.q("SELECT * FROM picks")}
    grades = {g["pick_id"]: g for g in store.q("SELECT * FROM grades")}
    for f in sorted(Path(ledger_dir).glob("*.ndjson")):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            x = json.loads(line)
            if x["type"] == "pick":
                db = picks.get(x["id"])
                if db is None or db["hash"] != x["hash"]:
                    problems.append(f"{f.name}:{n} pick {x['id']} differs from the database")
            else:
                db = grades.get(x["pick_id"])
                if db is None or db["grade"] != x["grade"]:
                    problems.append(f"{f.name}:{n} grade for {x['pick_id']} differs from the database")
    return problems
