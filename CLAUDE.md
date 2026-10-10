# Global rules

Two skill plugins are installed. Use each where it is stronger; call the named skill, don't improvise a blend.

## mattpocock-skills: thinking
- Planning or any non-trivial change: no skill. Ask the open design questions through the `AskUserQuestion` tool, up to four per call with the recommended option first, never as numbered questions in chat. Don't call `grilling` or Superpowers' brainstorming.
- Module/interface design: `codebase-design`. Project vocabulary: `domain-modeling` (`GLOSSARY.md`, ADRs).
- Bugs, failures, slowness: `diagnosing-bugs` (feedback loop first, then hypotheses).
- Reviewing a diff: `code-review` (Standards and Spec axes, reported separately).
- Writing or editing CLAUDE.md, skills, agent docs: `writing-for-agents`.
- Ticket-driven work: `to-spec` → `to-tickets` → `implement` (or `implement-spec` for a whole spec on one branch). Work bigger than one session: `wayfinder`.
- End of a long session: `retro` (environment improvements). Before context runs out: `handoff`, not compaction. Unclear message from me: user runs `/wait-what`.
- Every few days on a live codebase: `improve-codebase-architecture`. PR bodies: `pr`. Lost? `ask-matt` routes.

## superpowers: execution
- Turning an agreed design into steps: `writing-plans`, then `executing-plans` or `subagent-driven-development`.
- Feature work: `using-git-worktrees` for isolation.
- Before saying anything is done, fixed, or passing: `verification-before-completion`.
- Skip `brainstorming` and `systematic-debugging`; the Matt equivalents above own those.

## Photo editing (paid work)
- Underwater or macro photo edits, ARW/RAW, Camera Raw, backscatter, "pop", PSD deliverables: `underwater-photoshop` skill. Local Photoshop via COM, never the Adobe cloud tools for the edit itself. Nothing is uploaded to Adobe cloud.

## Defaults
- Issue tracker: GitHub Issues via `gh`. Docs, specs, ADRs: `docs/` in the repo.
- Run `/setup-matt-pocock-skills` once per repo before the engineering skills.
- Destructive git (`push`, `reset --hard`, `clean -f`, `branch -D`, `checkout .`) is blocked by a hook. Tell the user the exact command to run.
- Styles in any form (CSS, Tailwind, StyleX, inline): read the `good-css` skill before writing them. `frontend-design` decides the look; `good-css` decides the declarations.
- MCP servers for one project go in that repo's `.mcp.json` (start from `mcp-presets/` in the setup repo), never in user settings.
- Setup lives in `C:/dev/claude-setup` (repo `Doofess/claude-setup`); change config there and run `install.ps1`, so the desktop stays identical.
