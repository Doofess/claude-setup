"""Gate for the pre-merge-review skill. Stdlib only: the hook runs it as `python -I -S gate.py check`.

check   PreToolUse hook (Bash and PowerShell). Refuses `gh pr merge` unless the PR's current head has a review record,
        and refuses `git push` while the branch's open PR has auto-merge on. Refusal = a deny JSON on stdout, exit 0.
record  `gate.py record <pr> --head <sha> --summary <file> [-R repo]`: posts the review summary as a PR comment and
        writes the record for the PR's head, provided that head is still the commit the review saw (--head).

Choices: a `gh pr merge` counts when it is run: outside quotes, as a quoted program path, in `"$(...)"`, or in the
quoted command of `bash -c`, `cmd /c`, `pwsh -Command`, `eval` and the like; text in `git commit -m "..."` or
`grep '...'` does not. When unsure it counts (a false refusal is cheap, a missed merge is not). A merge fails closed
(no answer from gh, a crash, or the time budget used up = refused); a push fails open (a new branch has no PR yet and
must be pushable). A `cd` earlier in the command moves where the PR is looked up, as it moves where gh runs.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

SKILL = "the pre-merge-review skill"
GH_TIMEOUT = 10  # one gh call
GH_BUDGET = 20  # all gh calls of one check, under the hook's own 30 s timeout (a killed hook lets the command run)
RECORD_TIMEOUT = 60  # record has no hook around it; a slow comment that times out would be posted twice on a retry
VIEW_MERGE = "url,number,headRefOid,state"
VIEW_PUSH = "url,number,state,autoMergeRequest"
UNKNOWN = "?"  # a folder the gate cannot resolve (`cd -`, a variable)

_deadline = None  # set by check(); record() has no budget

ARG = r"""(?:"[^"]*"|'[^']*'|\S+)"""
MERGE_RE = re.compile(  # `gh pr merge`, also with quoted words and `pr`'s own -R/--repo before `merge` (gh takes both)
    r"""(?<![A-Za-z0-9_-])gh(?:\.exe)?["']?\s+["']?pr["']?"""
    r"""(?P<pre>(?:\s+(?:-R\s*%s|--repo(?:=|\s+)%s))*)\s+["']?merge["']?(?![\w-])""" % (ARG, ARG),
    re.IGNORECASE,
)
PUSH_RE = re.compile(
    r"""(?<![A-Za-z0-9_-])git(?:\.exe)?["']?"""
    r"""((?:\s+(?:-C\s+%s|-c\s+%s|--(?:git-dir|work-tree|namespace)\s+%s|--[A-Za-z][\w-]*(?:=%s)?|-p|-P))*)"""
    r"""\s+push(?![\w-])""" % (ARG, ARG, ARG, ARG),
    re.IGNORECASE,
)
CD_ARG = r"""(?:"[^"]*"|'[^']*'|[^\s;&|)]+)"""  # stops at a separator: `cd sub; x`
CD_WORDS = r"""cd|chdir|pushd|popd|sl|set-location|push-location|pop-location"""
CD_RE = re.compile(  # a folder change the gate can follow: a plain statement of its own
    r"""(?:^|[;&|\n\r(])\s*(?P<word>cd|chdir|pushd|sl|set-location|push-location)(?![\w./\\-])"""
    r"""(?:\s+/d|\s+-(?:path|literalpath))?(?:\s+(?P<arg>%s))?""" % CD_ARG,
    re.IGNORECASE,
)
CD_WORD_RE = re.compile(r"""(?<![\w.$/\\-])(?:%s)(?![\w./\\-])""" % CD_WORDS, re.IGNORECASE)  # any folder change
CONTINUATION_RE = re.compile(r"(?:\\|`)\r?\n")  # Bash `\` and PowerShell backtick line continuations

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


def run_gh(args, cwd=None, timeout=GH_TIMEOUT):
    """(returncode, stdout, first stderr line). Any failure to run gh is returncode -1.

    Output goes to temporary files, not pipes: on a timeout, subprocess kills gh and then reads its pipes with no
    timeout, which on Windows can hang while a child of gh still holds them."""
    if _deadline is not None:
        timeout = min(timeout, _deadline - time.monotonic())
        if timeout < 1:
            return -1, "", "the gate's gh calls used up their %d s budget" % GH_BUDGET
    try:
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            p = subprocess.run(gh_command() + list(args), cwd=cwd or None, stdin=subprocess.DEVNULL, stdout=out,
                               stderr=err, timeout=timeout)
            out.seek(0)
            err.seek(0)
            stdout = out.read().decode("utf-8", errors="replace")
            stderr = err.read().decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return -1, "", "gh could not run (%s)" % type(e).__name__
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    return p.returncode, stdout, (lines[0] if lines else "gh exited with code %d" % p.returncode)


def view_pr(selector, repo, fields, cwd=None, timeout=GH_TIMEOUT):
    """(dict, None) or (None, reason)."""
    args = ["pr", "view"] + ([selector] if selector else []) + (["-R", repo] if repo else []) + ["--json", fields]
    code, out, err = run_gh(args, cwd, timeout)
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

def scan(text, esc):
    """Per position (and one past the end): (the quote open there or None, the parenthesis depth there, where that
    quote opened). `esc` is the shell's escape character (`\\` in Bash, backtick in PowerShell): it makes the next
    character literal outside single quotes, so `\\"` inside `bash -c "..."` does not close the string."""
    states = []
    quote = None
    opened = None
    depth = 0
    skip = False
    for i, c in enumerate(text):
        states.append((quote, depth, opened))
        if skip:
            skip = False
        elif c == esc and quote != "'":
            skip = True
        elif quote:
            if c == quote:
                quote = opened = None
        elif c in "\"'":
            quote, opened = c, i
        elif c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
    states.append((quote, depth, opened))
    return states


SHELL_ARG_RE = re.compile(  # what a quoted string must follow for a shell to run it: bash -c, pwsh -Command, cmd /c...
    r"""(?:^|[\s;&|(])(?:-\w*c|-command|/c|/k|eval|iex|invoke-expression)\s*$""", re.IGNORECASE)
NAME_RE = re.compile(r"""(?:gh|git|cd|chdir|pushd|popd|sl|set-location|push-location|pop-location)(?:\.exe)?""",
                     re.IGNORECASE)


SUBST_RE = re.compile(r"""(?:\$\(|`)\s*$""")  # `"$(gh pr merge 3)"`: a command substitution inside double quotes


def runs(command, pos, states):
    """Whether the command word at `pos` (gh, git, cd...) is run, not just text: it is outside quotes, it is a
    quoted program path (`"C:\\...\\gh.exe" pr merge`), it opens a command substitution in double quotes
    (`"$(gh ...)"`), or its quoted string is a shell's command argument (`bash -c "..."`, `pwsh -Command '...'`).
    Text in `git commit -m "..."`, `grep '...'` or `echo "..."` is not run."""
    quote, _, opened = states[pos]
    if quote is None:
        return True
    name = NAME_RE.match(command, pos)
    if name and command[name.end():name.end() + 1] == quote and (pos - 1 == opened or command[pos - 1] in "\\/"):
        return True  # the whole quoted word is the program: `"gh"`, `'C:\...\gh.exe'`
    if quote == '"' and SUBST_RE.search(command, opened + 1, pos):
        return True
    return SHELL_ARG_RE.search(command, 0, opened) is not None


def run_matches(regex, command, states):
    """The matches of `regex` (MERGE_RE, PUSH_RE) whose command word is run, not just quoted text."""
    return [m for m in regex.finditer(command) if runs(command, m.start(), states)]


def region_end(text, start, limit, esc, outer=None):
    """End of a command's arguments: the first separator, `)` or `#` comment outside quotes (a Bash backtick too:
    in PowerShell it is the escape), the closing `outer` quote when the command sits inside a quoted string
    (`bash -c "gh pr merge 3"`), or `limit`. The `&` of a redirect (`2>&1`, `&>file`) is not a separator."""
    quote = None
    skip = False
    n = min(len(text), limit)
    for i in range(start, n):
        c = text[i]
        if skip:
            skip = False
        elif c == esc and quote != "'":
            skip = True
        elif quote:
            if c == quote:
                quote = None
        elif c == outer:
            return i
        elif c in "\"'":
            quote = c
        elif c == "&" and (text[i - 1] == ">" or text[i + 1:i + 2] == ">"):
            continue
        elif c in ";|&\n\r)`":
            return i
        elif c == "#" and text[i - 1].isspace():
            return i
    return n


TOKEN_RE = re.compile(r"""(?:[^\s"']|"[^"]*"|'[^']*')+""")
REDIRECT_RE = re.compile(r"""^(?:[0-9]*|&)(?:>>?|<)&?""")
QUOTED_RE = re.compile(r""""([^"]*)"|'([^']*)'""")


def tokens(region):
    """Shell words, quotes removed, a quoted part inside a word kept whole (`--work-tree="C:\\a b"`). Backslashes stay
    as they are (Windows paths)."""
    out = []
    for t in TOKEN_RE.findall(region):
        t = QUOTED_RE.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), t)
        if t:
            out.append(t)
    return out


def parse_merge(region):
    """{selector, repo, disable_only, match_head} from the text after `gh pr merge`. `disable_only`: it has
    `--disable-auto` and nothing that merges or turns auto-merge on (--auto, --merge, --squash, --rebase, --admin)."""
    selector = repo = match_head = None
    disable_auto = merges = False
    toks = tokens(region)
    i = 0
    while i < len(toks):
        t = toks[i]
        i += 1
        redirect = REDIRECT_RE.match(t)
        if redirect:  # `2>&1`, `>out.txt`; a bare `>` or `2>` takes the next word as its file
            if redirect.end() == len(t) and not t.endswith("&"):
                i += 1
            continue
        if t.startswith("--"):
            name, eq, val = t.partition("=")
            if name == "--disable-auto":
                disable_auto = True
            elif name in ("--auto", "--merge", "--squash", "--rebase", "--admin"):
                merges = True
            elif name in VALUE_LONG:
                if not eq and i < len(toks):
                    val = toks[i]
                    i += 1
                if name == "--repo":
                    repo = val or repo
                elif name == "--match-head-commit":
                    match_head = val or match_head
        elif t.startswith("-") and len(t) > 1:
            # short flags, alone or in a cluster (`-sd`); a flag that takes a value ends the cluster: the value is
            # the rest of the word (`-tmerge`, `-Ro/r`) or, when the flag is last, the next word
            for k, c in enumerate(t[1:], 1):
                if c in "msr":  # -m, -s, -r
                    merges = True
                elif "-" + c in VALUE_SHORT:
                    if k == len(t) - 1:
                        val = toks[i] if i < len(toks) else ""
                        i += 1
                    else:
                        val = t[k + 1:]
                    if c == "R":
                        repo = val or repo
                    break
        elif selector is None:
            selector = t
    return {"selector": selector, "repo": repo, "disable_only": disable_auto and not merges, "match_head": match_head}


def find_merges(command, states, esc):
    """One dict per `gh pr merge`, with `pos`, where it starts in the command."""
    matches = run_matches(MERGE_RE, command, states)
    out = []
    for k, m in enumerate(matches):
        limit = matches[k + 1].start() if k + 1 < len(matches) else len(command)
        # the quote open after `merge`: a quoted command's (`bash -c "gh pr merge 3"`), not a quoted gh.exe path's
        end = region_end(command, m.end(), limit, esc, outer=states[m.end()][0])
        merge = parse_merge((m.group("pre") or "") + " " + command[m.end():end])
        merge["pos"] = m.start()
        out.append(merge)
    return out


def norm_dir(path, cwd):
    """A folder argument as a native path: strips quotes, expands ~, maps Git Bash /c/x to C:/x, resolves against cwd.
    UNKNOWN on Windows for a path rooted without a drive (`/tmp/x`: Git Bash maps it under its own install folder,
    PowerShell under the current drive) and for a relative path against an UNKNOWN cwd."""
    path = path.strip("\"'")
    if path == "~" or path.startswith(("~/", "~\\")):
        path = os.path.expanduser(path)
    if os.name == "nt":
        m = re.match(r"^/([A-Za-z])(?:/(.*))?$", path)
        if m:
            path = "%s:/%s" % (m.group(1), m.group(2) or "")
        elif re.match(r"^[/\\](?![/\\])", path):
            return UNKNOWN
    if not os.path.isabs(path) and cwd:
        if cwd == UNKNOWN:
            return UNKNOWN
        path = os.path.join(cwd, path)
    return path


def dir_at(command, pos, cwd, states):
    """The folder a command at `pos` runs in: cwd, moved by each `cd`/`Set-Location` before it. UNKNOWN when one of
    them goes somewhere the gate cannot resolve (`cd -`, a variable, `/tmp` on Windows), or is not a plain statement
    of its own: inside parentheses (a subshell in Bash, not in PowerShell), inside a quoted command
    (`bash -c "cd x && ..."`), `popd`, or a `cd` the gate cannot parse. A `cd` in quoted text that is not run
    (`git commit -m "cd x"`) does not count."""
    plain = {m.start("word"): m for m in CD_RE.finditer(command, 0, pos)}
    d = cwd
    for w in CD_WORD_RE.finditer(command, 0, pos):
        if not runs(command, w.start(), states):
            continue
        m = plain.get(w.start())
        quote, depth, _ = states[w.start()]
        if m is None or quote or depth:
            d = UNKNOWN
            continue
        arg = m.group("arg")
        if arg is None:  # a bare `cd` goes home
            d = os.path.expanduser("~")
        elif arg == "-" or "$" in arg or "%" in arg:
            d = UNKNOWN
        else:
            path = norm_dir(arg, None if d == UNKNOWN else d)
            d = path if path != UNKNOWN and os.path.isabs(path) else UNKNOWN
    return d


def push_dir(options, d):
    """The folder a `git [options] push` works in, from its -C, --work-tree and --git-dir options."""
    toks = tokens(options)
    work_tree = git_dir = None
    i = 0
    while i < len(toks):
        t = toks[i]
        i += 1
        name, eq, val = t.partition("=")
        if t == "-C" and i < len(toks):
            d = norm_dir(toks[i], d)  # several -C stack, as in git
            i += 1
        elif t == "-c":
            i += 1
        elif name in ("--work-tree", "--git-dir", "--namespace"):
            if not eq and i < len(toks):
                val = toks[i]
                i += 1
            if name == "--work-tree" and val:
                work_tree = norm_dir(val, d)
            elif name == "--git-dir" and val:
                git_dir = norm_dir(val, d).rstrip("/\\")
    if work_tree:
        return work_tree
    if git_dir:
        return os.path.dirname(git_dir) if os.path.basename(git_dir).lower() == ".git" else git_dir
    return d


def find_push_dirs(command, cwd, states):
    """One folder per `git push`, deduplicated. A push from a folder the gate cannot resolve is skipped (fail open)."""
    dirs = []
    for m in run_matches(PUSH_RE, command, states):
        d = dir_at(command, m.start(), cwd, states)
        if d == UNKNOWN:
            continue
        d = push_dir(m.group(1) or "", d)
        if d == UNKNOWN:
            continue
        if d not in dirs:
            dirs.append(d)
    return dirs


# ---- check ----

def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason,
    }}))


def check_merge(merge, directory, cwd, sets_gh_repo):
    selector, repo, match_head = merge["selector"], merge["repo"], merge["match_head"]
    by_url = bool(selector) and selector.lower().startswith(("http://", "https://"))
    where = "PR %s" % selector if selector else "this branch's PR"
    if not by_url and not repo:
        if sets_gh_repo:
            return ("Merge refused: the command sets GH_REPO, so the gate cannot be sure it checks the PR gh would "
                    "merge. Name the PR by its URL (or -R owner/repo), and use %s before merging." % SKILL)
        if directory == UNKNOWN:
            return ("Merge refused: the command changes folder in a way the gate cannot follow (`cd -`, a variable, a "
                    "subshell or a quoted command), so it cannot tell which repository's PR this is. Name the PR by its "
                    "URL, and use %s before merging." % SKILL)
    pr, err = view_pr(selector, repo, VIEW_MERGE, cwd if directory == UNKNOWN else directory)
    if pr is None:
        return ("Merge refused: could not read %s (%s). Fix that or name the PR explicitly, then use %s before merging."
                % (where, err, SKILL))
    url, sha = pr.get("url"), pr.get("headRefOid")
    if not url or not valid_sha(sha):
        return "Merge refused: gh gave no URL or head commit for %s. Use %s before merging." % (where, SKILL)
    if not has_record(url, sha):
        return ("Merge refused: PR #%s (%s) has no pre-merge review at head %s. Use %s: review this head, fix the real "
                "findings, record the review, then merge. If the head changes, the review has to be done again."
                % (pr.get("number"), url, sha[:7], SKILL))
    if (match_head or "").strip().lower() != sha.lower():
        found = "names %s, not" % match_head[:7] if match_head else "is missing; it must name"
        return ("Merge refused: --match-head-commit %s the reviewed head. Add `--match-head-commit %s` to the merge, so "
                "GitHub refuses it if the head moves after this check." % (found, sha))
    return None


def check_push(directory):
    pr, _ = view_pr(None, None, VIEW_PUSH, directory)
    if pr is None:  # no PR yet, or gh unavailable: a new branch must be pushable
        return None
    if pr.get("state") == "OPEN" and pr.get("autoMergeRequest"):
        return ("Push refused: PR #%s (%s) is open with auto-merge on, so the new commits would merge without a "
                "review. Run `gh pr merge %s --disable-auto` as its own command first (the gate reads auto-merge "
                "before a command runs, so a disable in the same command does not count), then push, then use %s "
                "and merge." % (pr.get("number"), pr.get("url"), pr.get("number"), SKILL))
    return None


def check_command(command, cwd, esc="\\"):
    """The refusal reasons for one shell command (empty = allowed). `esc`: the shell's escape character."""
    command = CONTINUATION_RE.sub(" ", command)
    states = scan(command, esc)
    reasons = []
    merges = [m for m in find_merges(command, states, esc) if not m["disable_only"]]
    if merges and run_matches(PUSH_RE, command, states):
        reasons.append("Merge refused: a command that pushes and merges together would merge unreviewed commits. "
                       "Push in one command, use %s, then merge in another." % SKILL)
    else:
        sets_gh_repo = "GH_REPO" in command
        seen = set()
        for merge in merges:
            directory = dir_at(command, merge["pos"], cwd, states)
            key = (merge["selector"], merge["repo"], merge["match_head"], directory)
            if key in seen:
                continue
            seen.add(key)
            reason = check_merge(merge, directory, cwd, sets_gh_repo)
            if reason:
                reasons.append(reason)
    for directory in find_push_dirs(command, cwd, states):
        reason = check_push(directory)
        if reason:
            reasons.append(reason)
    return reasons


def check(stdin_bytes):
    global _deadline
    try:
        data = json.loads(stdin_bytes.decode("utf-8-sig", errors="replace"))
        tool = data.get("tool_name")
        command = (data.get("tool_input") or {}).get("command")
        cwd = data.get("cwd") or None
    except (ValueError, AttributeError):
        return 0
    if tool not in ("Bash", "PowerShell") or not isinstance(command, str):
        return 0
    _deadline = time.monotonic() + GH_BUDGET
    command = CONTINUATION_RE.sub(" ", command)  # before the try, so the crash path sees a continued merge too
    try:
        reasons = check_command(command, cwd, "`" if tool == "PowerShell" else "\\")
    except Exception as e:  # a crash would exit 1, which Claude Code takes as allow: never for a merge
        reasons = []
        if MERGE_RE.search(command):
            reasons.append("Merge refused: the pre-merge gate failed (%s: %s). Fix gate.py, or merge after %s with "
                           "the gate working." % (type(e).__name__, e, SKILL))
    if reasons:
        deny(" ".join(reasons))
    return 0


# ---- record ----

def body_posted(comments, body):
    """Whether one of the PR's comments (gh's `comments` list) already has this body, line endings aside."""
    def norm(text):
        return text.replace("\r\n", "\n").strip() if isinstance(text, str) else None
    want = norm(body)
    return isinstance(comments, list) and any(isinstance(c, dict) and norm(c.get("body")) == want for c in comments)


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
    if re.fullmatch(r"[0-9a-f]{7,64}", seen) is None:  # 40 for SHA-1, 64 for SHA-256 repositories
        return fail("--head must be the reviewed commit, 7 to 64 hex characters, got %r" % args.head)
    pr, err = view_pr(args.pr, args.repo, VIEW_MERGE + ",comments", timeout=RECORD_TIMEOUT)
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
    if body_posted(pr.get("comments"), body):  # a retry after a timeout or a failed record write: post it once
        print("the same review comment is already on the PR; not posting it again")
    else:
        fd, tmp = tempfile.mkstemp(prefix="pre-merge-review-", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
            code, _, err = run_gh(["pr", "comment", args.pr] + (["-R", args.repo] if args.repo else [])
                                  + ["--body-file", tmp], timeout=RECORD_TIMEOUT)
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
