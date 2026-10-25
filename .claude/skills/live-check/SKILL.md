---
name: live-check
description: Use for a "live check", to "screenshot the status bar" or the session-cards mod in a real Claude Code window, or to answer "what does the engine do" by searching the installed claude binary and claude-code.d.ts.
---

# live-check

Two scripts, run from the repo root with `pwsh -NoProfile -File`.

## capture.ps1: screenshot a demo session

`.claude/skills/live-check/capture.ps1 -Out <png> [-Columns 120] [-Rows 30] [-Prompt <word>] [-Worktree <path>] [-Mode bypassPermissions] [-PluginDir <probe mod>] [-Keep]`

- Waits `-Wait` seconds (15 to 60) before the capture, so a prompt's turn can finish and the demo outlives the fullscreen boot canary: a launch killed within 10 s of its first frame is a strike, and two strikes turn fullscreen off machine-wide (`fullscreenAutoDisabled` in `~/.claude.json`) until `/tui fullscreen` or an update.
- Starts a demo `claude.exe` in its own Windows Terminal window, with `NO_COLOR`, `CLAUDECODE`, `CLAUDE_PID` and all `CLAUDE_CODE_*` env vars stripped (otherwise it is colourless and warns that transcripts are off).
- `-Worktree` writes a temp `--settings` file: `statusLine.command` runs the worktree's `statusbar.py`, `env.CLAUDE_CODE_PLUGIN_DIRS` loads the worktree's `mods/session-cards`. Use it to check a branch without merging or running its `install.ps1`.
- `-PluginDir` adds `--plugin-dir`: a probe mod beside the installed ones (say, a `session.start` hook that tries an API after a delay).
- Finds the window with EnumWindows, captures with `PrintWindow` (never a screen grab: the user may be in a fullscreen game), then stops only the demo's `claude.exe` (matched by the temp settings file name in its command line) and sends `WM_CLOSE` to its window. Never kill `WindowsTerminal.exe` or any other `claude.exe`: the live session is one.
- `-Keep` leaves the demo running for further probing; stop it yourself by command line.

## engine.ps1: what does the engine do

`.claude/skills/live-check/engine.ps1 [-Pattern <regex>] [-Types]`

Prints the running version (`claude --version`), the binary path and the matching `claude-code.d.ts`. `-Pattern` searches the binary (ripgrep if present, else .NET regex; 80 characters of context, 20 matches); `-Types` prints the d.ts. Check `RenderComponent` in the current d.ts before telling the user a surface cannot be replaced; answers change between builds.

## Live-checking a mod without restarting

Copy `.claude-plugin`, `hooks` and `types` into `~/.claude/dev-mods/<session id>/<mod>/` (the plugin-authoring skill's watched folder). The engine asks once, loads at turn end, reloads on each save; the transcript carries `<mod>: This mod reloaded...` or `...didn't load`. Delete the copy afterwards or a restart loads the mod twice. To probe a fresh window, start it with `claude.exe --plugin-dir <probe mod folder>`.

## Engine surfaces a mod cannot change (2.1.310)

- Background-agent list under the prompt: not a `ui.render` surface (the Agent `ToolUse` row above it is the mod's).
- Typed slash commands: the engine draws its own grey echo row whatever the hook returns.
- `PromptHint`'s `hint` omits the mode label drawn before it on the same row (`bypass permissions on` and so on; widths: default 0, acceptEdits 21, auto 18, bypass 27, dontAsk 18, plan 17). The mode is on no event; `statusbar.py` reads it from the transcript's last `permission-mode` line and lags after Shift+Tab until the turn ends.
- "1 shell still running" on the turn-end line is the engine's live count of background tasks, read from its store, not a `TurnDuration` prop. The mod draws its own copy: a shell's end reaches it as `prompt.submit` with origin `task-notification` and `<task-id>` in the text.
- A demo started in a worktree with uncommitted code runs `.claude/hooks/stop_tests.py` (every suite on its first run there) at each turn end: "running Stop hook" for a minute or more. Commit first, or run the hook once with that `cwd` to stamp it.
- `PromptHint` pills (`1 shell`, monitors, agents) are clickable only while the hook keeps the engine's line: return `next(e)` with `tail` set. A rewritten `hint` or a tree of the hook's own turns them into plain text; a hook's own `Button` running `$.command.run({ command: 'tasks' })` opens the same list at once when idle, but mid-turn the run is queued (`Prompt from the <mod> plugin › /tasks`) until the turn ends. The engine's pill is `inverse` only while hovered or selected. The engine puts its own ` · ` in front of `tail` and collapses its spaces. Pills are drawn in the theme's `background` colour.
- `CommandOutput` fires only for `local_command` rows with `commandRun`; picker commands (`/model`, `/effort`) never get a card.
