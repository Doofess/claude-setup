# claude-setup

My Claude Code setup, kept in git so every PC I use looks and behaves the same. One script, `install.ps1`, sets up a fresh
Windows machine: a custom status bar, a mod that tidies the conversation view, a theme, three skills and the terminal's
font and colours. Everything else is Claude Code's own default: no plugins, agents, hooks, MCP servers, language servers
or global CLAUDE.md.

![The status bar: repo, branch, model and effort, context meter, 5-hour and 7-day plan meters, cost, session time](images/statusbar.png)

## What you see

### The status bar

The line along the bottom of Claude Code, read left to right:

- **Where you are**: the repo (GitHub in violet, GitLab in its orange with its own icon, read from the origin remote) and the branch (Claude Code shows the PR badge itself; on the hint line the mod draws its `#` yellow and the number white and underlined, still a link to the PR).
- **Who is working**: the model and the effort level. Each model and each effort level has its own colour, so you can
  tell at a glance whether you're on Opus (Claude orange) or Sonnet, at high or medium. Fable's name is a gold gradient, and a running Fable subagent's row pulses.
- **How full the context is**: a meter that reaches 100% at the auto-compact point (about 267k of the 300k window), not
  at the end of the window. When it's full, it's time to `/clear`.
- **How much plan is left**: the 5-hour and 7-day usage meters, each with the time until it resets.
- **What the session has cost**, in green.
- **How long the session has run**, beside a clock, both in the repo name's violet.

The meters change colour as they fill: green below 50%, yellow from 50%, orange from 70% and red from 90%. The same
session late in a busy day:

![The same bar with the context meter orange at 75%, the 5-hour meter red at 93% and the 7-day meter yellow at 57%](images/statusbar-busy.png)

When the window is narrow, the least important pieces drop first: session time, cost, then reset times and
the plan meters. Repo, branch, model with its effort, and context always stay; on a very narrow window the repo loses its owner, then
letters of its name. Once the line fits, any dropped piece that still fits comes back, so
no room is wasted:

<img src="images/statusbar-narrow.png" width="380" alt="The bar at 60 columns: the repo cut to claude-s…, then branch, model and context">

Dropped pieces aren't lost. The session-cards mod (below) moves them onto Claude Code's hint line, beside the
permissions text:

- A reset time whose meter stays on the top row sits right under the meter's first block, without its `→`.
- A meter that moves takes its reset time with it (`7D ████ 32%  → 4d21h`), its first block under the last meter
  left on the top row. Where it can't line up, it goes to the right.
- The rest (cost, session time) is right-aligned at the margin, or, when a moved meter holds the margin, in the
  free space before it.
- Where pieces collide, the least important one drops, in the bar's own order; the hint always stays.
- While background work shows on the hint line (`1 shell`, monitors, agents) and Claude is idle, the row keeps this
  layout and the pill is the mod's own: a white block that opens the background-tasks list when clicked. While Claude
  works, Claude Code's own line stays instead, since a mod's `/tasks` waits for the turn to end and Claude Code's pill
  opens at once; the pieces then follow it dim, packed left after a ` · `, a meter as its percentage alone, since dim
  blocks can't show how full it is.

![At 104 columns the bar keeps repo, branch, model, effort, context and the 5-hour meter; the 7-day meter moves onto the hint line with its reset time, right-aligned](images/hint-overflow.png)

The icons come from a Nerd Font. On a machine without one, the installer switches the bar to short words instead
(`ctx`, `5H`, `7D`), so it reads fine in any monospace font. To see the bar without starting Claude Code, run
`python statusbar.py --demo`.

### Session cards

`mods/session-cards` is a Claude Code mod that makes a long session easier to scan:

- **Your prompts** become a coloured card headed with the time you sent them, so you can find your own messages again.
- **Slash-command output** gets a violet card of its own. A command row the engine hands to the mod (one queued while
  Claude works, such as `/compact`) is a violet `You ran /compact` card rather than a prompt card.
  Only output Claude Code keeps as a command result gets a card (`/context`, `/color`, `/reload-plugins`, `/memory`,
  `/skills`, `/usage`, `/rename`). Some commands get none, since Claude Code hands the mod nothing to draw:
  - Pickers and dialogs (`/model`, `/effort`, `/mcp`, `/plugin`, `/theme`, `/login`, `/advisor`) keep their result
    line as a plain row that no mod hook sees.
  - `/clear` prints nothing.
  - Skills print no output row.
  - In fullscreen, a dialog closed with Esc leaves no row.
- **The end of each turn** is a coloured line with how long it took and when it finished (`✻ Baked for 1s · done 4:20 PM`).
  While background shells run, every such line ends in a dim `· 1 shell still running`, which goes away when the
  shell's notification arrives. While a background agent runs, Claude Code's own line stays, since only it knows when
  the agent ends.
- **Tool calls** shrink to one short row each: an icon and a few words. Runs of reads, searches and shell commands
  keep Claude Code's own one-line summary ("Searched for 1 pattern, read 1 file…"), as in the picture below.
- **Agents** get a row showing the agent type, its model and effort (in the same colours as the status bar), what it's
  doing right now, how long it has been running and how many tokens it has used.

![A real session: the prompt card with its time, Claude Code's summary of three tool calls, and an Explore agent row showing Haiku, low effort, 4 s and 7k tokens](images/session-cards.png)

### Behind the scenes

Nothing to look at here, but it shapes every session:

- **`advisor-switch`**: turns Claude Code's advisor on (Opus, or Fable when Opus is stuck) and off for one project, in
  its `.claude/settings.local.json`. Claude runs it itself before and after a plan with workers; the installer removes a
  user-level `advisorModel`, so the advisor is never on in every project at once.
- **`pre-merge-review`**: the review a pull request gets before it is merged: the built-in `/code-review` at `high`, Claude
  triages the findings and fixes the real ones, new commits are reviewed again, then it merges with
  `gh pr merge <PR url> --squash --delete-branch`. The skill also holds `gate.py`, a `PreToolUse` hook script that
  refuses `gh pr merge` until the review is recorded for the PR's current head (`gate.py record`, which also posts the
  summary as a PR comment, writes the record in `~/.claude/pre-merge-review/`) and the merge names that head with
  `--match-head-commit`, and refuses any `git push` from a branch whose open PR has auto-merge on. The installer does
  not register it (the template has no hooks); a project that wants the enforcement adds
  `python -I -S ~/.claude/skills/pre-merge-review/gate.py check; exit 0` as a `PreToolUse` hook on `Bash|PowerShell`.
  Without it the procedure is a rule Claude follows, not a check on what commands run.
- **`setup-check`**: `/setup-check` proves every shell shows the same setup and repairs drift (see
  [Check a machine](#check-a-machine)).

## Set up a new machine (Windows)

1. Install [Claude Code](https://code.claude.com), [Git for Windows](https://git-scm.com) (it brings Git Bash),
   [GitHub CLI](https://cli.github.com), [Node](https://nodejs.org) 26+ and [Python](https://python.org) 3.10+. With winget:

   ```powershell
   winget install Anthropic.ClaudeCode Git.Git GitHub.cli OpenJS.NodeJS Python.Python.3.14
   npm i -g pnpm
   winget install --id astral-sh.ruff -e
   ```

   Then run `npm install` at the repo root (installs the pinned Biome, which lints the mod).

2. Run `claude` once and sign in, then `gh auth login`.
3. Clone and install:

   ```powershell
   git clone https://github.com/Doofess/claude-setup C:\dev\claude-setup
   cd C:\dev\claude-setup
   .\install.cmd
   ```

   `install.cmd` runs `install.ps1` under PowerShell 7 when it is installed, else Windows PowerShell, past 5.1's
   blocked-scripts policy. From Git Bash, run `./install.sh`, which calls it.

4. Restart Claude Code and open a new terminal tab.

The installer installs JetBrainsMono Nerd Font through winget if the machine has no Nerd Font, sets Windows Terminal's
font and colour scheme. On a PC that still has the old setup, its first run also does the
[clean-slate reset](#clean-slate-once-per-pc). Options:

| Flag | Effect |
| --- | --- |
| `-KeepFont` | keep the machine's own terminal font |
| `-KeepScheme` | keep the machine's own colour scheme |
| `-SkipFont` | skip the font install and the font change |

It backs up the previous files (`CLAUDE.md`, `settings.json`, `statusbar.py`, `keybindings.json`, the state file,
`agents/` and `~/.claude.json`, plus the terminal settings) to `~/.claude/backups/claude-setup-<timestamp>/` on every
run. `-Check` changes nothing.

### Clean slate (once per PC)

The first run on a PC resets it, then records `"cleanSlate": "2026-11-28"` in `~/.claude/claude-setup-state.json`. Later
runs see the key and skip the reset. The key is written only when every piece worked, so a failure (named in the
`DONE WITH FAILURES` list) repeats the whole reset on the next run. Each piece prints a line, or says there was nothing
to do. In this order:

1. Uninstalls every plugin that `claude plugin list --json` shows at user scope (`claude plugin uninstall <id> --scope
   user`); Claude Code's own `@builtin` plugins, session plugins and claude.ai's synced ones are not touched. A plugin at
   project or local scope is not uninstalled: it is printed with its project folder and the command to run there
   (`cd <folder>; claude plugin uninstall <id> --scope project`).
2. Removes every plugin marketplace but `claude-plugins-official` (`claude plugin marketplace remove <name>`; the names
   come from `claude plugin marketplace list --json`, or `~/.claude/plugins/known_marketplaces.json`).
3. Deletes every file in `~/.claude/agents/` and `~/.claude/CLAUDE.md`.
4. Deletes the skill folders `~/.claude/skills/underwater-photoshop`, `find-skills` and `codex`, and `~/.claude/photo-edit`.
   Every other skill folder, `synced` included, stays.
5. Removes the Kotlin language server the old installer put in `%LOCALAPPDATA%\Programs\kotlin-lsp`, and its shim folder's
   entry from your user Path (the registry value, written back as ExpandString; never the machine Path). The
   TypeScript language server and the rustup `rust-analyzer` components stay: they are ordinary dev tools.
6. `clean_slate.py` deletes `claudeInChromeDefaultEnabled` and every project's `disabledMcpServers` from `~/.claude.json`
   (read, edit, swap in under Claude Code's own lock; every other key stays), and the keys `mcp_off.py` and
   `chrome_off.py` kept in the state file.
7. Writes `~/.claude/settings.json` fresh from the template, so every retired key is gone. This happens once, even when
   another step failed and a later run repeats the reset. Later runs merge instead.

Everything deleted is in the run's backup folder first, except these: the skill folders, `~/.claude/photo-edit` and
the Kotlin language server are not backed up (the skills are in this repo's git history), and the plugins can be
installed again from their marketplaces.

### Check a machine

After installing, or on a new PC, run `/setup-check` in Claude Code. It finds the clone through
`~/.claude/claude-setup-state.json`, checks the clone is up to date, runs `shell_matrix.py` to compare every shell,
repairs any difference with `install.cmd`, and runs the matrix again. It is done when the matrix exits 0. It asks
before pulling, and it never edits the repo. What the installer can't do (a group-policy pin, a shell winget couldn't
install, signing in to `claude` and `gh`) it hands to you with the exact command.

### Same screen on every PC

After installing, the installer prints a `Same experience` table (`name  expected  actual  ok|FAIL`) and fails if any
row is wrong. It checks everything that decides what the screen looks like: the Nerd Font and Windows Terminal's font
face and `cellHeight`, the `Campbell` colour scheme, Claude Code's theme (`custom:clear` with its file), the status line command, the
session-cards mod being loaded, and Claude Code 2.1.308+, Python 3.10+ and Git Bash. The shell rows cover the rest:
`Terminal profile overrides` (no profile sets its own font or colour scheme; `-KeepFont` / `-SkipFont` excuse font overrides and `-KeepScheme` colour scheme ones, and the row shows `kept`), `Terminal default profile` (PowerShell 7),
`Git Bash profile` (present in Windows Terminal), `PowerShell 7` (pwsh found), `Windows PowerShell policy`
(RemoteSigned or looser; a group-policy pin that is stricter is a FAIL and named), `PowerShell profiles` (the
claude-setup block in both profile files) and `VS Code terminal` (font, Campbell colours and contrast set; `no VS Code`
shows `kept`). These rows only read, so they run under `-Check` too. It also runs the status bar on
sample data and prints it, so a broken bar or a mangled meter glyph stops the install. Rows covered by `-KeepFont`,
`-KeepScheme` or `-SkipFont` show `kept`.
The install records the keep flags it ran with in `~/.claude/claude-setup-state.json` (`flags`); `/setup-check` and
`shell_matrix.py` pass them to the check and the repair, so a font or scheme you kept is never overwritten.

## Changing something

Edit the files here, run `.\install.ps1`, commit and push. On the other machine: `git pull`, then `.\install.ps1`.

From Claude Code's `!` prompt (Git Bash, so use forward slashes):

```bash
git -C C:/dev/claude-setup pull && powershell -ExecutionPolicy Bypass -File C:/dev/claude-setup/install.ps1
```

## Daily habits

- `/clear` when the context meter nears 100% (the auto-compact point), or when `/context` shows usage near 267k.
- `/usage` weekly; `/context` when a session feels heavy; `/skill-doctor` monthly to spot skills that load but never run.
- Start sessions from the repo folder, not `C:\Windows\System32`. Windows Terminal opens in `C:\dev`, and the
  PowerShell 7 profile moves a shell started in System32 (Start menu, taskbar) to `C:\dev`.

## Reference

### What goes where

| In this repo | On the machine |
| --- | --- |
| `settings.json` | written fresh as `~/.claude/settings.json` on a PC's first run, merged into it after (model, theme, status line, `env`, permissions; see the merge rules below) |
| `themes/*.json` | `~/.claude/themes/`; `custom:clear` is Claude Code's `dark` with `userMessageBackground` set to Campbell's background `#0c0c0c`, so the sticky prompt line at the top (the last prompt, once it scrolls away) has no grey bar, and `background` set to Campbell's bright white `#F2F2F2`, so background work (the `1 shell` pill under the prompt, the background-tasks dialog) is white instead of cyan. A typed `/command`'s echo row and the selected row in the background-tasks list lose their grey too. Its text stays the dim `subtle` grey and it has no border: Claude Code draws that one-row line itself, with no mod hook |
| `statusbar.py` | `~/.claude/statusbar.py`, run by `statusLine` in `settings.json` every 60 s so the reset countdowns move |
| `skills/<name>/` | `~/.claude/skills/<name>/` |
| `mods/session-cards/` | stays in the repo; `install.ps1` adds its folder to `CLAUDE_CODE_PLUGIN_DIRS` in `~/.claude/settings.json` and checks it with `claude plugin validate` |
| `terminal/profile.json` | not copied; its font and `colorScheme` are written into Windows Terminal's `profiles.defaults`, and a `colorScheme` on the default profile itself is removed (see [`terminal/README.md`](../terminal/README.md)) |
| `clean_slate.py` | not copied; the one-time reset runs it to edit `~/.claude.json` and the state file |

Not versioned on purpose: `~/.claude.json` (login state; the reset edits two toggles in it), `.credentials.json`,
`history.jsonl`. Synced plugins and claude.ai connectors follow the account, so they need no setup here.

### Status bar details

- The context meter's end is the auto-compact window minus 33k: 13k that Claude Code keeps free plus 20k reserved for the reply.
- Each meter has 8 cells: the filled part in the bright level colour, the rest in a dark shade of the same colour; its
  icon and numbers take that colour too.
- Separators, the other icons, the branch name and reset times are sent as exact white rather than the terminal's
  default foreground (light grey in most schemes), so nothing on the line is grey. The branch icon is the meters' yellow.
- Effort runs green, yellow, the bypass red, then xhigh and max as the `/effort` picker draws them, held still: xhigh in
  the violet of `accept edits` with its middle letter lit, max a rainbow that starts at the bolt.
- The pieces dropped on a narrow terminal are written to `~/.claude/statusbar-overflow/<session_id>.json`, as text with
  their colours, with where each one goes and the width of the mode label in front of the hint (read from the session
  transcript); files older than a day are removed. The session-cards mod reads them for the hint line. Beside the
  plain hints (`? for shortcuts`, `(shift+tab to cycle)`), and beside a hint of only the background pill and the PR
  badge while Claude is idle, it draws the line itself, the pill as its own Button that runs `/tasks`; beside any other
  hint it hands the pieces to Claude Code's `tail`, since a rewritten hint turns the engine's pills into dead text. In a
  GitHub repo the file also holds `pull`, the PR address the mod links the badge's number to.
- Reset times and the session time leave out a zero hour count past a day: `5d`, not `5d0h`.
- Most of the bar's and the mod's colours are the colour scheme's own 16; Claude orange, the repo's violet and high
  effort's red (the red of `bypass permissions on`) are Claude Code's exact theme colours. The icons depend on the Nerd
  Font's glyph widths, so a different scheme or font gives a different screen.

### User level vs project level

The user level (`settings.json` here, written into `~/.claude/settings.json`) holds only:

- the status line, the `custom:clear` theme, the session-cards mod, permissions (`bypassPermissions`), the model (`opus`)
  and a few preferences (`autoCompactWindow`, `feedbackDrafts`, `autoUpdatesChannel`, `tui`, `editorMode` and others);
- skills: `advisor-switch`, `setup-check` and `pre-merge-review`.

It sets no plugin, marketplace, hook, MCP rule, skill override, model setting, agent or global CLAUDE.md: all of those
are Claude Code's defaults. A project that needs one adds it in its own `.claude/settings.json` (MCP servers in
`.mcp.json`).

### Settings merge rules

On a PC's first run the template is written as `~/.claude/settings.json` (see the clean slate above). After that
`settings.json` is merged into the machine's: `env` entry by entry (the repo wins a conflict, the machine's other
entries stay), `permissions` with arrays unioned, and every other key replaced by the repo's value. A key removed from
the repo stays on the machine, so retiring one needs an explicit step in `install.ps1`.

`env.CLAUDE_CODE_PLUGIN_DIRS` (`;`-separated) is the one `env` entry that is unioned rather than replaced: the
machine's own folders stay, ours (`<repo>/mods/session-cards`, with `<repo>` being this clone in forward slashes) is
added once, and an existing entry ending in `/mods/session-cards` (from an older clone or worktree) is replaced by it.
Entries are compared ignoring slash style, trailing slash and case.

### Tool policy

- The rule: nothing is switched on or off at user level. Plugins, MCP servers, language servers, hooks, agents and
  global rules are added in the project (or session) that uses them, so a session loads only what it needs.
- To get a built-in tool back that Claude Code ships on, or to turn one off, use that project's `.claude/settings.json`
  or `/config`; the installer sets none of them.
- Changing a machine back to a fuller setup is a change to the template and `install.ps1`, not a leftover on the PC:
  the merge keeps machine keys the template does not name.

## History

The first visual setup (a custom theme, the readable-session mod, a Windows Terminal "Readable" scheme and an older
status line) was retired on 2026-10-23 and rebuilt as the status bar and session-cards mod above. Tag `visual-v1` holds
the old version, and the installer removes it from machines that still have it.

The clean slate on 2026-11-28 removed every plugin, marketplace, custom agent, hook, MCP rule and language server this
setup installed, and the global `CLAUDE.md`. The photo-edit plugin (the `underwater-photoshop` skill) and its
marketplace are gone from the repo; the git history before that commit holds them. Everything the reset deletes is in
the backup the run made.
