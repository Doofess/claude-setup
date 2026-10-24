---
name: codex
description: Use when a question is about Codex CLI itself, when independent research or a second opinion would help, or when the user asks to give Codex a task. Hands the task to OpenAI's Codex CLI in the background.
---

# Hand a task to Codex

Codex CLI is installed on this PC and signed in to the user's OpenAI subscription, so its work costs Claude nothing.
It runs in the background while you keep working. Its answer is a lead, not evidence: verify before acting on it.

## Good tasks

- Questions about Codex itself: its config keys, skills, agents, hooks. It knows its own CLI better than you do.
- Independent research, in parallel with a Claude subagent on the same question: where the two disagree is
  where to look.
- A second opinion on a plan, a diff or a bug theory. Give it the files, not your conclusion.

## How

1. **Brief.** Write the brief to a file in the scratchpad: the goal, what is ruled out, the files to read, the output
   wanted (format and length), and "mark anything you could not verify as UNVERIFIED".
2. **Run** it with the Bash tool and `run_in_background: true` (it takes minutes):

   ```bash
   codex exec -s read-only --skip-git-repo-check --ephemeral -C "<dir>" -o "<scratchpad>/codex-answer.md" - < "<scratchpad>/codex-brief.md" > "<scratchpad>/codex-run.log" 2>&1
   ```

   - `-s read-only`: it can read and run read-only commands, never edit. Always pass it for research and reviews:
     the codex-setup config gives Codex full access by default.
   - `-o` writes only its final message, so the answer file stays small. The log has the full run; read only its
     tail.
   - `-m gpt-6-astra` for the hardest questions; the default model is fine otherwise.
3. **Read** `codex-answer.md` when the task notification arrives. Don't poll.
4. **Verify** each claim you will act on: `codex <command> --help`, the files it names, the binary
   (`rg -a` on the codex exe), or a test. Tell the user which parts you checked.

## Edits

Only in a git worktree you made for the task: `-s workspace-write -C "<worktree>"`. `-C` only sets the folder;
`workspace-write` is what keeps its writes inside it (and the temp folders), checked on this PC. Tell it not to
commit; review its diff, run the tests and commit yourself.

## Updating Codex

`codex update`, run with the PowerShell tool, not Git Bash: from Git Bash the updater's bare `tar` is Git's GNU tar,
which can't extract to a `C:\` path, and it fails with "did not contain the expected package layout".
Then `codex app-server daemon update`: `codex update` leaves the background daemon on the old version
(`codex app-server daemon version` prints both). It restarts the daemon, so run it when no Codex task is running.
