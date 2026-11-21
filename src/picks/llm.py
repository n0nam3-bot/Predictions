"""Free-tier LLM chain: Gemini, Mistral, Cloudflare Workers AI, OpenRouter. Never Groq.
Model names and limits change; they live in config.yaml and are checked by the source audit."""
import json
import os

import requests

from .timing import iso


class LLMUnavailable(RuntimeError):
    pass


def _post(url, headers, body, timeout=40):
    r = requests.post(url, headers=headers, json=body, timeout=timeout)
    if r.status_code >= 400:
        raise LLMUnavailable(f"HTTP {r.status_code}")
    return r.json()


def call_gemini(key, model, system, user):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = _post(url, {"x-goog-api-key": key}, {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}})
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _openai_compat(url, key, model, system, user):
    data = _post(url, {"Authorization": f"Bearer {key}"}, {
        "model": model, "temperature": 0.2,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    return data["choices"][0]["message"]["content"]


def call_mistral(key, model, system, user):
    return _openai_compat("https://api.mistral.ai/v1/chat/completions", key, model, system, user)


def call_openrouter(key, model, system, user):
    return _openai_compat("https://openrouter.ai/api/v1/chat/completions", key, model, system, user)


def call_cloudflare(key, model, system, user):
    account, token = key.split(":", 1)               # CLOUDFLARE_AI = "<account id>:<api token>"
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
    data = _post(url, {"Authorization": f"Bearer {token}"},
                 {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    return data["result"]["response"]


PROVIDERS = [("gemini", "GEMINI_API_KEY", call_gemini), ("mistral", "MISTRAL_API_KEY", call_mistral),
             ("cloudflare", "CLOUDFLARE_AI", call_cloudflare), ("openrouter", "OPENROUTER_API_KEY", call_openrouter)]


class Chain:
    """Tries providers in order, tracks a daily call budget per provider in the quota table."""

    def __init__(self, store, cfg, now, env=None, providers=PROVIDERS):
        self.store, self.cfg, self.now = store, cfg.get("llm", {}), now
        self.env = os.environ if env is None else env
        self.providers = providers
        self.day = iso(now)[:10]

    def available(self):
        return [p for p in self.providers if self.env.get(p[1]) and p[0] in self.cfg]

    def _used(self, name):
        row = self.store.q("SELECT used FROM quota WHERE key = ?", (f"llm:{name}:{self.day}",))
        return row[0]["used"] if row else 0

    def _count(self, name, cap):
        self.store.x("INSERT INTO quota (key, used, cap, updated_utc) VALUES (?, 1, ?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET used = used + 1, updated_utc = excluded.updated_utc",
                     (f"llm:{name}:{self.day}", cap, iso(self.now)))

    def _record(self, name, ok, msg=""):
        rows = self.store.q("SELECT json FROM snapshots WHERE key = 'llm_status'")
        cur = json.loads(rows[0]["json"]) if rows else {}
        e = cur.setdefault(name, {})
        if ok:
            e["ok_utc"] = iso(self.now)
        else:
            e["error"], e["error_utc"] = msg[:200], iso(self.now)
        self.store.x("INSERT INTO snapshots (key, json, updated_utc) VALUES ('llm_status', ?, ?) ON CONFLICT(key) DO UPDATE SET "
                     "json = excluded.json, updated_utc = excluded.updated_utc", (json.dumps(cur), iso(self.now)))

    def generate(self, system, user):
        errors = []
        for name, env_key, fn in self.available():
            cap = self.cfg[name]["daily_cap"]
            if self._used(name) >= 0.85 * cap:
                errors.append(f"{name}: over 85% of daily budget")
                continue
            try:
                self._count(name, cap)
                text = fn(self.env[env_key].strip(), self.cfg[name]["model"], system, user)
                self._record(name, True)
                return text, name
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                self._record(name, False, str(exc))
        raise LLMUnavailable("; ".join(errors) or "no provider configured")
