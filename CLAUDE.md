# Global rules

## Planning and design
- Planning or any non-trivial change: ask the open design questions through the `AskUserQuestion` tool, up to four per call with the recommended option first, never as numbered questions in chat. Don't call Superpowers' `brainstorming`.
- Reviewing a diff: the built-in `/code-review`.

## superpowers: execution
- Turning an agreed design into steps: `writing-plans`, then `executing-plans` by default. Use `subagent-driven-development` only for a plan too long for one context, with each subagent's model set explicitly.
- Feature work: `using-git-worktrees` for isolation.
- Bugs and failures: `systematic-debugging`.
- Before saying anything is done, fixed, or passing: `verification-before-completion`.

## Models and usage
- Sessions start on Sonnet. A big design is planned on Opus in plan mode and written to a file; then `/clear` and implement on Sonnet. Fable only when Opus is stuck: it has its own weekly cap.
- Always set a subagent's model: Haiku for search and reading test output, Sonnet for implementation, Opus only for a whole-branch review. Never leave it to inherit the session's model.
- Start a new session for an unrelated task instead of carrying a long context.

## Photo editing (paid work)
- Underwater or macro photo edits, ARW/RAW, Camera Raw, backscatter, "pop", PSD deliverables: `underwater-photoshop` skill. Local Photoshop via COM, never the Adobe cloud tools for the edit itself. Nothing is uploaded to Adobe cloud.

## Defaults
- Issue tracker: GitHub Issues via `gh`. Docs, specs, ADRs: `docs/` in the repo.
- Git: run `push` and other history-changing commands yourself when I ask for them; don't hand the command back to me. Confirm first only for what can't be undone (`push --force` to a shared branch, `reset --hard`, `clean -f`, `branch -D`).
- Styles in any form (CSS, Tailwind, StyleX, inline): `frontend-design` decides the look. When the `good-css` plugin is installed, read its skill before writing the declarations.
- MCP servers for one project go in that repo's `.mcp.json` (start from `mcp-presets/` in the setup repo), never in user settings.
- Setup lives in `C:/dev/claude-setup` (repo `Doofess/claude-setup`); change config there and run `install.ps1`, so the desktop stays identical.
