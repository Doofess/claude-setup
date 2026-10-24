# claude-setup (this repo)

## What lives where
- Installed globally by `install.ps1`: root `settings.json`, `global/CLAUDE.md`, `statusbar.py`, `skills/`, `agents/`, `themes/`, `mods/session-cards`.
- `.claude/` is this repo's own project config (hooks, skill, settings).

## Tests
- `python -m unittest discover -s tests -q`
- `claude plugin test mods/session-cards` and `claude plugin validate mods/session-cards` (its one plugin-directory warning is pre-existing).

## Install
- Only from main, after merging: `pwsh -NoProfile -File install.ps1`. A worktree's install repoints `CLAUDE_CODE_PLUGIN_DIRS`.
- `install.ps1` must parse under Windows PowerShell 5.1. A hook checks.

## Flow
- Work in worktrees under `.claude/worktrees/`, open a PR, then `gh pr merge N --squash --delete-branch`.
- Leave the worktree directory before merging, or its removal fails.

## Engine facts
- Binary: `$USERPROFILE/.local/share/claude/versions/<version>`, search it with `rg -a`.
- Mod API types: `$LOCALAPPDATA/Temp/claude/bundled-skills/<version>/*/plugin-authoring/types/claude-code.d.ts`.
- The `live-check` skill does both, plus the demo-window capture.
