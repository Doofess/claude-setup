# Global rules

Two skill plugins are installed. Use each where it is stronger; call the named skill, don't improvise a blend.

## mattpocock-skills: thinking
- Planning or any non-trivial change: `grilling` (user runs `/grill-me` or `/grill-with-docs`). Replaces Superpowers' brainstorming.
- Module/interface design: `codebase-design`. Project vocabulary: `domain-modeling` (`GLOSSARY.md`, ADRs).
- Bugs, failures, slowness: `diagnosing-bugs` (feedback loop first, then hypotheses).
- Reviewing a diff: `code-review` (Standards and Spec axes, reported separately).
- Writing or editing CLAUDE.md, skills, agent docs: `writing-for-agents`.

## superpowers: execution
- Turning an agreed design into steps: `writing-plans`, then `executing-plans` or `subagent-driven-development`.
- Feature work: `using-git-worktrees` for isolation.
- Before saying anything is done, fixed, or passing: `verification-before-completion`.
- Skip `brainstorming` and `systematic-debugging`; the Matt equivalents above own those.

## Defaults
- Issue tracker: GitHub Issues via `gh`. Docs, specs, ADRs: `docs/` in the repo.
- Run `/setup-matt-pocock-skills` once per repo before the engineering skills.
- Destructive git (`push`, `reset --hard`, `clean -f`, `branch -D`, `checkout .`) is blocked by a hook. Tell the user the exact command to run.
- Setup lives in `C:/dev/claude-setup` (repo `Doofess/claude-setup`); change config there and run `install.ps1`, so the desktop stays identical.
