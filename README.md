# Pre-game picks board

A free, self-updating site that posts pre-game analysis for MLB, NFL, NBA, NHL, UFC and DWCS about 30 minutes before each team game and 90 minutes before the first bout of a card, grades every pick, and keeps a public win-loss-void record. No visitor ever clicks “run”.

How it fits together (all free tiers):
- **GitHub Actions** is the clock: `schedule`, `tick`, `grade`, `ledger`, and `inbox` (applies zip uploads).
- **Turso** (SQLite over HTTPS) is the system of record. Picks are insert-only with a hash chain, exported daily to `data/ledger/`.
- **Vercel** serves `site/` and a read-only API in `api/`.

Visitors can step through any date with the date control: today updates live, past days show every game with its locked pick and result.

Start here: [`docs/SETUP_PHONE.md`](docs/SETUP_PHONE.md). Rules and limits: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md). Feeds: [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md). Problems: [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Honest status (v0.1)
Built and tested offline: zip inbox, store, hash-chained ledger, timing windows, grading rules, records, validator, baseline model, ESPN parsers (on synthetic fixtures), read-only API, site.
Not done yet: real-feed verification (run the `audit` task), injury weighting, fighter data, spread and total picks, backtests. The baseline is unvalidated and will mostly PASS. The site labels it Experimental.

## Develop
```
python3 -m pip install -r requirements.txt
bash scripts/ci.sh                     # tests (Python and Node)
PYTHONPATH=src python3 -m picks demo   # rebuild site/demo/latest.json (fictional data)
python3 -m http.server -d site 8000    # open /?demo=1
```
Informational only. Not betting advice. 21+. 1-800-GAMBLER.
