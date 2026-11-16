import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CMD = json.loads((ROOT / "vercel.json").read_text())["ignoreCommand"]


def sh(cmd, cwd, env=None):
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True)


def commit(repo, path, text):
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    sh("git add -A && git -c user.name=t -c user.email=t@t commit -qm c && git rev-parse HEAD", repo)
    return sh("git rev-parse HEAD", repo).stdout.strip()


def test_ignored_build_step_semantics(tmp_path):
    sh("git init -q -b main", tmp_path)
    first = commit(tmp_path, "site/index.html", "v1")
    inbox_only = commit(tmp_path, "inbox/applied.json", "[]")
    workflow_only = commit(tmp_path, ".github/workflows/x.yml", "name: x")
    # nothing deployed yet: must build (exit code 1 means build, 0 means skip)
    assert sh(CMD, tmp_path, {"VERCEL_GIT_PREVIOUS_SHA": ""}).returncode != 0
    # the failure the owner hit: HEAD only touched a workflow, but the site has never been deployed
    assert sh(CMD, tmp_path, {"VERCEL_GIT_PREVIOUS_SHA": ""}).returncode != 0
    # last good deploy was the first commit; later commits touched no site/api files: skip
    assert sh(CMD, tmp_path, {"VERCEL_GIT_PREVIOUS_SHA": first}).returncode == 0
    site_change = commit(tmp_path, "site/app.js", "new")
    assert sh(CMD, tmp_path, {"VERCEL_GIT_PREVIOUS_SHA": first}).returncode != 0
    api_change = commit(tmp_path, "api/x.js", "new")
    assert sh(CMD, tmp_path, {"VERCEL_GIT_PREVIOUS_SHA": site_change}).returncode != 0
    assert sh(CMD, tmp_path, {"VERCEL_GIT_PREVIOUS_SHA": api_change}).returncode == 0
    # unknown previous commit (shallow clone): build rather than skip
    assert sh(CMD, tmp_path, {"VERCEL_GIT_PREVIOUS_SHA": "0" * 40}).returncode != 0
