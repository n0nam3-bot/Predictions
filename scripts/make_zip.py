#!/usr/bin/env python3
"""Build an inbox-ready zip of this project: python3 scripts/make_zip.py picks-board-v0.1.zip [notes]"""
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", "inbox", "data", "audit_out", ".vercel", ".venv"}


def main(out, notes="Full project"):
    version = out.replace(".zip", "")
    files = []
    for dirpath, dirs, names in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for n in sorted(names):
            p = Path(dirpath) / n
            if n.endswith((".pyc", ".zip", ".db")) or p.name == ".DS_Store":
                continue
            files.append(p)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("inbox.manifest.json", json.dumps({"version": version, "notes": notes}, indent=1))
        for p in files:
            info = zipfile.ZipInfo(str(p.relative_to(ROOT)).replace(os.sep, "/"), date_time=(2026, 11, 15, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if os.access(p, os.X_OK) else 0o100644) << 16
            zf.writestr(info, p.read_bytes())
    print(f"{out}: {len(files) + 1} entries")


if __name__ == "__main__":
    main(sys.argv[1], *(sys.argv[2:3]))
