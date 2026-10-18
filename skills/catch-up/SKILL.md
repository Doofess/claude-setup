---
name: catch-up
description: Use when the session-start notice says another machine has new sessions in this project, or the user asks what they did on their other PC, desktop or laptop. Summarizes those sessions from the OneDrive history copy.
---

# Catch up on another machine's sessions

Each machine copies its `~/.claude/projects` to `%OneDrive%\Projects\CLI Conversation History\<MACHINE>\projects`
(`history_sync.py sync`, run by the SessionEnd and Stop hooks). This skill reads the *other* machines' copies for the
current project. Keep it cheap: the digest goes to a Haiku agent, never into this context.

1. Run, with the session's working directory as `<cwd>`:

   ```bash
   python -I -S ~/.claude/skills/catch-up/history_sync.py extract --cwd "<cwd>"
   ```

   If it prints `Nothing new…` or `No OneDrive history folder…`, tell the user that line and stop.
   Otherwise it prints `digest: <path>; <n> sessions from <machines>` (plus how many older ones were left out).

2. Dispatch an `Explore` agent with `model: haiku`. Don't Read the digest yourself. Brief:

   > Read `<digest path>`, the prompts (USER) and replies (CLAUDE) from sessions on another machine. Return at most
   > 400 words under these headings: **Done**, **Decisions**, **Files and repos touched**, **Open todos**,
   > **Affects this machine** (config to pull, installs, branches to fetch). Use only what the digest says; write
   > "none" for an empty heading.

3. Show the user the summary, headed with the machines and session count from step 1.

4. Save what will still matter later (decisions, open todos, the state of a project) to your memory system as
   project memories, with absolute dates and the source machine. Skip the narration of what happened, and update
   an existing memory instead of adding a duplicate.

5. Only after steps 3 and 4, run:

   ```bash
   python -I -S ~/.claude/skills/catch-up/history_sync.py mark
   ```

   Then the next catch-up and the session-start notice cover only newer sessions.
