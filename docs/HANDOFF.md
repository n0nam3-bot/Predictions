# HANDOFF: read this first, in every new chat

This file is the single source of truth for how the project works, what is broken, and what comes next. Any chat that changes the project must update it in the same zip (section 12). If this file and the code disagree, the code wins: fix this file.

| | |
|---|---|
| Repo | https://github.com/n0nam3-bot/Predictions (public, branch `main`) |
| Code version | 0.3.4 (`src/picks/__init__.py` and `SITE_VERSION` in `site/app.js`; keep them equal by hand, no test enforces it) |
| Doc verified | 2026-11-23 against commit `5783ff1` |
| Live site URL | not recorded yet: ask the owner once, then write it here (section 11) |
| Owner | GitHub user `n0nam3-bot`, works from a phone |

Evidence tags used below: **[verified]** observed in the repo, the committed ledger or the test run on 2026-11-23. **[inferred]** concluded from reading code, not observed. **[owner]** stated by the owner in chat.

## 0. The 60-second briefing

**What it is.** A free, self-updating site that posts pre-game analysis for MLB, NFL, NBA, NHL, UFC and Dana White's Contender Series (DWCS) about 30 minutes before each team game and 90 minutes before the first bout of a card, grades every pick W, L or V (void), and keeps a public record. No visitor ever clicks "run".

**How it runs.** GitHub Actions is the clock (`Pipeline` workflow). Turso (free SQLite over HTTPS) is the database. Vercel serves `site/` and a read-only API in `api/`. Every change ships as one zip uploaded to the repo from a phone; the `Inbox` workflow unzips it, runs the tests and commits it.

**Where it stands (evidence: committed ledger, 2026-11-17 to 2026-11-22).**
- The machine works [verified]: 112 picks posted on time, the hash chain is intact, 146 Python and 16 Node tests pass.
- It has never produced a PLAY [verified]: 112 of 112 are PASS, 0 graded, record 0-0-0, 0 top picks.
- **Blocker 1:** team ratings are unavailable because the production database holds only about 5 to 7 games per team (8 are needed). That caps coverage at 75%, under the 85% required, so every team pick is a forced PASS. History did not grow even in the 7 hours after v0.3.4 shipped. Cause unknown. See P0-1.
- **Blocker 2 (wording only):** AI text never succeeded: Gemini returned 404, then 503 and timeouts. All text is the built-in template. See P0-2.
- UFC and DWCS post empty PASS rows: no odds in the ESPN feed and no fighter data. See P1-3.

**First moves in a new chat.** Do section 1. If the task touches production, ask the owner for the Status panel text (section 10.7). Unless told otherwise, the next task is roadmap item R0.1: get history loading and prove it.

## 1. Start-up protocol for Claude

1. Read this whole file.
2. `git clone https://github.com/n0nam3-bot/Predictions.git` in the sandbox. github.com is reachable from bash, while `web_fetch` often refuses GitHub URLs, so clone instead. Compare `git log -5` with the "Doc verified" commit above: anything newer is not reflected here.
3. Run `bash scripts/ci.sh`. Expect `ci ok`. If it fails at HEAD, report that first.
4. The only live data visible from the sandbox is `data/ledger/*.ndjson` (picks and grades, exported daily at about 03:35 New York time, so it lags by up to a day). Turso, Vercel, Actions logs and Issues are not reachable, and GitHub's REST API returned HTTP 403 (rate limit) from the sandbox on 2026-11-23. For live state ask the owner to paste the Status panel, the latest Pipeline run summary, or the newest `Inbox log` comment (section 10.7). Never ask for browser-console output.
5. Read sections 9 (lessons) and 10 (recipes) before editing anything.
6. Before the chat ends: update sections 5, 6, 7 and 12 of this file and ship it in the same zip as the code.

## 2. The owner's working constraints (treat as requirements)

- **Phone only.** No laptop, no browser console. Every manual step must be doable in a mobile browser and be given as exact taps and copy-paste text. All changes ship as ONE zip (section 10.1).
- **On-screen debugging.** Anything that needs diagnosing must show up in the Status panel, the Inbox log issue, or an Actions run summary.
- **$0, free tiers only.** No paid service, no card on file. Vercel Hobby is non-commercial: no ads, no monetization.
- **No Groq** as an LLM provider [owner]. GitHub Models is retired (July 2026).
- **Production-ready over prototype.** Prefer boring, tested, verifiable.
- **Public repo.** Never commit secrets or personal information. The inbox rejects zips that contain secret-looking strings.
- **Truthfulness first.** Numbers come from code, never from an LLM. An unavailable input is stated as unavailable. PASS when there is no edge is a feature: never tune thresholds just to manufacture PLAYs.
- Gambling-adjacent: keep the footer disclaimers ("Informational only, not betting advice. 21+. 1-800-GAMBLER.").

## 3. Requirements the owner stated, and where each stands

| # | Requirement [owner] | Status | Notes |
|---|---|---|---|
| R1 | Public repo that auto-pulls free data and shows analytics and predictions to every visitor, no click-to-run | Met | Actions, Turso, Vercel. The site polls `/api/latest` every 60 s. |
| R2 | The whole project costs $0 | Met, watch | Vercel Hobby (non-commercial), Turso free limits (unverified), Odds API 500 credits a month. |
| R3 | Team-game analysis posted within 30 minutes of start | Met [verified] | 43 of 43 picks since v0.3.2 posted 29.5 to 29.7 minutes before start. None LATE. |
| R4 | MMA analysis posted 1h30m before the first bout | Timing met, content empty | The UFC card posted 94.7 min before the first bout (`due_minutes: 95`). No odds, no fighter data. |
| R5 | Highlight top-rated predictions | Built, never exercised | Top Pick: edge at least 4%, coverage at least 95%, max 5 per ET day. 0 so far. |
| R6 | Daily win-loss-void record plus overall record since release | Built, empty | 0 graded picks yet. |
| R7 | Sport filter, default all | Met | Tabs; last choice remembered in `localStorage`; deep link `#s=nba`. |
| R8 | Extremely accurate analysis that reflects the actual truth: styles, matchups, past faceoffs, streaks, injuries, schedules, travel and rest, anything else worth considering | **Partial** | Have: market, Elo ratings (need history), rest and back-to-back, last-5 form, injury lists without player impact. Missing: starting goalies and pitchers, quarterback status, lineups, travel, head-to-head, styles, weather, every fighter input. |
| R9 | Sports: MLB, NFL, NBA, NHL, UFC, DWCS | Partial | NBA, NHL, NFL live. MLB is off-season (never exercised live). UFC rows are empty. No DWCS card seen yet. |
| R10 | Analyst logic: no-vig edge, PASS when no edge | Met | Proportional de-vig; edge = model minus no-vig market. |
| R11 | Zip uploaded from a phone is unzipped into the right folders by an Action | Met | 9 zips applied, 2 failed (fixed by v0.3.2), 1 duplicate skipped. |
| R12 | Free LLM providers only | Met, not working | Gemini key is set but failing; the other providers appear unset. |

## 4. How everything works

### 4.1 The pieces

| Piece | Where | Role |
|---|---|---|
| `Pipeline` workflow | `.github/workflows/pipeline.yml` (hand-installed) | The clock. Cron plus manual tasks. |
| `Inbox` workflow | `.github/workflows/inbox.yml` (generated) | Applies zip uploads. |
| Python package `picks` | `src/picks/` | All logic. Python 3.12. Deps: requests, pyyaml, pytest. |
| Turso | external, free | System of record. Reached by plain HTTPS (`/v2/pipeline`), no driver. |
| Vercel | `vercel.json`, `site/`, `api/` | Static site and read-only serverless API (Hobby). |
| cron-job.org | the owner's account, see `docs/RELIABLE_CLOCK.md` | Dispatches `Pipeline` task `tick` on a timer because GitHub's own cron skips runs. Uses a fine-grained token limited to Actions on this repo. |
| ESPN public JSON | `site.api.espn.com` | Schedules, scores, moneylines, injuries, UFC events. Unofficial. |
| The Odds API | optional `ODDS_API_KEY` | Fallback moneylines only for games ESPN has none for; at most once per sport per 20 min; stops at 85% of 500 credits a month. |
| LLM chain | optional keys | Gemini, Mistral, Cloudflare Workers AI, OpenRouter, then the template. |

### 4.2 The runtime loop (`Pipeline`)

All tasks run `python -m picks.cli <task>` with `PYTHONPATH=src`, then write a summary to the run page. Every function takes the clock as an argument so `simulate_now` can replay any moment.

- **`tick`** (GitHub cron `2-59/5 * * * *` plus the external timer): heartbeat; housekeeping (run `schedule` if the last one is over 3 h old; remember to grade if the last grade is over 40 min old); find due items; for each, refresh that day's ESPN scoreboard and the injuries, fill missing moneylines from the Odds API, build the facts packet, model, decide, write the narrative, insert the locked pick; then grade if due; then `maybe_backfill` (up to 3 minutes, only while stored history is below `model.min_history`); then write the Status snapshot and rebuild the site snapshots.
- **`schedule`** (cron `7 */3 * * *`): upsert every feed sport's games for ET today minus 7 days to plus 2 days; refresh injuries.
- **`grade`** (cron `17,47 * * * *`): grade PLAY picks whose game is final.
- **`ledger`** (cron `35 8 * * *`, 08:35 UTC, about 03:35 ET): export yesterday's and today's (ET) picks and grades to `data/ledger/YYYY-MM-DD.ndjson`, verify chain and files, store the result in snapshot `ledger_check`, and commit `ledger: daily export` as the repo owner.
- **`backfill`** (manual, `days` default 240): loads finished games in 30-day chunks, newest first, for each feed sport (order: nfl, nba, nhl, mlb, ufc); stops after a 10-minute budget; remembers finished chunks (`backfill_done`); sets `backfill_complete` only when nothing failed; then runs `backtest`.
- **`backtest`** (manual): walk-forward Elo check per sport (accuracy, log loss, Brier vs a naive home-rate baseline) into snapshot `backtest`. Shown as "Rating check".
- **`verify`**: hash chain plus database vs ledger files. **`audit`**: probes every free source from Actions and uploads the `audit-samples` artifact. **`setup-check`**: lists missing secrets and the age of the last tick. **`demo`**: rebuilds fictional demo JSON in the runner's temp dir (not committed).
- **Concurrency:** group `pipeline-<schedule | task | manual>`, `cancel-in-progress: false`, 15-minute timeout. See P1-7.

### 4.3 Timing (`src/picks/timing.py`, `config.yaml: timing`)

- Team game: DUE at or under T-30 minutes, LATE under T-10, MISSED once the scheduled start has passed. Candidate window: status scheduled or delayed, start between now minus 30 min and now plus 4 h.
- MMA: the whole card is judged by its first bout. DUE at or under T-95, LATE under T-60. Candidate window: events with a bout starting between now minus 12 h and now plus 6 h.
- Once the start has passed nothing is posted; the game is flagged `missed = 1` and excluded from every record.
- Observed [verified]: team picks post 29.5 to 29.7 min before start (ticks run far more often than every 5 minutes at game times); the UFC card posted 94.7 min before the first bout. The site displays "posts at T-90" for bouts (`publish_target`), a small mismatch with the T-95 config.

### 4.4 The facts packet and coverage (`facts.py`)

Each game gets five inputs. Every one carries `value`, `source`, `fetched_at`, or a `reason` it is missing.

| Input | Weight | Source and rule |
|---|---|---|
| market | 0.35 | ESPN moneyline (or Odds API). No-vig by the proportional method. Opening line = first stored snapshot. |
| ratings | 0.25 | Elo from stored final scores. Needs `min_rated_games` (8) stored games for BOTH teams. |
| schedule_rest | 0.10 | Days off (0 = played yesterday), games in the last 7 days. Needs earlier stored games for both teams. |
| recent_form | 0.10 | Last 5 stored results with scores and goal or point difference. |
| injuries | 0.20 | ESPN list filtered to Out, Doubtful, Questionable, Day-To-Day (top 6 per team). Long-term injured reserve is counted, not listed. No player value, so the size of an absence is not measured. |

`coverage` = sum of the weights of available inputs. Bouts: ratings, rest and form are permanently unavailable ("fighter data is not connected yet"), and injuries are not fetched for bouts, so bout coverage can never exceed 0.35.

### 4.5 Model (`ratings.py`, `model.py`)

1. Elo from every stored final, all teams start at 1500, rebuilt each run (no season-to-season reversion). Per-sport K and home advantage in `config.yaml` (NBA 20/70, NHL 8/35, NFL 20/48, MLB 6/25). Margin-of-victory multiplier `(1 + ln(1 + margin)) * 2.2 / (0.001 * winnerEloDiff + 2.2)`.
2. Schedule nudges in logit points: days-off difference (clamped to +/-3) times 0.02; back-to-back 0.05.
3. Blend with the market: `p = sigmoid(logit(market) + 0.25 * (ratingLogit - logit(market)))`. If ratings are unavailable, the model equals the market and the edge is exactly 0.

### 4.6 Decision (`decide.py`)

The candidate is the side with the larger edge (model minus no-vig market). PASS reasons are checked in this order: no market or model; coverage under 0.85; edge above 0.10 (treated as a data error); edge under 0.025; expected value at the quoted price not positive. Otherwise PLAY with `units = clamp(round(edge / 0.02 * coverage), 1, 3)` and `confidence = clamp(round(10 * coverage * min(edge / 0.08, 1)), 1, 10)`. Top Pick: PLAY with edge at least 0.04 and coverage at least 0.95, at most 5 per ET day, decided at publish and locked. **Moneyline picks only**; spread and total grading exists in `grading.py` but nothing generates those picks.

### 4.7 Grading and records (`grading.py`, `records.py`)

W, L or V. Void: cancelled, no contest, withdrawn, replaced; tie or draw on a moneyline; postponed, suspended or delayed and not completed within 48 h. A final without a score or winner becomes `PENDING_REVIEW` and is retried. Profit is in units at the posted price; closing-line value compares the posted price with the last odds snapshot at or before the start. A graded pick cannot change (database trigger). Records count PLAY picks only: today (ET date of the scheduled start), overall, per sport, top picks, 30-day history, current streak. Win % excludes voids. PASS never counts.

### 4.8 Analysis text (`narrative.py`, `llm.py`, `validator.py`)

A template always writes the five sections (market, matchup, context, projection, risk) plus a three-line thesis from the packet. If any provider key is set, the chain (config order: gemini, mistral, cloudflare, openrouter) is asked to reword it; each provider has a daily cap in `config.yaml` and is skipped past 85% of it. The validator rejects any number or name not in the packet and any claim about an unavailable input. A validation failure is retried up to 2 more times; a provider error (404, 503, timeout) falls back to the template at once. `narrative_source` and `validator_problems` are stored with the pick.

### 4.9 Integrity

Picks are insert-only (database triggers). Each row's SHA-256 covers 21 columns plus the previous hash. The daily NDJSON export in git lets anyone re-verify. Checked offline on 2026-11-23 [verified]: 112 picks, one unbroken chain from genesis, no forks, no duplicate games.

### 4.10 Site and API

- `site/` (vanilla JS, no build): summary headline and overall record; sport tabs; date control (previous, next, Today, date picker); groups Plays, Passed (largest edge first), a collapsed "without odds or enough data", Waiting for analysis, Not analysed; expandable detail per row; Status panel; banner when offline or when the last tick is over 30 minutes old. Polls every 60 s. Deep links `#d=YYYY-MM-DD&s=nba`. `?demo=1` loads fictional `site/demo/latest.json`.
- `api/` (Vercel functions, read-only token, GET and HEAD only): `/api/latest` (snapshot: games from now minus 26 h to now plus 36 h, records, health, top picks), `/api/record`, `/api/day?date=YYYY-MM-DD` (one ET day, today minus 400 to plus 14), `/api/game?id=`, `/api/health` (deployed commit, database ok, snapshot age). CDN cache: 20 s plus 300 s stale-while-revalidate, one hour for days older than 2.
- Vercel builds only when `site/`, `api/`, `vercel.json` or `package.json` changed.

### 4.11 The inbox (zip) system

Triggers on a push by the repo owner that touches `inbox/*.zip` or a root `*.zip`; also manual (`zip`, `revert_sha`). `scripts/apply_inbox.py` (stdlib only, embedded in `inbox.yml`):
- Allowlist: dirs `site api src db tests docs scripts fixtures`; root files `config.yaml vercel.json package.json package-lock.json requirements.txt README.md .gitignore`; `inbox.manifest.json` (`version`, `notes`, `delete[]`, `move{}`); `.github/workflows/*.yml`. Anything else rejects the WHOLE zip. Also rejected: path escapes, symlinks, encrypted entries, `.env*`, secret-looking content, more than 2000 files, over 10 MB a file or 100 MB total.
- Workflow files are applied only if the `INBOX_PAT` secret exists; otherwise they are quarantined to `inbox/needs-manual/<zip>/...`.
- Same sha256 as an applied zip: skipped. Otherwise apply, run `bash scripts/ci.sh`; on failure the tree is restored, the zip moves to `inbox/failed/`, and the tail of the test output goes to the `Inbox log` issue. On success: commit `inbox: apply <zip> (N files)` as the repo owner (Vercel Hobby blocks other authors), update `inbox/applied.json`, push, and if `SITE_URL` is set wait up to 10 minutes for `/api/health` to report the new commit.

### 4.12 Database (`db/schema.sql`, idempotent, statements split by `-- split`)

`games`, `odds_snapshots`, `facts`, `picks` (insert-only, hash chain), `grades`, `snapshots` (key/json), `quota`, `heartbeat`, `inbox_log` (unused). Snapshot keys: `latest`, `record`, `health`, `sources`, `injuries:<sport>`, `integrations` (Status), `ledger_check`, `backtest`, `backfill_done`, `backfill_complete`, `llm_status`, `oddsapi_last:<sport>`. Quota keys: `llm:<provider>:<UTC date>`, `oddsapi:<YYYY-MM>`. Heartbeat kinds: tick, schedule, grade, backfill (last 300 kept). `store.migrate` runs on every CLI call; there is no migration framework (P2-6).

### 4.13 Configuration (`config.yaml`, change by zip, no code edits)

Current values: timezone America/New_York; timing team 30/10, mma 95/60; thresholds `play_min_edge` 0.025, `play_min_coverage` 0.85, `edge_error_cap` 0.10, `top_min_edge` 0.04, `top_min_coverage` 0.95, `top_per_day` 5, `max_units` 3; model `anchor_shrink` 0.25, `min_rated_games` 8, `min_history` nfl 100 / nba 150 / nhl 150, `logit_weights` rest 0.02 and back-to-back 0.05; LLM daily caps gemini 200, mistral 300, cloudflare 100, openrouter 40; Gemini model `gemini-flash-latest`.

### 4.14 Secrets and variables (names only, never values)

- GitHub Actions secrets: `TURSO_URL`, `TURSO_WRITE_TOKEN` (required); `INBOX_PAT` (fine-grained, this repo, Contents and Workflows read/write; probably unset [inferred]); `GEMINI_API_KEY` (set [verified by attempts]); `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`, `CLOUDFLARE_AI` (`ACCOUNT_ID:API_TOKEN`), `ODDS_API_KEY` (apparently unset [inferred from UFC having no odds]). Variable: `SITE_URL`.
- Vercel environment: `TURSO_URL`, `TURSO_READ_TOKEN` (read-only token).
- The external timer has its own token (Actions read and write on this repo only).

### 4.15 File map

```
.github/workflows/pipeline.yml   the clock (hand-installed)
.github/workflows/inbox.yml      generated: scripts/inbox.yml.tmpl + scripts/apply_inbox.py
api/                             Vercel read-only functions (_lib/db.js, http.js, shape.js; latest, record, day, game, health)
config.yaml                      every tunable number
data/ledger/YYYY-MM-DD.ndjson    daily audit export (bot-written, never zipped)
db/schema.sql                    schema
docs/                            DATA_SOURCES, METHODOLOGY, RELIABLE_CLOCK, RUNBOOK, SETUP_PHONE, HANDOFF (this file)
fixtures/                        synthetic ESPN samples used by tests
inbox/                           applied.json, failed/, needs-manual/ (bot-written)
scripts/                         apply_inbox, build_inbox_yml, inbox.yml.tmpl, make_zip, setup_check, source_audit, ci.sh
site/                            index.html, app.js, styles.css, demo/latest.json (fictional)
src/picks/                       cli, pipeline, store, ledger, timing, facts, ratings, model, decide, market,
                                 grading, records, narrative, llm, validator, status, backtest, demo, config,
                                 sources/espn.py, sources/oddsapi.py
tests/                           13 pytest files (146 tests), tests/api/*.test.mjs (16 Node tests), fake_turso.py
vercel.json, package.json        deploy config (package.json version 0.1.0 is stale, P2-1)
```

## 5. Current state (evidence as of 2026-11-23)

- **Code:** v0.3.4, HEAD `5783ff1`. `scripts/ci.sh` passes: 146 pytest and 16 Node tests [verified]. The committed `inbox.yml` is byte-identical to the generator's output [verified]. The live `pipeline.yml` is the v0.3 version (has the `backtest` task and the 240-day default); the copies in `inbox/needs-manual/` are obsolete [verified].
- **Inbox history [verified]:** applied v0.1, v0.1.1-vercel-fix, v0.2.0, v0.2.1, v0.2.2, v0.2.3, v0.3.2, v0.3.3, v0.3.4. Failed v0.3.0 and v0.3.1 (lesson 1). One duplicate skipped.
- **Picks 2026-11-17 to 2026-11-22 [verified]:** 112 total: NHL 45, NBA 43, NFL 12, UFC 12 (one card on 11-21), MLB 0, DWCS 0. All PASS, all ON_TIME. 0 grades, 0 top picks.
  - 57 picks (11-17 to 11-20, old model, coverage 1.00): PASS because edge was under 2.5%. Edges ranged from -0.83% to +1.54%, median 0.12%.
  - 43 team picks since v0.3.2: PASS because coverage was 0.75 (39) or 0.55 (4); ratings unavailable; model equals market, edge exactly 0.
  - 12 UFC picks: coverage 0.00, no moneyline in the feed.
- **Proven in production [verified]:** ESPN scoreboards, moneylines and injuries for NBA, NHL, NFL; T-30 timing; hash-chain export; daily ledger commits; Vercel serving. **Never observed:** MLB, DWCS, UFC odds, any grade, any PLAY, any top pick, a successful LLM call.
- **Not visible from the sandbox (ask the owner when needed):** the Status panel, whether `backfill` has been run since 11-22, which secrets are set, the cron-job.org schedule, Actions failures, the live site URL.

## 6. Known issues

### P0: blockers

**P0-1. History is not loaded, so no team pick can reach PLAY** [symptom verified, cause unknown]
- Evidence: since v0.3.2 every NBA and NHL pick has coverage 0.75 and the missing input is ratings ("needs 8 stored games per team (home has 5, away has 5)"). NFL teams show 0 to 2 stored games. The counts did not grow after v0.3.4 (which added `min_history`, the threshold that makes the tick load history by itself) was applied at 2026-11-22T17:57Z: the last picks, up to 2026-11-23T01:00Z, still show 5 to 7 (NBA, NHL) and 0 to 2 (NFL). Those are the counts the 7-day schedule refresh alone would store, so no backfill data has landed.
- Why it blocks everything: with ratings missing, coverage tops out at 0.75 (under 0.85) and the model equals the market.
- Hypotheses [inferred], check in this order:
  - H1 Head-of-line blocking: `run_backfill` walks sports in config order, newest chunk first, and retries failed chunks first on every run. If an early chunk keeps timing out (30 s x 2 attempts), the 3-minute per-tick budget is spent there and later sports are never reached.
  - H2 ESPN's date-range scoreboard (`dates=YYYYMMDD-YYYYMMDD&limit=1000`) behaves differently than the parser expects for a 30-day span (cap, partial, HTTP 400). It has never been checked against a real response.
  - H3 `maybe_backfill` is not reached or raises after publishing (that would turn the tick run red but keep the picks).
  - H4 Turso rejects the bulk upsert (60 statements per request).
- Diagnose (owner, phone): site, Status, Data section: read "Finished games stored", "History load" (prints `Problems:` with the error text) and "Rating check". Then Actions, Pipeline, Run workflow, task `backfill`, days `240`; open the run and paste its summary plus any `backfill ... FAILED` lines.
- Fix direction: round-robin the sports so one failure cannot starve the others; remember failed chunks with a retry limit; smaller chunks if ranges misbehave; show per-chunk errors in the Status panel; add a real captured ESPN range response to `fixtures/` with a test.
- Done when: Status shows finished games at or above `min_history` for NBA, NHL and NFL, and the following day's team picks show coverage at or above 0.85 in the ledger.

**P0-2. AI text never succeeds** [verified]
- Evidence: all 112 picks have `narrative_source: template`. Gemini attempts began 2026-11-21T17:30Z: 28 picks logged `HTTP 404` (model `gemini-2.5-flash`); v0.3.4 switched the model to the alias `gemini-flash-latest`, the 404s stopped, and the next 15 picks logged `HTTP 503` high demand (11) or a read timeout (4). Zero successes. No other provider appears to be configured.
- Impact: wording only (numbers never come from the LLM). Each failed call can add up to 40 s to a tick.
- Fix direction: one retry with short backoff on 503 and timeouts; a shorter timeout (about 15 s); a circuit breaker that skips a failing provider for 30 minutes; a second free provider key (Mistral) so the chain has a fallback. Done when: Status "AI text" shows a provider as Working and most picks are not `template`.

### P1: correctness and risk

**P1-3. UFC and DWCS can never PLAY** [verified]
- The one UFC card seen (2026-11-21, 12 bouts) posted with coverage 0.00: "no moneyline in the feed for this game". Even with odds, bout coverage tops out at 0.35. No DWCS card has appeared. `ODDS_API_KEY` is probably unset [inferred], so the fallback never ran. See R2.x. Owner decision pending: keep showing empty PASS rows for bouts or hide bouts until real analysis exists.

**P1-4. Nothing involving a PLAY has run on live data** [verified]
- Grading, records, top picks, units, closing-line value and the Plays group are covered by unit tests and the demo only (0 grade lines exist). Expect surprises on the first real PLAY: watch the next two `grade` runs and the record cards closely.

**P1-5. The model has no real edge source** [verified numbers, inferred conclusion]
- v0.3.x blends only 25% of a results-only Elo rating toward a market that already knows goalies, lineups and news. Under the old model, 57 full-coverage picks never reached the 2.5% edge. Even with history loaded, PLAYs will be rare to nonexistent. That is by design, but it does not meet the owner's goal of accurate, highlighted picks. See R0.3 and Phase 1.

**P1-6. Stale data can look fresh** [inferred]
- `facts.build_packet` stamps `fetched_at` with the current time for market and injuries, but the values can be older: the injuries snapshot is only replaced when the feed returns data (a failed or empty fetch keeps the old list), and odds persist via `COALESCE(excluded.odds_json, games.odds_json)`. A pick can be priced on old odds or injuries while claiming full coverage. Fix: store each input's true timestamp, set max ages (for example odds under 15 minutes, injuries under 6 hours at publish), and treat older data as unavailable.

**P1-7. Overlapping writers can race** [inferred, never observed]
- The GitHub-cron tick and an external-timer tick fall in different concurrency groups, so two ticks can run at once. `ledger.insert_pick` reads the last hash and then inserts without a transaction, so two simultaneous picks for different games could fork the chain. Two grade runs could trip the `grades_final_is_final` trigger and fail the run. Offline check on 2026-11-23: no fork in 112 picks. Fix: one shared concurrency group for all database-writing tasks and/or an atomic insert.

### P2: backlog

- P2-1 `package.json` says 0.1.0 while the code is 0.3.4; README says "v0.3". Keep version strings in one place.
- P2-2 `docs/DATA_SOURCES.md` still says every feed is unverified. ESPN scoreboards, moneylines and injuries for NBA, NHL, NFL are proven in production; UFC odds and DWCS are not.
- P2-3 `fixtures/` are synthetic ("Demo Fight Night"). Add sanitized real samples from the `audit-samples` artifact.
- P2-4 `inbox/failed/*.zip` (v0.3.0, v0.3.1) and `inbox/needs-manual/*` (v0.1 to v0.2.3 `pipeline.yml` copies) are obsolete. `inbox/` is outside the zip allowlist, so delete them by hand in the GitHub web UI.
- P2-5 Table `inbox_log` exists but no code uses it.
- P2-6 No schema-migration mechanism: `CREATE TABLE IF NOT EXISTS` never alters an existing table and SQLite has no `ADD COLUMN IF NOT EXISTS`. Adding a column needs a guarded migration first.
- P2-7 The site shows "posts at T-90" for bouts but the config posts at T-95.
- P2-8 A tick that runs a 3-minute backfill plus slow LLM calls can delay the next tick (same concurrency group) [inferred].
- P2-9 ESPN is unofficial and may change or block, with no second source for scores. Turso free-tier limits are not monitored beyond the Status panel.
- P2-10 `scripts/build_inbox_yml.py` ignores its arguments and always overwrites `.github/workflows/inbox.yml`, even with `--help`.

## 7. Roadmap

Order is a proposal unless marked [owner]; the owner decides priorities. Each item has a "done when".

### Phase 0: unblock the first real PLAY
- **R0.1 Get history loading and prove it.** Diagnose per P0-1, fix `run_backfill`, run it, confirm in Status. Done when: finished games stored are at or above `min_history` (NBA 150, NHL 150, NFL 100) and ledger picks show coverage at or above 0.85.
- **R0.2 Show backfill failures on-screen.** Status "History load" lists the per-sport, per-chunk error text; the Actions summary prints it too.
- **R0.3 Shadow-grade every PASS lean.** Store the lean side's would-be result in a separate table that never touches the official W-L-V, so model skill (accuracy, log loss vs market, closing-line value) can be measured without waiting for PLAYs. Done when: Status shows these over at least a few hundred games.
- **R0.4 Fix or replace Gemini** (P0-2) and add a second free provider.

### Phase 1: make picks meaningful [owner: "extremely accurate, reflecting actual truth"]
- R1.1 Freshness guards (P1-6) and one-writer concurrency (P1-7).
- R1.2 Real predictive inputs, each a new packet input with its own coverage weight and an honest "unavailable" path: NHL starting goalies (NHL web API), MLB probable pitchers (MLB Stats API, season returns around late March 2027), NFL quarterback status and weather (nflverse, NWS or Open-Meteo), NBA late scratches and rotation, confirmed lineups.
- R1.3 Travel and rest distance, head-to-head history ("past faceoffs") and streaks from stored games.
- R1.4 Injury impact by player role or value, not just names (needs a data source; ESPN's feed has none).
- R1.5 Validate before trusting: calibration and closing-line value over hundreds of graded plays; only then retune `anchor_shrink`, thresholds and Elo parameters, and record the evidence in `docs/METHODOLOGY.md`.
- R1.6 Spread and total picks (grading already supports them; needs line capture and a model).

### Phase 2: MMA [owner: UFC and DWCS in scope]
- R2.1 Odds for bouts: check what ESPN returns for UFC in the `audit` artifact; otherwise set `ODDS_API_KEY` (`mma_mixed_martial_arts` is already mapped).
- R2.2 A fighter data source and a bout model (UFCStats: read its terms first). Confirm DWCS cards are found by event name.
- R2.3 Until then, decide whether bouts should be shown at all.

### Phase 3: product and hygiene
- R3.1 Top-picks section pinned first, record history view, per-sport windows.
- R3.2 Failure alerts beyond the site banner (for example an issue opened when the last tick is over 60 minutes old).
- R3.3 Real captured fixtures and parser tests; clear the P2 backlog; schema migrations.
- R3.4 Season handling: MLB returns around late March 2027, NFL ends in February.

## 8. Decisions and who made them

- [owner] Public repo, $0, no click-to-run, phone-only workflow, zip uploads applied by an Action, Vercel and a free database floated, analyst logic = no-vig edge with PASS when there is no edge, no Groq.
- Chosen in the build: Vercel + Turso + GitHub Actions; Turso over plain HTTPS so Actions and Vercel need no extra packages.
- Picks are insert-only rows with a SHA-256 hash chain, exported daily to git. **The ledger format is frozen:** do not change `HASHED_COLUMNS`, `canonical` or `_norm` in `src/picks/ledger.py`; that would break `verify` for every existing row.
- A locked pick is never edited. If one is wrong, leave it and say so in the changelog; there is no override path by design.
- Numbers come from code only; an LLM may reword the template and the validator gates it.
- Moneyline picks only. PASS rows are stored (they show the analysis) but never count in a record.
- Nothing is posted after the scheduled start; such games are flagged missed and excluded.
- Day boundaries and "today" use America/New_York.
- Workflow files change only by manual paste unless `INBOX_PAT` is set.

## 9. Lessons learned (do not repeat)

1. **Tests must never read real repo data.** v0.3.0 and v0.3.1 failed the inbox tests because `test_cli_commands_against_sqlite` ran `verify` against the real `data/ledger/` (the build sandbox had none, so it passed there). Fixed in v0.3.2 with `PICKS_LEDGER_DIR` and temp dirs. Any test touching `data/`, `inbox/` or a database path must use `tmp_path`.
2. **Test in a copy of the real repo.** `make_zip.py` excludes `data/` and `inbox/`, so a sandbox build is not the real tree. Clone the repo and dry-run the zip (section 10.1) before handing it over.
3. **One path outside the allowlist rejects the whole zip.** For example a root `HANDOFF.md`; that is why this file lives in `docs/`. The same applies to anything that looks like a secret.
4. **Parsers written without live data are unproven.** `docs/DATA_SOURCES.md` was written when the build sandbox had no internet. Use the `audit` task and the committed ledger as ground truth, not fixtures.
5. **A threshold or weight change can silently remove every PLAY.** v0.3.2 added the ratings input (weight 0.25) and raised the coverage bar from 0.80 to 0.85; with no history loaded, coverage fell from 1.00 to 0.75. Before changing `coverage_weights`, `play_min_coverage` or an input requirement, check what production data can actually supply.
6. **GitHub's own cron is unreliable;** the external timer is required (`docs/RELIABLE_CLOCK.md`). It works: since v0.3.2, 43 of 43 team picks posted within 0.5 minutes of T-30.
7. **Never run `scripts/build_inbox_yml.py` casually, not even with `--help`:** it overwrites `inbox.yml`. Restore with `git checkout -- .github/workflows/inbox.yml` if that happens by accident.
8. **The owner cannot open a console:** every failure needs on-screen text (Status panel, Inbox log, run summary).

## 10. Recipes

### 10.1 Ship a change (the only normal path)
1. Clone the real repo and edit there, never in a stale copy.
2. Change code and tests together. Bump `__version__` in `src/picks/__init__.py` and `SITE_VERSION` in `site/app.js` (equal). Update this file (sections 5 to 7 and 12).
3. `bash scripts/ci.sh` must print `ci ok` in the clone (pytest, `node --check` on the site and API JS, Node API tests).
4. Build a zip of only the changed files plus `inbox.manifest.json` (`{"version": "...", "notes": "...", "delete": [], "move": {}}`), using only allowlisted paths (section 4.11). Never include `data/`, `inbox/` or secrets. `python3 scripts/make_zip.py <name>.zip "<notes>"` zips the whole project; hand-built partial zips are fine.
5. Dry-run on a fresh clone: `python3 scripts/apply_inbox.py --repo <fresh clone> --no-git --zip <zip>`. It applies the zip and runs the same tests the workflow will. Expect `applied`.
6. Give the owner phone steps: github.com, the repo, Add file, Upload files, choose the zip, Commit directly to `main`. The `Inbox` workflow runs and reports in the `Inbox log` issue; Vercel redeploys if `site/`, `api/`, `vercel.json` or `package.json` changed.
7. After the deploy, the Status panel's "Website version" and the updater version must match.

### 10.2 Change a workflow file
`.github/workflows/*.yml` arrives in `inbox/needs-manual/` unless `INBOX_PAT` is set. Manual paste: GitHub, open the file, pencil icon, paste, Commit. Or add `INBOX_PAT` (fine-grained token, this repo only, Contents and Workflows read/write) as an Actions secret so zips can update workflows. After editing `scripts/apply_inbox.py` or `scripts/inbox.yml.tmpl`, regenerate `inbox.yml` with `python3 scripts/build_inbox_yml.py` (no arguments) and install it the same manual way; the workflow prefers the repo's `scripts/apply_inbox.py` when it compiles, else the embedded copy.

### 10.3 A zip failed
Main is untouched and the zip is in `inbox/failed/`. Read the newest comment on the `Inbox log` issue (it prints the last test lines), or Actions, Inbox, the failed run, step "Apply zips". Reproduce with the dry-run in 10.1 on a clone of the real repo, fix, and upload a new zip.

### 10.4 Roll back
Actions, Inbox, Run workflow, paste the commit SHA into `revert_sha`.

### 10.5 Run a task or replay a moment
Actions, Pipeline, Run workflow, choose the task (`tick`, `schedule`, `grade`, `ledger`, `verify`, `backfill`, `backtest`, `audit`, `setup-check`, `demo`). `days` applies to `backfill`. `simulate_now` (UTC, for example `2026-11-15T23:55:00Z`) pretends it is that time.

### 10.6 Add a sport or data source
Add it to `config.yaml` (`sports`, `model.elo`, coverage), `SPORT_ORDER` in `pipeline.py` and `SPORTS` in `site/app.js`; add a parser test built from a real captured sample; run the `audit` task; record the result in `docs/DATA_SOURCES.md`.

### 10.7 Read production state from a phone
- Site, Status panel (groups: Updates, Odds, AI text, Data, System, Website).
- `<site>/api/health` (deployed commit, database ok, snapshot age) and `<site>/api/latest`.
- Actions, Pipeline, newest run, Summary (JSON result of the task).
- Issues, `Inbox log`.
- `data/ledger/*.ndjson` in the repo (picks and grades, one day behind).
- Settings, Secrets and variables, Actions (names only); the `setup-check` task lists what is missing.

### 10.8 Keep this file true
Never paste secrets. Do not copy this file into Claude Project knowledge: a copy goes stale, so always clone the repo and read `docs/HANDOFF.md` from it.

## 11. Open questions for the owner

1. What is the live site URL? (Write it into the table at the top.)
2. Status panel, Data section: what do "Finished games stored", "History load" and "Rating check" say? Has `backfill` been run since 11-22?
3. Which secrets are set? (`setup-check` shows it.) Is `INBOX_PAT` set? Is `ODDS_API_KEY` set?
4. How is the cron-job.org timer configured (interval, still active)?
5. UFC and DWCS: keep showing empty PASS rows, or hide bouts until real analysis exists?
6. Which phase should come first after R0.1? (Proposed: R0.3 shadow grading, then R1.2 goalies.)

## 12. Keeping this file alive, and the changelog

At the end of every session that changes anything: bump "Doc verified" (date and commit), refresh section 5, add or close issues in section 6, reorder the roadmap, and add a changelog row. Delete resolved issues from section 6 and record them below instead. Keep it short and true.

| Date | Version | What changed |
|---|---|---|
| 2026-11-15 | none | `inbox.yml` created by hand. |
| 2026-11-16 | v0.1, v0.1.1 | First full build (64 files): inbox, store, hash-chained ledger, timing, grading, records, validator, ESPN parsers, API, site, docs. v0.1.1 fixed the Vercel ignored-build step. |
| 2026-11-17 | v0.2.0 to v0.2.3 | Date picker and `/api/day`, Odds API fallback, day-by-day `backfill` task, external-timer doc, tick housekeeping (schedule every 3 h, grade every 40 min). |
| 2026-11-19 to 11-20 | v0.3.0, v0.3.1 | FAILED the inbox tests (lesson 1). Moved to `inbox/failed/`. |
| 2026-11-21 | v0.3.2 | Elo ratings from stored scores (`ratings.py`), value-side edge, sport-specific text, T-30 posting (was T-35), 240-day range backfill, rating check, thresholds: coverage 0.85 (was 0.80), top coverage 0.95 (was 0.90), `anchor_shrink` 0.25 (was 0.5); test isolation fix; Status panel. |
| 2026-11-21 | v0.3.3 | `vercel.json` ignored-build-step tweak. |
| 2026-11-22 | v0.3.4 | Gemini model alias, LLM error text, history auto-load when thin (`min_history`), `lean_side`, Status additions. |
| 2026-11-23 | docs only | Added this handoff file and a pointer in `README.md`. |
