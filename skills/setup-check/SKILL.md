---
name: setup-check
description: Use when setting up this Claude Code configuration on a PC, after install.ps1, when the screen or behaviour differs between shells or PCs, or when the user asks whether the setup is right.
---

# Prove and repair the setup

Proves that every shell on this PC shows the same setup, and repairs what drifted. Run every command with the
PowerShell tool (`<repo>` is the clone path, with backslashes). Never edit the repo's files from this skill: drift on
the machine is fixed by the installer, not by editing the repo.

1. **Find the clone.** Read `repo` from `~/.claude/claude-setup-state.json`:
   `(Get-Content "$HOME\.claude\claude-setup-state.json" -Raw | ConvertFrom-Json).repo`.
   If the file or the key is missing, ask the user for the clone path (the installer records it on its next run).
   Read `flags` the same way (`(Get-Content "$HOME\.claude\claude-setup-state.json" -Raw | ConvertFrom-Json).flags`):
   the flags the last install ran with, such as `-KeepFont`. Missing means none.
2. **Check it is the main checkout.** Both must hold, else stop and ask for the main clone:
   - `git -C <repo> rev-parse --git-dir` prints the same as `git -C <repo> rev-parse --git-common-dir`
   - `git -C <repo> branch --show-current` prints `main`

   Never run a worktree's `install.cmd`: it repoints `CLAUDE_CODE_PLUGIN_DIRS` at the worktree.
3. **Fresh?** Run `git -C <repo> fetch -q`, then `git -C <repo> status -sb`. If main is behind, say so and run
   `git -C <repo> pull --ff-only` only after the user says yes.
4. **Prove.** Run `python -I "<repo>\shell_matrix.py"` (quoted: the path may hold spaces) with the PowerShell tool's
   timeout set to 600000 ms, because it takes a few minutes and the 2-minute default would cut it off. Every shell
   runs `install.cmd -Check`. Its last line is `shell matrix: all N shells match` (exit 0) or
   `shell matrix: K difference(s)` (exit 1). Quote the failing lines of the table.
5. **Repair.** For any FAIL run `& "<repo>\install.cmd"` with the `flags` from step 1 added (only `-KeepFont`,
   `-KeepScheme` and `-SkipFont`, so a repair never overwrites a font or scheme the user kept). Set the PowerShell
   tool's timeout to 600000 ms: a full install outlasts the 2-minute default. Then run step 4 again. If it still fails after one repair, show the rows and stop; do not loop.
6. **Hand over what the installer can't fix.** Name the row and give the exact command:

   | Row | Tell the user |
   |---|---|
   | Windows PowerShell policy pinned stricter than RemoteSigned by group policy | Their IT policy owns it and the installer can't change it. Ask the administrator, or use PowerShell 7. |
   | A shell is missing and winget couldn't install it | `winget install Microsoft.PowerShell`, `winget install Git.Git` or `winget install Microsoft.WindowsTerminal`, then step 5. |
   | Claude Code not signed in | Run `claude` and sign in. |
   | GitHub CLI not signed in | `gh auth login` |

7. **Clean slate.** The `cleanSlate` key in the state file (read it like `repo` in step 1) must be set. Then
   `claude plugin list --json` must show no user-scope plugin besides Claude Code's own `@builtin` ones; `~/.claude/skills`
   must hold `advisor-switch`, `setup-check` and `pre-merge-review` (and claude.ai's `synced`), with no
   `underwater-photoshop`, `find-skills` or `codex`; `~/.claude/agents` must hold no file; `~/.claude/CLAUDE.md` must not
   exist; `~/.claude/settings.json` must have no `hooks`, `enabledPlugins` or `deniedMcpServers`. A missing key or a
   leftover means the one-time reset did not finish: repair with step 5 and read its `Clean slate` lines. A plugin the
   user installs on purpose later is theirs; report it, do not remove it.
8. **Done only when step 4 exits 0.** Quote its last line verbatim. Restart notes: Windows Terminal picks up profile
   changes live (a new tab is enough); Claude Code needs a restart for `settings.json` changes, so tell the user to
   restart it if step 5 ran.
