# claude-setup

My Claude Code configuration, versioned so every machine runs the same setup.

| File | Lands at |
| --- | --- |
| `CLAUDE.md` | `~/.claude/CLAUDE.md` (global rules: plugin split, defaults) |
| `settings.json` | merged into `~/.claude/settings.json` (plugins, hooks, status line, model) |
| `statusline.py` | `~/.claude/statusline.py` (settings launch it as `python -S -c "import statusline; statusline.main()"` with `~/.claude` on `sys.path`, so each one-second render loads the cached `__pycache__/*.pyc` instead of recompiling the script; the installer deletes that cache when it copies a new version) |
| `hooks/bigquery-headers.py` | `~/.claude/hooks/` (turns the `gcloud` sign-in into the bearer token for the BigQuery MCP server) |
| `skills/<name>/` | `~/.claude/skills/<name>/` (personal skills; `underwater-photoshop` drives local Photoshop) |
| `mcp-presets/` | not installed; copy one into a repo as `.mcp.json` (see its README) |

Not versioned on purpose: `~/.claude.json` (login state, user-scope MCP servers), `.credentials.json`, `history.jsonl`, `~/.remember/`.
Synced plugins and claude.ai connectors follow the account, so they need no setup here.

## BigQuery MCP server

Google's remote MCP server (`https://bigquery.googleapis.com/mcp`) supports neither dynamic client
registration nor a built-in client, so instead of creating an OAuth client and storing its secret, the
Google Cloud CLI signs in once and `hooks/bigquery-headers.py` hands Claude Code a fresh token on each
connection (cached 45 minutes, owner-only file). Project: `bookandry` (the app's own Google Cloud
project, BigQuery sandbox, no billing needed).

1. `winget install Google.CloudSDK`, then open a new terminal.
2. `gcloud config set project bookandry` and `gcloud auth login --update-adc` (one browser approval).
3. `.\install.ps1 -SkipPlugins` registers the server (`claude mcp get bigquery` should say Connected).

The signed-in account needs `roles/mcp.toolUser`, `roles/bigquery.jobUser` and `roles/bigquery.dataViewer`
on the project; they were granted on 2026-10-09. Tools: `list_dataset_ids`, `get_table_info`,
`execute_sql_readonly`, `execute_sql`, and job helpers.

## Plugin and MCP policy

- Always-on (user scope): the skills plugins, three LSPs, context7, playwright, chrome-devtools-mcp, remember, and `good-css` from its own marketplace (`vojtaholik/good-css`, declared in `extraKnownMarketplaces`). About five live MCP servers.
- Everything tied to one project (databases, deploy target, observability, Kubernetes) is project scope: `mcp-presets/`.
- The GitHub MCP server stays off; `gh` covers it with far less context.
- `deniedMcpServers` blocks the claude.ai connectors nobody uses (Slack, Linear, Atlassian, Notion, Figma, Intercom, desktop-commander). Adobe and Canva are **not** blocked; both are in use. Adobe: the "Adobe for creativity" claude.ai connector is the only route to Adobe tools from the CLI (the plugin copies 403). Photo edits themselves run in local Photoshop via the `underwater-photoshop` skill.

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
5. Photo work: `python -m venv ~/.claude/skills/underwater-photoshop/.venv` and `pip install -r skills/underwater-photoshop/requirements.txt` into it. Needs Photoshop 2026 installed (COM `Photoshop.Application`).

## Keybindings

`keybindings.json` is merged into `~/.claude/keybindings.json` per context and key (other bindings survive). It unbinds the panel's collapse shortcut (`ctrl+x ctrl+a`, `abovePrompt:toggle`) so the `readable-session` band above the prompt stays on; the `[-]` click is engine-drawn and cannot be removed from a mod.

## Settings merge rules

`settings.json` is merged into the machine's `~/.claude/settings.json`: `enabledPlugins` and `env` per entry (the
repo wins on conflict, other machine entries stay), `permissions` with arrays unioned, `hooks` per event and per
command, and every other key replaced by the repo's value. `<repo>` inside an `env` value expands to this clone's
path with forward slashes, so `CLAUDE_CODE_PLUGIN_DIRS` points at `<clone>/mods/readable-session` wherever the repo
lives; other directories already in that variable (`;`-separated) are kept and ours is added once.

## Changing config

Edit the files here, run `.\install.ps1` (add `-SkipPlugins` when only config changed), commit, push. On the other machine: `git pull` then `.\install.ps1`.

The installer backs up the previous files to `~/.claude/backups/claude-setup-<timestamp>/` every run.
