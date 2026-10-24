---
name: advisor-switch
description: Use when about to execute a multi-step plan with subagent workers (advisor on, Opus), when Opus at xhigh is stuck on a problem (advisor Fable), or when that plan or problem is done (advisor off). Switches Claude Code's advisor for the current project only.
---

# Advisor, per project

The advisor is a second model the session (and every subagent, which inherits it) can consult before it reports
done. It costs an uncached read of the conversation on each call, so it is on only while the work needs it, and only
in this project: the setting lives in the project's `.claude/settings.local.json` (personal, kept out of git), never in
`~/.claude/settings.json`, where it would turn on in every session of every project.

## When

| Situation | Run |
|---|---|
| About to execute a multi-step plan whose tasks go to Sonnet `worker` subagents | `opus` |
| Opus at `xhigh` is stuck on the same problem after real attempts | `fable` (its own weekly cap; ask the user for `/model fable` only if that is not enough) |
| The plan is finished, or the stuck problem is solved | `off` |
| Unsure what is set | `status` |

Small inline work, questions and single-file fixes do not need it. Don't ask the user to type `/advisor`: it writes
the user-level file.

## How

```bash
python "<this skill's folder>/advisor.py" opus     # or fable, off, status
```

Run it from anywhere inside the project; it finds the git top level. It prints one line, for example
`advisor: opus for C:\dev\Airport, from the next prompt`.

- The change is live from the next prompt, not the turn that makes it. On first use, confirm the advisor tool appeared.
- Other sessions open in the same project see it too; sessions in other projects do not.
- Switch it `off` when the work ends, in the same turn as the last task's report.
