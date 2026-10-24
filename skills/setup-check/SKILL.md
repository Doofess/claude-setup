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
2. **Check it is the main checkout.** Both must hold, else stop and ask for the main clone:
   - `git -C <repo> rev-parse --git-dir` prints the same as `git -C <repo> rev-parse --git-common-dir`
   - `git -C <repo> branch --show-current` prints `main`

   Never run a worktree's `install.cmd`: it repoints `CLAUDE_CODE_PLUGIN_DIRS` at the worktree.
3. **Fresh?** Run `git -C <repo> fetch -q`, then `git -C <repo> status -sb`. If main is behind, say so and run
   `git -C <repo> pull --ff-only` only after the user says yes.
4. **Prove.** Run `python -I <repo>\shell_matrix.py`. It takes a few minutes, because every shell runs
   `install.cmd -Check`. Its last line is `shell matrix: all N shells match` (exit 0) or
   `shell matrix: K difference(s)` (exit 1). Quote the failing lines of the table.
5. **Repair.** For any FAIL run `& "<repo>\install.cmd"`, adding `-SkipPlugins` when only terminal rows failed. Then
   run step 4 again. If it still fails after one repair, show the rows and stop; do not loop.
6. **Hand over what the installer can't fix.** Name the row and give the exact command:

   | Row | Tell the user |
   |---|---|
   | Windows PowerShell policy pinned stricter than RemoteSigned by group policy | Their IT policy owns it and the installer can't change it. Ask the administrator, or use PowerShell 7. |
   | A shell is missing and winget couldn't install it | `winget install Microsoft.PowerShell`, `winget install Git.Git` or `winget install Microsoft.WindowsTerminal`, then step 5. |
   | Claude Code not signed in | Run `claude` and sign in. |
   | GitHub CLI not signed in | `gh auth login` |

7. **Done only when step 4 exits 0.** Quote its last line verbatim. Restart notes: Windows Terminal picks up profile
   changes live (a new tab is enough); Claude Code needs a restart for `settings.json` changes, so tell the user to
   restart it if step 5 ran.
