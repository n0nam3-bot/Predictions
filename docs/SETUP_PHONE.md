# Setup from a phone (about 25 minutes, once)

## Keys cheat sheet: what, where to get it, where to paste it

Every secret below goes in **one place**: your repo’s Actions secrets page.
**Add a secret:** https://github.com/n0nam3-bot/Predictions/settings/secrets/actions/new  (all secrets: https://github.com/n0nam3-bot/Predictions/settings/secrets/actions)
**Add a variable (SITE_URL):** https://github.com/n0nam3-bot/Predictions/settings/variables/actions
(If you rename the repo, swap the name in those links.) Name must match exactly; paste only the value, no quotes.

| Secret name | Needed? | Get it here | Notes |
|---|---|---|---|
| `TURSO_URL` | Yes | https://turso.tech (dashboard, your database) | Starts with `libsql://` |
| `TURSO_WRITE_TOKEN` | Yes | Turso dashboard, your database, create a **full-access** token | Also add the read-only one to Vercel (below) |
| `INBOX_PAT` | Recommended | https://github.com/settings/personal-access-tokens/new | Fine-grained token, this repo only, Contents + Workflows read/write |
| `GEMINI_API_KEY` | Optional | https://aistudio.google.com/apikey | Free tier. Nicer analysis text |
| `MISTRAL_API_KEY` | Optional | https://console.mistral.ai/api-keys | Second choice if Gemini is busy |
| `OPENROUTER_API_KEY` | Optional | https://openrouter.ai/keys | Third choice, free models only |
| `CLOUDFLARE_AI` | Optional | https://dash.cloudflare.com/profile/api-tokens | Value is `ACCOUNT_ID:API_TOKEN`. Token needs the Workers AI permission |
| `ODDS_API_KEY` | Only if ESPN has no odds | https://the-odds-api.com/ | Free, 500 credits a month. See step 13 |

The optional keys go in **GitHub only**, not Vercel. Vercel needs just two variables, set at https://vercel.com/dashboard (open the project, Settings, Environment Variables): `TURSO_URL` and `TURSO_READ_TOKEN` (the read-only token).

After adding anything: Actions tab, **Pipeline**, Run workflow, task **setup-check**. Its summary shows what is still missing and links straight to the right page. Provider sites move their pages sometimes; if a link is dead, search the provider name plus “API keys”.

Everything below works in your phone’s browser. After this, every change is a zip upload.

## A. GitHub

1. **Create the repo.** github.com, New repository. Name it anything (for example `picks-board`), set it to **Public**, tick **Add a README**, create.
2. **Let Actions write.** Repo, Settings, Actions, General, Workflow permissions: choose **Read and write permissions**, Save.
3. **Paste the inbox workflow (the one manual file).** Repo, Add file, **Create new file**. In the name box type `.github/workflows/inbox.yml` (typing the slashes makes the folders). Paste the whole contents of the `inbox.yml` file you were given. Commit to `main`.
4. **Recommended: add `INBOX_PAT` so zips can also update workflow files.**
   Profile photo, Settings, Developer settings, Personal access tokens, **Fine-grained tokens**, Generate new token.
   Repository access: **Only select repositories**, pick this repo. Permissions: **Contents: Read and write** and **Workflows: Read and write**. Generate and copy the token.
   Back in the repo: Settings, Secrets and variables, Actions, **New repository secret**, name `INBOX_PAT`, paste the token.
   Skip this and everything still works, except that files under `.github/workflows/` arrive in `inbox/needs-manual/...` and you paste them in by hand like step 3 (only `pipeline.yml` matters).
5. **Upload the project zip.** Repo, Add file, **Upload files**, choose `picks-board-v0.1.zip`, Commit directly to `main`. The repo root is fine.
   Open the **Actions** tab, then **Inbox (apply zip uploads)**. It unzips, checks, runs the tests, commits and reports in an issue called **Inbox log** (your phone gets a notification).
   If you did not add `INBOX_PAT`: open `inbox/needs-manual/picks-board-v0.1/.github/workflows/pipeline.yml`, copy it, and create `.github/workflows/pipeline.yml` the same way as step 3.

## B. Database (Turso, free)

6. turso.tech, sign in with GitHub, **Create database** (any name, region near you). Copy its URL (starts with `libsql://`).
   Create **two tokens** for that database: one **full access** (for GitHub) and one **read-only** (for Vercel). If the dashboard only offers full access, use it for both and be aware that a leak of the Vercel project would then expose write access.
7. Add these as Actions secrets (links in the cheat sheet above):
   - `TURSO_URL` = the `libsql://...` URL
   - `TURSO_WRITE_TOKEN` = the full-access token
   - Optional free LLM keys (analysis text falls back to a built-in template without them): `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`, `CLOUDFLARE_AI` (format `ACCOUNT_ID:API_TOKEN`). Groq is deliberately not supported.
8. Actions tab, **Pipeline**, Run workflow, task **setup-check**. The run summary lists anything still missing.

## C. Vercel (free Hobby plan, non-commercial use only)

9. vercel.com, sign in with GitHub, Add New, Project, import the repo. Framework Preset: **Other**. Leave build settings alone (`vercel.json` sets them).
   Environment Variables: `TURSO_URL` and `TURSO_READ_TOKEN` (the read-only token). Deploy.
10. Copy the site address (for example `https://picks-board.vercel.app`). In GitHub: Settings, Secrets and variables, Actions, **Variables** tab, New repository variable `SITE_URL` with that address. Inbox runs will then confirm each deploy.

## D. First run

11. Actions, Pipeline, Run workflow: **schedule** (loads games), then **backfill** (loads the past 240 days), then **tick**, then **audit**.
    The audit tests every free data feed from GitHub’s servers and lists what works. Read it before trusting any feed (see `docs/DATA_SOURCES.md`).
12. Open the site. Until real injury data and a validated model exist, most games will correctly show **PASS**. That is the system refusing to guess.

## E. Making it analyse real games (what you need)

13. **Odds.** Run the `audit` task and open the **ESPN scoreboard** rows. The Notes column ends with “N with moneyline”. If N is above zero for the sports in season, the odds come free from ESPN and you need nothing else.
    If it is zero, get a free key at the-odds-api.com (no card, 500 credits a month) and add it as the secret `ODDS_API_KEY`. It is used only for games ESPN has no moneyline for, at most once per sport every 20 minutes, and never past 85% of the month.
14. **History.** The updater now loads history by itself, a few minutes per update, until every league has enough (the Status panel shows “History load”). To speed it up, run the `backfill` task (default 240 days). Ratings, rest, recent form and the date picker all read stored games, and a team needs 8 stored games before it is rated. It also runs the **Rating check** shown on the Status panel.
15. **Injuries.** The audit’s **ESPN injuries** rows must say rows greater than zero. If they fail, injuries stay unavailable and every game is a PASS (coverage cannot reach 80%).
16. **Text.** An LLM key is optional. Without one, analysis text comes from the built-in template.
17. **Then wait one slate.** Open the site, pick a past date with the date control, and check games against the real result. Do not trust a PLAY until the record has a few hundred graded plays.

## F. Make the clock reliable (do this)

GitHub's own schedule often skips runs on a new repo, and nothing gets posted when a tick misses its window. Follow `docs/RELIABLE_CLOCK.md` (free, about 5 minutes) to have cron-job.org start the tick every 5 minutes.

## If something breaks

- **An upload “failed” or the site shows the old version:** open the repo’s **Issues** tab, the issue called **Inbox log**. The newest comment says why, and for a failed test it prints the last lines of the test output. You can also open Actions, **Inbox (apply zip uploads)**, the failed run, step **Apply zips**. Paste that text here and it can be fixed. The site’s Status panel shows the **Website version** and the updater’s version side by side: if they differ, one of them has not been upgraded.
- **The `backfill` task was cancelled after 15 minutes:** older versions fetched one day at a time. The current one stops itself after about 10 minutes, remembers what it finished, and says “Run backfill again to continue.” Just run it again.

- **Vercel says the build was canceled by the Ignored Build Step:** you have an older `vercel.json`. Upload `picks-board-v0.1.1-vercel-fix.zip`, then in Vercel open Deployments and Redeploy. From v0.1.1 the first deploy always builds, and later ones are skipped only when nothing under `site/` or `api/` changed since the last good deploy.
- **Site shows old code after a zip:** Vercel Hobby blocks deploys whose commit author is not you. Inbox commits are authored as you, so check that the Vercel account uses the same GitHub login. The Inbox log issue says when a deploy was not confirmed.
- **Nothing publishes:** Actions tab, look at the latest **Pipeline** run summary. See `docs/RUNBOOK.md`.
- **Roll back a bad upload:** Actions, Inbox, Run workflow, paste the commit SHA into `revert_sha`.
