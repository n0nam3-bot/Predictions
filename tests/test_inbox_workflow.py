import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows" / "inbox.yml"


def test_workflow_is_up_to_date_with_script():
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_inbox_yml
    assert WF.read_text() == build_inbox_yml.build(), "run: python3 scripts/build_inbox_yml.py"


def test_embedded_script_is_byte_identical_and_compiles():
    doc = yaml.safe_load(WF.read_text())
    run = [s for s in doc["jobs"]["apply"]["steps"] if s.get("id") == "apply"][0]["run"]
    embedded = re.search(r"<<'PYEOF'\n(.*?)\nPYEOF\n", run, re.S).group(1)
    assert embedded.strip() == (ROOT / "scripts" / "apply_inbox.py").read_text().strip()
    compile(embedded, "embedded", "exec")


def test_workflow_shape():
    doc = yaml.safe_load(WF.read_text())
    on = doc[True]
    assert on["push"]["paths"] == ["inbox/*.zip", "*.zip"]
    assert "workflow_dispatch" in on
    assert doc["permissions"] == {"contents": "write", "issues": "write"}
    assert doc["concurrency"]["cancel-in-progress"] is False
    assert doc["jobs"]["apply"]["if"] == "github.actor == github.repository_owner"


def test_shell_steps_parse_with_bash_n():
    doc = yaml.safe_load(WF.read_text())
    for step in doc["jobs"]["apply"]["steps"]:
        if "run" in step:
            res = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
            assert res.returncode == 0, (step.get("name"), res.stderr)
