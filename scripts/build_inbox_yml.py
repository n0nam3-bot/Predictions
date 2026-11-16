#!/usr/bin/env python3
"""Build .github/workflows/inbox.yml by embedding scripts/apply_inbox.py into the template."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDENT = " " * 10


def build():
    tmpl = (ROOT / "scripts" / "inbox.yml.tmpl").read_text()
    script = (ROOT / "scripts" / "apply_inbox.py").read_text().rstrip("\n").splitlines()
    if any(line.strip() == "PYEOF" for line in script):
        raise SystemExit("apply_inbox.py must not contain a line that is only PYEOF")
    embedded = "\n".join((INDENT + line) if line else "" for line in script)
    return tmpl.replace("__EMBEDDED__", embedded)


if __name__ == "__main__":
    out = ROOT / ".github" / "workflows" / "inbox.yml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build())
    print(f"wrote {out}", file=sys.stderr)
