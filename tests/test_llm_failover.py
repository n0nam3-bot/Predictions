"""Gemini kept failing in production: HTTP 404 (gemini-2.5-flash was retired), then 503 "high demand" and 429 "quota"
on the "latest" alias. The chain now has several models per provider, switches by itself, remembers which model is
cooling down between runs, discovers the models a key can call, and never makes one pick wait long."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from picks import config, llm, status
from picks.timing import iso
from test_engine import mkstore

CFG = config.load()
T0 = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
ENV = {"GEMINI_API_KEY": "k", "MISTRAL_API_KEY": "k"}
GEM = CFG["llm"]["gemini"]["models"]
MIS = CFG["llm"]["mistral"]["model"]
BUSY = llm.LLMUnavailable("HTTP 503: This model is currently experiencing high demand. Spikes in demand are usually temporary.")


class Script:
    """Provider functions that answer per (provider, model): an exception is raised, anything else is returned."""

    def __init__(self, plan=None, on_call=None):
        self.plan, self.calls, self.on_call = dict(plan or {}), [], on_call

    def fn(self, name):
        def call(key, model, system, user):
            self.calls.append((name, model))
            if self.on_call:
                self.on_call()
            out = self.plan.get((name, model), "{}")
            if isinstance(out, Exception):
                raise out
            return out
        return call

    def providers(self):
        return [("gemini", "GEMINI_API_KEY", self.fn("gemini")), ("mistral", "MISTRAL_API_KEY", self.fn("mistral"))]


def snap(s, key):
    rows = s.q("SELECT json FROM snapshots WHERE key = ?", (key,))
    return json.loads(rows[0]["json"]) if rows else None


def test_the_next_gemini_model_is_tried_when_the_first_fails():
    s, sc = mkstore(), Script({("gemini", GEM[0]): BUSY})
    assert llm.Chain(s, CFG, T0, ENV, sc.providers()).generate("s", "u") == ("{}", "gemini")
    assert sc.calls == [("gemini", GEM[0]), ("gemini", GEM[1])]
    cool = snap(s, "llm_cooldown")
    assert list(cool) == [f"gemini/{GEM[0]}"] and cool[f"gemini/{GEM[0]}"]["n"] == 1
    st = snap(s, "llm_status")["gemini"]
    assert st["ok_model"] == GEM[1] and "error" not in st                       # the provider worked, so no provider-level error


def test_a_cooling_model_is_skipped_by_later_runs_then_retried_with_a_longer_wait():
    s, sc = mkstore(), Script({("gemini", GEM[0]): BUSY})
    llm.Chain(s, CFG, T0, ENV, sc.providers()).generate("s", "u")
    sc.calls.clear()
    llm.Chain(s, CFG, T0 + timedelta(seconds=30), ENV, sc.providers()).generate("s", "u")
    assert sc.calls == [("gemini", GEM[1])]                                     # the first model is still cooling (60 s)
    sc.calls.clear()
    llm.Chain(s, CFG, T0 + timedelta(seconds=90), ENV, sc.providers()).generate("s", "u")
    assert sc.calls[0] == ("gemini", GEM[0])                                    # cooldown over: tried again, fails again
    e = snap(s, "llm_cooldown")[f"gemini/{GEM[0]}"]
    assert e["n"] == 2 and e["until"] == iso(T0 + timedelta(seconds=90 + 120))  # the wait doubled


def test_a_success_clears_the_cooldown():
    s, sc = mkstore(), Script({("gemini", GEM[0]): BUSY})
    llm.Chain(s, CFG, T0, ENV, sc.providers()).generate("s", "u")
    sc.plan.clear()
    sc.calls.clear()
    llm.Chain(s, CFG, T0 + timedelta(minutes=5), ENV, sc.providers()).generate("s", "u")
    assert sc.calls == [("gemini", GEM[0])] and snap(s, "llm_cooldown") == {}


def test_a_retired_model_waits_a_day_and_a_bad_key_stops_the_provider():
    s = mkstore()
    gone = Script({("gemini", GEM[0]): llm.LLMUnavailable("HTTP 404: models/x is not found for API version v1beta")})
    llm.Chain(s, CFG, T0, ENV, gone.providers()).generate("s", "u")
    assert snap(s, "llm_cooldown")[f"gemini/{GEM[0]}"]["until"] == iso(T0 + timedelta(days=1))

    s2 = mkstore()
    bad = Script({("gemini", GEM[0]): llm.LLMUnavailable("HTTP 403: Your API key was reported as leaked")})
    assert llm.Chain(s2, CFG, T0, ENV, bad.providers()).generate("s", "u") == ("{}", "mistral")
    assert bad.calls == [("gemini", GEM[0]), ("mistral", MIS)]                  # the second Gemini model was not wasted on
    assert "403" in snap(s2, "llm_status")["gemini"]["error"]


def test_the_wait_google_asks_for_is_respected():
    s = mkstore()
    sc = Script({("gemini", GEM[0]): llm.LLMUnavailable("HTTP 429: You exceeded your current quota. Please retry in 300.5s.")})
    llm.Chain(s, CFG, T0, ENV, sc.providers()).generate("s", "u")
    until = snap(s, "llm_cooldown")[f"gemini/{GEM[0]}"]["until"]
    assert until == iso(T0 + timedelta(seconds=302.5))


def test_when_every_model_fails_the_error_names_each_and_the_provider_is_marked():
    s = mkstore()
    sc = Script({("gemini", m): BUSY for m in GEM})
    with pytest.raises(llm.LLMUnavailable) as exc:
        llm.Chain(s, CFG, T0, {"GEMINI_API_KEY": "k"}, sc.providers()).generate("s", "u")
    msg = str(exc.value)
    assert all(m in msg for m in GEM) and len(msg) <= 260
    assert "503" in snap(s, "llm_status")["gemini"]["error"]
    # nothing left to try: the next call says so without calling anyone
    sc.calls.clear()
    with pytest.raises(llm.LLMUnavailable, match="cooling down"):
        llm.Chain(s, CFG, T0 + timedelta(seconds=10), {"GEMINI_API_KEY": "k"}, sc.providers()).generate("s", "u")
    assert sc.calls == []


def test_one_pick_never_waits_past_the_time_limit():
    s, t = mkstore(), [0.0]
    sc = Script({("gemini", m): llm.LLMUnavailable("timed out") for m in GEM}, on_call=lambda: t.__setitem__(0, t[0] + 30))
    chain = llm.Chain(s, CFG, T0, ENV, sc.providers(), clock=lambda: t[0])
    with pytest.raises(llm.LLMUnavailable, match="out of time"):
        chain.generate("s", "u")
    assert sc.calls == [("gemini", GEM[0]), ("gemini", GEM[1])]                  # 30 s + 30 s used the 45 s; Mistral was never tried


LISTING = {"models": [
    {"name": "models/gemini-3-flash-preview", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent", "countTokens"]},
    {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-live-2.5-flash", "supportedGenerationMethods": ["bidiGenerateContent"]},
    {"name": "models/gemini-2.5-flash-native-audio", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.0-flash-exp", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3-pro", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gemini-3-flash", "supportedGenerationMethods": ["embedContent"]}]}


def test_discovery_keeps_only_text_flash_models_stable_first():
    assert llm.gemini_candidates(LISTING) == ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview"]


def test_discovered_models_extend_the_list_and_are_cached_for_twelve_hours():
    s, found = mkstore(), {"n": 0}

    def discover(key):
        found["n"] += 1
        return [GEM[0], "gemini-9-flash"]

    def providers(sc):
        fn = sc.fn("gemini")
        fn.discover = discover
        return [("gemini", "GEMINI_API_KEY", fn)]

    sc = Script({("gemini", GEM[0]): BUSY, ("gemini", GEM[1]): BUSY})
    assert llm.Chain(s, CFG, T0, ENV, providers(sc)).generate("s", "u") == ("{}", "gemini")
    assert sc.calls == [("gemini", GEM[0]), ("gemini", GEM[1]), ("gemini", "gemini-9-flash")]      # configured first, discovered after, no duplicates
    assert found["n"] == 1
    llm.Chain(s, CFG, T0 + timedelta(hours=2), ENV, providers(sc)).generate("s", "u")
    assert found["n"] == 1                                                                         # cached
    llm.Chain(s, CFG, T0 + timedelta(hours=13), ENV, providers(sc)).generate("s", "u")
    assert found["n"] == 2                                                                         # refreshed


def test_a_failing_discovery_does_not_break_the_chain_and_is_retried_in_an_hour():
    s, found = mkstore(), {"n": 0}

    def discover(key):
        found["n"] += 1
        raise llm.LLMUnavailable("HTTP 500 listing models")

    sc = Script()
    fn = sc.fn("gemini")
    fn.discover = discover
    prov = [("gemini", "GEMINI_API_KEY", fn)]
    assert llm.Chain(s, CFG, T0, ENV, prov).generate("s", "u") == ("{}", "gemini")
    llm.Chain(s, CFG, T0 + timedelta(minutes=30), ENV, prov).generate("s", "u")
    assert found["n"] == 1
    llm.Chain(s, CFG, T0 + timedelta(minutes=70), ENV, prov).generate("s", "u")
    assert found["n"] == 2


def test_status_names_the_working_model_and_the_ones_cooling_down():
    s, sc = mkstore(), Script({("gemini", GEM[0]): BUSY})
    llm.Chain(s, CFG, T0, ENV, sc.providers()).generate("s", "u")
    d = {i["name"]: i for i in status.compute(s, CFG, T0 + timedelta(seconds=30), ENV)["items"]}      # still inside the 60 s cooldown
    g = d["Gemini"]
    assert g["state"] == "ok" and f"({GEM[1]})" in g["detail"] and f"Cooling down: {GEM[0]} (back in 1 min)" in g["detail"]
    assert d["Analysis text comes from"]["detail"] == "Gemini"
    # all of Gemini failing: the panel says it switches by itself and keeps the 404 hint
    s2 = mkstore()
    dead = Script({("gemini", m): llm.LLMUnavailable("HTTP 404") for m in GEM})
    llm.Chain(s2, CFG, T0, ENV, dead.providers()).generate("s", "u")
    d2 = {i["name"]: i for i in status.compute(s2, CFG, T0 + timedelta(minutes=1), ENV)["items"]}
    assert d2["Gemini"]["state"] == "bad" and "switches models by itself" in d2["Gemini"]["detail"] and "model name" in d2["Gemini"]["detail"]


class Resp:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, ""

    def json(self):
        return self._body


def test_the_model_list_call_sends_the_key_in_a_header_and_reports_http_errors(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers)
        return Resp(200, LISTING)

    monkeypatch.setattr(llm.requests, "get", fake_get)
    assert llm.discover_gemini("secret")[0] == "gemini-2.5-flash"
    assert seen["headers"] == {"x-goog-api-key": "secret"} and seen["url"].endswith("/v1beta/models") and "secret" not in seen["url"]
    monkeypatch.setattr(llm.requests, "get", lambda *a, **k: Resp(403, {}))
    with pytest.raises(llm.LLMUnavailable, match="HTTP 403"):
        llm.discover_gemini("secret")


def test_the_wait_time_survives_in_the_error_message(monkeypatch):
    msg = ("You exceeded your current quota, please check your plan and billing details. For more information on this error, "
           "head to: https://ai.google.dev/gemini-api/docs/rate-limits.\n* Quota exceeded for metric: generate_content_free_tier_requests, "
           "limit: 20, model: gemini-flash-latest\nPlease retry in 33.5s.")
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: Resp(429, {"error": {"message": msg}}))
    with pytest.raises(llm.LLMUnavailable) as exc:
        llm.call_gemini("k", GEM[0], "s", "u")
    assert llm.retry_after(exc.value) == 33.5 and llm.classify(exc.value) == ("quota", 60)


def test_a_subscription_required_error_rests_the_provider_for_hours():
    """Mistral answered HTTP 402 "You need a subscription to access this API" on the owner's Status panel."""
    err = llm.LLMUnavailable("HTTP 402: You need a subscription to access this API.")
    assert llm.classify(err) == ("auth", 21600)
    s = mkstore()
    sc = Script({("mistral", MIS): err})
    with pytest.raises(llm.LLMUnavailable):
        llm.Chain(s, CFG, T0, {"MISTRAL_API_KEY": "k"}, sc.providers()).generate("s", "u")
    assert snap(s, "llm_cooldown")[f"mistral/{MIS}"]["until"] == iso(T0 + timedelta(hours=6))
    sc.calls.clear()
    with pytest.raises(llm.LLMUnavailable, match="cooling down"):
        llm.Chain(s, CFG, T0 + timedelta(hours=1), {"MISTRAL_API_KEY": "k"}, sc.providers()).generate("s", "u")
    assert sc.calls == []
