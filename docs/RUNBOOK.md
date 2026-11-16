# Runbook

| Symptom | Likely cause | Fix |
|---|---|---|
| Site says “nothing published yet” | Database empty | Pipeline, run `schedule`, then `tick`. Check `setup-check`. |
| Site shows “Data may be delayed” | GitHub skipped scheduled runs | Run `tick` by hand. Optional: a free pinger such as cron-job.org can call the workflow-dispatch API every 5 minutes with a fine-grained token limited to this repo. |
| A game has no pick and is marked missed | The tick that would have posted it ran after the start | By design nothing is posted after the start. Nothing to fix. |
| Status panel shows a feed failing | ESPN changed or blocked | Run `audit`, open the `audit-samples` artifact, fix the parser, upload a zip. |
| Ledger check shows problems | Database and git export disagree | Do not edit anything. Run `verify`; compare the named line with `data/ledger/`. |
| Inbox log says tests failed | The zip broke something | Main is untouched and the zip moved to `inbox/failed/`. Fix and upload a new zip. |
| Deploy not confirmed | Vercel blocked the commit author, or `SITE_URL` is wrong | Check the Vercel project uses your GitHub login; check the variable. |
| Turso errors | Token expired or revoked | Create new tokens, update `TURSO_WRITE_TOKEN` (GitHub) and `TURSO_READ_TOKEN` (Vercel). |
| Scheduled runs stopped | GitHub pauses schedules on repos with no activity for 60 days | Any commit or a manual run restarts them. Ledger commits normally prevent this. |

Rollback: Actions, **Inbox**, Run workflow, put the commit SHA in `revert_sha`.
Simulate a moment in time: Actions, **Pipeline**, Run workflow, `simulate_now` (UTC), for example to test a publish without waiting for a game.
