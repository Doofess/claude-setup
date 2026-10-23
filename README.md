# claude-setup

My Claude Code configuration, versioned so every machine runs the same setup.

| File | Lands at |
| --- | --- |
| `CLAUDE.md` | `~/.claude/CLAUDE.md` (global rules: plugin split, defaults) |
| `settings.json` | merged into `~/.claude/settings.json` (plugins, model and effort, skill overrides) |
| `agents/*.md` | `~/.claude/agents/` (`Explore` on Haiku without CLAUDE.md, replacing the built-in; `worker` on Sonnet at medium effort for implementation briefs) |
| `mcp_off.py` | not installed; the installer runs it to turn the claude.ai Adobe connector off once per project in `~/.claude.json` |
| `statusbar.py` | `~/.claude/statusbar.py`, run by the `statusLine` in `settings.json` (refreshed every 60 s so the reset countdowns move). Row 1: repo, branch, PR, model and effort. Row 2: a context meter that runs to the auto-compact point (the auto-compact window minus 33k: 13k Claude Code keeps free plus 20k reserved for the reply), the 5-hour and 7-day plan meters with their reset times, then cost and lines changed. The installer runs the installed command through Git Bash `-c` (no profile, as Claude Code does) on sample data (`--demo` shows the same rows) and prints the two rows; it fails the install when they are wrong, when the meter glyph does not survive the UTF-8 round trip, or when no Nerd Font is installed (the icons would be empty boxes) |
| `skills/<name>/` | `~/.claude/skills/<name>/` (personal skills; `underwater-photoshop` drives local Photoshop) |
| `mcp-presets/` | not installed; copy one into a repo as `.mcp.json` (see its README) |

Not versioned on purpose: `~/.claude.json` (login state, user-scope MCP servers), `.credentials.json`, `history.jsonl`, `~/.remember/`.
Synced plugins and claude.ai connectors follow the account, so they need no setup here.

## Plugin and MCP policy

- Always-on (user scope): superpowers, frontend-design, context7, playwright, and the typescript, pyright and rust-analyzer LSPs. claude-md-management is pinned off (never used). The synced docs/docx/pdf/pptx/xlsx skills and the browser and computer-use skills load by name only (`skillOverrides`). `good-css` is declared in `extraKnownMarketplaces` (`vojtaholik/good-css`) and its enabling is left to the machine.
- Everything tied to one project (databases, deploy target, observability, Kubernetes) is project scope: `mcp-presets/`.
- The GitHub MCP server stays off; `gh` covers it with far less context.
- `deniedMcpServers` blocks every claude.ai connector except Adobe, Supabase and Cloudflare (Slack, Linear, Atlassian, Notion, Figma, Intercom, Claude Docs, Vercel, Canva, Spotify, Google Docs/Sheets/Calendar/Drive, Gmail, and desktop-commander). BigQuery is retired; the installer removes the user-scope server and its hook. Adobe: the "Adobe for creativity" claude.ai connector is the only route to Adobe tools from the CLI (the plugin copies 403). It costs about 5k tokens a turn, so the installer turns it off in each project it knows (`mcp_off.py`); `/mcp` turns it back on for one project, and that choice survives re-runs. A deny-list entry would not work here: deny lists union across settings sources, so `--settings` cannot lift one for a session. A project first opened after the last install starts with Adobe on. Photo edits themselves run in local Photoshop via the `underwater-photoshop` skill.

## Daily habits

- `/clear` before `/context` shows usage near the auto-compact point (about 267k with the 300k `autoCompactWindow`).
- `/clear` when the context meter in the status bar nears 100%: that is the auto-compact point, 33k below the window.
- `/usage` weekly; `/context` when a session feels heavy; `/skill-doctor` monthly to spot skills that load but never run.
- Start sessions from the repo folder, not `C:\Windows\System32`. The installer sets Windows Terminal to open in `C:\dev`, and adds a block to the PowerShell 7 profile that moves a shell started in System32 (Start menu, taskbar) to `C:\dev`.

## New machine (Windows)

1. Install: [Claude Code](https://code.claude.com), [Git for Windows](https://git-scm.com) (provides Git Bash), [GitHub CLI](https://cli.github.com), [Node](https://nodejs.org) 26+, [Python](https://python.org) 3.10+.
   With winget: `winget install Anthropic.ClaudeCode Git.Git GitHub.cli OpenJS.NodeJS Python.Python.3.14` then `npm i -g pnpm`.
2. `claude` once and sign in. `gh auth login`.
3. ```powershell
   git clone https://github.com/Doofess/claude-setup C:\dev\claude-setup
   cd C:\dev\claude-setup
   .\install.ps1
   ```
   The installer also installs JetBrainsMono Nerd Font through winget when the machine has no Nerd Font, and sets it as the Windows Terminal default only when that file names no font yet (kept for a later visual rebuild; `-SkipFont` turns this off). It never overwrites a font you chose, and removes hooks this repo has retired.
4. Restart Claude Code and open a new terminal tab. In any repo, run `/setup-matt-pocock-skills` once.
5. Photo work: `python -m venv ~/.claude/skills/underwater-photoshop/.venv` and `pip install -r skills/underwater-photoshop/requirements.txt` into it. Needs Photoshop 2026 installed (COM `Photoshop.Application`).

## Settings merge rules

`settings.json` is merged into the machine's `~/.claude/settings.json`: `enabledPlugins` and `env` per entry (the
repo wins on conflict, other machine entries stay), `permissions` with arrays unioned, `hooks` per event and per
command, and every other key replaced by the repo's value. A key removed from the repo stays on the machine, so
retiring one needs an explicit step in `install.ps1` (see "Removing the retired visual setup").

## Visual setup

The visual setup (theme, readable-session mod, Windows Terminal scheme, status line) was removed on 2026-10-23 to be rebuilt from scratch; tag `visual-v1` holds it. The installer undoes it on machines that had it.

## Changing config

Edit the files here, run `.\install.ps1` (add `-SkipPlugins` when only config changed), commit, push. On the other machine: `git pull` then `.\install.ps1`.

From Claude Code's `!` prompt (which is Git Bash, so backslashes don't work):

```bash
git -C C:/dev/claude-setup pull && powershell -ExecutionPolicy Bypass -File C:/dev/claude-setup/install.ps1
```

The installer backs up the previous files to `~/.claude/backups/claude-setup-<timestamp>/` every run.
