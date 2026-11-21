# Methodology (version 0.3)

This is a transparent rating model, not a proven edge. Read the **Rating check** row on the site’s Status panel for how well it actually predicts winners, and judge the record by closing-line value over hundreds of graded plays.

## Timing
- Team games: the analysis posts at the first tick at or under 30 minutes before the scheduled start. A tick that runs after T-10 counts as `LATE`.
- MMA: the whole card posts about 90 minutes before the first bout (`LATE` after T-60).
- Once a game (or a card’s first bout) has started, nothing is posted. It is flagged missed and excluded from every record.
- GitHub’s own cron skips runs, so use the outside timer in `docs/RELIABLE_CLOCK.md`.

## Inputs (the facts packet)
Every input records its source and fetch time, or the reason it is missing.
- **Market:** the moneyline from ESPN (or the fallback odds source), with our own snapshots for line movement. No-vig probabilities use the proportional method.
- **Ratings:** Elo from final scores stored in the database (`backfill` loads them). Margin of victory counts; each sport has its own K and home advantage in `config.yaml`. A team needs 8 stored games before it is rated.
- **Rest and schedule:** calendar days off since each team’s last game (0 = back-to-back) and games in the last 7 days.
- **Recent form:** the last 5 results with scores and goal or point difference. “Last N” uses the games actually stored.
- **Injuries:** ESPN’s list, filtered to Out, Doubtful, Questionable and Day-To-Day. Long-term injured reserve is counted but not listed. The feed has no player value, so the size of an absence is **not measured**.

## Model
1. Rating probability for the home side from the Elo gap plus home advantage.
2. Small schedule nudges in logit points (`logit_weights`): days-off difference and back-to-backs.
3. Blend with the market: the model takes `anchor_shrink` (25%) of the gap between its rating and the no-vig market. The market already knows goalies, lineups and news; the rating only knows results.
4. Edge for each side = model probability minus no-vig market probability. The side with the larger edge is the candidate.

`python -m picks.cli backtest` (also run by `backfill`) replays every stored game in order, predicting each before learning from it, and reports accuracy, log loss and Brier score against a naive home-win-rate baseline. It checks the rating alone, not profit.

## Decision
PLAY needs all of: coverage at least 85% (so injuries must be present); edge at least 2.5%; edge not above 10% (larger is treated as a probable data error); positive expected value at the quoted price after the vig. Otherwise PASS, with the side it leaned toward and the numbers. Units scale with edge and coverage (1 to 3); confidence is edge and coverage scaled to 1 to 10.

Expect mostly PASS. A rating built from scores will rarely disagree with a market by more than a few points, and it should not.

## What it cannot see yet
Starting goalies (hockey), starting pitchers (baseball), quarterback and weather (football), lineup confirmations, travel distance, officials, player-level impact, and everything about fighters. The text says so for each sport instead of guessing.

## Top picks
A PLAY with edge at least 4% and coverage at least 95% is marked Top Pick when posted, up to five per ET day. The mark is part of the locked pick.

## Grading
Graded at the posted price as W, L or V. Void: spread or total lands on the number; tie or draw on a moneyline; cancelled, no contest, withdrawal; postponed or suspended and not completed within 48 hours. Overtime and shootouts count. Inconsistent results become `PENDING_REVIEW` and are retried. Win % leaves out voids; profit is in units at the posted price. Closing-line value compares the posted price with the last pre-game odds snapshot.

## Records
Graded PLAY picks only: today (New York date of the scheduled start), since launch, per sport, top picks, and the current streak. PASS never counts.

## Integrity
Picks are insert-only in the database as a hash chain, exported daily to `data/ledger/*.ndjson`; `verify` checks the chain and the database against those files.
