#!/usr/bin/env bash
# Everything that must pass before an upload is accepted into main.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! python3 -c "import pytest, yaml, requests" 2>/dev/null; then
  python3 -m pip install -q -r requirements.txt 2>/dev/null || python3 -m pip install -q --break-system-packages -r requirements.txt
fi
python3 -m pytest -q tests
for f in site/app.js site/lib.js scripts/preview_dom.js api/*.js api/_lib/*.js; do node --check "$f"; done
node --test tests/api/*.test.mjs tests/site/*.test.mjs
echo "ci ok"
