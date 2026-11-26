# Data sources

**Status (2026-11-23).** Proven in production: ESPN scoreboards, one request per day, with moneylines and final scores for NBA, NHL, NFL and MLB; ESPN injuries for NBA, NHL and NFL; ESPN date ranges for MLB. **ESPN answers a date-range scoreboard request with HTTP 400 for NFL, NBA and NHL** (seen on the Status panel; MLB’s works), so history for those leagues is loaded one day at a time. Not yet seen live: UFC odds and Contender Series cards. The parsers were first written from documented shapes and tested on synthetic fixtures, so the `audit` task (Pipeline, task `audit`) is still the way to probe every source from GitHub’s servers and save real samples.

| Source | Used for | Notes |
|---|---|---|
| ESPN public JSON (`site.api.espn.com`) | Schedules, scores, odds, injuries, UFC events | Unofficial and may change or block. Preseason (season type 1) and off-season (type 4) events are ignored: starters rest, so their scores would distort the ratings. Used in v0. ESPN has no valid `dwcs` league address (it returns HTTP 400), so Contender Series bouts are picked out of the UFC feed by event name. If ESPN does not list them there, DWCS stays empty; the audit shows how many it found. |
| MLB Stats API | Probable pitchers, lineups (next step) | Probed by the audit, not used yet. |
| NHL web API | Goalies, schedule (next step) | Probed, not used yet. |
| NBA cdn.nba.com | Live JSON (next step) | `stats.nba.com` often blocks cloud IPs; do not depend on it. |
| nflverse open data | NFL EPA, play by play (next step) | Probed, not used yet. |
| UFCStats | Fighter statistics (next step) | Check its terms before scraping. |
| NWS API, Open-Meteo | Weather (next step) | Free, no key. |
| The Odds API | Fallback moneylines | Used only when ESPN has none for a game about to be posted. One credit per sport per call, at most once per sport every 20 minutes, stops at 85% of 500 a month. Needs the `ODDS_API_KEY` secret. |

## Free LLM providers (optional; text only, numbers never come from the model)
Order tried: Gemini API, Mistral, Cloudflare Workers AI, OpenRouter free models, then the built-in template. Model names and free limits change without notice (Google retired `gemini-2.5-flash`; the `gemini-flash-latest` alias is often busy, HTTP 503, or out of quota, HTTP 429), so a provider can list several models in `config.yaml` and the updater switches by itself: a model that fails is skipped for a while (1 minute, doubling on repeated failures, a day if it no longer exists), remembered between runs, and the next model or provider is tried at once. Gemini's list is also read from Google's own model list, so a renamed or new Flash model is picked up without editing anything. One pick waits at most 45 seconds for AI text. Each provider has a daily budget of successful calls in `config.yaml`; the pipeline stops at 85% of it. Only public game data is ever sent. **Groq is not used. GitHub Models is not used (retired July 30, 2026).**

Every LLM sentence must pass the validator: each number and name has to appear in the facts packet and nothing may be claimed about an unavailable input. Otherwise the template text is shown.
