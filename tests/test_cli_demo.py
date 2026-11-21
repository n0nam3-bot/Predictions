import json

from picks import cli, demo, pipeline, store
from test_pipeline import Src, game, T0
from datetime import timedelta


def test_cli_does_nothing_without_a_database(capsys):
    assert cli.main(["tick"], env={}) == 0
    assert "Database not configured" in capsys.readouterr().out


def test_cli_commands_against_sqlite(tmp_path, capsys):
    env = {"PICKS_DB": str(tmp_path / "p.db"), "PICKS_LEDGER_DIR": str(tmp_path / "ledger")}
    start = T0 + timedelta(hours=2)
    src = Src([game("g1", start)])
    assert cli.main(["migrate"], env=env) == 0
    assert cli.main(["schedule", "--now", T0.isoformat()], source=src, env=env) == 0
    assert cli.main(["tick", "--now", (start - timedelta(minutes=30)).isoformat()], source=src, env=env) == 0
    out = capsys.readouterr().out
    assert '"published": 1' in out
    assert cli.main(["verify"], env=env) == 0
    st = store.connect(env)
    assert len(st.q("SELECT * FROM picks")) == 1


def test_demo_is_labelled_and_complete(tmp_path):
    out = tmp_path / "latest.json"
    assert cli.main(["demo", "--out", str(out)]) == 0
    d = json.loads(out.read_text())
    assert d["source"] == "demo" and "not real picks" in d["demo_note"]
    verdicts = {g["pick"]["verdict"] for g in d["games"] if g["pick"]}
    grades = {g["grade"]["grade"] for g in d["games"] if g["grade"]}
    assert verdicts == {"PLAY", "PASS"} and grades == {"W", "L", "V"}
    assert any(g["pick"] and g["pick"]["tag"] == "LATE" for g in d["games"])
    assert any(g["pick"] and g["pick"]["top_pick"] for g in d["games"])
    assert d["records"]["overall"]["w"] > 0 and len(d["records"]["history"]) == 30
    assert not any("Groq" in json.dumps(d) for _ in [0])


def test_tick_tops_up_schedule_and_grade_when_only_tick_is_triggered(tmp_path):
    env = {"PICKS_DB": str(tmp_path / "p.db")}
    start = T0 + timedelta(hours=2)
    src = Src([game("g1", start)])
    now = (start - timedelta(minutes=30)).isoformat()
    assert cli.main(["tick", "--now", now], source=src, env=env) == 0          # nothing scheduled yet, no manual schedule run
    st = store.connect(env)
    assert len(st.q("SELECT * FROM picks")) == 1                                 # tick scheduled the games itself
    kinds = {r["kind"] for r in st.q("SELECT kind FROM heartbeat")}
    assert {"schedule", "tick", "grade"} <= kinds
    before = len(src.fetches)
    later = (start - timedelta(minutes=25)).isoformat()
    cli.main(["tick", "--now", later], source=src, env=env)
    assert len([f for f in src.fetches[before:]]) < 3                            # no full re-schedule within 3 hours


def test_ledger_command_uses_the_configured_folder_never_the_repo_data(tmp_path):
    env = {"PICKS_DB": str(tmp_path / "p.db"), "PICKS_LEDGER_DIR": str(tmp_path / "ledger")}
    start = T0 + timedelta(hours=2)
    src = Src([game("g1", start)])
    cli.main(["tick", "--now", (start - timedelta(minutes=30)).isoformat()], source=src, env=env)
    assert cli.main(["ledger", "--now", (start - timedelta(minutes=20)).isoformat()], source=src, env=env) == 0
    assert list((tmp_path / "ledger").glob("*.ndjson")) and cli.main(["verify"], env=env) == 0
