# Data sources

**Status: unverified until you run Pipeline, task `audit`.** I could not reach these services from where this was built, so the parsers were written from documented shapes and tested on synthetic fixtures only. The audit runs from GitHub’s servers, saves real samples, and tells you which feeds work.

| Source | Used for | Notes |
|---|---|---|
| ESPN public JSON (`site.api.espn.com`) | Schedules, scores, odds, injuries, UFC events | Unofficial and may change or block. Used in v0. DWCS slug is unknown; the audit tries `dwcs`, `dana-white-contender-series`, `contender-series`. |
| MLB Stats API | Probable pitchers, lineups (next step) | Probed by the audit, not used yet. |
| NHL web API | Goalies, schedule (next step) | Probed, not used yet. |
| NBA cdn.nba.com | Live JSON (next step) | `stats.nba.com` often blocks cloud IPs; do not depend on it. |
| nflverse open data | NFL EPA, play by play (next step) | Probed, not used yet. |
| UFCStats | Fighter statistics (next step) | Check its terms before scraping. |
| NWS API, Open-Meteo | Weather (next step) | Free, no key. |
| The Odds API | Cross-checking odds | Free plan is 500 credits a month, so it is not called in v0. |

## Free LLM providers (optional; text only, numbers never come from the model)
Order tried: Gemini API, Mistral, Cloudflare Workers AI, OpenRouter free models, then the built-in template. Limits change often and are not always published, so each has a daily call budget in `config.yaml` and the pipeline stops at 85% of it. Only public game data is ever sent. **Groq is not used. GitHub Models is not used (retired July 30, 2026).**

Every LLM sentence must pass the validator: each number and name has to appear in the facts packet and nothing may be claimed about an unavailable input. Otherwise the template text is shown.
