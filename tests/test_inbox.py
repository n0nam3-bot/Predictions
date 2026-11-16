import json
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

import apply_inbox as ai


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def make_repo(tmp_path):
    """A working repo with a local bare 'origin'."""
    origin = tmp_path / "origin.git"
    run(["git", "init", "--bare", "-q", "-b", "main", str(origin)], tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    run(["git", "init", "-q", "-b", "main"], repo)
    run(["git", "remote", "add", "origin", str(origin)], repo)
    (repo / "README.md").write_text("hello\n")
    (repo / "inbox").mkdir()
    (repo / "inbox" / ".gitkeep").write_text("")
    run(["git", "add", "-A"], repo)
    run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"], repo)
    run(["git", "push", "-q", "origin", "main"], repo)
    return repo, origin


def make_zip(path, files, symlinks=()):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        for name, target in symlinks:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
    return path


def commit_zip(repo, zip_path):
    run(["git", "add", "-A"], repo)
    run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "upload"], repo)


def apply(repo, *extra):
    return ai.main(["--repo", str(repo), "--author-name", "Owner",
                    "--author-email", "1+owner@users.noreply.github.com", "--test-cmd", "", *extra])


def test_apply_places_files_and_deletes_zip(tmp_path):
    repo, origin = make_repo(tmp_path)
    z = make_zip(repo / "inbox" / "u1.zip", {"site/index.html": "<h1>x</h1>", "src/a.py": "print(1)\n"})
    commit_zip(repo, z)
    assert apply(repo, "--push") == 0
    assert (repo / "site" / "index.html").read_text() == "<h1>x</h1>"
    assert not (repo / "inbox" / "u1.zip").exists()
    log = run(["git", "log", "-1", "--format=%an|%ae|%s"], repo).strip()
    assert log.startswith("Owner|1+owner@users.noreply.github.com|inbox: apply u1.zip")
    assert run(["git", "rev-parse", "main"], origin).strip() == run(["git", "rev-parse", "HEAD"], repo).strip()
    applied = json.loads((repo / "inbox" / "applied.json").read_text())
    assert applied[0]["name"] == "u1.zip"


def test_zip_at_repo_root_is_found(tmp_path):
    repo, _ = make_repo(tmp_path)
    z = make_zip(repo / "update.zip", {"docs/a.md": "a"})
    commit_zip(repo, z)
    assert apply(repo) == 0
    assert (repo / "docs" / "a.md").exists() and not (repo / "update.zip").exists()


def test_wrapper_folder_is_stripped_but_real_roots_are_not(tmp_path):
    files, _ = ai.read_zip(make_zip(tmp_path / "a.zip", {"proj-main/site/x.html": "1", "proj-main/config.yaml": "a: 1"}))
    assert set(files) == {"site/x.html", "config.yaml"}
    files, _ = ai.read_zip(make_zip(tmp_path / "b.zip", {"site/x.html": "1", "site/y.html": "2"}))
    assert set(files) == {"site/x.html", "site/y.html"}


@pytest.mark.parametrize("name", ["../evil.txt", "site/../../evil.txt", "/etc/passwd", "C:/evil.txt",
                                  "site\\..\\..\\evil.txt"])
def test_zip_slip_and_absolute_paths_rejected(tmp_path, name):
    z = make_zip(tmp_path / "bad.zip", {name: "x"})
    with pytest.raises(ai.Rejected):
        ai.read_zip(z)


def test_symlink_rejected(tmp_path):
    z = make_zip(tmp_path / "s.zip", {"site/a.html": "x"}, symlinks=[("site/link", "/etc/passwd")])
    with pytest.raises(ai.Rejected, match="symlink"):
        ai.read_zip(z)


@pytest.mark.parametrize("name", ["data/ledger/x.ndjson", "inbox/applied.json", ".env", "site/.env.local",
                                  ".git/config", "random.txt", ".github/ISSUE_TEMPLATE/x.md"])
def test_outside_allowlist_rejected(tmp_path, name):
    with pytest.raises(ai.Rejected):
        ai.read_zip(make_zip(tmp_path / "o.zip", {name: "x"}))


def test_secret_like_content_rejected(tmp_path):
    fake = "ghp_" + "a" * 36
    with pytest.raises(ai.Rejected, match="secret"):
        ai.read_zip(make_zip(tmp_path / "k.zip", {"docs/notes.md": f"token {fake}"}))
    pem = "-----BEGIN " + "PRIVATE KEY-----"
    with pytest.raises(ai.Rejected, match="secret"):
        ai.read_zip(make_zip(tmp_path / "k2.zip", {"docs/key.txt": pem}))


def test_too_many_files_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "MAX_FILES", 3)
    z = make_zip(tmp_path / "m.zip", {f"docs/{i}.md": "x" for i in range(5)})
    with pytest.raises(ai.Rejected, match="too many"):
        ai.read_zip(z)


def test_one_bad_entry_means_nothing_is_applied(tmp_path):
    repo, _ = make_repo(tmp_path)
    z = make_zip(repo / "inbox" / "mix.zip", {"site/ok.html": "ok", "../evil": "x"})
    commit_zip(repo, z)
    assert apply(repo) == 1
    assert not (repo / "site" / "ok.html").exists()
    assert (repo / "inbox" / "failed" / "mix.zip").exists()
    assert not (repo / "inbox" / "mix.zip").exists()


def test_workflows_are_quarantined_without_pat(tmp_path):
    repo, _ = make_repo(tmp_path)
    z = make_zip(repo / "inbox" / "w.zip", {".github/workflows/pipeline.yml": "name: x", "docs/a.md": "a"})
    commit_zip(repo, z)
    assert apply(repo) == 0
    assert not (repo / ".github" / "workflows" / "pipeline.yml").exists()
    assert (repo / "inbox" / "needs-manual" / "w" / ".github" / "workflows" / "pipeline.yml").exists()
    assert (repo / "docs" / "a.md").exists()


def test_workflows_applied_with_pat(tmp_path):
    repo, _ = make_repo(tmp_path)
    z = make_zip(repo / "inbox" / "w.zip", {".github/workflows/pipeline.yml": "name: x"})
    commit_zip(repo, z)
    assert apply(repo, "--allow-workflows") == 0
    assert (repo / ".github" / "workflows" / "pipeline.yml").read_text() == "name: x"


def test_manifest_delete_and_move(tmp_path):
    repo, _ = make_repo(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "old.md").write_text("old")
    (repo / "docs" / "gone.md").write_text("gone")
    run(["git", "add", "-A"], repo)
    run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "docs"], repo)
    manifest = json.dumps({"version": "1", "notes": "tidy", "delete": ["docs/gone.md"],
                           "move": {"docs/old.md": "docs/new.md"}})
    z = make_zip(repo / "inbox" / "m.zip", {"inbox.manifest.json": manifest, "docs/extra.md": "e"})
    commit_zip(repo, z)
    assert apply(repo) == 0
    assert (repo / "docs" / "new.md").read_text() == "old"
    assert not (repo / "docs" / "old.md").exists() and not (repo / "docs" / "gone.md").exists()
    assert not (repo / "inbox.manifest.json").exists()


def test_manifest_cannot_touch_forbidden_paths(tmp_path):
    manifest = json.dumps({"delete": ["data/ledger/2026-01-01.ndjson"]})
    with pytest.raises(ai.Rejected):
        ai.read_zip(make_zip(tmp_path / "x.zip", {"inbox.manifest.json": manifest}))


def test_duplicate_zip_is_skipped(tmp_path):
    import shutil
    repo, _ = make_repo(tmp_path)
    z = make_zip(repo / "inbox" / "d.zip", {"docs/a.md": "a"})
    commit_zip(repo, z)
    assert apply(repo) == 0
    (repo / "docs" / "a.md").write_text("edited later")
    # d.zip was consumed, so rebuild identical bytes from the recorded sha instead
    applied = json.loads((repo / "inbox" / "applied.json").read_text())
    assert applied[0]["name"] == "d.zip"
    again = make_zip(tmp_path / "src.zip", {"docs/a.md": "a"})
    ai_sha = ai.sha256_file(again)
    applied.append({"sha256": ai_sha, "name": "src.zip"})
    (repo / "inbox" / "applied.json").write_text(json.dumps(applied))
    shutil.copy(again, repo / "inbox" / "d_again.zip")
    commit_zip(repo, None)
    assert apply(repo) == 0
    assert (repo / "docs" / "a.md").read_text() == "edited later"
    assert not (repo / "inbox" / "d_again.zip").exists()
    assert "skip duplicate" in run(["git", "log", "-1", "--format=%s"], repo)


def test_failing_tests_leave_main_untouched_and_move_zip(tmp_path):
    repo, origin = make_repo(tmp_path)
    before = run(["git", "rev-parse", "HEAD"], repo).strip()
    z = make_zip(repo / "inbox" / "t.zip", {"src/new.py": "x = 1\n", "README.md": "changed\n"})
    commit_zip(repo, z)
    uploaded = run(["git", "rev-parse", "HEAD"], repo).strip()
    rc = ai.main(["--repo", str(repo), "--test-cmd", "exit 3", "--push"])
    assert rc == 1
    assert not (repo / "src" / "new.py").exists()
    assert (repo / "README.md").read_text() == "hello\n"
    assert (repo / "inbox" / "failed" / "t.zip").exists()
    # history after the upload commit only adds the 'failed' move
    msgs = run(["git", "log", "--format=%s", f"{uploaded}..HEAD"], repo).strip().splitlines()
    assert msgs == ["inbox: failed t.zip"]
    assert before != uploaded


def test_dry_run_changes_nothing(tmp_path):
    repo, _ = make_repo(tmp_path)
    z = make_zip(repo / "inbox" / "dr.zip", {"docs/a.md": "a"})
    commit_zip(repo, z)
    assert apply(repo, "--dry-run") == 0
    assert (repo / "inbox" / "dr.zip").exists() and not (repo / "docs").exists()


def test_multiple_zips_apply_in_filename_order(tmp_path):
    repo, _ = make_repo(tmp_path)
    make_zip(repo / "inbox" / "a_first.zip", {"docs/v.md": "one"})
    make_zip(repo / "inbox" / "b_second.zip", {"docs/v.md": "two"})
    commit_zip(repo, None)
    assert apply(repo) == 0
    assert (repo / "docs" / "v.md").read_text() == "two"


def test_executable_bit_is_kept(tmp_path):
    zp = tmp_path / "x.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        info = zipfile.ZipInfo("scripts/run.sh")
        info.external_attr = 0o100755 << 16
        zf.writestr(info, "#!/bin/sh\n")
    files, _ = ai.read_zip(zp)
    assert files["scripts/run.sh"][1] & 0o111


def test_unchanged_workflow_is_not_quarantined(tmp_path):
    repo, _ = make_repo(tmp_path)
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "inbox.yml").write_text("name: same")
    run(["git", "add", "-A"], repo)
    run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "wf"], repo)
    z = make_zip(repo / "inbox" / "u.zip", {".github/workflows/inbox.yml": "name: same", "docs/a.md": "a"})
    commit_zip(repo, z)
    assert apply(repo) == 0
    assert not (repo / "inbox" / "needs-manual").exists()


def test_tests_shipped_inside_the_zip_are_run_on_first_upload(tmp_path):
    repo, _ = make_repo(tmp_path)
    z = make_zip(repo / "inbox" / "first.zip", {"scripts/ci.sh": "#!/bin/sh\necho broken >&2\nexit 7\n", "docs/a.md": "a"})
    commit_zip(repo, z)
    assert ai.main(["--repo", str(repo)]) == 1                       # no --test-cmd: default picks up the new ci.sh
    assert not (repo / "docs" / "a.md").exists() and (repo / "inbox" / "failed" / "first.zip").exists()
    z = make_zip(repo / "inbox" / "second.zip", {"scripts/ci.sh": "#!/bin/sh\necho fine\n", "docs/a.md": "a"})
    commit_zip(repo, z)
    assert ai.main(["--repo", str(repo)]) == 0 and (repo / "docs" / "a.md").exists()
