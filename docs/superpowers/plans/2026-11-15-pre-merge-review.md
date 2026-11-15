# Pre-merge review: a skill and a gate hook

The user's choices (2026-11-15): user level, from this repo, for every project; a hook enforces it; the reviewer is the
built-in `/code-review` at `high`; Claude triages the findings, fixes the real ones, reviews new commits again, then merges.

Why: in the omnichannel repo a PR got `gh pr merge --auto --merge` right after `gh pr create`, CI passed and GitHub merged
it while the user's own `/code-review` of it was still running.

## Parts

1. `skills/pre-merge-review/SKILL.md`: the procedure (Claude writes it; see Task 2).
2. `skills/pre-merge-review/gate.py`: stdlib-only Python (runs under `python -I -S`), two commands:
   - `gate.py check`: the PreToolUse hook. Reads the hook JSON on stdin (`tool_name`, `tool_input.command`, `cwd`). Acts
     only for `Bash` and `PowerShell`. To refuse, it prints
     `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`
     and exits 0; to allow, it prints nothing and exits 0. Rules:
     - **merge**: every `gh pr merge` in the command (`gh` or `gh.exe`; split on `&&`, `||`, `;`, `|`, newlines), unless that
       one has `--disable-auto`. A command that also runs `git push` is refused (push, then review, then merge, as separate
       commands). Otherwise the PR is resolved with `gh pr view [selector] [-R repo] --json url,number,headRefOid,state` in
       `cwd` (selector = the first positional after `merge`: a number, URL or branch; none = the current branch). Allowed
       only if a record exists for that `url` at that `headRefOid`. If `gh` fails, refused (fail closed) with its first
       stderr line. The refusal names the PR, the short head SHA and the next step (the `pre-merge-review` skill).
     - **push**: every `git push` (allowing `git -C <dir>` and `git -c k=v` before `push`). The current branch's PR (in
       `cwd`, or the `-C` dir) is read with `gh pr view --json url,number,state,autoMergeRequest`. Refused only when that PR
       is OPEN and `autoMergeRequest` is set: new commits would merge unreviewed; the reason says to run
       `gh pr merge <n> --disable-auto` first. When `gh` fails or there is no PR, allowed (fail open: a new branch must push).
   - `gate.py record <pr> --head <sha> --summary <file> [-R repo]`: run from the repo. `--head` is required: the commit
     the review saw (a full SHA, or a prefix of at least 7 characters). Reads the PR (`url`, `number`, `headRefOid`,
     `state`; must be OPEN) and refuses (exit 1, nothing posted, nothing written) when its `headRefOid` is not `--head`:
     the head moved since the review, review the new head. Then posts a PR comment (`gh pr comment <pr> --body-file <tmp>`) whose first line is
     `**Pre-merge review** of <full sha> (built-in \`/code-review high\`)`, then the summary file's text; then writes the
     record and prints `recorded <url> at <sha7>`. Refuses an empty summary. Exit 1 with a message on any failure, and no
     record is written when the comment fails.
   - Records: one JSON file per (url, sha) in `~/.claude/pre-merge-review/` (`<sha256(url)[:16]>-<sha>.json` holding
     `url`, `sha`, `recorded_at`). Tests override the folder with `PRE_MERGE_REVIEW_DIR` and the `gh` command with
     `PRE_MERGE_REVIEW_GH` (a path to a Python script run with the current interpreter).
   - Not covered, said in the skill: merges through `gh api` or the web page; a push of another branch than the current
     one; the user's own `!` commands (hooks never see them; that is the user's escape hatch).
   - After the first review of PR #65: a `cd`/`Set-Location` earlier in the command moves where the PR is looked up (one the gate cannot follow, or `GH_REPO`, needs the PR's URL); `\`/backtick line continuations are joined; `~`, `--git-dir` and `--work-tree` place a push; a crash or the 20 s budget for all `gh` calls refuses a merge (a killed hook would let it run); `--match-head-commit` must name the head, and the skill's merge uses it.
3. `settings.json` (template): `hooks.PreToolUse` gets
   `{"matcher": "Bash|PowerShell", "hooks": [{"type": "command", "command": "python -I -S ~/.claude/skills/pre-merge-review/gate.py check", "timeout": 30}]}`.
   `install.ps1` already copies `skills/` and merges hook events (`Merge-HookEvents`); check that nothing in it or its tests
   assumes the template has no hooks, and that the installed settings get the entry.
4. Docs: `global/CLAUDE.md` (the user level now also holds the pre-merge-review skill and its gate; the Git default names
   the review before any `gh pr merge`), `README.md` (the user-level list and the hooks section), this repo's `CLAUDE.md`
   Flow line (its own `gh pr merge N --squash --delete-branch` passes the gate too).

## Tasks

- [x] **Task 1 (worker, Sonnet, effort high): gate.py, its tests, the template and the docs of part 3 and 4.** Tests in
  `tests/test_pre_merge.py` (unittest, the style of `tests/test_hooks.py`), with a fake `gh`: merge refused without a
  record, allowed with one, refused again after the head moves; `--disable-auto` passes; `gh pr merge` chained with
  `git push` refused; selector forms (none, number, URL, branch, `-R`); several merges in one command; a merge inside a
  PowerShell command; `gh` failing → merge refused, push allowed; push refused only for an open PR with auto-merge on;
  `git -C dir push`; record posts the comment and writes the file, refuses a closed PR or an empty summary, writes nothing
  when the comment fails; non-shell tools and unrelated commands pass with no output. Then
  `python -m unittest discover -s tests -q`: all pass.
- [x] **Task 2 (Claude): SKILL.md.** Baseline: the omnichannel session of 2026-11-15 (merge turned on at PR creation,
  review after the merge). Then a check with a fresh agent that, given the skill, plans the commands for "CI is green on
  PR #N, merge it" and for "CI failed after auto-merge was on; fix and merge".
- [ ] **Task 3 (Claude): verify, PR, install.** Full test suite; PR; after the merge, `install.ps1` from main, then
  `/setup-check`; a live check in a scratch repo is not needed: the hook's refusal shows on the first real merge.
