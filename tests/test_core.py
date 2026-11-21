from datetime import datetime, timedelta, timezone

import pytest

from picks import config, grading, market, records, timing

CFG = config.load()


def test_implied_and_no_vig():
    assert market.american_to_implied(-110) == pytest.approx(0.5238, abs=1e-4)
    assert market.american_to_implied(+150) == pytest.approx(0.4, abs=1e-6)
    pa, pb, vig = market.no_vig_two_way(-110, -110)
    assert pa == pytest.approx(0.5) and pb == pytest.approx(0.5) and vig == pytest.approx(0.0476, abs=1e-3)
    pa, pb, _ = market.no_vig_two_way(-200, +170)
    assert pa + pb == pytest.approx(1.0) and pa > 0.6
    qa, qb, _ = market.no_vig_two_way(-200, +170, "power")
    assert qa + qb == pytest.approx(1.0) and qa > pa   # power method gives favourites a bit more


def test_ev_profit_and_conversions():
    assert market.ev_per_unit(0.55, -110) == pytest.approx(0.55 * 1.90909 - 1, abs=1e-4)
    assert market.profit_units(+150, 2) == 3.0
    assert market.profit_units(-200, 2) == 1.0
    assert market.prob_to_american(0.6) == -150 and market.prob_to_american(0.4) == 150
    with pytest.raises(ValueError):
        market.american_to_decimal(0)


def test_units_and_confidence_are_bounded():
    assert market.units_for(0.5, 1.0, 3) == 3 and market.units_for(0.001, 0.5, 3) == 1
    assert 1 <= market.confidence_for(0.03, 0.9) <= 10


START = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("minutes_before,expected", [
    (60, timing.WAIT), (31, timing.WAIT), (30, timing.DUE), (25, timing.DUE), (11, timing.DUE),
    (9, timing.LATE), (1, timing.LATE), (0, timing.MISSED), (-5, timing.MISSED)])
def test_team_windows(minutes_before, expected):
    now = START - timedelta(minutes=minutes_before)
    assert timing.classify("team", START, now, False, CFG) == expected


@pytest.mark.parametrize("minutes_before,expected", [
    (120, timing.WAIT), (96, timing.WAIT), (95, timing.DUE), (90, timing.DUE), (59, timing.LATE), (0, timing.MISSED)])
def test_mma_windows(minutes_before, expected):
    assert timing.classify("mma", START, START - timedelta(minutes=minutes_before), False, CFG) == expected


def test_published_is_final_state():
    assert timing.classify("team", START, START + timedelta(hours=1), True, CFG) == timing.PUBLISHED


def test_mma_card_is_judged_by_first_bout_and_published_together():
    bouts = [{"id": f"b{i}", "kind": "bout", "event_id": "E1", "start_utc": timing.iso(START + timedelta(hours=i))}
             for i in range(4)]
    now = START - timedelta(minutes=92)           # inside T-95 of the earliest bout
    items = timing.due_items(bouts, now, set(), CFG)
    assert len(items) == 1 and items[0][0] == timing.DUE and len(items[0][3]) == 4
    assert timing.due_items(bouts, START - timedelta(minutes=200), set(), CFG) == []
    assert timing.due_items(bouts, now, {"b0", "b1", "b2", "b3"}, CFG) == []


def test_publish_target():
    assert timing.publish_target("team", START) == START - timedelta(minutes=30)
    assert timing.publish_target("mma", START) == START - timedelta(minutes=90)


def G(**kw):
    base = {"status": "final", "home_score": 100, "away_score": 90, "start_utc": "2026-11-15T20:00:00Z"}
    return {**base, **kw}


NOW = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("pick,game,grade", [
    ({"market": "ML", "selection": "home"}, G(), "W"),
    ({"market": "ML", "selection": "away"}, G(), "L"),
    ({"market": "ML", "selection": "home"}, G(home_score=90), "V"),                     # tie
    ({"market": "ML", "selection": "home"}, G(winner="draw", home_score=None, away_score=None), "V"),
    ({"market": "ML", "selection": "away"}, G(winner="away", home_score=None, away_score=None), "W"),
    ({"market": "SPREAD", "selection": "home", "line": -10}, G(), "V"),                 # push
    ({"market": "SPREAD", "selection": "home", "line": -9.5}, G(), "W"),
    ({"market": "SPREAD", "selection": "away", "line": 10.5}, G(), "W"),
    ({"market": "SPREAD", "selection": "away", "line": 9.5}, G(), "L"),
    ({"market": "TOTAL", "selection": "over", "line": 190}, G(), "V"),
    ({"market": "TOTAL", "selection": "over", "line": 189.5}, G(), "W"),
    ({"market": "TOTAL", "selection": "under", "line": 189.5}, G(), "L"),
    ({"market": "ML", "selection": "home"}, G(status="cancelled"), "V"),
    ({"market": "ML", "selection": "home"}, G(status="no_contest"), "V"),
    ({"market": "ML", "selection": "home"}, G(status="in_progress"), "PENDING"),
    ({"market": "ML", "selection": "home"}, G(status="postponed"), "PENDING"),
    ({"market": "ML", "selection": "home"}, G(status="final", home_score=None, away_score=None), "PENDING_REVIEW"),
])
def test_grading_rules(pick, game, grade):
    assert grading.grade_pick(pick, game, NOW)["grade"] == grade


def test_postponed_becomes_void_after_48_hours():
    later = datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc)
    assert grading.grade_pick({"market": "ML", "selection": "home"}, G(status="postponed"), later)["grade"] == "V"


def row(start, grade, sport="nba", odds=-110, units=1, top=False, verdict="PLAY"):
    return {"start_utc": start, "grade": grade, "sport": sport, "odds": odds, "units": units,
            "top_pick": top, "verdict": verdict}


def test_records_today_overall_sport_top_and_streak():
    now = "2026-11-15T18:00:00Z"                       # 1pm ET on Nov 15
    rows = [row("2026-11-14T00:30:00Z", "W"), row("2026-11-14T23:00:00Z", "L"),
            row("2026-11-15T17:00:00Z", "W", "nhl", +150, 2, True), row("2026-11-15T19:00:00Z", "V"),
            row("2026-11-15T23:00:00Z", None, "nfl"), row("2026-11-15T23:00:00Z", None, "nfl", verdict="PASS")]
    rec = records.build_records(rows, now)
    assert rec["overall"]["w"] == 2 and rec["overall"]["l"] == 1 and rec["overall"]["v"] == 1
    assert rec["overall"]["pending"] == 1                       # PASS rows never count
    assert rec["today"]["w"] == 1 and rec["today"]["v"] == 1 and rec["today"]["pending"] == 1
    assert rec["top_picks"]["w"] == 1 and rec["top_picks"]["units"] == 3.0
    assert rec["overall"]["win_pct"] == 66.7
    assert rec["overall"]["units"] == pytest.approx(0.909 - 1 + 3.0, abs=0.01)
    assert rec["by_sport"]["nhl"]["w"] == 1
    assert rec["streak"] == "W1" and len(rec["history"]) == 30
    assert rec["history"][-1]["date"] == "2026-11-15"


def test_et_day_boundary():
    # 02:00 UTC Nov 16 is still Nov 15 in New York
    assert str(records.et_date("2026-11-16T02:00:00Z")) == "2026-11-15"
