import json
from datetime import timedelta

from picks import config, llm, narrative, pipeline, status
from test_engine import add_game, mkstore, packet
from test_pipeline import T0, Src, game

CFG = config.load()


def items(out):
    return {i["name"]: i for i in out["items"]}


def test_nothing_configured_says_so_plainly():
    s = mkstore()
    out = status.compute(s, CFG, T0, {})
    d = items(out)
    assert d["Updater"]["state"] == "bad" and "never run" in d["Updater"]["detail"]
    assert d["The Odds API"]["state"] == "off" and "ODDS_API_KEY" in d["The Odds API"]["detail"]
    for label in ("Gemini", "Mistral", "Cloudflare Workers AI", "OpenRouter"):
        assert d[label]["state"] == "off"
    assert d["Gemini"]["detail"].endswith("GEMINI_API_KEY.")
    assert d["Analysis text comes from"]["detail"].startswith("The built-in template")
    assert out["version"] and d["Pipeline version"]["detail"] == out["version"]


def test_ai_provider_states_follow_real_calls():
    s = mkstore()
    env = {"GEMINI_API_KEY": "k", "MISTRAL_API_KEY": "k", "CLOUDFLARE_AI": "no-colon", "OPENROUTER_API_KEY": "k"}
    assert items(status.compute(s, CFG, T0, env))["Gemini"]["state"] == "idle"
    assert items(status.compute(s, CFG, T0, env))["Cloudflare Workers AI"]["state"] == "bad"

    def fn(ok):
        def call(key, model, system, user):
            if not ok:
                raise llm.LLMUnavailable("HTTP 404")
            return "{}"
        return call

    chain = llm.Chain(s, CFG, T0, env, [("gemini", "GEMINI_API_KEY", fn(False)), ("mistral", "MISTRAL_API_KEY", fn(True))])
    assert chain.generate("s", "u")[1] == "mistral"
    d = items(status.compute(s, CFG, T0 + timedelta(minutes=1), env))
    assert d["Gemini"]["state"] == "bad" and "404" in d["Gemini"]["detail"] and "model name" in d["Gemini"]["detail"]
    assert d["Mistral"]["state"] == "ok" and "1 of 300 calls today" in d["Mistral"]["detail"]
    assert d["Analysis text comes from"]["detail"] == "Mistral"


def test_odds_states():
    s = mkstore()
    start = T0 + timedelta(hours=2)
    pipeline.upsert_game(s, game("a", start), T0)
    pipeline.upsert_game(s, game("b", start, odds=None), T0)
    d = items(status.compute(s, CFG, T0, {}))
    assert d["ESPN odds"]["state"] == "warn" and "1 of 2" in d["ESPN odds"]["detail"]
    d = items(status.compute(s, CFG, T0, {"ODDS_API_KEY": "k"}))
    assert d["The Odds API"]["state"] == "idle"
    s.x("INSERT INTO quota (key, used, cap, updated_utc) VALUES ('oddsapi:2026-11', 12, 500, 't')")
    assert "12 of 500" in items(status.compute(s, CFG, T0, {"ODDS_API_KEY": "k"}))["The Odds API"]["detail"]
    pipeline._note_source(s, "odds:nba", False, "The Odds API HTTP 401", T0)
    d = items(status.compute(s, CFG, T0, {"ODDS_API_KEY": "k"}))
    assert d["The Odds API"]["state"] == "bad" and "401" in d["The Odds API"]["detail"]


def test_status_reaches_the_public_health_snapshot(tmp_path):
    from picks import cli
    env = {"PICKS_DB": str(tmp_path / "p.db"), "GEMINI_API_KEY": "k"}
    start = T0 + timedelta(hours=2)
    assert cli.main(["tick", "--now", (start - timedelta(minutes=30)).isoformat()], source=Src([game("g1", start)]), env=env) == 0
    from picks import store
    health = pipeline.get_snapshot(store.connect(env), "latest")["health"]
    names = {i["name"]: i for i in health["integrations"]["items"]}
    assert names["Gemini"]["state"] in ("idle", "bad", "ok") and names["Updater"]["state"] == "ok"
    assert "secret" not in json.dumps(health["integrations"]).lower().replace("github secret", "")        # never a key value


def test_signals_are_short_and_grounded():
    p = packet()
    sig = narrative.signals(p, None)
    assert "Home rated higher by 60" in sig
    assert "Away on a back-to-back" in sig and len(sig) <= 3 and not any("Harbor" in x for x in sig)
    p["inputs"]["ratings"]["value"] = None
    p["inputs"]["schedule_rest"]["value"] = None
    p["inputs"]["recent_form"]["value"] = None
    p["inputs"]["injuries"]["value"] = None
    assert narrative.signals(p, None) == []


def test_status_ignores_feeds_we_no_longer_fetch_and_reports_history_load():
    s = mkstore()
    pipeline._note_source(s, "scoreboard:dwcs", False, "ESPN request failed: HTTP 400", T0)
    pipeline._note_source(s, "scoreboard:nba", True, "2026-11-20", T0)
    d = items(status.compute(s, CFG, T0, {}))
    assert d["Game feeds"]["state"] == "ok" and "1 of 1" in d["Game feeds"]["detail"]
    assert d["History load"]["state"] == "idle"
    pipeline._note_source(s, "backfill:nba", False, "ESPN request failed: HTTP 503", T0)
    d = items(status.compute(s, CFG, T0, {}))
    assert d["History load"]["state"] == "bad" and "NBA" in d["History load"]["detail"]
    assert d["Finished games stored"]["state"] in ("idle", "warn")


def test_gemini_error_text_comes_through():
    import requests

    class R:
        status_code = 404
        text = ""

        def json(self):
            return {"error": {"message": "models/gemini-2.5-flash is not found for API version v1beta"}}

    orig = requests.post
    requests.post = lambda *a, **k: R()
    try:
        try:
            llm.call_gemini("k", "gemini-2.5-flash", "s", "u")
        except llm.LLMUnavailable as exc:
            assert "404" in str(exc) and "is not found" in str(exc)
        else:
            raise AssertionError("should fail")
    finally:
        requests.post = orig
    assert CFG["llm"]["gemini"]["model"] == "gemini-flash-latest"
