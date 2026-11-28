"""skills/pre-merge-review/gate.py: the PreToolUse gate and the record command, against a fake `gh`."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "skills", "pre-merge-review", "gate.py")

SHA_A = "a" * 40
SHA_B = "b" * 40
URL = "https://github.com/o/r/pull/7"
PIN = " --match-head-commit " + SHA_A  # every allowed merge names the reviewed head

# The fake gh. State (PRs, switches) is a JSON file the test rewrites; every call is appended to calls.jsonl.
FAKE_GH = r'''
import json, os, sys

state_path = os.environ["FAKE_GH_STATE"]
with open(state_path, encoding="utf-8") as f:
    state = json.load(f)
args = sys.argv[1:]
call = {"args": args, "cwd": os.getcwd()}
if args[:2] == ["pr", "comment"]:
    with open(args[args.index("--body-file") + 1], encoding="utf-8") as f:
        call["body"] = f.read()
with open(os.path.join(os.path.dirname(state_path), "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(call) + "\n")
if state.get("fail"):
    sys.stderr.write("gh: network down\nsecond line\n")
    sys.exit(1)
if args[:2] == ["pr", "view"]:
    rest = args[2:]
    selector = None
    i = 0
    while i < len(rest):
        if rest[i] in ("-R", "--json"):
            i += 2
            continue
        selector = rest[i]
        i += 1
    fields = rest[rest.index("--json") + 1].split(",")
    for pr in state["prs"]:
        if selector is None and pr.get("current") or selector in (str(pr["number"]), pr["url"], pr.get("branch")):
            print(json.dumps({k: pr.get(k) for k in fields}))
            sys.exit(0)
    sys.stderr.write('no pull requests found for "%s"\n' % selector)
    sys.exit(1)
if args[:2] == ["pr", "comment"]:
    if state.get("comment_fail"):
        sys.stderr.write("gh: comment refused\n")
        sys.exit(1)
    for pr in state["prs"]:  # GitHub keeps the comment: later views list it
        if args[2] in (str(pr["number"]), pr["url"]):
            pr.setdefault("comments", []).append({"body": call["body"].replace("\n", "\r\n")})
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    sys.exit(0)
sys.stderr.write("fake gh: unexpected %r\n" % args)
sys.exit(2)
'''


def pr(number=7, sha=SHA_A, state="OPEN", auto=None, current=True, branch="feat/x", url=None):
    return {"number": number, "url": url or "https://github.com/o/r/pull/%d" % number, "headRefOid": sha,
            "state": state, "autoMergeRequest": auto, "current": current, "branch": branch}


def load_gate():
    spec = importlib.util.spec_from_file_location("pre_merge_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pre merge ")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.records = os.path.join(self.tmp, "records")
        self.cwd = os.path.join(self.tmp, "my repo")
        os.makedirs(self.cwd)
        self.state_path = os.path.join(self.tmp, "state.json")
        self.calls_path = os.path.join(self.tmp, "calls.jsonl")
        self.fake = os.path.join(self.tmp, "fake_gh.py")
        with open(self.fake, "w", encoding="utf-8") as f:
            f.write(FAKE_GH)
        self.set_state([pr()])

    def set_state(self, prs, **extra):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(dict(prs=prs, **extra), f)

    def env(self):
        env = dict(os.environ)
        env.update(PRE_MERGE_REVIEW_DIR=self.records, PRE_MERGE_REVIEW_GH=self.fake, FAKE_GH_STATE=self.state_path,
                   HOME=self.tmp, USERPROFILE=self.tmp)  # `~` in a command is the test folder
        return env

    def run_gate(self, argv, stdin=None):
        return subprocess.run([sys.executable, "-I", "-S", GATE] + argv, input=stdin, capture_output=True, text=True,
                              encoding="utf-8", env=self.env())

    def check(self, command, tool="Bash", cwd=None):
        payload = {"tool_name": tool, "tool_input": {"command": command}, "cwd": cwd or self.cwd}
        p = self.run_gate(["check"], json.dumps(payload))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
        return json.loads(p.stdout) if p.stdout.strip() else None

    def denial(self, command, **kw):
        out = self.check(command, **kw)
        self.assertIsNotNone(out, "expected a refusal for: " + command)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "deny")
        return hso["permissionDecisionReason"]

    def calls(self):
        if not os.path.exists(self.calls_path):
            return []
        with open(self.calls_path, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]

    def view_calls(self):
        return [c for c in self.calls() if c["args"][:2] == ["pr", "view"]]

    def write_summary(self, text="Two findings, both fixed."):
        path = os.path.join(self.tmp, "summary.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def record(self, pr_ref="7", head=SHA_A, summary=None, *extra):
        return self.run_gate(["record", pr_ref, "--head", head, "--summary", summary or self.write_summary(), *extra])

    def record_files(self):
        return sorted(os.listdir(self.records)) if os.path.isdir(self.records) else []


class MergeTest(GateCase):
    def test_refused_without_a_record(self):
        reason = self.denial("gh pr merge --auto --merge")
        self.assertIn("#7", reason)
        self.assertIn(URL, reason)
        self.assertIn("aaaaaaa", reason)
        self.assertNotIn("a" * 8, reason)
        self.assertIn("pre-merge-review skill", reason)

    def test_allowed_with_a_record_and_refused_again_after_the_head_moves(self):
        p = self.record()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIsNone(self.check("gh pr merge 7 --squash --delete-branch" + PIN))
        self.set_state([pr(sha=SHA_B)])
        reason = self.denial("gh pr merge 7 --squash --delete-branch")
        self.assertIn("bbbbbbb", reason)

    def test_the_record_belongs_to_one_pr(self):
        self.record()
        self.set_state([pr(), pr(number=8, current=False)])
        self.assertIn("#8", self.denial("gh pr merge 8"))

    def test_disable_auto_passes_without_asking_gh(self):
        self.assertIsNone(self.check("gh pr merge 7 --disable-auto"))
        self.assertIsNone(self.check("gh pr merge --disable-auto"))
        self.assertEqual(self.calls(), [])

    def test_merge_chained_with_a_push_is_refused(self):
        self.record()
        for cmd in ("git push && gh pr merge 7 --auto", "gh pr merge 7; git push origin HEAD",
                    "git -C . push | gh pr merge 7"):
            self.assertIn("pushes and merges", self.denial(cmd), cmd)

    def test_selector_forms(self):
        self.set_state([pr(), pr(number=8, current=False, branch="fix/y")])
        self.record()
        cases = [
            ("gh pr merge", None, None),
            ("gh pr merge --squash", None, None),
            ("gh pr merge 8", "8", None),
            ("gh pr merge --squash 8 --delete-branch", "8", None),
            ("gh pr merge https://github.com/o/r/pull/8", "https://github.com/o/r/pull/8", None),
            ("gh pr merge fix/y", "fix/y", None),
            ("gh pr merge 8 -R o/r", "8", "o/r"),
            ("gh pr merge -R o/r 8", "8", "o/r"),
            ("gh pr merge 8 --repo o/r", "8", "o/r"),
            ("gh pr merge 8 --repo=o/r", "8", "o/r"),
            ("gh pr merge -Ro/r 8", "8", "o/r"),
            ("gh pr merge --body 'two words' 8", "8", None),
            ("gh pr merge --body \"a; b\" 8", "8", None),
            ("gh.exe pr merge 8", "8", None),
            ('"C:\\Program Files\\GitHub CLI\\gh.exe" pr merge 8', "8", None),
            # `pr`'s own -R/--repo before `merge`, and quoted words: gh takes them all
            ("gh pr -R o/r merge 8 --auto", "8", "o/r"),
            ("gh pr -Ro/r merge 8", "8", "o/r"),
            ("gh pr --repo o/r merge 8", "8", "o/r"),
            ("gh pr --repo=o/r merge 8", "8", "o/r"),
            ('gh "pr" merge 8', "8", None),
            ("gh pr 'merge' 8", "8", None),
            # a redirect's & does not end the arguments; an escaped quote does not end a quoted command
            ("gh pr merge 2>&1 8 -R o/r", "8", "o/r"),
            ('bash -c "gh pr merge 8 --subject \\"a b\\" -R o/r"', "8", "o/r"),
        ]
        for cmd, selector, repo in cases:
            with self.subTest(cmd=cmd):
                os.path.exists(self.calls_path) and os.remove(self.calls_path)
                self.check(cmd)
                views = self.view_calls()
                self.assertEqual(len(views), 1)
                args = views[0]["args"]
                self.assertEqual(args[:2], ["pr", "view"])
                self.assertEqual(args[2] if selector else None, selector)
                self.assertEqual(args[args.index("-R") + 1] if "-R" in args else None, repo)
                self.assertEqual(args[args.index("--json") + 1], "url,number,headRefOid,state")

    def test_the_current_branch_pr_is_resolved_in_cwd(self):
        self.check("gh pr merge")
        self.assertEqual(os.path.normcase(self.view_calls()[0]["cwd"]), os.path.normcase(self.cwd))

    def test_several_merges_in_one_command(self):
        self.set_state([pr(), pr(number=8, current=False)])
        self.record("7")
        reason = self.denial("gh pr merge 7 --squash && gh pr merge 8 --squash")
        self.assertIn("#8", reason)
        self.assertNotIn("#7 ", reason)
        self.record("8")
        self.assertIsNone(self.check("gh pr merge 7 --squash" + PIN + " && gh pr merge 8 --squash" + PIN))
        self.assertIsNone(self.check("gh pr merge 7" + PIN + "\ngh pr merge 8" + PIN))
        # a disable-auto on one does not excuse the other
        self.set_state([pr(number=9, current=False), pr(number=10, current=False)])
        self.assertIn("#9", self.denial("gh pr merge 9 && gh pr merge 10 --disable-auto"))
        self.assertIn("#10", self.denial("gh pr merge 9 --disable-auto; gh pr merge 10"))

    def test_merge_inside_a_powershell_command(self):
        self.assertIn("#7", self.denial("& gh.exe pr merge 7 --auto --merge", tool="PowerShell"))
        self.assertIn("#7", self.denial("gh pr create --fill; gh pr merge --auto --merge", tool="PowerShell"))
        self.record()
        self.assertIsNone(self.check("gh pr merge 7 --squash" + PIN, tool="PowerShell"))

    def test_gh_failing_refuses_the_merge(self):
        self.record()
        self.set_state([pr()], fail=True)
        reason = self.denial("gh pr merge 7")
        self.assertIn("network down", reason)
        self.assertNotIn("second line", reason)
        self.assertIn("pre-merge-review skill", reason)

    def test_an_unknown_pr_refuses_the_merge(self):
        self.assertIn("no pull requests found", self.denial("gh pr merge 99"))

    def test_a_missing_gh_refuses_the_merge(self):
        env = self.env()
        env["PRE_MERGE_REVIEW_GH"] = os.path.join(self.tmp, "nope.py")
        p = subprocess.run([sys.executable, "-I", "-S", GATE, "check"], capture_output=True, text=True, env=env,
                           input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "gh pr merge 7"},
                                             "cwd": self.cwd}))
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_a_nonexistent_cwd_refuses_the_merge(self):
        self.assertIn("pre-merge-review skill", self.denial("gh pr merge 7", cwd=os.path.join(self.tmp, "gone")))

    def test_a_merge_inside_another_command_or_quotes_is_still_caught(self):
        # the choice: a false refusal is acceptable, a missed merge is not
        for cmd, tool in (('bash -c "gh pr merge 7 --auto"', "Bash"), ('cmd /c "gh pr merge 7"', "Bash"),
                          ("bash -lc 'gh pr merge 7'", "Bash"), ('eval "gh pr merge 7"', "Bash"),
                          ('echo "$(gh pr merge 7)"', "Bash"), ('echo "`gh pr merge 7`"', "Bash"),
                          ('"C:\\Program Files\\GitHub CLI\\gh.exe" pr merge 7', "Bash"),
                          ("pwsh -Command 'gh pr merge 7'", "PowerShell"),
                          ("& 'C:\\Program Files\\GitHub CLI\\gh.exe' pr merge 7", "PowerShell"),
                          ('Invoke-Expression "gh pr merge 7"', "PowerShell"),
                          ('echo "now gh pr merge 7"', "Bash"), ('echo "$(true && gh pr merge 7 --squash)"', "Bash"),
                          # an apostrophe in a heredoc, here-string or comment must not hide what follows
                          ("git commit -F - <<'EOF'\nit's done\nEOF\ngh pr merge 7 --squash", "Bash"),
                          ("echo hi # it's\ngh pr merge 7 --squash", "Bash"),
                          ("git commit -m @'\nit's fixed\n'@; gh pr merge 7", "PowerShell")):
            self.assertIn("Merge refused", self.denial(cmd, tool=tool), cmd)

    def test_quoted_text_counts_too(self):
        # the choice: telling run commands from text needs a real shell parser, so a mention is refused as well
        for cmd in ("grep -n 'gh pr merge' README.md", 'git commit -m "docs: gh pr merge needs a review"'):
            self.assertIn("Merge refused", self.denial(cmd), cmd)

    def test_a_misread_quote_cannot_cut_a_disable_auto_merge_short(self):
        self.assertIn("#7", self.denial("echo hi # it's\ngh pr merge 7 --disable-auto --body 'x' --auto"))
        self.assertIsNone(self.check("echo hi # it's\ngh pr merge 7 --disable-auto"))

    def test_a_corrupt_record_does_not_count(self):
        self.record()
        (name,) = self.record_files()
        with open(os.path.join(self.records, name), "w") as f:
            f.write("{not json")
        self.assertIn("#7", self.denial("gh pr merge 7"))

    def test_a_cd_in_the_command_moves_where_the_pr_is_looked_up(self):
        other = os.path.join(self.tmp, "other repo")
        os.makedirs(os.path.join(other, "sub"))
        self.record()
        cases = [
            ('cd "%s" && gh pr merge 7 --squash' % other, other),
            ("cd '../other repo' && gh pr merge 7", other),
            ('cd "%s"; cd sub; gh pr merge 7' % other, os.path.join(other, "sub")),
            ("Set-Location -Path '%s'; gh pr merge 7" % other, other),
            ('cd /d "%s" && gh pr merge 7' % other, other),
            ("gh pr merge 7 && cd '%s'" % other, self.cwd),
            ("cd && gh pr merge 7", self.tmp),
        ]
        for cmd, where in cases:
            with self.subTest(cmd=cmd):
                os.path.exists(self.calls_path) and os.remove(self.calls_path)
                self.assertIsNone(self.check(cmd.replace("gh pr merge 7", "gh pr merge 7" + PIN)))
                self.assertEqual(os.path.normcase(os.path.normpath(self.view_calls()[0]["cwd"])),
                                 os.path.normcase(os.path.normpath(where)))

    def test_a_cd_the_gate_cannot_follow_needs_the_pr_url(self):
        self.record()
        os.remove(self.calls_path)
        for cmd in ("cd - && gh pr merge 7", 'cd "$REPO" && gh pr merge', "cd $env:X; gh pr merge 7"):
            self.assertIn("by its URL", self.denial(cmd), cmd)
        self.assertEqual(self.calls(), [])
        self.assertIsNone(self.check("cd - && gh pr merge %s --squash" % URL + PIN))
        self.assertEqual(os.path.normcase(self.view_calls()[0]["cwd"]), os.path.normcase(self.cwd))

    def test_line_continuations_keep_the_selector_and_the_repo(self):
        self.set_state([pr(), pr(number=8, current=False)])
        self.record()
        for cmd, tool in (("gh pr merge \\\n  8 --squash", "Bash"), ("gh pr merge `\r\n  8 -R o/r", "PowerShell")):
            with self.subTest(cmd=cmd):
                os.path.exists(self.calls_path) and os.remove(self.calls_path)
                self.assertIn("#8", self.denial(cmd, tool=tool))
                self.assertEqual(self.view_calls()[0]["args"][2], "8")

    def test_gh_repo_in_the_command_needs_a_url_or_repo(self):
        self.record()
        os.remove(self.calls_path)
        self.assertIn("GH_REPO", self.denial("GH_REPO=a/b gh pr merge 7"))
        self.assertIn("GH_REPO", self.denial("$env:GH_REPO = 'a/b'; gh pr merge", tool="PowerShell"))
        self.assertEqual(self.calls(), [])
        self.assertIsNone(self.check("GH_REPO=o/r gh pr merge 7 -R o/r" + PIN))
        self.assertIsNone(self.check("GH_REPO=o/r gh pr merge %s" % URL + PIN))

    def test_match_head_commit_must_name_the_full_reviewed_head(self):
        self.record()
        self.assertIsNone(self.check("gh pr merge 7 --auto --merge --match-head-commit " + SHA_A.upper()))
        self.assertIsNone(self.check("gh pr merge 7 --match-head-commit=" + SHA_A))
        for cmd, said in (("gh pr merge 7 --auto --merge", "is missing"),
                          ("gh pr merge 7 --match-head-commit aaaaaaa", "names aaaaaaa, not"),
                          ("gh pr merge 7 --match-head-commit bbbbbbb", "names bbbbbbb, not")):
            reason = self.denial(cmd)
            self.assertIn(said, reason, cmd)
            self.assertIn("--match-head-commit " + SHA_A, reason, cmd)
        # with no record, the missing review comes first
        self.set_state([pr(sha=SHA_B)])
        self.assertIn("no pre-merge review", self.denial("gh pr merge 7"))

    def test_a_disable_auto_counts_only_on_a_merge_that_does_nothing_else(self):
        for cmd in ("gh pr merge 7 --auto --merge # --disable-auto", "gh pr merge 7 --squash --disable-auto",
                    "gh pr merge 7 -s --disable-auto", "gh pr merge 7 --disable-auto --admin",
                    'bash -c "gh pr merge 7 --auto" && echo x --disable-auto',
                    "gh pr merge 7 --disable-auto 2>&1 --auto"):
            self.assertIn("#7", self.denial(cmd), cmd)
        self.assertIsNone(self.check("gh pr merge 7 --disable-auto -d"))

    def test_short_flag_clusters_and_attached_values(self):
        # a value flag (-t, -b, -F, -A, -R) ends its cluster: `-tmerge` is a subject, not -m
        for cmd in ("gh pr merge 7 --disable-auto -tmerge", "gh pr merge 7 --disable-auto -bsquash",
                    "gh pr merge 7 --disable-auto -dt rsm"):
            self.assertIsNone(self.check(cmd), cmd)
        self.assertEqual(self.calls(), [])
        for cmd in ("gh pr merge 7 --disable-auto -sd", "gh pr merge 7 --disable-auto -dm"):
            self.assertIn("#7", self.denial(cmd), cmd)
        self.set_state([pr(), pr(number=8, current=False)])
        for cmd in ("gh pr merge 8 -sRo/r", "gh pr merge 8 -sR o/r"):
            os.path.exists(self.calls_path) and os.remove(self.calls_path)
            self.assertIn("#8", self.denial(cmd), cmd)
            self.assertEqual(self.view_calls()[0]["args"][2:5], ["8", "-R", "o/r"], cmd)

    def test_a_powershell_backtick_escape_does_not_end_a_quoted_command(self):
        reason = self.denial('bash -c "gh pr merge 8 --subject `"a b`" -R o/r"', tool="PowerShell")
        self.assertIn("no pull requests found", reason)  # the fake gh was asked for 8 in o/r: the -R was seen
        self.assertEqual(self.view_calls()[0]["args"][2:5], ["8", "-R", "o/r"])

    def test_a_cd_in_a_subshell_or_quotes_needs_the_pr_url(self):
        other = os.path.join(self.tmp, "other repo")
        os.makedirs(other)
        self.record()
        os.remove(self.calls_path)
        for cmd in ('(cd "%s"); gh pr merge 7' % other, "bash -c \"cd '%s' && gh pr merge 7\"" % other,
                    "popd; gh pr merge 7", "echo cd; gh pr merge 7"):
            self.assertIn("by its URL", self.denial(cmd + PIN), cmd)
        self.assertEqual(self.calls(), [])
        self.assertIsNone(self.check('(cd "%s"); gh pr merge %s' % (other, URL) + PIN))

    def test_a_cd_in_quoted_text_needs_the_pr_url(self):
        self.record()
        os.remove(self.calls_path)
        self.assertIn("by its URL", self.denial('git commit -m "cd elsewhere" && gh pr merge 7' + PIN))
        self.assertEqual(self.calls(), [])
        self.assertIsNone(self.check('git commit -m "cd elsewhere" && gh pr merge %s' % URL + PIN))

    @unittest.skipUnless(os.name == "nt", "a drive-less rooted path is Windows-only")
    def test_a_rooted_path_without_a_drive_needs_the_pr_url(self):
        self.record()
        os.remove(self.calls_path)
        for cmd in ("cd /tmp/x && gh pr merge 7", "cd \\x; gh pr merge 7"):
            self.assertIn("by its URL", self.denial(cmd + PIN), cmd)
        self.assertEqual(self.calls(), [])


class PushTest(GateCase):
    def test_refused_for_an_open_pr_with_auto_merge_on(self):
        self.set_state([pr(auto={"enabledBy": {"login": "x"}, "mergeMethod": "MERGE"})])
        reason = self.denial("git push")
        self.assertIn("gh pr merge 7 --disable-auto", reason)
        self.assertIn("pre-merge-review skill", reason)
        self.assertEqual(self.view_calls()[0]["args"][-1], "url,number,state,autoMergeRequest")

    def test_allowed_when_auto_merge_is_null_off_or_the_pr_is_not_open(self):
        self.set_state([pr(auto=None)])
        self.assertIsNone(self.check("git push -u origin feat/x"))
        self.set_state([pr(state="MERGED", auto={"mergeMethod": "MERGE"})])
        self.assertIsNone(self.check("git push"))
        self.set_state([pr(state="CLOSED", auto={"mergeMethod": "MERGE"})])
        self.assertIsNone(self.check("git push"))
        self.assertEqual(len(self.view_calls()), 3)

    def test_allowed_when_gh_fails_or_there_is_no_pr(self):
        self.set_state([pr(auto={"mergeMethod": "MERGE"})], fail=True)
        self.assertIsNone(self.check("git push"))
        self.set_state([])
        self.assertIsNone(self.check("git push -u origin new-branch"))

    def test_git_dash_C_and_dash_c_before_push(self):
        other = os.path.join(self.tmp, "other repo")
        os.makedirs(other)
        self.set_state([pr(auto={"mergeMethod": "MERGE"})])
        for cmd in ('git -C "%s" push' % other, "git -C '%s' push origin x" % other):
            with self.subTest(cmd=cmd):
                os.path.exists(self.calls_path) and os.remove(self.calls_path)
                self.assertIn("--disable-auto", self.denial(cmd))
                self.assertEqual(os.path.normcase(self.view_calls()[0]["cwd"]), os.path.normcase(other))
        os.remove(self.calls_path)
        self.assertIn("--disable-auto", self.denial("git -c push.default=current push"))
        self.assertEqual(os.path.normcase(self.view_calls()[0]["cwd"]), os.path.normcase(self.cwd))
        os.remove(self.calls_path)
        os.makedirs(os.path.join(self.cwd, "sub"))
        self.denial("git -C sub -c k=v push")
        self.assertEqual(os.path.normcase(self.view_calls()[0]["cwd"]), os.path.normcase(os.path.join(self.cwd, "sub")))

    def test_tilde_git_dir_work_tree_and_cd_place_the_push(self):
        other = os.path.join(self.tmp, "other repo")
        os.makedirs(other)
        os.makedirs(os.path.join(self.tmp, "plain"))
        self.set_state([pr(auto={"mergeMethod": "MERGE"})])
        cases = [
            ("git -C ~/plain push", os.path.join(self.tmp, "plain")),
            ('git --git-dir "%s" push' % os.path.join(other, ".git"), other),
            ('git --work-tree="%s" push' % other, other),
            ('cd "%s" && git push' % other, other),
            ("Set-Location '%s'; git push" % other, other),
        ]
        for cmd, where in cases:
            with self.subTest(cmd=cmd):
                os.path.exists(self.calls_path) and os.remove(self.calls_path)
                self.assertIn("as its own command", self.denial(cmd))
                self.assertEqual(os.path.normcase(os.path.normpath(self.view_calls()[0]["cwd"])),
                                 os.path.normcase(os.path.normpath(where)))

    def test_a_push_from_a_folder_the_gate_cannot_follow_passes(self):
        self.set_state([pr(auto={"mergeMethod": "MERGE"})])
        self.assertIsNone(self.check("cd - && git push"))
        self.assertEqual(self.calls(), [])

    def test_a_disable_in_the_same_command_does_not_count(self):
        self.set_state([pr(auto={"mergeMethod": "MERGE"})])
        reason = self.denial("gh pr merge 7 --disable-auto && git push")
        self.assertIn("as its own command", reason)

    def test_the_push_is_in_a_chain_or_powershell(self):
        self.set_state([pr(auto={"mergeMethod": "MERGE"})])
        self.assertIn("--disable-auto", self.denial("git add -A && git commit -m x && git push"))
        self.assertIn("--disable-auto", self.denial("git commit -m x; git push", tool="PowerShell"))

    def test_other_git_commands_are_not_pushes(self):
        self.set_state([pr(auto={"mergeMethod": "MERGE"})])
        for cmd in ("git status", "git pull", "git pushd", "git log --oneline", "echo git-push"):
            self.assertIsNone(self.check(cmd), cmd)
        self.assertEqual(self.calls(), [])

    def test_a_quoted_push_or_one_after_a_here_string_is_checked(self):
        self.set_state([pr(auto={"mergeMethod": "MERGE"})])
        for cmd, tool in (("bash -c 'git push'", "Bash"), ("git commit -m @'\nit's fixed\n'@; git push", "PowerShell"),
                          ("git commit -F - <<'EOF'\nit's done\nEOF\ngit push", "Bash")):
            self.assertIn("--disable-auto", self.denial(cmd, tool=tool), cmd)

    def test_a_push_in_quoted_text_still_joins_a_merge(self):
        self.record()
        self.assertIn("pushes and merges together",
                      self.denial('git commit -m "push with git push" && gh pr merge 7' + PIN))

    def test_norm_dir(self):
        gate = load_gate()
        self.assertEqual(gate.norm_dir('"C:\\a b"', "X:\\cwd"), "C:\\a b" if os.name == "nt" else os.path.join("X:\\cwd", "C:\\a b"))
        if os.name == "nt":
            self.assertEqual(gate.norm_dir("/c/dev/x", "C:\\cwd"), "c:/dev/x")
            self.assertEqual(gate.norm_dir("sub", "C:\\cwd"), os.path.join("C:\\cwd", "sub"))
            self.assertEqual(gate.norm_dir("/tmp/x", "C:\\cwd"), gate.UNKNOWN)
            self.assertEqual(gate.norm_dir("\\x", "C:\\cwd"), gate.UNKNOWN)
            self.assertEqual(gate.norm_dir("//server/share", "C:\\cwd"), "//server/share")
        self.assertEqual(gate.norm_dir("sub", gate.UNKNOWN), gate.UNKNOWN)


class PassThroughTest(GateCase):
    def test_non_shell_tools_pass_with_no_output(self):
        for tool in ("Read", "Edit", "Task", ""):
            p = self.run_gate(["check"], json.dumps({"tool_name": tool, "tool_input": {"command": "gh pr merge 7"},
                                                     "cwd": self.cwd}))
            self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""), tool)

    def test_unrelated_commands_pass_with_no_output(self):
        for cmd in ("ls -la", "gh pr view 7", "gh pr create --fill", "gh pr checks 7", "gh pr comment 7 -b merge",
                    "gh issue merge", "echo gh pr", "git status && git diff", "mygh pr merge 7", "python -m unittest"):
            p = self.run_gate(["check"], json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd},
                                                     "cwd": self.cwd}))
            self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""), cmd)
        self.assertEqual(self.calls(), [])

    def test_bad_input_passes(self):
        for stdin in ("", "not json", "[]", "{}", json.dumps({"tool_name": "Bash"}),
                      json.dumps({"tool_name": "Bash", "tool_input": {"command": None}})):
            p = self.run_gate(["check"], stdin)
            self.assertEqual((p.returncode, p.stdout), (0, ""), stdin)


class RecordTest(GateCase):
    def test_posts_the_comment_and_writes_the_record(self):
        p = self.record("7", SHA_A, self.write_summary("Found two things.\nBoth fixed."))
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertEqual(p.stdout.strip(), "recorded %s at aaaaaaa" % URL)
        (comment,) = [c for c in self.calls() if c["args"][:2] == ["pr", "comment"]]
        self.assertEqual(comment["args"][2], "7")
        first, _, rest = comment["body"].partition("\n")
        self.assertEqual(first, "**Pre-merge review** of %s (built-in `/code-review high`)" % SHA_A)
        self.assertIn("Found two things.\nBoth fixed.", rest)
        name = "%s-%s.json" % (hashlib.sha256(URL.encode()).hexdigest()[:16], SHA_A)
        self.assertEqual(self.record_files(), [name])
        with open(os.path.join(self.records, name), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual((data["url"], data["sha"]), (URL, SHA_A))
        self.assertIn("recorded_at", data)

    def test_a_retry_does_not_post_the_same_comment_twice(self):
        # the first try posted the comment and failed after it (a timeout, an unwritable record folder)
        self.assertEqual(self.record().returncode, 0)
        os.remove(os.path.join(self.records, self.record_files()[0]))
        p = self.record()
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertIn("already on the PR", p.stdout)
        self.assertIn("recorded %s at aaaaaaa" % URL, p.stdout)
        self.assertEqual(len([c for c in self.calls() if c["args"][:2] == ["pr", "comment"]]), 1)
        self.assertEqual(len(self.record_files()), 1)
        # a changed summary is a new comment
        self.assertEqual(self.record("7", SHA_A, self.write_summary("Round two: one more fix.")).returncode, 0)
        self.assertEqual(len([c for c in self.calls() if c["args"][:2] == ["pr", "comment"]]), 2)

    def test_the_comment_goes_through_the_repo_flag(self):
        self.assertEqual(self.record("7", SHA_A, None, "-R", "o/r").returncode, 0)
        for c in self.calls():
            self.assertEqual(c["args"][c["args"].index("-R") + 1], "o/r")

    def test_a_matching_full_sha_and_a_short_prefix_both_work(self):
        self.assertEqual(self.record("7", SHA_A).returncode, 0)
        os.remove(os.path.join(self.records, self.record_files()[0]))
        p = self.record("7", SHA_A[:7].upper())
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        # the record and the comment carry the PR's full head, not the prefix
        self.assertEqual(len(self.record_files()), 1)
        self.assertIn(SHA_A, self.record_files()[0])
        self.assertIn(SHA_A, [c for c in self.calls() if "body" in c][-1]["body"].splitlines()[0])
        self.assertIsNone(self.check("gh pr merge 7" + PIN))

    def test_a_moved_head_is_refused_with_no_comment_and_no_record(self):
        self.set_state([pr(sha=SHA_B)])
        for head in (SHA_A, SHA_A[:7]):
            p = self.record("7", head)
            self.assertEqual(p.returncode, 1)
            self.assertIn("head moved", p.stderr)
            self.assertIn("pre-merge-review skill", p.stderr)
        self.assertEqual([c for c in self.calls() if c["args"][:2] == ["pr", "comment"]], [])
        self.assertEqual(self.record_files(), [])

    def test_a_sha256_head_can_be_recorded(self):
        sha256 = "c" * 64
        self.set_state([pr(sha=sha256)])
        p = self.record("7", sha256)
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertIsNone(self.check("gh pr merge 7 --match-head-commit " + sha256))

    def test_a_prefix_shorter_than_seven_is_refused(self):
        p = self.record("7", SHA_A[:6])
        self.assertEqual(p.returncode, 1)
        self.assertIn("--head", p.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.record_files(), [])

    def test_head_is_required_and_must_be_hex(self):
        p = self.run_gate(["record", "7", "--summary", self.write_summary()])
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.record("7", "zzzzzzzz").returncode, 1)
        self.assertEqual(self.record_files(), [])

    def test_a_closed_pr_is_refused(self):
        for state in ("CLOSED", "MERGED"):
            self.set_state([pr(state=state)])
            p = self.record()
            self.assertEqual(p.returncode, 1, state)
            self.assertIn(state, p.stderr)
            self.assertIn("pre-merge-review skill", p.stderr)
        self.assertEqual(self.record_files(), [])
        self.assertEqual([c for c in self.calls() if c["args"][:2] == ["pr", "comment"]], [])

    def test_an_empty_summary_is_refused(self):
        for text in ("", "  \n\n"):
            p = self.record("7", SHA_A, self.write_summary(text))
            self.assertEqual(p.returncode, 1)
            self.assertIn("pre-merge-review skill", p.stderr)
        p = self.record("7", SHA_A, os.path.join(self.tmp, "missing.md"))
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.record_files(), [])
        self.assertEqual(self.calls(), [])

    def test_nothing_is_recorded_when_the_comment_fails(self):
        self.set_state([pr()], comment_fail=True)
        p = self.record()
        self.assertEqual(p.returncode, 1)
        self.assertIn("comment refused", p.stderr)
        self.assertEqual(self.record_files(), [])
        self.assertIn("#7", self.denial("gh pr merge 7"))

    def test_gh_failing_on_the_view_records_nothing(self):
        self.set_state([pr()], fail=True)
        p = self.record()
        self.assertEqual(p.returncode, 1)
        self.assertIn("network down", p.stderr)
        self.assertEqual(self.record_files(), [])


class PatternTimeTest(unittest.TestCase):
    """A failed search must stay fast: a hook killed at its timeout lets the command run. 24 repeats took the old,
    ambiguous patterns about 5 s (doubling with each one), so a regression fails here instead of hanging."""

    def test_repeated_options_do_not_backtrack(self):
        gate = load_gate()
        n = 24
        cases = [(gate.PUSH_RE, "git" + opt * n, " push") for opt in
                 (" -c a=b", " -C 'x'", ' -c "a b"', " -C x", " --git-dir --x", " --a=b", " -p", " -P")]
        cases += [(gate.MERGE_RE, "gh pr" + opt * n, " merge 3") for opt in
                  (' -R "x"', " -R x", " -Rx", " --repo x", " --repo=x", " -r 'x'")]
        for regex, head, tail in cases:
            with self.subTest(text=head[:24]):
                for text, found in ((head + " commit", False), (head + tail, True)):
                    start = time.perf_counter()
                    match = regex.search(text)
                    self.assertLess(time.perf_counter() - start, 0.5)
                    self.assertEqual(match is not None, found)


class FailClosedTest(unittest.TestCase):
    """In-process: a crash or the gh time budget refuses a merge and lets a push through."""

    def run_check(self, gate, command):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": ROOT}).encode()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(gate.check(payload), 0)
        return json.loads(out.getvalue()) if out.getvalue().strip() else None

    def test_a_crash_refuses_a_merge_and_lets_a_push_through(self):
        gate = load_gate()

        def boom(*_):
            raise RuntimeError("parser bug")

        gate.find_merges = boom
        for command in ("gh pr merge 7 --squash", "gh pr \\\n  merge 7", "gh pr -R o/r merge 7"):
            out = self.run_check(gate, command)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny", command)
            self.assertIn("RuntimeError: parser bug", out["hookSpecificOutput"]["permissionDecisionReason"])
        gate = load_gate()
        gate.find_push_dirs = boom
        self.assertIsNone(self.run_check(gate, "git push"))

    def test_the_time_budget_refuses_a_merge_and_lets_a_push_through(self):
        gate = load_gate()
        gate.GH_BUDGET = 0
        gate.subprocess = None  # any gh call would crash, and a crash would show a different reason
        out = self.run_check(gate, "gh pr merge 7")
        self.assertIn("budget", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.run_check(gate, "git push"))


if __name__ == "__main__":
    unittest.main()
