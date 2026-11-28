---
name: pre-merge-review
description: Use when about to merge a pull request or turn on its auto-merge (`gh pr merge`, with or without `--auto`), when the pre-merge gate refused a merge or a push, or when new commits are about to reach a PR that was already reviewed or has auto-merge on.
---

# Review before every merge

A pull request merges only after the built-in `/code-review` at `high` has reviewed the exact commit that merges, and
each of its findings has been checked against the code. Auto-merge counts as merging: once it is on, GitHub merges the
moment CI passes, whatever review is still running.

`gate.py check` can run as a PreToolUse hook on Bash and PowerShell: it then refuses `gh pr merge` until a review of the
PR's current head commit is recorded, and refuses a `git push` to a PR whose auto-merge is on. This setup no longer
installs that hook, so the steps below are the whole procedure; the gate rows further down apply only where it is wired.

## Steps

1. **Auto-merge off.** Check it even on a PR you just opened: `gh pr view <n> --json url,autoMergeRequest,headRefOid`.
   If `autoMergeRequest` is not null, run `gh pr merge <n> --disable-auto`.
2. **Everything pushed.** `git status -sb` shows no `ahead`; push if it does. Note the PR's `url` and `headRefOid`: the
   head is the commit the review sees, and `record` needs it. Do not push again until step 5.
3. **Review.** Skill tool, skill `code-review`, args `high <the PR's url>` (the full URL, never the bare number: the
   review resolves a number against the session's own repository, which may be another one; no `--comment`: `record`
   posts the summary). It runs in the background: wait for its result notification. Do not merge, and do not start a
   second review, while it runs. Check that its findings name files the PR changes (`gh pr diff <n> --name-only`); if
   they don't, it reviewed something else: run it again. If it fails or never reports, run it once more; if that fails
   too, stop and tell the user. Never merge without it.
4. **Triage.** Check every finding against the code (superpowers:receiving-code-review). Each one ends as **fixed** or
   **not changed** with the reason you found in the code, never "the reviewer said so" or "probably fine".
5. **Fixes.** Commit them, run the project's checks, push. New commits are a new head: back to step 2 for it (note the
   new `headRefOid`), however small the change. Stop when a review leaves nothing that needs a change. If a third round
   still finds something that needs a change, stop and ask the user how to go on.
6. **Record.** Write the triage to a file outside the repository (the system temp folder) with the file-writing tool,
   not a shell heredoc or `echo`: the gate refuses any shell command whose text holds `gh pr merge`, even as data.
   One line per finding (`fixed` or `not changed`, `file:line`, what changed or why not), every round, newest
   round last; for a review with no findings, the line `no findings`. Then, from inside the repository:

   ```bash
   python "<this skill's folder>/gate.py" record <n> --head <headRefOid from step 2> --summary <file>
   ```

   It refuses when the PR's head is no longer the reviewed commit (review the new head). Otherwise it posts the summary
   as a PR comment headed with the reviewed commit, records that commit, and prints `recorded <url> at <sha7>`.
7. **Merge** with the project's usual command, the PR's URL as the selector and `--match-head-commit <full headRefOid>`
   (for example `gh pr merge <url> --auto --merge --match-head-commit <headRefOid>`): the URL needs no folder to find
   the PR, and GitHub itself refuses the merge if the head moves after the gate's check. The gate lets it through only for the recorded head, with that flag naming it in full.
   With `--auto`, the PR is not merged yet: say so, and watch it until GitHub merges it or CI fails.
8. **New commits after the merge is on** (a failed CI run, a late fix): commit locally as needed, but run
   `gh pr merge <n> --disable-auto` as its own command before the push (the gate reads auto-merge before a command runs,
   so `--disable-auto && git push` is still refused), then push and go back to step 2 for the new head. A lint-only or
   one-line fix is no exception.

Tell the user: when auto-merge is on, that it is on and what the review found (how many findings, what was fixed, what
was left and why); when GitHub has merged it, that it merged.

## When the gate refuses

| Refusal | Do |
|---|---|
| no review recorded for the head | steps 1 to 7 for that head |
| the head moved since the review | step 2 again for the new head; the record is per commit |
| `gh pr merge` and `git push` in one command | run them separately, with the review between |
| push refused: auto-merge is on | step 8 |
| the PR could not be read (`gh` failed) | fix `gh` (auth, network, the selector); do not merge another way |
| it cannot tell which repository (`GH_REPO`, `cd -`, a variable, a subshell) | name the PR by its URL |
| `--match-head-commit` is missing or names another commit | add the full `headRefOid` the refusal names (the recorded head) |
| the command only mentions `gh pr merge` or `git push` (a grep, a commit message, a heredoc) | write text with the file-writing tool, commit with `git commit -F <file>`, grep for `'gh pr merg[e]'` or `'git pus[h]'` |

## Red flags

| Thought | Reality |
|---|---|
| "CI is green, the review is nearly done, merge now" | The review exists to stop the merge. Wait for it. |
| "It's a one-line follow-up commit, no need to re-review" | The record is per commit. Review it; a small diff is a fast review. |
| "I'll record now and look at the findings after the merge" | The record posts a comment saying the review was triaged. Record only after step 5. |
| "`not changed: fine` will do for this one" | Each reason comes from the code you read: the line that makes the finding wrong or harmless. |
| "Auto-merge is on, so tell the user it's merged" | It merges when CI passes. Report it as on, then as merged when it is. |
| "The gate is in the way; merge through `gh api` or the web page" | Never route around it. If the user wants a merge without review, they run `! gh pr merge ...` themselves. |
| "Turn auto-merge on at PR creation, as usual" | Not any more: auto-merge goes on in step 7, after the record. |
| "The review is slow; record `no findings` and merge" | The gate checks the record, not the review, so it can't stop this. The PR comment would tell the user a review ran that didn't. |

Not covered by the gate: merges through `gh api` or the browser, a push of a branch other than the current one, `gh`
aliases, and the user's own `!` commands. The steps still apply to all but the last.
