# claude-setup (this repo)

## What lives where
- Installed globally by `install.ps1`: root `settings.json`, `statusbar.py`, `skills/`, `themes/`, `mods/session-cards`. No plugins, agents, hooks, MCP servers, language servers or global CLAUDE.md: the setup is a clean slate.
- `.claude/` is this repo's own project config: the `live-check` skill only (no hooks, no settings).

## Tests
- `python -m unittest discover -s tests -q`
- `claude plugin test mods/session-cards` and `claude plugin validate mods/session-cards` (its one plugin-directory warning is pre-existing).

## Install
- Only from main, after merging: `pwsh -NoProfile -File install.ps1`. A worktree's install repoints `CLAUDE_CODE_PLUGIN_DIRS`.
- `install.ps1` must parse under Windows PowerShell 5.1. Check with `powershell -NoProfile -Command "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('<abs path>\install.ps1',[ref]$null,[ref]$e); $e.Count"`: it must print 0.
- The first run on a PC does the one-time clean-slate reset (`cleanSlate` key in `~/.claude/claude-setup-state.json`); `-Check` never changes anything.

## Flow
- Work in worktrees under `.claude/worktrees/`, open a PR, run the `pre-merge-review` skill, then `gh pr merge <PR url> --squash --delete-branch`.
- Leave the worktree directory before merging, or its removal fails.

## Engine facts
- Binary: `$USERPROFILE/.local/share/claude/versions/<version>`, search it with `rg -a`.
- Mod API types: `$LOCALAPPDATA/Temp/claude/bundled-skills/<version>/*/plugin-authoring/types/claude-code.d.ts`.
- The `live-check` skill does both, plus the demo-window capture.
