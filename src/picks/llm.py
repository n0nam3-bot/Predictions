"""Free-tier LLM chain: Gemini, Mistral, Cloudflare Workers AI, OpenRouter. Never Groq.

Model names and free limits change without notice: Google retired gemini-2.5-flash (HTTP 404) and the
"latest" alias is often busy (HTTP 503) or out of quota (HTTP 429). So every provider has a list of models and the
chain switches by itself. A model that fails goes on a cooldown that is remembered between runs (snapshot
`llm_cooldown`, doubling on repeated failures), and the next model or provider is tried at once. Gemini's list is
also read from the API (`models.list`), so a renamed or newly released Flash model is picked up without a code
change. One pick never waits longer than `llm.max_seconds`; after that it uses the built-in template."""
import json
import os
import re
import time
from datetime import timedelta

import requests

from .timing import iso, parse_utc


class LLMUnavailable(RuntimeError):
    pass


READ_TIMEOUT = [25]       # seconds one HTTP call may take; the chain lowers it so a pick never outlasts llm.max_seconds


def _post(url, headers, body, timeout=None):
    r = requests.post(url, headers=headers, json=body, timeout=timeout or (10, READ_TIMEOUT[0]))
    if r.status_code >= 400:
        why = ""
        try:
            body = r.json()
            why = (body.get("error") or {}).get("message") or body.get("message") or ""
        except Exception:
            why = (r.text or "")[:100]
        raise LLMUnavailable(f"HTTP {r.status_code}" + (f": {str(why)[:300]}" if why else ""))
    return r.json()


def call_gemini(key, model, system, user):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = _post(url, {"x-goog-api-key": key}, {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}})
    return data["candidates"][0]["content"]["parts"][0]["text"]


SKIP_WORDS = ("image", "tts", "audio", "live", "embedding", "imagen", "veo", "robotics", "computer", "thinking", "exp", "learnlm")


def gemini_candidates(listing):
    """Flash models in a models.list answer that support generateContent, minus image, audio, live and experimental
    variants. Stable before preview, newer before older, full size before Lite."""
    found = []
    for m in listing.get("models", []):
        name = str(m.get("name", "")).removeprefix("models/")
        low = name.lower()
        if "flash" not in low or "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        if any(w in low for w in SKIP_WORDS):
            continue
        found.append(name)

    def rank(name):
        ver = re.search(r"(\d+(?:\.\d+)?)", name)
        return ("preview" in name.lower(), -(float(ver.group(1)) if ver else 0.0), "lite" in name.lower(), name)

    return sorted(set(found), key=rank)


def discover_gemini(key):
    """Names of the Flash models this key can call right now."""
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 1000},
                     headers={"x-goog-api-key": key}, timeout=(10, 15))
    if r.status_code >= 400:
        raise LLMUnavailable(f"HTTP {r.status_code} listing models")
    return gemini_candidates(r.json())


call_gemini.discover = discover_gemini


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


def classify(exc):
    """(kind, base cooldown in seconds) for a failed call. 'auth' stops the whole provider, 'gone' (model no longer
    exists) and 'bad' (request refused) wait long, the rest back off from the base."""
    msg = str(exc)
    low = msg.lower()
    m = re.match(r"HTTP (\d{3})", msg)
    code = int(m.group(1)) if m else 0
    if code == 402 or "need a subscription" in low or "payment required" in low:
        return "auth", 21600                         # the account needs a plan or credit: nothing to retry for hours
    if code in (401, 403) or "api key not valid" in low:
        return "auth", 3600
    if code == 404 or "is not found" in low:
        return "gone", 86400
    if code == 400:
        return "bad", 21600
    if code == 429 or "quota" in low or "rate limit" in low:
        return "quota", 60
    if code >= 500 or "high demand" in low or "overloaded" in low:
        return "overload", 60
    return "timeout", 120                            # read timeouts and connection errors


def retry_after(exc):
    """Seconds Google asks us to wait ("Please retry in 33.5s"), if the message says so."""
    m = re.search(r"retry in ([\d.]+)\s*s", str(exc), re.I)
    return float(m.group(1)) if m else None


class Chain:
    """Tries providers in order and, inside a provider, its models in order. Keeps a daily budget per provider in
    the quota table (successful calls) and a cooldown per model in the `llm_cooldown` snapshot."""

    def __init__(self, store, cfg, now, env=None, providers=PROVIDERS, clock=time.monotonic):
        self.store, self.cfg, self.now = store, cfg.get("llm", {}), now
        self.env = os.environ if env is None else env
        self.providers = providers
        self.day = iso(now)[:10]
        self.clock = clock
        self._cool = None
        self._disc = None          # discovered model lists, read from the database once per run

    def available(self):
        return [p for p in self.providers if self.env.get(p[1]) and p[0] in self.cfg]

    # ---- bookkeeping in the database
    def _snap(self, key, default):
        rows = self.store.q("SELECT json FROM snapshots WHERE key = ?", (key,))
        return json.loads(rows[0]["json"]) if rows else default

    def _put(self, key, value):
        self.store.x("INSERT INTO snapshots (key, json, updated_utc) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                     "json = excluded.json, updated_utc = excluded.updated_utc", (key, json.dumps(value), iso(self.now)))

    def _used(self, name):
        row = self.store.q("SELECT used FROM quota WHERE key = ?", (f"llm:{name}:{self.day}",))
        return row[0]["used"] if row else 0

    def _count(self, name, cap):
        self.store.x("INSERT INTO quota (key, used, cap, updated_utc) VALUES (?, 1, ?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET used = used + 1, updated_utc = excluded.updated_utc",
                     (f"llm:{name}:{self.day}", cap, iso(self.now)))

    def _record(self, name, ok, msg="", model=None):
        cur = self._snap("llm_status", {})
        e = cur.setdefault(name, {})
        if ok:
            e["ok_utc"] = iso(self.now)
            if model:
                e["ok_model"] = model
        else:
            e["error"], e["error_utc"] = msg[:200], iso(self.now)
        self._put("llm_status", cur)

    # ---- cooldowns
    def _cooldowns(self):
        if self._cool is None:
            self._cool = self._snap("llm_cooldown", {})
        return self._cool

    def cooling_until(self, name, model):
        e = self._cooldowns().get(f"{name}/{model}")
        return e["until"] if e and e["until"] > iso(self.now) else None

    def _fail(self, name, model, exc):
        kind, base = classify(exc)
        cool, key = self._cooldowns(), f"{name}/{model}"
        n = cool.get(key, {}).get("n", 0) + 1
        if kind in ("auth", "gone", "bad"):
            secs = base
        else:
            secs = min(max(base * 2 ** (n - 1), (retry_after(exc) or 0) + 2), 21600)
        cool[key] = {"until": iso(parse_utc(self.now) + timedelta(seconds=secs)), "n": n, "why": str(exc)[:80]}
        self._put("llm_cooldown", cool)
        return kind

    def _ok(self, name, model):
        cool = self._cooldowns()
        if cool.pop(f"{name}/{model}", None) is not None:
            self._put("llm_cooldown", cool)

    # ---- which models to try
    def _extra_models(self, name, fn, key):
        """Models the provider's own list says this key can call (Gemini only), cached for 12 hours."""
        disc = getattr(fn, "discover", None)
        if not disc or not self.cfg[name].get("discover"):
            return []
        if self._disc is None:
            self._disc = self._snap("llm_models", {})
        cache = self._disc
        e = cache.get(name) or {}
        if not (e.get("at") and parse_utc(e["at"]) > parse_utc(self.now) - timedelta(hours=12)):
            try:
                e = {"at": iso(self.now), "models": disc(key)[:8]}
            except Exception as exc:                  # keep what we had and look again in an hour
                e = {"at": iso(parse_utc(self.now) - timedelta(hours=11)), "models": e.get("models", []), "error": str(exc)[:100]}
            cache[name] = e
            self._put("llm_models", cache)
        return e.get("models", [])

    def models(self, name, fn, key):
        conf = self.cfg[name]
        out = list(conf.get("models") or ([conf["model"]] if conf.get("model") else []))
        out += [m for m in self._extra_models(name, fn, key) if m not in out]
        return out[: int(conf.get("max_models", 5))]

    def generate(self, system, user):
        errors, started = [], self.clock()
        limit = float(self.cfg.get("max_seconds", 45))
        for name, env_key, fn in self.available():
            cap = self.cfg[name]["daily_cap"]
            if self._used(name) >= 0.85 * cap:
                errors.append(f"{name}: over 85% of daily budget")
                continue
            key, failed = self.env[env_key].strip(), []
            for model in self.models(name, fn, key):
                if self.cooling_until(name, model):
                    continue
                left = limit - (self.clock() - started)
                if left <= 1:
                    errors.append("out of time")
                    raise LLMUnavailable("; ".join(errors)[:260])
                READ_TIMEOUT[0] = max(3, min(25, left))
                try:
                    text = fn(key, model, system, user)
                except Exception as exc:
                    failed.append(f"{model}: {str(exc)[:70]}")
                    if self._fail(name, model, exc) == "auth":
                        break                         # every model of this provider will say the same
                    continue
                finally:
                    READ_TIMEOUT[0] = 25
                self._count(name, cap)
                self._ok(name, model)
                self._record(name, True, model=model)
                return text, name
            if failed:
                self._record(name, False, "; ".join(failed))
                errors.append(f"{name}: " + "; ".join(failed))
            else:
                errors.append(f"{name}: every model is cooling down")
        raise LLMUnavailable("; ".join(errors)[:260] or "no provider configured")
