# Setup from a phone (about 25 minutes, once)

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
7. Repo, Settings, Secrets and variables, Actions, add secrets:
   - `TURSO_URL` = the `libsql://...` URL
   - `TURSO_WRITE_TOKEN` = the full-access token
   - Optional free LLM keys (analysis text falls back to a built-in template without them): `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`, `CLOUDFLARE_AI` (format `ACCOUNT_ID:API_TOKEN`). Groq is deliberately not supported.
8. Actions tab, **Pipeline**, Run workflow, task **setup-check**. The run summary lists anything still missing.

## C. Vercel (free Hobby plan, non-commercial use only)

9. vercel.com, sign in with GitHub, Add New, Project, import the repo. Framework Preset: **Other**. Leave build settings alone (`vercel.json` sets them).
   Environment Variables: `TURSO_URL` and `TURSO_READ_TOKEN` (the read-only token). Deploy.
10. Copy the site address (for example `https://picks-board.vercel.app`). In GitHub: Settings, Secrets and variables, Actions, **Variables** tab, New repository variable `SITE_URL` with that address. Inbox runs will then confirm each deploy.

## D. First run

11. Actions, Pipeline, Run workflow: **schedule** (loads games), then **tick**, then **audit**.
    The audit tests every free data feed from GitHub’s servers and lists what works. Read it before trusting any feed (see `docs/DATA_SOURCES.md`).
12. Open the site. Until real injury data and a validated model exist, most games will correctly show **PASS**. That is the system refusing to guess.

## If something breaks

- **Vercel says the build was canceled by the Ignored Build Step:** you have an older `vercel.json`. Upload `picks-board-v0.1.1-vercel-fix.zip`, then in Vercel open Deployments and Redeploy. From v0.1.1 the first deploy always builds, and later ones are skipped only when nothing under `site/` or `api/` changed since the last good deploy.
- **Site shows old code after a zip:** Vercel Hobby blocks deploys whose commit author is not you. Inbox commits are authored as you, so check that the Vercel account uses the same GitHub login. The Inbox log issue says when a deploy was not confirmed.
- **Nothing publishes:** Actions tab, look at the latest **Pipeline** run summary. See `docs/RUNBOOK.md`.
- **Roll back a bad upload:** Actions, Inbox, Run workflow, paste the commit SHA into `revert_sha`.
