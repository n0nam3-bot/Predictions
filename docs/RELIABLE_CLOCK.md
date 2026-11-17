# A reliable clock (free, 5 minutes on a phone)

GitHub's own schedule is best-effort. On a new or quiet repo it can skip runs for hours, and picks are only posted when a tick runs inside the window before a game. A free outside timer fixes that. It just pokes GitHub every 5 minutes; everything else stays the same.

## 1. A token that may only start workflows
https://github.com/settings/personal-access-tokens/new
- Name: `picks-timer`. Expiration: the longest offered.
- Repository access: **Only select repositories**, choose your repo (`n0nam3-bot/Predictions`).
- Permissions, Repository: **Actions: Read and write** (Metadata read is added for you). Nothing else.
- Generate and copy the token. (Do not reuse `INBOX_PAT`; this one should be able to do less.)

## 2. The timer (cron-job.org, free)
Create an account at https://cron-job.org, then **Create cronjob**:
- Title: `picks tick`
- URL: `https://api.github.com/repos/n0nam3-bot/Predictions/actions/workflows/pipeline.yml/dispatches`
- Schedule: every 5 minutes
- Under Advanced:
  - Request method: **POST**
  - Headers (add each):
    - `Authorization` = `Bearer YOUR_TOKEN`
    - `Accept` = `application/vnd.github+json`
    - `X-GitHub-Api-Version` = `2022-11-28`
    - `Content-Type` = `application/json`
    - `User-Agent` = `cron-job.org`
  - Request body: `{"ref":"main","inputs":{"task":"tick"}}`
- Save. A healthy call returns **204**. Use "Test run" once to see it.

The tick now also refreshes the schedule every 3 hours and grades finished games every 40 minutes by itself, so this one timer is enough.

## 3. Check it
Actions tab, Pipeline: new runs with the event `workflow_dispatch` appear every 5 minutes. The site's Status panel shows Last tick under 10 minutes. Setup-check also reports the age of the last tick.

If cron-job.org shows 401 or 403 the token is wrong or lacks Actions write; 404 means the repo or workflow name in the URL is wrong; 422 means the body is not valid JSON.
