"""Stop hook: run the test suites at turn end, only when code changed since the last run in this worktree."""

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys

MAX_LINES = 30
MOD = "mods/session-cards"
# Code, and the config files the tests read (the global settings template, themes, terminal profile, CLAUDE.md).
WATCHED = ("*.py", "*.ps1", "*.json", "*.toml", "CLAUDE.md", "global/*", "themes/*", "terminal/*", "mods/*", "tests/*")
PYTHON_SUITE = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]
MOD_SUITE = ["claude", "plugin", "test", MOD]


def git(root, *args):
    p = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.stdout if p.returncode == 0 else ""


def watched(path):
    path = path.replace("\\", "/")
    return any(fnmatch.fnmatch(path, pat) for pat in WATCHED)


def untracked(root):
    return [p for p in git(root, "ls-files", "--others", "--exclude-standard").splitlines() if watched(p)]


def changed_paths(root):
    names = git(root, "diff", "--name-only", "HEAD").splitlines() + untracked(root)
    return sorted({n.replace("\\", "/") for n in names if watched(n)})


def fingerprint(root):
    h = hashlib.sha256()
    h.update(git(root, "rev-parse", "HEAD").encode())
    diff = subprocess.run(["git", "-C", root, "diff", "HEAD", "--", *WATCHED], capture_output=True).stdout
    h.update(diff)
    for rel in sorted(untracked(root)):
        h.update(rel.encode())
        try:
            with open(os.path.join(root, rel), "rb") as f:
                h.update(f.read())
        except OSError:
            pass
    return h.hexdigest()


def suites(root, changed):
    out = []
    changed = [c for c in changed if watched(c)]
    if any(not c.startswith("mods/") for c in changed):
        out.append(list(PYTHON_SUITE))
    if any(c.startswith("mods/") for c in changed):
        out.append(list(MOD_SUITE))
    return out


def run_suite(cmd, root):
    """Return (exit code, combined output). Replaced by tests."""
    try:
        p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=540)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "could not run %s: %s" % (" ".join(cmd[:4]), e)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def summarize(label, output):
    lines = [ln for ln in output.splitlines() if ln.strip()]
    names = [ln for ln in lines if re.match(r"(FAIL|ERROR):", ln)]
    tail = lines[-8:]
    return [label + " failed:", *names[:12], *[ln for ln in tail if ln not in names]]


def report(failures):
    lines = [ln for f in failures for ln in f]
    if len(lines) > MAX_LINES:
        lines = [*lines[: MAX_LINES - 1], "... (truncated)"]
    return "\n".join(lines)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    cwd = data.get("cwd") or os.getcwd()
    root = git(cwd, "rev-parse", "--show-toplevel").strip()
    git_dir = git(cwd, "rev-parse", "--absolute-git-dir").strip()
    if not root or not git_dir:
        return 0
    stamp = os.path.join(git_dir, "claude-stop-tests")
    fp = fingerprint(root)
    try:
        with open(stamp) as f:
            old = f.read().strip()
    except OSError:
        old = None
    if old == fp:
        return 0
    if old is not None:
        todo = suites(root, changed_paths(root))
    else:  # first run in this worktree: every suite the repo has
        todo = suites(root, ["tests/"] + ([MOD + "/"] if os.path.isdir(os.path.join(root, MOD)) else []))
    failures = []
    for cmd in todo:
        code, output = run_suite(cmd, root)
        if code != 0:
            failures.append(summarize(" ".join(cmd[-3:]) if cmd[0] != sys.executable else "python suite", output))
    try:
        with open(stamp, "w") as f:
            f.write(fp)
    except OSError:
        pass
    if not failures:
        return 0
    text = report(failures)
    if data.get("stop_hook_active"):
        print(json.dumps({"systemMessage": text}))
        return 0
    print(text, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
