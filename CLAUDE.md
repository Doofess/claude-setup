# Global rules

## Planning and design
- Planning or any non-trivial change: ask the open design questions through the `AskUserQuestion` tool, up to four per call with the recommended option first, never as numbered questions in chat. Don't call Superpowers' `brainstorming`.
- Reviewing a diff: the built-in `/code-review`.

## superpowers: execution
- Turning an agreed design into steps: `writing-plans`, then `executing-plans` by default. Under it, dispatch each plan task that edits more than a couple of files to `worker` with the task's brief, then check its report and run the tests yourself; do small tasks inline. Use `subagent-driven-development` only for a plan too long for one context; its implementers are `worker` unless a task needs Opus.
- Feature work: `using-git-worktrees` for isolation.
- Bugs and failures: `systematic-debugging`.
- Before saying done, fixed or passing: run the check (tests, build, the command itself) in this turn and quote the relevant output.

## Models and usage
- Sessions run on Opus 5.5 at high effort; `/effort xhigh` for the hardest problems (effort changes keep the cache, model switches don't). Pick the model at session start.
- In plans and outside them, delegate whenever the work means reading or editing more than a couple of files, and set every subagent's model: `Explore` (Haiku, read-only: Read, Grep, Glob) for search and reading files; `worker` (Sonnet, medium) for implementation, with `effort: high` for concurrency, parsers, security, or after a failed first attempt; Sonnet for web research (Opus when the main thread will act on it unchecked); Opus for a whole-branch review; an explicit `model` on `Plan` agents.
- Advisor: `/advisor opus` before executing a multi-step plan with workers, so each Sonnet worker gets an Opus check before it reports done; `/advisor off` when the plan is finished. Fable only when Opus at `xhigh` is stuck (it has its own weekly cap): `/advisor fable` first, `/model fable` only if that isn't enough. No saved `advisorModel`: subagents inherit it, and the main thread would pay for uncached reads on every call.
- Don't use `fork` for research or side work: forks run on the session model. Use a fresh typed agent with a tight brief.

## Context hygiene
- One task per session; `/clear` between unrelated tasks; `/rewind` to abandon a path.
- Keep command output small: `tail`, `grep` or quiet flags, print only test failures.
- Read large docs (`PLAN.md`, specs) by heading with `offset`/`limit`, never whole.
- In Playwright prefer `browser_evaluate` returning a small JSON value over screenshots and snapshots; screenshot only when judging the look.

## Compact instructions
When compacting, keep decisions, file paths, open todos and failing test names.

## Photo editing (paid work)
- Underwater or macro photo edits, ARW/RAW, Camera Raw, backscatter, "pop", PSD deliverables: `underwater-photoshop` skill. Local Photoshop via COM, never the Adobe cloud tools for the edit itself. Nothing is uploaded to Adobe cloud.

## Defaults
- Issue tracker: GitHub Issues via `gh`. Docs, specs, ADRs: `docs/` in the repo.
- Git: run `push` and other history-changing commands yourself when I ask for them; don't hand the command back to me. Confirm first only for what can't be undone (`push --force` to a shared branch, `reset --hard`, `clean -f`, `branch -D`).
- Styles in any form (CSS, Tailwind, StyleX, inline): `frontend-design` decides the look. When the `good-css` plugin is installed, read its skill before writing the declarations.
- The claude.ai Adobe connector is off by default (about 5k tokens a turn); turn it on per project with `/mcp` for Express, Acrobat or Firefly work.
- MCP servers for one project go in that repo's `.mcp.json` (start from `mcp-presets/` in the setup repo), never in user settings.
- Setup lives in `C:/dev/claude-setup` (repo `Doofess/claude-setup`); change config there and run `install.ps1`, so the desktop stays identical.
