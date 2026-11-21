import json

import pytest

from picks import config, decide, facts, model, ratings, store, validator

CFG = config.load()


def mkstore():
    s = store.SqliteStore()
    store.migrate(s)
    return s


def add_game(s, gid, home, away, start, status="scheduled", winner=None, odds=None, sport="nba", kind="team", hs=None, as_=None):
    s.x("INSERT INTO games (id, sport, kind, event_id, start_utc, home, away, status, winner, home_score, away_score, odds_json, updated_utc) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (gid, sport, kind, gid, start, home, away, status, winner, hs, as_, json.dumps(odds) if odds else None, start))


def seed_ratings(s, home="Harbor City Anglers", away="Lakeview Herons", n=10, home_wins=7, away_wins=3, sport="nba"):
    """n finals per team with scores, so ratings, days off and form all exist."""
    from datetime import datetime, timedelta, timezone
    base = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    k = 0
    for team, wins, last_gap in ((home, home_wins, 0), (away, away_wins, 1)):
        for i in range(n):
            k += 1
            won = (i * 7) % n < wins                       # spreads the wins around instead of bunching them
            when = base + timedelta(days=(n - i) * 1 + last_gap - 1)
            hs, as_ = (105, 98) if won else (98, 105)
            add_game(s, f"h{k}", team, f"Past Opp {i}", when.strftime("%Y-%m-%dT%H:%M:%SZ"), "final", "home" if won else "away",
                     sport=sport, hs=hs, as_=as_)


def test_packet_marks_missing_inputs_and_coverage():
    s = mkstore()
    add_game(s, "g1", "Harbor City Anglers", "Lakeview Herons", "2026-11-15T00:00:00Z", odds={"home_ml": -150, "away_ml": 130, "book": "demo"})
    g = s.q("SELECT * FROM games WHERE id='g1'")[0]
    p = facts.build_packet(s, g, "2026-11-14T23:30:00Z")
    assert p["inputs"]["market"]["value"]["no_vig_home"] == pytest.approx(0.5798, abs=1e-3)
    assert {u["key"] for u in p["unavailable"]} == {"ratings", "schedule_rest", "recent_form", "injuries"}
    assert "needs 8 stored games" in p["inputs"]["ratings"]["reason"]
    assert facts.coverage(p, CFG["coverage_weights"]) == 0.35


def test_packet_has_ratings_days_off_form_and_filtered_injuries():
    s = mkstore()
    seed_ratings(s)
    add_game(s, "g1", "Harbor City Anglers", "Lakeview Herons", "2026-11-14T00:00:00Z", odds={"home_ml": -110, "away_ml": -110})
    s.x("INSERT INTO snapshots (key, json, updated_utc) VALUES ('injuries:nba', ?, 't')", (json.dumps({
        "Harbor City Anglers": [{"name": "Sam Rook", "status": "Out"}, {"name": "Old Hand", "status": "Injured Reserve"},
                                {"name": "Pat Day", "status": "Day-To-Day"}],
        "Lakeview Herons": []}),))
    g = s.q("SELECT * FROM games WHERE id='g1'")[0]
    p = facts.build_packet(s, g, "2026-11-13T23:30:00Z")
    r = p["inputs"]["ratings"]["value"]
    assert r["home_games"] == 10 and r["home_record"] == "7-3" and r["away_record"] == "3-7"
    assert r["home_elo"] > r["away_elo"] and r["p_home"] > 0.6 and r["unit"] == "points"
    sr = p["inputs"]["schedule_rest"]["value"]
    assert sr["home_days_off"] >= 0 and "home_back_to_back" in sr
    form = p["inputs"]["recent_form"]["value"]
    assert form["home"]["games"] == 5 and form["home"]["w"] + form["home"]["l"] == 5
    inj = p["inputs"]["injuries"]["value"]
    assert [x["name"] for x in inj["home"]] == ["Sam Rook", "Pat Day"] and inj["home_long_term"] == 1      # IR not listed, but counted
    assert facts.coverage(p, CFG["coverage_weights"]) == 1.0


def packet(rated=True, p_elo=0.60):
    inputs = {"market": {"value": {"home_ml": -110, "away_ml": -110, "no_vig_home": 0.5, "no_vig_away": 0.5}},
              "ratings": {"value": {"p_home": p_elo, "home_elo": 1540, "away_elo": 1480, "elo_gap": 60, "home_adv": 70, "home_games": 10,
                                    "away_games": 10, "home_record": "7-3", "away_record": "3-7", "home_margin": 2.1, "away_margin": -3.0,
                                    "unit": "points"} if rated else None},
              "schedule_rest": {"value": {"home_days_off": 3, "away_days_off": 0, "home_back_to_back": False, "away_back_to_back": True,
                                          "home_games_in_last_7_days": 2, "away_games_in_last_7_days": 4}},
              "recent_form": {"value": {"home": {"w": 4, "l": 1, "games": 5, "diff": 12.0}, "away": {"w": 2, "l": 3, "games": 5, "diff": -9.0}}},
              "injuries": {"value": {"home": [], "away": [], "home_long_term": 0, "away_long_term": 0}}}
    return {"game": {"home": "Harbor City Anglers", "away": "Lakeview Herons", "sport": "nba", "kind": "team"}, "inputs": inputs, "unavailable": []}


def test_model_is_anchored_and_directional():
    m = model.project(packet(), CFG)
    assert 0.50 < m["p_home"] < m["rating_home"]                   # moves toward the rating, but only part of the way
    assert m["rating_home"] > 0.6 and m["rated"] is True
    assert m["p_home"] + m["p_away"] == pytest.approx(1.0, abs=1e-3)
    assert {a["name"] for a in m["adjustments"]} == {"rest", "back_to_back"}
    bare = model.project(packet(rated=False), CFG)
    assert bare["p_home"] == 0.5 and bare["rated"] is False and bare["adjustments"] == []
    nm = packet()
    nm["inputs"]["market"]["value"] = None
    assert model.project(nm, CFG) is None


def test_decide_pass_reasons_and_play():
    p, m = packet(p_elo=0.5), model.project(packet(p_elo=0.5), CFG)
    assert "Coverage" in decide.decide(p, m, 0.60, CFG)["reason"]
    d = decide.decide(p, m, 1.0, CFG)
    assert d["verdict"] == "PASS" and "minimum" in d["reason"] and d["selection"] == "home"     # lean is still reported
    big = {"p_home": 0.57, "p_away": 0.43, "adjustments": []}
    d = decide.decide(p, big, 1.0, CFG)
    assert d["verdict"] == "PLAY" and d["selection"] == "home" and d["units"] >= 1 and d["rank_score"] > 0
    assert "sanity cap" in decide.decide(p, {"p_home": 0.70, "p_away": 0.30, "adjustments": []}, 1.0, CFG)["reason"]
    p2 = packet()
    p2["inputs"]["market"]["value"] = {"home_ml": -300, "away_ml": 250, "no_vig_home": 0.70, "no_vig_away": 0.30}
    assert decide.decide(p2, {"p_home": 0.725, "p_away": 0.275, "adjustments": []}, 1.0, CFG)["verdict"] == "PASS"   # price loses after vig
    assert decide.decide(p, None, 1.0, CFG)["verdict"] == "PASS"
    assert CFG["thresholds"]["play_min_coverage"] > 0.80            # missing injuries (0.20 of coverage) must block a PLAY


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
    assert validator.check_narrative("Injury reports are unavailable for this game.", PKT, MODEL) == []


def test_validator_percent_rounding():
    assert validator.check_narrative("Model: 60% for Harbor City Anglers.", PKT, MODEL) == []
    assert validator.check_narrative("Model: 64% for Harbor City Anglers.", PKT, MODEL) != []


def test_ratings_rise_for_winners_and_home_advantage_matters():
    r = ratings.Ratings({"k": 20, "home": 70})
    assert r.p_home("A", "B") == pytest.approx(0.5 + (ratings.expected(70) - 0.5))        # equal teams: home edge only
    for _ in range(5):
        r.update("A", "B", 110, 100)
    assert r.elo["A"] > 1500 > r.elo["B"] and r.elo["A"] + r.elo["B"] == pytest.approx(3000)
    assert r.avg_margin("A") == 10 and r.wins["A"] == 5 and r.losses["B"] == 5
    big, small = ratings.Ratings({"k": 20, "home": 0}), ratings.Ratings({"k": 20, "home": 0})
    big.update("A", "B", 130, 90), small.update("A", "B", 101, 100)
    assert big.elo["A"] > small.elo["A"]                                                     # margin of victory counts
