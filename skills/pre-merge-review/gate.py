"""Gate for the pre-merge-review skill. Stdlib only: the hook runs it as `python -I -S gate.py check`.

check   PreToolUse hook (Bash and PowerShell). Refuses `gh pr merge` unless the PR's current head has a review record,
        and refuses `git push` while the branch's open PR has auto-merge on. Refusal = a deny JSON on stdout, exit 0.
record  `gate.py record <pr> --head <sha> --summary <file> [-R repo]`: posts the review summary as a PR comment and
        writes the record for the PR's head, provided that head is still the commit the review saw (--head).

Choices: a `gh pr merge` is found anywhere in the command text, quoted or not, so `bash -c "gh pr merge 3"` is caught
and `echo "gh pr merge 3"` is refused too (a false refusal is cheap, a missed merge is not). A merge fails closed
(no answer from gh = refused); a push fails open (a new branch has no PR yet and must be pushable).
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

SKILL = "the pre-merge-review skill"
GH_TIMEOUT = 10
VIEW_MERGE = "url,number,headRefOid,state"
VIEW_PUSH = "url,number,state,autoMergeRequest"

MERGE_RE = re.compile(r"""(?<![A-Za-z0-9_-])gh(?:\.exe)?["']?\s+pr\s+merge(?![\w-])""", re.IGNORECASE)
ARG = r"""(?:"[^"]*"|'[^']*'|\S+)"""
PUSH_RE = re.compile(
    r"""(?<![A-Za-z0-9_-])git(?:\.exe)?["']?"""
    r"""((?:\s+(?:-C\s+%s|-c\s+%s|--[A-Za-z][\w-]*(?:=%s)?|-p|-P))*)"""
    r"""\s+push(?![\w-])""" % (ARG, ARG, ARG),
    re.IGNORECASE,
)
DIR_RE = re.compile(r"""-C\s+(%s)""" % ARG)

# gh pr merge flags that take a value (the next token, or after "=").
VALUE_LONG = {"--repo", "--body", "--body-file", "--subject", "--match-head-commit", "--author-email"}
VALUE_SHORT = {"-R", "-b", "-F", "-t", "-A"}


# ---- shared helpers ----

def record_dir():
    return os.environ.get("PRE_MERGE_REVIEW_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "pre-merge-review")


def record_path(url, sha):
    return os.path.join(record_dir(), "%s-%s.json" % (hashlib.sha256(url.encode("utf-8")).hexdigest()[:16], sha))


def has_record(url, sha):
    try:
        with open(record_path(url, sha), encoding="utf-8") as f:
            data = json.load(f)
        return data.get("url") == url and data.get("sha") == sha
    except (OSError, ValueError, AttributeError):
        return False


def gh_command():
    override = os.environ.get("PRE_MERGE_REVIEW_GH")
    return [sys.executable, override] if override else ["gh"]


def run_gh(args, cwd=None):
    """(returncode, stdout, first stderr line). Any failure to run gh is returncode -1."""
    try:
        p = subprocess.run(
            gh_command() + list(args), cwd=cwd or None, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=GH_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return -1, "", "gh could not run (%s)" % type(e).__name__
    lines = [ln.strip() for ln in p.stderr.splitlines() if ln.strip()]
    return p.returncode, p.stdout, (lines[0] if lines else "gh exited with code %d" % p.returncode)


def view_pr(selector, repo, fields, cwd=None):
    """(dict, None) or (None, reason)."""
    args = ["pr", "view"] + ([selector] if selector else []) + (["-R", repo] if repo else []) + ["--json", fields]
    code, out, err = run_gh(args, cwd)
    if code != 0:
        return None, err
    try:
        data = json.loads(out)
    except ValueError:
        return None, "gh printed no JSON"
    if not isinstance(data, dict):
        return None, "gh printed no JSON object"
    return data, None


def valid_sha(sha):
    return isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{7,64}", sha) is not None


# ---- command parsing ----

def region_end(text, start, limit):
    """End of a command's arguments: the first separator outside quotes, or `limit`."""
    quote = None
    i = start
    n = min(len(text), limit)
    while i < n:
        c = text[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in ";|&\n\r":
            return i
        i += 1
    return n


def tokens(region):
    try:
        toks = shlex.split(region, posix=False)
    except ValueError:
        toks = region.split()
    out = []
    for t in toks:
        t = t.strip("\"'")
        if t:
            out.append(t)
    return out


def parse_merge(region):
    """(selector, repo, disable_auto) from the text after `gh pr merge`."""
    selector = repo = None
    disable_auto = False
    toks = tokens(region)
    i = 0
    while i < len(toks):
        t = toks[i]
        i += 1
        if t.startswith("--"):
            name, eq, val = t.partition("=")
            if name == "--disable-auto":
                disable_auto = True
            elif name in VALUE_LONG:
                if not eq and i < len(toks):
                    val = toks[i]
                    i += 1
                if name == "--repo":
                    repo = val or repo
        elif t in VALUE_SHORT:
            val = toks[i] if i < len(toks) else ""
            i += 1
            if t == "-R":
                repo = val or repo
        elif t.startswith("-R") and len(t) > 2:
            repo = t[2:]
        elif t.startswith("-"):
            continue
        elif selector is None:
            selector = t
    return selector, repo, disable_auto


def find_merges(command):
    matches = list(MERGE_RE.finditer(command))
    out = []
    for k, m in enumerate(matches):
        limit = matches[k + 1].start() if k + 1 < len(matches) else len(command)
        out.append(parse_merge(command[m.end():region_end(command, m.end(), limit)]))
    return out


def norm_dir(path, cwd):
    """A `git -C` directory as a native path: strips quotes, maps Git Bash /c/x to C:/x, resolves against cwd."""
    path = path.strip("\"'")
    if os.name == "nt":
        m = re.match(r"^/([A-Za-z])(?:/(.*))?$", path)
        if m:
            path = "%s:/%s" % (m.group(1), m.group(2) or "")
    if not os.path.isabs(path) and cwd:
        path = os.path.join(cwd, path)
    return path


def find_push_dirs(command, cwd):
    """One directory per `git push` (the last -C wins, as in git), None entries collapsed to cwd, deduplicated."""
    dirs = []
    for m in PUSH_RE.finditer(command):
        found = DIR_RE.findall(m.group(1) or "")
        d = norm_dir(found[-1], cwd) if found else cwd
        if d not in dirs:
            dirs.append(d)
    return dirs


# ---- check ----

def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason,
    }}))


def check_merge(selector, repo, cwd):
    pr, err = view_pr(selector, repo, VIEW_MERGE, cwd)
    where = "PR %s" % selector if selector else "this branch's PR"
    if pr is None:
        return ("Merge refused: could not read %s (%s). Fix that or name the PR explicitly, then use %s before merging."
                % (where, err, SKILL))
    url, sha = pr.get("url"), pr.get("headRefOid")
    if not url or not valid_sha(sha):
        return "Merge refused: gh gave no URL or head commit for %s. Use %s before merging." % (where, SKILL)
    if has_record(url, sha):
        return None
    return ("Merge refused: PR #%s (%s) has no pre-merge review at head %s. Use %s: review this head, fix the real "
            "findings, record the review, then merge. If the head changes, the review has to be done again."
            % (pr.get("number"), url, sha[:7], SKILL))


def check_push(directory):
    pr, _ = view_pr(None, None, VIEW_PUSH, directory)
    if pr is None:  # no PR yet, or gh unavailable: a new branch must be pushable
        return None
    if pr.get("state") == "OPEN" and pr.get("autoMergeRequest"):
        return ("Push refused: PR #%s (%s) is open with auto-merge on, so the new commits would merge without a "
                "review. Run `gh pr merge %s --disable-auto` first, push, then use %s and merge."
                % (pr.get("number"), pr.get("url"), pr.get("number"), SKILL))
    return None


def check(stdin_bytes):
    try:
        data = json.loads(stdin_bytes.decode("utf-8-sig", errors="replace"))
        tool = data.get("tool_name")
        command = (data.get("tool_input") or {}).get("command")
        cwd = data.get("cwd") or None
    except (ValueError, AttributeError):
        return 0
    if tool not in ("Bash", "PowerShell") or not isinstance(command, str):
        return 0
    reasons = []
    merges = [m for m in find_merges(command) if not m[2]]
    if merges and PUSH_RE.search(command):
        reasons.append("Merge refused: a command that pushes and merges together would merge unreviewed commits. "
                       "Push in one command, use %s, then merge in another." % SKILL)
    else:
        seen = set()
        for selector, repo, _ in merges:
            if (selector, repo) in seen:
                continue
            seen.add((selector, repo))
            reason = check_merge(selector, repo, cwd)
            if reason:
                reasons.append(reason)
    for directory in find_push_dirs(command, cwd):
        reason = check_push(directory)
        if reason:
            reasons.append(reason)
    if reasons:
        deny(" ".join(reasons))
    return 0


# ---- record ----

def record(argv):
    ap = argparse.ArgumentParser(prog="gate.py record", description="Post the review summary and record the review.")
    ap.add_argument("pr")
    ap.add_argument("--head", required=True, help="the commit the review saw (full SHA or a prefix of 7+ characters)")
    ap.add_argument("--summary", required=True)
    ap.add_argument("-R", "--repo")
    args = ap.parse_args(argv)

    def fail(msg):
        print("record failed: %s" % msg, file=sys.stderr)
        return 1

    try:
        with open(args.summary, encoding="utf-8-sig") as f:
            summary = f.read().strip()
    except (OSError, UnicodeDecodeError) as e:
        return fail("cannot read the summary file (%s)" % e)
    if not summary:
        return fail("the summary file is empty. Write the review's findings and what was done about each, as %s says."
                    % SKILL)
    seen = args.head.strip().lower()
    if re.fullmatch(r"[0-9a-f]{7,40}", seen) is None:
        return fail("--head must be the reviewed commit, 7 to 40 hex characters, got %r" % args.head)
    pr, err = view_pr(args.pr, args.repo, VIEW_MERGE)
    if pr is None:
        return fail("could not read the PR (%s)" % err)
    url, sha = pr.get("url"), pr.get("headRefOid")
    if not url or not valid_sha(sha):
        return fail("gh gave no URL or head commit")
    if pr.get("state") != "OPEN":
        return fail("PR #%s is %s, not OPEN. Only an open PR is reviewed and recorded (%s)."
                    % (pr.get("number"), pr.get("state"), SKILL))
    if not sha.lower().startswith(seen):
        return fail("the head moved since the review: it saw %s, the PR is now at %s. Review the new head with %s."
                    % (seen[:7], sha[:7], SKILL))
    body = "**Pre-merge review** of %s (built-in `/code-review high`)\n\n%s\n" % (sha, summary)
    fd, tmp = tempfile.mkstemp(prefix="pre-merge-review-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        code, _, err = run_gh(["pr", "comment", args.pr] + (["-R", args.repo] if args.repo else [])
                              + ["--body-file", tmp])
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if code != 0:
        return fail("the PR comment was not posted, so nothing is recorded (%s)" % err)
    try:
        os.makedirs(record_dir(), exist_ok=True)
        path = record_path(url, sha)
        part = path + ".tmp"
        with open(part, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"url": url, "sha": sha, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, f)
        os.replace(part, path)
    except OSError as e:
        return fail("the comment is posted but the record could not be written (%s)" % e)
    print("recorded %s at %s" % (url, sha[:7]))
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "check":
        return check(sys.stdin.buffer.read())
    if len(argv) >= 2 and argv[1] == "record":
        return record(argv[2:])
    print("usage: gate.py check | gate.py record <pr> --head <sha> --summary <file> [-R repo]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
