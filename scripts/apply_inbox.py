#!/usr/bin/env python3
"""Apply zip uploads (inbox/*.zip or ./*.zip) to this repo.

Stdlib only, so it can run before anything else exists. The same file is embedded
in .github/workflows/inbox.yml (built by scripts/build_inbox_yml.py) so the very
first zip can be applied after pasting that one workflow file.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ALLOW_DIRS = {"site", "api", "src", "db", "tests", "docs", "scripts", "fixtures"}
ALLOW_FILES = {"config.yaml", "vercel.json", "package.json", "package-lock.json",
               "requirements.txt", "README.md", ".gitignore"}
WORKFLOWS = ".github/workflows/"
KNOWN_ROOTS = ALLOW_DIRS | {".github", "data", "inbox"}
MANIFEST = "inbox.manifest.json"
MAX_FILES, MAX_FILE, MAX_TOTAL = 2000, 10 * 1024 * 1024, 100 * 1024 * 1024
JUNK = ("__MACOSX/", ".DS_Store", "Thumbs.db")

SECRET_PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(rb"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(rb"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(rb"\beyJ[A-Za-z0-9_\-]{20,}\.eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}"),
]


class Rejected(Exception):
    """The whole zip is refused; nothing is applied."""


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_path(raw):
    """Normalise a zip/manifest path or raise Rejected."""
    p = raw.replace("\\", "/")
    if "\x00" in p or p.startswith("/") or re.match(r"^[A-Za-z]:", p):
        raise Rejected(f"absolute or invalid path: {raw!r}")
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or ".." in parts:
        raise Rejected(f"path escapes the repo: {raw!r}")
    if ".git" in parts:
        raise Rejected(f"touches .git: {raw!r}")
    return "/".join(parts)


def classify(path):
    """Return 'normal' or 'workflow'; raise Rejected for paths outside the allowlist."""
    parts = path.split("/")
    if parts[-1].startswith(".env"):
        raise Rejected(f"env file refused: {path}")
    if path.startswith(WORKFLOWS) and path.endswith((".yml", ".yaml")) and len(parts) == 3:
        return "workflow"
    if len(parts) == 1 and (path in ALLOW_FILES or path == MANIFEST):
        return "normal"
    if len(parts) > 1 and parts[0] in ALLOW_DIRS:
        return "normal"
    raise Rejected(f"outside the allowlist: {path}")


def looks_secret(data):
    return any(p.search(data) for p in SECRET_PATTERNS)


def check_manifest(m):
    if not isinstance(m, dict):
        raise Rejected("manifest must be a JSON object")
    delete = m.get("delete", [])
    move = m.get("move", {})
    if not isinstance(delete, list) or not isinstance(move, dict):
        raise Rejected("manifest: delete must be a list and move an object")
    for p in list(delete) + list(move) + list(move.values()):
        if not isinstance(p, str):
            raise Rejected("manifest paths must be strings")
        classify(clean_path(p))
    return {"version": m.get("version"), "notes": m.get("notes"),
            "delete": [clean_path(p) for p in delete],
            "move": {clean_path(a): clean_path(b) for a, b in move.items()}}


def read_zip(zip_path):
    """Validate a zip and return ({path: (bytes, mode, kind)}, manifest_dict)."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise Rejected(f"not a valid zip: {exc}")
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        infos = [i for i in infos if not any(j in i.filename for j in JUNK)]
        if len(infos) > MAX_FILES:
            raise Rejected(f"too many files ({len(infos)} > {MAX_FILES})")
        entries = {}
        for info in infos:
            if info.flag_bits & 0x1:
                raise Rejected(f"encrypted entry: {info.filename}")
            kind = (info.external_attr >> 16) & 0o170000
            if kind in (stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK):
                raise Rejected(f"symlink or special file: {info.filename}")
            path = clean_path(info.filename)
            if path.lower() in {k.lower() for k in entries}:
                raise Rejected(f"duplicate path: {path}")
            entries[path] = info
        # strip one wrapper folder (e.g. "repo-main/") unless it is a real repo folder
        tops = {p.split("/")[0] for p in entries}
        if len(tops) == 1 and entries and all("/" in p for p in entries):
            only = next(iter(tops))
            if only not in KNOWN_ROOTS:
                entries = {p[len(only) + 1:]: i for p, i in entries.items()}
        total, out, manifest = 0, {}, {}
        for path, info in entries.items():
            kind = classify(path)
            with zf.open(info) as fh:
                data = fh.read(MAX_FILE + 1)
            if len(data) > MAX_FILE:
                raise Rejected(f"file over {MAX_FILE // 1048576} MB: {path}")
            total += len(data)
            if total > MAX_TOTAL:
                raise Rejected("unpacked size over 100 MB")
            if looks_secret(data):
                raise Rejected(f"looks like a secret: {path}")
            if path == MANIFEST:
                try:
                    manifest = json.loads(data.decode("utf-8"))
                except ValueError as exc:
                    raise Rejected(f"bad {MANIFEST}: {exc}")
                continue
            out[path] = (data, (info.external_attr >> 16) & 0o777, kind)
    return out, check_manifest(manifest)


def build_plan(repo, files, manifest, zip_stem, allow_workflows):
    plan = []
    for old, new in manifest["move"].items():
        plan.append({"action": "move", "path": new, "from": old})
    for p in manifest["delete"]:
        plan.append({"action": "delete", "path": p})
    for path, (data, mode, kind) in sorted(files.items()):
        target = Path(repo) / path
        if kind == "workflow" and not allow_workflows:
            if target.exists() and target.read_bytes() == data:
                plan.append({"action": "unchanged", "path": path})
            else:
                plan.append({"action": "quarantine", "path": path,
                             "target": f"inbox/needs-manual/{zip_stem}/{path}"})
            continue
        if not target.exists():
            action = "add"
        elif target.read_bytes() == data:
            action = "unchanged"
        else:
            action = "replace"
        plan.append({"action": action, "path": path})
    return plan


def apply_plan(repo, files, plan):
    repo = Path(repo)
    for step in plan:
        if step["action"] == "move":
            src, dst = repo / step["from"], repo / step["path"]
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
        elif step["action"] == "delete":
            tgt = repo / step["path"]
            if tgt.is_file():
                tgt.unlink()
    for step in plan:
        if step["action"] in ("add", "replace"):
            data, mode, _ = files[step["path"]]
            tgt = repo / step["path"]
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_bytes(data)
            tgt.chmod(0o755 if mode & 0o111 else 0o644)
        elif step["action"] == "quarantine":
            tgt = repo / step["target"]
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_bytes(files[step["path"]][0])


def git(repo, *args, check=True):
    res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip() or res.stdout.strip()}")
    return res


def find_zips(repo):
    repo = Path(repo)
    found = sorted((repo / "inbox").glob("*.zip")) if (repo / "inbox").is_dir() else []
    return found + sorted(repo.glob("*.zip"))


def load_applied(repo):
    p = Path(repo) / "inbox" / "applied.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            return []
    return []


def save_applied(repo, rows):
    p = Path(repo) / "inbox" / "applied.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows[-200:], indent=1) + "\n")


def run_tests(repo, cmd):
    """cmd None = use scripts/ci.sh if the (just applied) tree has one; "" = skip tests."""
    if cmd is None:
        cmd = "bash scripts/ci.sh" if (Path(repo) / "scripts" / "ci.sh").exists() else ""
    if not cmd:
        return True, "(no test command)"
    res = subprocess.run(cmd, shell=True, cwd=repo, capture_output=True, text=True, timeout=1500)
    tail = "\n".join((res.stdout + res.stderr).strip().splitlines()[-40:])
    return res.returncode == 0, tail


def remove_zip(repo, zip_path, use_git):
    rel = os.path.relpath(zip_path, repo)
    if use_git and git(repo, "ls-files", "--error-unmatch", rel, check=False).returncode == 0:
        git(repo, "rm", "-q", "-f", "--", rel)
    elif Path(zip_path).exists():
        Path(zip_path).unlink()


def fail_zip(repo, zip_path, use_git, commit_opts):
    """Restore the tree and move the zip to inbox/failed/ so it is not retried."""
    failed = Path(repo) / "inbox" / "failed"
    dst = failed / Path(zip_path).name
    rel = os.path.relpath(zip_path, repo)
    if use_git:
        git(repo, "reset", "--hard", "-q", "HEAD")
        git(repo, "clean", "-fdq")
        if Path(zip_path).exists():
            failed.mkdir(parents=True, exist_ok=True)
            git(repo, "mv", "-f", rel, os.path.relpath(dst, repo))
            git(repo, *commit_opts, "commit", "-q", "-m", f"inbox: failed {Path(zip_path).name}")
    elif Path(zip_path).exists():
        failed.mkdir(parents=True, exist_ok=True)
        shutil.move(str(zip_path), str(dst))


def process_zip(repo, zip_path, args, commit_opts):
    repo = Path(repo)
    name = Path(zip_path).name
    sha = sha256_file(zip_path)
    use_git = not args.no_git
    result = {"zip": name, "sha256": sha, "status": "applied", "plan": [], "notes": None, "tests": None}
    applied = load_applied(repo)
    if any(r.get("sha256") == sha for r in applied):
        result["status"] = "duplicate"
        if not args.dry_run:
            remove_zip(repo, zip_path, use_git)
            if use_git:
                git(repo, *commit_opts, "commit", "-q", "-m", f"inbox: skip duplicate {name}")
        return result
    try:
        files, manifest = read_zip(zip_path)
        result["plan"] = build_plan(repo, files, manifest, Path(name).stem, args.allow_workflows)
        result["notes"] = manifest.get("notes")
        if args.dry_run:
            result["status"] = "dry-run"
            return result
        apply_plan(repo, files, result["plan"])
        ok, tail = run_tests(repo, args.test_cmd)
        result["tests"] = {"ok": ok, "tail": tail}
        if not ok:
            raise Rejected("tests failed after applying the zip")
        n = sum(1 for s in result["plan"] if s["action"] in ("add", "replace", "move", "delete"))
        applied.append({"sha256": sha, "name": name, "applied_utc": now_utc(), "changes": n})
        save_applied(repo, applied)
        remove_zip(repo, zip_path, use_git)
        if use_git:
            git(repo, "add", "-A")
            git(repo, *commit_opts, "commit", "-q", "--allow-empty", "-m", f"inbox: apply {name} ({n} files)")
    except Rejected as exc:
        result["status"] = "failed"
        result["reason"] = str(exc)
        if not args.dry_run:
            fail_zip(repo, zip_path, use_git, commit_opts)
    return result


def push_with_retry(repo):
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    for _ in range(4):
        if git(repo, "push", "origin", f"HEAD:{branch}", check=False).returncode == 0:
            return True
        git(repo, "pull", "--rebase", "-q", "origin", branch, check=False)
    return False


def render_report(results, pushed):
    if not results:
        return "### Inbox\n\nNo zip found.\n"
    lines = ["### Inbox", ""]
    for r in results:
        label = {"applied": "applied", "failed": "FAILED", "duplicate": "skipped (already applied)",
                 "dry-run": "dry run"}[r["status"]]
        lines.append(f"**{r['zip']}**: {label}")
        if r.get("reason"):
            lines.append(f"- Reason: {r['reason']}")
        counts = {}
        for s in r["plan"]:
            counts[s["action"]] = counts.get(s["action"], 0) + 1
        if counts:
            lines.append("- Plan: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
        for s in r["plan"]:
            if s["action"] == "quarantine":
                lines.append(f"- Needs a manual paste or the INBOX_PAT secret: `{s['path']}` "
                             f"(saved in `{s['target']}`)")
        if r.get("tests") and not r["tests"]["ok"]:
            lines.append("- Test output (tail):\n```\n" + r["tests"]["tail"] + "\n```")
        if r.get("notes"):
            lines.append(f"- Notes: {r['notes']}")
    if pushed is False:
        lines.append("\nPush failed after retries; main was not updated.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--allow-workflows", action="store_true")
    ap.add_argument("--zip", help="apply only this zip")
    ap.add_argument("--test-cmd", default=None)
    ap.add_argument("--author-name", default=os.environ.get("INBOX_AUTHOR_NAME", "inbox"))
    ap.add_argument("--author-email",
                    default=os.environ.get("INBOX_AUTHOR_EMAIL", "inbox@users.noreply.github.com"))
    ap.add_argument("--report-file", default=None)
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    commit_opts = ["-c", f"user.name={args.author_name}", "-c", f"user.email={args.author_email}"]
    zips = [Path(args.zip)] if args.zip else find_zips(repo)
    results = [process_zip(repo, z, args, commit_opts) for z in zips]
    pushed = None
    if args.push and not args.no_git and not args.dry_run and results:
        pushed = push_with_retry(repo)
    report = render_report(results, pushed)
    print(report)
    if args.report_file:
        Path(args.report_file).write_text(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report)
    bad = any(r["status"] == "failed" for r in results) or pushed is False
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
