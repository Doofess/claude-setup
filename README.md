# claude-setup

A Claude Code setup kept as code: one installer makes every Windows PC the same, and a hook refuses to merge a pull request until its latest commit has been reviewed.

![Claude Code's status bar: repo, branch and its pull request, model and effort, a context meter, 5-hour and 7-day plan meters with reset times, session cost and session time](docs/images/statusbar.png)

## What is in it

- `skills/pre-merge-review`: a pull request review procedure and `gate.py`, the hook that enforces it.
- `install.ps1`: one re-runnable command for all of it, plus plugins, language servers and terminal colours.
- `statusbar.py`: the line in the picture.
- `mods/session-cards`: a Claude Code mod that restyles the conversation view.
- `global/CLAUDE.md` (rules for planning, delegation and git), two agents and three more skills.
- `shell_matrix.py`: checks that four Windows shells end up the same.

Setting up a new PC in full and daily use: [docs/manual.md](docs/manual.md).

## The engineered parts

The settings template sets `bypassPermissions` and turns off its warning, so Claude Code runs commands without asking. The merge gate is the one check on what commands run; the rest of the working rules are instructions in `global/CLAUDE.md`.

### Pre-merge review gate

`gate.py` (553 lines, standard-library Python) runs before every Bash and PowerShell command. It refuses `gh pr merge` until `gate.py record` has stored a review for the PR's current head commit, and the merge must pass that commit as `--match-head-commit`, so GitHub rejects it if a new commit lands in between. It also refuses `git push` while the branch's PR has auto-merge on.

A merge it cannot check is refused: a `gh` error, a crash, or a spent 20 s budget, which is kept under the hook's 30 s timeout. A push it cannot check goes through, since a new branch has no PR yet. Its option patterns cannot backtrack exponentially, so a long run of repeated options cannot stall it.

It checks that a review was recorded, not what it found. It does not see merges through `gh api` or the web page, or pushes of a branch other than the checked-out one. If Python or `gate.py` itself is missing or fails to start, the hook lets everything through. `tests/test_pre_merge.py` has 60 cases: most run the gate as a subprocess against a fake `gh` (quoting, `cd` tracking, records), and the rest cover crashes, the time budget, pattern timing and the hook command itself.

### Settings merge

The installer merges into each machine's own settings: `enabledPlugins` and `env` entry by entry, `permissions` arrays unioned, `hooks` matched by event and command so a machine's own hooks stay beside the gate, everything else replaced. The helpers are pure functions, tested under PowerShell 5.1 and 7 for identical output, and for a second install leaving one copy of the gate beside the machine's own hooks. A hand-written JSONC editor changes Windows Terminal's settings without losing the user's comments (9 test fixtures), and a second run leaves the file unchanged.

### Status bar

Claude Code runs `statusbar.py` every 60 s: session JSON in, one line out. The context meter reaches 100% at the auto-compact point. On a narrow terminal the least important pieces drop, any that still fit come back, and the dropped ones go through a per-session file to the mod, which draws them on the hint line. `tests/test_statusbar.py` has 83 cases, from layout at several widths to remote URL parsing.

### Session-cards mod

`register.tsx` (1,109 lines of TypeScript) uses Claude Code's mod API for prompt cards, one-row tool calls and agent rows with model, effort, time and tokens. Its 91 cases in 5 files cover those rows and the hint-line placement.

## Testing

374 Python test methods in 14 `unittest` files and 91 cases in the mod's 5 test files. `unittest` reports 473, because the installer-helper tests run once under each PowerShell engine. The installer tests check its functions and source text; two opt-in tests run `-Check` on the real machine. There is no CI. Hooks in this repo lint each edit and, at turn end, run the suite for whatever changed.

```powershell
python -m unittest discover -s tests -q
claude plugin test mods/session-cards
```

## Install

Windows only, built for its owner's PCs. It also changes Windows Terminal, VS Code's terminal, PowerShell profiles and the execution policy. It backs up the Claude Code and Terminal settings first; `-Check` changes nothing.

```powershell
winget install Anthropic.ClaudeCode Git.Git GitHub.cli OpenJS.NodeJS Python.Python.3.14
claude            # sign in once, then exit
gh auth login
git clone https://github.com/Doofess/claude-setup C:\dev\claude-setup
cd C:\dev\claude-setup
.\install.cmd -Check
.\install.cmd
```

## Status

In daily use. Windows only, no releases, no CI.

## License

MIT. See [LICENSE](LICENSE).
