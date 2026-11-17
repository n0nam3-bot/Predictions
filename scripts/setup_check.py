#!/usr/bin/env python3
"""Tell me, in plain words, what is still missing from the setup. Runs in Actions (Pipeline -> setup-check)."""
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from picks import store  # noqa: E402

LLM_KEYS = ["GEMINI_API_KEY", "MISTRAL_API_KEY", "CLOUDFLARE_AI", "OPENROUTER_API_KEY"]
GET_KEY = {"GEMINI_API_KEY": "https://aistudio.google.com/apikey", "MISTRAL_API_KEY": "https://console.mistral.ai/api-keys",
           "OPENROUTER_API_KEY": "https://openrouter.ai/keys", "CLOUDFLARE_AI": "https://dash.cloudflare.com/profile/api-tokens",
           "ODDS_API_KEY": "https://the-odds-api.com/"}


def secrets_url(env):
    return f"https://github.com/{env.get('GITHUB_REPOSITORY', 'OWNER/REPO')}/settings/secrets/actions"


def check(env, http_get=requests.get):
    rows, ok = [], True
    new_secret = secrets_url(env) + "/new"

    def add(label, status, hint=""):
        nonlocal ok
        rows.append((label, status, hint))
        ok = ok and status != "MISSING"

    for k, hint in (("TURSO_URL", f"Turso database URL (libsql://...). [Add the secret]({new_secret}). See docs/SETUP_PHONE.md."),
                    ("TURSO_WRITE_TOKEN", f"Full-access Turso token. [Add the secret]({new_secret}).")):
        add(k, "ok" if env.get(k) else "MISSING", "" if env.get(k) else hint)
    if env.get("TURSO_URL") and env.get("TURSO_WRITE_TOKEN"):
        try:
            st = store.TursoStore(env["TURSO_URL"], env["TURSO_WRITE_TOKEN"])
            store.migrate(st)
            games = st.q("SELECT COUNT(*) AS n FROM games")[0]["n"]
            picks = st.q("SELECT COUNT(*) AS n FROM picks")[0]["n"]
            add("Database reachable, schema applied", "ok", f"{games} games, {picks} picks stored")
        except Exception as exc:
            add("Database reachable, schema applied", "MISSING", f"{exc}. Check the URL and that the token is full access.")
    have = [k for k in LLM_KEYS if env.get(k)]
    add("Free LLM key (optional)", "ok" if have else "optional", ", ".join(have) if have else
        f"None set, so analysis text comes from the built-in template. [Get a Gemini key]({GET_KEY['GEMINI_API_KEY']}), "
        f"then [add it as GEMINI_API_KEY]({new_secret}). Groq is not used.")
    add("ODDS_API_KEY (optional)", "ok" if env.get("ODDS_API_KEY") else "optional",
        "Fallback odds, used only when ESPN has no moneyline for a game." if env.get("ODDS_API_KEY") else
        f"Only needed if the audit shows ESPN returns no moneylines. [Get a free key]({GET_KEY['ODDS_API_KEY']}) (500 credits a month), "
        f"then [add it as ODDS_API_KEY]({new_secret}).")
    add("INBOX_PAT (optional)", "ok" if env.get("INBOX_PAT_SET") == "true" else "optional",
        "" if env.get("INBOX_PAT_SET") == "true" else "Without it, zips cannot update .github/workflows files; they are saved for a manual paste.")
    site = (env.get("SITE_URL") or "").rstrip("/")
    if not site:
        add("SITE_URL variable (optional)", "optional", "Set it to your Vercel URL so inbox runs can confirm a deploy.")
    else:
        try:
            r = http_get(site + "/api/health", timeout=15)
            body = r.json()
            add("Vercel site reachable", "ok" if r.status_code == 200 and body.get("ok") else "MISSING",
                f"commit {(body.get('commit') or 'unknown')[:7]}, database {body.get('db')}. If db is error, check TURSO_READ_TOKEN in Vercel.")
        except Exception as exc:
            add("Vercel site reachable", "MISSING", f"{exc}. Is the project deployed and is SITE_URL correct?")
    return rows, ok


def render(rows, ok, env=None):
    env = env or {}
    lines = ["### Setup check", "", f"Secrets live here: [{secrets_url(env)}]({secrets_url(env)}). Variables (like SITE_URL) are on the Variables tab of the same page.", "",
             "| Item | Status | What to do |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    lines.append("")
    lines.append("Everything required is in place." if ok else "Something required is missing. Fix the rows marked MISSING and run this again.")
    return "\n".join(lines) + "\n"


def main():
    rows, ok = check(os.environ)
    report = render(rows, ok, os.environ)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
