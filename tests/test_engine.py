import json

import pytest

from picks import config, decide, facts, model, store, validator

CFG = config.load()


def mkstore():
    s = store.SqliteStore()
    store.migrate(s)
    return s


def add_game(s, gid, home, away, start, status="scheduled", winner=None, odds=None, sport="nba", kind="team"):
    s.x("INSERT INTO games (id, sport, kind, event_id, start_utc, home, away, status, winner, odds_json, updated_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (gid, sport, kind, gid, start, home, away, status, winner, json.dumps(odds) if odds else None, start))


def test_packet_marks_missing_inputs_and_coverage():
    s = mkstore()
    add_game(s, "g1", "Harbor City Anglers", "Lakeview Herons", "2026-11-15T00:00:00Z",
             odds={"home_ml": -150, "away_ml": 130, "book": "demo"})
    g = s.q("SELECT * FROM games WHERE id='g1'")[0]
    p = facts.build_packet(s, g, "2026-11-14T23:30:00Z")
    assert p["inputs"]["market"]["value"]["no_vig_home"] == pytest.approx(0.5798, abs=1e-3)
    keys = {u["key"] for u in p["unavailable"]}
    assert keys == {"schedule_rest", "recent_form", "injuries"}
    assert facts.coverage(p, CFG["coverage_weights"]) == 0.4


def test_packet_uses_history_for_rest_and_form():
    s = mkstore()
    for i, (h, a, w) in enumerate([("Harbor City Anglers", "Lakeview Herons", "home"),
                                   ("Lakeview Herons", "Harbor City Anglers", "away"),
                                   ("Harbor City Anglers", "Ridge Bears", "home")]):
        add_game(s, f"h{i}", h, a, f"2026-11-{10 + i}T00:00:00Z", "final", w)
    add_game(s, "g1", "Harbor City Anglers", "Lakeview Herons", "2026-11-14T00:00:00Z",
             odds={"home_ml": -150, "away_ml": 130})
    g = s.q("SELECT * FROM games WHERE id='g1'")[0]
    p = facts.build_packet(s, g, "2026-11-13T23:30:00Z")
    assert p["inputs"]["schedule_rest"]["value"]["home_rest_days"] == 2.0
    assert p["inputs"]["recent_form"]["value"]["home"]["games"] == 3


def packet(cov_inputs=True):
    inputs = {"market": {"value": {"home_ml": -110, "away_ml": -110, "no_vig_home": 0.5, "no_vig_away": 0.5}},
              "schedule_rest": {"value": {"home_rest_days": 3.0, "away_rest_days": 1.0, "home_back_to_back": False,
                                          "away_back_to_back": True} if cov_inputs else None},
              "recent_form": {"value": {"home": {"w": 4, "l": 1, "games": 5}, "away": {"w": 2, "l": 3, "games": 5}}},
              "injuries": {"value": {"home": [], "away": []}}}
    return {"game": {"home": "Harbor City Anglers", "away": "Lakeview Herons"}, "inputs": inputs, "unavailable": []}


def test_model_is_anchored_and_directional():
    m = model.project(packet(), CFG)
    assert 0.5 < m["p_home"] < 0.53                         # small, market-anchored nudge toward the rested side
    assert m["p_home"] + m["p_away"] == pytest.approx(1.0, abs=1e-3)
    assert {a["name"] for a in m["adjustments"]} == {"rest", "back_to_back", "form"}
    nm = packet()
    nm["inputs"]["market"]["value"] = None
    assert model.project(nm, CFG) is None


def test_decide_pass_reasons_and_play():
    p, m = packet(), model.project(packet(), CFG)
    assert decide.decide(p, m, 0.60, CFG)["verdict"] == "PASS"          # coverage too low
    assert "Coverage" in decide.decide(p, m, 0.60, CFG)["reason"]
    d = decide.decide(p, m, 1.0, CFG)
    assert d["verdict"] == "PASS" and "minimum" in d["reason"]          # edge below threshold
    big = {"p_home": 0.57, "p_away": 0.43, "adjustments": []}
    d = decide.decide(p, big, 1.0, CFG)
    assert d["verdict"] == "PLAY" and d["selection"] == "home" and d["units"] >= 1 and d["rank_score"] > 0
    crazy = {"p_home": 0.70, "p_away": 0.30, "adjustments": []}
    assert "sanity cap" in decide.decide(p, crazy, 1.0, CFG)["reason"]
    p2 = packet()
    p2["inputs"]["market"]["value"] = {"home_ml": -300, "away_ml": 250, "no_vig_home": 0.70, "no_vig_away": 0.30}
    thin = {"p_home": 0.725, "p_away": 0.275, "adjustments": []}
    d = decide.decide(p2, thin, 1.0, CFG)
    assert d["verdict"] == "PASS"                                       # +2.5% edge but price loses after vig
    assert decide.decide(p, None, 1.0, CFG)["verdict"] == "PASS"


PKT = {"game": {"home": "Harbor City Anglers", "away": "Lakeview Herons", "start_utc": "2026-11-15T00:00:00Z"},
       "inputs": {"market": {"value": {"home_ml": -150, "away_ml": 130, "no_vig_home": 0.5798}}},
       "unavailable": [{"key": "injuries", "label": "injuries", "keywords": ["injur", "inactive"]}]}
MODEL = {"p_home": 0.5951, "adjustments": []}


def test_validator_accepts_grounded_text():
    text = "Harbor City Anglers are priced at -150 with a 58.0% no-vig chance. Our model has them at 59.5%."
    assert validator.check_narrative(text, PKT, MODEL) == []


def test_validator_rejects_fabricated_number_and_name():
    bad = validator.check_narrative("Harbor City Anglers have won 9 straight and Marcus Vale is hot.", PKT, MODEL)
    assert any("number" in b for b in bad) and any("Marcus" in b for b in bad)


def test_validator_rejects_claims_about_unavailable_inputs():
    bad = validator.check_narrative("Harbor City Anglers look healthy with no injuries listed.", PKT, MODEL)
    assert any("unavailable input" in b for b in bad)
    ok = validator.check_narrative("Injury reports are unavailable for this game.", PKT, MODEL)
    assert ok == []


def test_validator_percent_rounding():
    assert validator.check_narrative("Model: 60% for Harbor City Anglers.", PKT, MODEL) == []
    assert validator.check_narrative("Model: 64% for Harbor City Anglers.", PKT, MODEL) != []
