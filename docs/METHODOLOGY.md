# Methodology (version 0.1)

This build is **plumbing plus an unvalidated baseline**. It has not been backtested. Nothing here claims an edge until the record, closing-line value and calibration say so.

## Timing
- Team games: analysis is posted about 30 minutes before the scheduled start. A game becomes due at T-35; the first tick after that posts it. Posted after T-10 counts as `LATE`.
- MMA: the whole card is posted about 90 minutes before the first bout (due at T-95; `LATE` after T-60).
- Once a game (or a card’s first bout) has started, nothing is posted for it. It is flagged `missed` and excluded from every record.
- GitHub cron can run late or skip runs, so due work is computed from timestamps in the database, not from run counts.

## Inputs (the facts packet)
Market line (ESPN, with our own odds snapshots for movement), rest and schedule and recent form (from games stored in the database), injuries (ESPN, if the feed works). Every input records its source and fetch time, or a reason it is missing. Coverage is the weighted share of inputs present (`coverage_weights` in `config.yaml`).

## Model (v0 baseline)
Start from the no-vig market probability (proportional method). Nudge it in logit space with rest difference, back-to-back flags and recent form (`logit_weights`), shrunk toward the market by `anchor_shrink`. Edge = model win probability minus no-vig market probability for the best side.

Known limits: moneyline only; MMA has no fighter data yet, so bouts are PASS; injuries are shown but not weighted; no backtest; one results source.

## Decision
PLAY needs all of: coverage at least 80%; edge at least 2.5%; edge not above 10% (larger is treated as a probable data error); positive expected value at the quoted price after the vig. Otherwise PASS, with the reason shown. Units scale with edge and coverage (1 to 3). Confidence is edge and coverage scaled to 1 to 10.

With today’s inputs, the baseline cannot reach 80% coverage without injury data, so expect PASS almost everywhere at first. That is intentional.

## Top picks
A PLAY with edge at least 4% and coverage at least 90% is marked Top Pick when it is posted, up to five per ET day. The mark is part of the locked pick, so it never changes afterwards.

## Grading
A pick is graded at the price it was posted. Win, loss, or void:
- Void: spread or total lands exactly on the number; tie or draw on a moneyline; game cancelled, no contest, withdrawal; postponed or suspended and not completed within 48 hours.
- Overtime and shootouts count unless a bet says regulation.
- If a result looks inconsistent (final with no score), the grade is `PENDING_REVIEW` (excluded from totals) and retried.
Win % leaves voids out. Profit is in units at the posted price. Closing-line value compares the posted price with the last odds snapshot before the start.

## Records
Computed from graded PLAY picks only: Today (America/New_York date of the scheduled start), since launch, per sport, Top Picks, a 30-day strip and the current streak. PASS cards never count.

## Integrity
Picks are insert-only in the database and form a hash chain. Once a day the day’s picks and grades are exported to `data/ledger/*.ndjson` in git, and `verify` checks the chain and the database against those files.
