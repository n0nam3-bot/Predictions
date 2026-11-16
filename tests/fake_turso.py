"""A tiny stand-in for Turso's /v2/pipeline endpoint, backed by in-memory SQLite."""
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

WRITE, READ = "write-token", "read-token"


def _enc(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, bytes):
        import base64
        return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": v}


def _dec(c):
    t = c["type"]
    if t == "null":
        return None
    if t == "integer":
        return int(c["value"])
    if t == "float":
        return float(c["value"])
    return c["value"]


class FakeTurso:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.lock = threading.Lock()
        self.calls = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                outer.calls += 1
                token = (self.headers.get("Authorization") or "").replace("Bearer ", "")
                if token not in (WRITE, READ) or self.path != "/v2/pipeline":
                    self.send_response(401)
                    self.end_headers()
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                results = []
                for req in body["requests"]:
                    if req["type"] == "close":
                        results.append({"type": "ok", "response": {"type": "close"}})
                        continue
                    sql = req["stmt"]["sql"]
                    args = [_dec(a) for a in req["stmt"].get("args", [])]
                    if token == READ and not sql.lstrip().upper().startswith("SELECT"):
                        results.append({"type": "error", "error": {"message": "read-only token"}})
                        continue
                    try:
                        with outer.lock:
                            cur = outer.db.execute(sql, args)
                            rows = cur.fetchall()
                            outer.db.commit()
                            cols = [{"name": d[0], "decltype": None} for d in (cur.description or [])]
                        results.append({"type": "ok", "response": {"type": "execute", "result": {
                            "cols": cols, "rows": [[_enc(v) for v in r] for r in rows],
                            "affected_row_count": max(cur.rowcount, 0), "last_insert_rowid": None}}})
                    except sqlite3.Error as exc:
                        results.append({"type": "error", "error": {"message": str(exc)}})
                payload = json.dumps({"baton": None, "base_url": None, "results": results}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
