# claude-setup

My Claude Code configuration, versioned so every machine runs the same setup.

| File | Lands at |
| --- | --- |
| `CLAUDE.md` | `~/.claude/CLAUDE.md` (global rules: plugin split, defaults) |
| `settings.json` | merged into `~/.claude/settings.json` (plugins, hooks, status line, model) |
| `hooks/block-dangerous-git.sh` | `~/.claude/hooks/` (blocks `git push`, `reset --hard`, `clean -f`, `branch -D`, `checkout .`) |
| `statusline.py` | `~/.claude/statusline.py` |

Not versioned on purpose: `~/.claude.json` (login state), `.credentials.json`, `history.jsonl`, `~/.remember/`.
Synced plugins and claude.ai connectors follow the account, so they need no setup here.

## New machine (Windows)

1. Install: [Claude Code](https://code.claude.com), [Git for Windows](https://git-scm.com) (provides Git Bash), [GitHub CLI](https://cli.github.com), [Node](https://nodejs.org) 26+, [Python](https://python.org) 3.10+.
   With winget: `winget install Anthropic.ClaudeCode Git.Git GitHub.cli OpenJS.NodeJS Python.Python.3.14` then `npm i -g pnpm`.
2. `claude` once and sign in. `gh auth login`.
3. ```powershell
   git clone https://github.com/Doofess/claude-setup C:\dev\claude-setup
   cd C:\dev\claude-setup
   .\install.ps1
   ```
4. Restart Claude Code. In any repo, run `/setup-matt-pocock-skills` once.

## Changing config

Edit the files here, run `.\install.ps1` (add `-SkipPlugins` when only config changed), commit, push. On the other machine: `git pull` then `.\install.ps1`.

The installer backs up the previous files to `~/.claude/backups/claude-setup-<timestamp>/` every run.
