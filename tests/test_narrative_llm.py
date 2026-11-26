import json

import pytest

from picks import config, decide, facts, llm, model, narrative, store, validator
from test_engine import add_game, mkstore, seed_ratings

CFG = config.load()


def build(with_history=True):
    s = mkstore()
    if with_history:
        seed_ratings(s, "Harbor City Anglers", "Lakeview Herons")
    add_game(s, "g1", "Harbor City Anglers", "Lakeview Herons", "2026-11-14T00:00:00Z",
             odds={"home_ml": -110, "away_ml": -110, "book": "Demo Book", "source": "demo"})
    s.x("INSERT INTO snapshots (key, json, updated_utc) VALUES ('injuries:nba', ?, 't')",
        (json.dumps({"Harbor City Anglers": [{"name": "Sam Rook", "status": "Out"}], "Lakeview Herons": []}),))
    g = s.q("SELECT * FROM games WHERE id='g1'")[0]
    p = facts.build_packet(s, g, "2026-11-13T23:30:00Z")
    m = model.project(p, CFG)
    cov = facts.coverage(p, CFG["coverage_weights"])
    d = {**decide.decide(p, m, cov, CFG), "coverage": cov}
    return p, m, d


def test_template_only_uses_packet_facts():
    for hist in (True, False):
        p, m, d = build(hist)
        n = narrative.template(p, m, d)
        assert narrative.validate_all(n, p, m, d) == []
        assert len(n["thesis"]) == 3 and n["headline"].startswith(("Pass", "PLAY"))


def test_template_flags_unavailable_inputs():
    p, m, d = build(False)
    n = narrative.template(p, m, d)
    assert "unavailable" in n["context"] and "unavailable" in n["matchup"]
    assert "goalie" not in (n["risk"] + n["matchup"]).lower()                      # hockey wording never leaks into NBA text


class FakeChain:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def generate(self, system, user):
        self.calls += 1
        return self.replies.pop(0), "fake"


def good_json(n):
    return json.dumps({**{k: n[k] for k in narrative.SECTIONS}, "thesis": n["thesis"]})


def test_llm_text_is_used_when_it_validates():
    p, m, d = build()
    base = narrative.template(p, m, d)
    out, src, problems = narrative.narrate(p, m, d, FakeChain([good_json(base)]))
    assert src == "fake" and problems == []


def test_fabricating_llm_falls_back_to_template():
    p, m, d = build()
    base = narrative.template(p, m, d)
    bad = json.loads(good_json(base))
    bad["context"] = "Harbor City Anglers have won 12 straight under coach Dana Quill."
    chain = FakeChain([json.dumps(bad)] * 3)
    out, src, problems = narrative.narrate(p, m, d, chain)
    assert src == "template" and problems and out["context"] == base["context"] and chain.calls == 3


def test_llm_outage_falls_back_without_raising():
    p, m, d = build()

    class Down:
        def generate(self, *a):
            raise llm.LLMUnavailable("quota")

    out, src, problems = narrative.narrate(p, m, d, Down())
    assert src == "template" and "llm unavailable" in problems[0]


def test_chain_order_budget_and_no_groq(monkeypatch):
    s = mkstore()
    calls = []

    def fake(name):
        def fn(key, model_, system, user):
            calls.append(name)
            if name == "gemini":
                raise llm.LLMUnavailable("HTTP 429")
            return "{}"
        return fn

    providers = [(n, k, fake(n)) for n, k, _ in llm.PROVIDERS]
    env = {"GEMINI_API_KEY": "a", "MISTRAL_API_KEY": "b", "OPENROUTER_API_KEY": "c", "GROQ_API_KEY": "nope"}
    chain = llm.Chain(s, CFG, "2026-11-15T12:00:00Z", env, providers)
    assert [p[0] for p in chain.available()] == ["gemini", "mistral", "openrouter"]
    gem_models = len(CFG["llm"]["gemini"]["models"])
    assert chain.generate("s", "u") == ("{}", "mistral") and calls == ["gemini"] * gem_models + ["mistral"]   # every Gemini model is tried first
    assert "groq" not in {p[0] for p in llm.PROVIDERS} and "groq" not in CFG["llm"]
    s.x("UPDATE quota SET used = 999 WHERE key LIKE 'llm:mistral:%'")
    calls.clear()
    assert chain.generate("s", "u")[1] == "openrouter"
    with pytest.raises(llm.LLMUnavailable):
        llm.Chain(s, CFG, "2026-11-15T12:00:00Z", {}, providers).generate("s", "u")


def test_the_template_passes_the_validator_even_when_no_value_happens_to_be_seven():
    """The text says "Games in the last 7 days". The validator rejects any number that is not in the data, so the 7 must be
    data: before it was, AI text that kept that sentence was rejected unless some score or record happened to contain a 7."""
    from datetime import datetime, timedelta, timezone
    s = mkstore()
    base = datetime(2026, 11, 13, 20, 0, tzinfo=timezone.utc)
    k = 0
    for team, wins in (("Harbor City Anglers", 6), ("Lakeview Herons", 4)):
        for i in range(10):
            k += 1
            won = i < wins
            when = (base - timedelta(days=3 * (i + 1))).strftime("%Y-%m-%dT%H:%M:%SZ")
            add_game(s, f"h{k}", team, f"Past Opp {i}", when, "final", "home" if won else "away", sport="nba",
                     hs=104 if won else 99, as_=99 if won else 104)
    add_game(s, "g1", "Harbor City Anglers", "Lakeview Herons", "2026-11-14T00:00:00Z",
             odds={"home_ml": -110, "away_ml": -110, "book": "Demo Book", "source": "demo"})
    g = s.q("SELECT * FROM games WHERE id='g1'")[0]
    p = facts.build_packet(s, g, "2026-11-13T23:30:00Z")
    assert p["inputs"]["schedule_rest"]["value"]["window_days"] == 7
    m = model.project(p, CFG)
    cov = facts.coverage(p, CFG["coverage_weights"])
    d = {**decide.decide(p, m, cov, CFG), "coverage": cov}
    n = narrative.template(p, m, d)
    assert "last 7 days" in n["context"]
    assert narrative.validate_all(n, p, m, d) == []
