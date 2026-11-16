"""One small interface over two backends: Turso (libSQL over HTTPS) and a local SQLite file.

Turso is reached with plain HTTPS (the /v2/pipeline endpoint), so GitHub Actions and Vercel
need no TCP, no IPv6 and no extra packages. Local SQLite is for tests and the offline demo.
"""
import base64
import os
import sqlite3
import time
from pathlib import Path

import requests

SCHEMA = Path(__file__).resolve().parent.parent.parent / "db" / "schema.sql"


def schema_statements():
    text = SCHEMA.read_text()
    return [s.strip() for s in text.split("\n-- split\n") if s.strip() and not s.strip().startswith("--\n")]


class SqliteStore:
    kind = "sqlite"

    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row

    def q(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, tuple(args)).fetchall()]

    def x(self, sql, args=()):
        cur = self.db.execute(sql, tuple(args))
        self.db.commit()
        return cur.rowcount

    def many(self, stmts):
        for sql, args in stmts:
            self.db.execute(sql, tuple(args))
        self.db.commit()


def _enc(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, bytes):
        return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": str(v)}


def _dec(cell):
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    if t == "blob":
        return base64.b64decode(cell["base64"])
    return cell["value"]


class StoreError(RuntimeError):
    pass


class StatementError(StoreError):
    """The database refused the statement (not worth retrying)."""


class TursoStore:
    kind = "turso"

    def __init__(self, url, token, timeout=20):
        self.endpoint = url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self.timeout = timeout

    def _post(self, stmts):
        body = {"requests": [{"type": "execute", "stmt": {"sql": s, "args": [_enc(a) for a in args]}}
                             for s, args in stmts] + [{"type": "close"}]}
        last, results = None, None
        for attempt in range(3):
            try:
                resp = requests.post(self.endpoint, json=body, headers=self.headers, timeout=self.timeout)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise StoreError(f"HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    raise StatementError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                results = resp.json()["results"]
                break
            except StatementError:
                raise
            except (requests.RequestException, StoreError, ValueError, KeyError) as exc:
                last = exc
                time.sleep(0.4 * (2 ** attempt))
        if results is None:
            raise StoreError(f"Turso request failed: {last}")
        out = []
        for r in results[:-1]:
            if r["type"] != "ok":
                raise StatementError(r.get("error", {}).get("message", "statement failed"))
            out.append(r["response"]["result"])
        return out

    def q(self, sql, args=()):
        res = self._post([(sql, args)])[0]
        names = [c["name"] for c in res["cols"]]
        return [dict(zip(names, (_dec(c) for c in row))) for row in res["rows"]]

    def x(self, sql, args=()):
        return self._post([(sql, args)])[0].get("affected_row_count", 0)

    def many(self, stmts):
        self._post(list(stmts))


def connect(env=None, write=True):
    """TURSO_URL + token -> Turso. PICKS_DB=path -> SQLite. Otherwise None (not configured)."""
    env = os.environ if env is None else env
    url = env.get("TURSO_URL")
    token = env.get("TURSO_WRITE_TOKEN" if write else "TURSO_READ_TOKEN") or env.get("TURSO_WRITE_TOKEN")
    if url and token:
        return TursoStore(url, token)
    if env.get("PICKS_DB"):
        return SqliteStore(env["PICKS_DB"])
    return None


def migrate(store):
    stmts = schema_statements()
    store.many([(s, ()) for s in stmts])
    return len(stmts)
