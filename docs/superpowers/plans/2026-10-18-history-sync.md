# History Sync and /catch-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Copy each machine's Claude Code history into OneDrive (never moving or changing the local copy) and give every machine a `/catch-up` skill that summarizes what the other machine did in the current project.

**Architecture:** One stdlib-only Python module, `skills/catch-up/history_sync.py`, with four subcommands: `sync` (SessionEnd and Stop hooks, detached), `check` (SessionStart hook, prints a one-line notice), `extract` and `mark` (used by the skill). The installer already copies `skills/*` to `~/.claude/skills/` and merges `settings.json` hooks, so `install.ps1` itself does not change.

**Tech Stack:** Python 3.10+ stdlib, `unittest` (same as `tests/test_mcp_off.py`), Claude Code hooks and skills.

**Spec:** the design agreed in conversation on 2026-10-18, summarized here:

- Local `~/.claude/projects` is only ever read. Nothing is moved, no junction, no `CLAUDE_CONFIG_DIR`.
- Destination: `%OneDrive%\Projects\CLI Conversation History\<COMPUTERNAME>\projects`, with one subfolder per machine.
- The copy adds and updates files and never deletes anything (archive).
- `cleanupPeriodDays: 365`.
- A SessionStart notice reports new sessions from other machines for the current project. `/catch-up` summarizes them.
- "New" means not read at the last catch-up (per-machine state file).
- The result goes into chat, and the lasting facts are saved to memory.
- Everything lives in `claude-setup`, delivered by PR to `Doofess/claude-setup`.

## Global Constraints

- Stdlib only. Hooks run as `python -S` (no site-packages), the same way the status line does.
- A hook must never break or slow a session. On any error, or when OneDrive is unset or missing, it exits 0 and prints nothing.
- Destination root: `os.environ["OneDrive"]` + `Projects/CLI Conversation History`. The machine name comes from `os.environ["COMPUTERNAME"]`, falling back to `platform.node()`.
- State and lock files are local and never synced: `~/.claude/catch-up-state.json`, `~/.claude/history-sync.lock`, `~/.claude/history-sync.log`, `~/.claude/catch-up-digest.md`.
- Work happens on branch `history-sync` in a worktree (`.claude/worktrees/` is gitignored).

## Review Focus

1. **OneDrive unset or its folder missing** (a new machine, OneDrive signed out): `sync` and `check` exit 0 silently. Tests are in Task 1 and Task 2.
2. **Source file locked or deleted mid-copy** (a live session, or the 365-day cleanup running): skip it, count an error, and carry on. A `.part` file is never left behind. Test is in Task 1.
3. **Truncated or corrupt JSONL line** (OneDrive still downloading): skip the line, don't crash. Test is in Task 3.
4. **Machine-name case** (`ROTEM` vs `rotem` folder): this machine's folder is excluded case-insensitively. Test is in Task 2.
5. **First catch-up with hundreds of sessions:** digest only the newest 10. The rest are still marked read, and the output says how many were left out. Test is in Task 3.

---

### Task 1: Copy to OneDrive (`sync`)

**Files:**
- Create: `skills/catch-up/history_sync.py`
- Test: `tests/test_history_sync.py`

**Interfaces:**
- Produces:
  - `sync_root() -> Path | None`: the root folder, or `None` when `OneDrive` is unset or `<OneDrive>/Projects` does not exist.
  - `machine_name() -> str`
  - `copy_new(src: Path, dst: Path) -> tuple[int, int]`: returns `(copied, errors)`.
  - `main(argv: list[str] | None = None) -> int`, with subcommands added by later tasks.
  - The module-level constant `CLAUDE_DIR = Path.home() / ".claude"`, which tests monkeypatch.

- [ ] **Step 1: Write the failing tests** in `tests/test_history_sync.py`. Import style follows `test_mcp_off.py`, with `sys.path` pointing at `skills/catch-up`. Use `tempfile.TemporaryDirectory()` trees.
  - `test_copies_new_files_keeping_tree`: `src/C--dev/a.jsonl` and `src/C--dev/s1/subagents/b.jsonl` both exist in `dst` with the same bytes, and the result is `(2, 0)`.
  - `test_second_run_copies_nothing`: a second `copy_new` returns `(0, 0)`.
  - `test_updates_grown_file`: append to `src/a.jsonl`, and `copy_new` returns `(1, 0)` with the new bytes in `dst`.
  - `test_never_deletes_extra_destination_files`: `dst/old.jsonl` is not in `src`, and it still exists afterwards.
  - `test_missing_source_file_counts_error_no_part_left`: patch `shutil.copy2` to raise `FileNotFoundError` for one file. The result has `errors == 1`, the other files are copied, and no `*.part` file exists under `dst`.
  - `test_sync_root_none_without_onedrive`: with `OneDrive` removed from `os.environ`, it returns `None`. With `OneDrive` set to a temp dir that has no `Projects` folder, it also returns `None`.
  - `test_sync_exits_zero_when_no_root`: `main(["sync"])` returns `0` and creates nothing.
  - `test_lock_blocks_second_sync`: a fresh lock file means `main(["sync"])` copies nothing. A lock older than 2 hours is taken over.

- [ ] **Step 2: Run them and confirm they fail**

  Run: `python -m unittest tests.test_history_sync -q` (from the worktree root)
  Expected: `ModuleNotFoundError: No module named 'history_sync'`

- [ ] **Step 3: Implement `history_sync.py`.**
  - `copy_new` walks `src` with `os.walk`. It copies a file when the destination is missing, its size differs, or the source mtime is more than 2 s newer. Each copy goes to `<dst>.part` with `shutil.copy2`, then `os.replace` into place. Any `OSError` counts as an error, the `.part` file is removed, and the walk continues.
  - `sync` steps:
    1. Get `sync_root()`. Return 0 if it is `None`.
    2. Take the lock (`os.open(O_CREAT|O_EXCL)`). If it is held and younger than 2 hours, return 0.
    3. Run `copy_new(CLAUDE_DIR/"projects", root/machine_name()/"projects")`.
    4. Overwrite `history-sync.log` with one line: ISO time, copied, errors.
    5. Remove the lock in `finally`.
  - `sync --detach` re-launches `[sys.executable, "-S", __file__, "sync"]`. On Windows it uses `subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP` with stdio set to `DEVNULL`. Then it returns 0 straight away, because SessionEnd must not wait for a 1 GB first copy.
  - `main` catches every exception and returns 0, so hooks never fail.

- [ ] **Step 4: Run the tests and confirm they pass**

  Run: `python -m unittest tests.test_history_sync -q`
  Expected: `OK`

- [ ] **Step 5: Commit**

  ```bash
  git add skills/catch-up/history_sync.py tests/test_history_sync.py docs/superpowers/plans/2026-10-18-history-sync.md
  git commit -m "history sync: copy ~/.claude/projects to OneDrive per machine, never deleting"
  ```

### Task 2: New-session notice (`check`)

**Files:**
- Modify: `skills/catch-up/history_sync.py`
- Test: `tests/test_history_sync.py`

**Interfaces:**
- Consumes: `sync_root()`, `machine_name()`, `CLAUDE_DIR` from Task 1.
- Produces:
  - `mangle(path: str) -> str`: replaces every char outside `[A-Za-z0-9]` with `-`.
  - `match_project_dirs(projects: Path, cwd: str) -> list[Path]`
  - `new_sessions(root: Path, me: str, cwd: str, read: dict[str, int]) -> list[Session]`
  - `Session` is a `NamedTuple(key: str, path: Path, machine: str, mtime_ns: int)`. `key` is the path relative to `root` with forward slashes, e.g. `DESKTOP/projects/C--dev/abc.jsonl`.
  - `load_state() -> dict` and `save_state(state: dict) -> None`, which read and write `CLAUDE_DIR/"catch-up-state.json"` with the shape `{"read": {key: mtime_ns}, "pending": {key: mtime_ns}}`. A missing or corrupt file loads as empty.

- [ ] **Step 1: Write the failing tests**
  - `test_mangle`: `mangle(r"C:\Users\HighL\.claude") == "C--Users-HighL--claude"`, and `mangle(r"C:\dev") == "C--dev"`.
  - `test_match_exact_first`: with dirs `C--dev` and `C--dev-bookandry`, the cwd `C:\dev` gives `[C--dev]`.
  - `test_match_falls_back_to_last_segment`: with dir `C--dev-bookandry`, the cwd `D:\work\bookandry` gives `[C--dev-bookandry]`. With no match it returns `[]`.
  - `test_new_sessions_excludes_this_machine_case_insensitive`: the root holds `ROTEM/projects/C--dev/a.jsonl` and `DESKTOP/projects/C--dev/b.jsonl`. With `me="rotem"`, only the `b` session comes back.
  - `test_new_sessions_only_top_level_jsonl`: `DESKTOP/projects/C--dev/s1/subagents/x.jsonl` and `memory/m.md` are ignored.
  - `test_new_sessions_skips_already_read`: a key in `read` with the same `mtime_ns` is skipped. A changed mtime counts as new.
  - `test_check_prints_notice`: with one new session from `DESKTOP`, `main(["check"])` with stdin `{"cwd": "C:\\dev"}` prints exactly `1 new session from DESKTOP in this project since your last catch-up. Run /catch-up to read it.` Two sessions use the plural form: `2 new sessions from DESKTOP ... Run /catch-up to read them.` Several machines are joined as `DESKTOP, WORK`.
  - `test_check_silent_when_nothing_or_no_root`: no new sessions, or no OneDrive, gives empty stdout and exit 0.

- [ ] **Step 2: Run them and confirm they fail**

  Run: `python -m unittest tests.test_history_sync -q`
  Expected: `AttributeError: module 'history_sync' has no attribute 'mangle'`

- [ ] **Step 3: Implement.**
  - `match_project_dirs`:
    - Compare names case-insensitively.
    - An exact `mangle(cwd)` match wins.
    - Otherwise, return the dirs whose name equals `mangle(basename)` or ends with `"-" + mangle(basename)`.
    - An empty basename (a drive root) gives `[]`.
  - `check` takes `cwd` from the hook JSON on stdin and falls back to `os.getcwd()`. It must only list directories and stat files, never read transcripts, so it stays fast on OneDrive placeholders.

- [ ] **Step 4: Run the tests and confirm they pass**

  Run: `python -m unittest tests.test_history_sync -q`
  Expected: `OK`

- [ ] **Step 5: Commit**: `git commit -am "history sync: SessionStart notice for other machines' new sessions"`

### Task 3: Digest for the skill (`extract`, `mark`)

**Files:**
- Modify: `skills/catch-up/history_sync.py`
- Test: `tests/test_history_sync.py`

**Interfaces:**
- Consumes: `new_sessions`, `match_project_dirs`, `load_state`, `save_state`, `Session` from Task 2.
- Produces:
  - `digest_session(path: Path) -> str`
  - `main(["extract", "--cwd", PATH, "--limit", "10"])` writes `CLAUDE_DIR/"catch-up-digest.md"` and prints one line: `digest: <path>; <n> sessions from <machines>` plus `(<m> older not included)` when some were cut. With nothing new it prints `Nothing new from other machines for this project.`
  - `main(["mark"])` moves `pending` into `read`.

- [ ] **Step 1: Write the failing tests.** Build JSONL fixtures in the test with `json.dumps` lines.
  - `test_digest_keeps_prompts_and_replies`: a user record with string content gives `USER: <text>`, and an assistant `text` block gives `CLAUDE: <text>`.
  - `test_digest_skips_noise`: none of the following appear in the output:
    - user `tool_result` blocks
    - assistant `tool_use` and `thinking` blocks
    - records with `isMeta: true` or `isSidechain: true`
    - `<system-reminder>…</system-reminder>` inside a prompt (removed, while the rest of the prompt stays)
    - non-user/assistant record types such as `attachment`
  - `test_digest_survives_bad_lines`: a truncated last line and a non-JSON line are skipped, and the valid records still appear.
  - `test_digest_header_and_cap`: the header line is `## <session id> · <first timestamp> → <last timestamp>`. A session over 8000 chars keeps its first 2000 and last 6000 chars, with a `[… <n> chars cut …]` marker in between.
  - `test_extract_limits_and_marks_all_pending`: 20 new sessions with `--limit 15` gives 15 in the digest, newest-by-mtime chosen and printed oldest-first. The printed line contains `(5 older not included)`. `pending` holds all 20 keys.
  - `test_mark_moves_pending_to_read`: after `mark`, `check` prints nothing and `pending == {}`.
  - `test_extract_nothing_new`: it prints the "Nothing new" line and writes no digest.

- [ ] **Step 2: Run them and confirm they fail**

  Run: `python -m unittest tests.test_history_sync -q`
  Expected: `AttributeError: ... 'digest_session'`

- [ ] **Step 3: Implement.** Each digest section starts with `# <machine> · <project dir>`. Prompts and replies are truncated to 800 chars each (cut from the plan's 1500 to keep /catch-up cheap). Files are read with `encoding="utf-8", errors="replace"`.

- [ ] **Step 4: Run all tests and confirm they pass**

  Run: `python -m unittest discover -s tests -q`
  Expected: `OK` (including the existing mcp_off and statusline tests)

- [ ] **Step 5: Commit**: `git commit -am "history sync: extract/mark digest for /catch-up"`

### Task 4: Skill, hooks, settings, README

**Files:**
- Create: `skills/catch-up/SKILL.md`
- Modify: `settings.json` (add `cleanupPeriodDays` and `hooks`)
- Modify: `README.md` (table row and a new "Conversation history sync" section)

**Interfaces:**
- Consumes: the `sync --detach`, `check`, `extract`, and `mark` subcommands.

- [ ] **Step 1: Write `SKILL.md`** with the `superpowers:writing-skills` skill. Frontmatter: `name: catch-up`. The description should say to use it when the SessionStart notice reports new sessions from another machine, or when the user asks what they did on the other PC. Body steps:
  1. Run `python -S ~/.claude/skills/catch-up/history_sync.py extract --cwd "<current dir>"`. If the output says nothing is new, say so and stop.
  2. Dispatch an `Explore` agent (`model: haiku`) to read the digest file. It returns: **Done**, **Decisions**, **Files/repos touched**, **Open todos**, and **Affects this machine** (e.g. a config change to pull or reinstall). It must stay under 400 words and must not invent anything that isn't in the digest.
  3. Show the summary to the user.
  4. Save the lasting facts (decisions, open todos, project state) to this machine's memory system as project memories, dated with absolute dates. Never save session narration.
  5. Run `... history_sync.py mark` only after steps 3–4 succeed.

- [ ] **Step 2: Add to `settings.json`:**

  ```json
  "cleanupPeriodDays": 365,
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "timeout": 10,
      "command": "python -S -c \"import os,sys;sys.path.insert(0,os.path.expanduser('~/.claude/skills/catch-up'));import history_sync;sys.exit(history_sync.main())\" check" }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command", "timeout": 10,
      "command": "python -S -c \"import os,sys;sys.path.insert(0,os.path.expanduser('~/.claude/skills/catch-up'));import history_sync;sys.exit(history_sync.main())\" sync --detach" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "timeout": 10,
      "command": "python -S -c \"import os,sys;sys.path.insert(0,os.path.expanduser('~/.claude/skills/catch-up'));import history_sync;sys.exit(history_sync.main())\" sync --detach" }] }]
  }
  ```

  Stop runs the same detached copy after each reply, so a session that is never exited cleanly (lid closed, terminal killed) still reaches OneDrive. The lock keeps overlapping runs from copying at the same time.

  With `-c`, `sys.argv` is `['-c', 'check']`, so `main(None)` must read `sys.argv[1:]`.

- [ ] **Step 3: Update `README.md`.**
  - Add a table row: `skills/catch-up/` lands at `~/.claude/skills/catch-up/`.
  - Add a "Conversation history sync" section covering:
    - where copies go
    - copy-only and never-delete
    - the 365-day retention
    - the SessionStart notice and `/catch-up`
    - the state file
    - that `--resume` lists only local sessions
    - how to check the last run (`~/.claude/history-sync.log`)

- [ ] **Step 4: Check the merge without touching the machine.** Dot-source the merge functions from `install.ps1`, feed them a copy of the current `~/.claude/settings.json` plus the repo template, and confirm the merged result has both hooks and `cleanupPeriodDays: 365`.

  Run: `pwsh -NoProfile -Command "<parse install.ps1 for Merge-* functions, merge, print hooks + cleanupPeriodDays as JSON>"`
  Expected: the JSON shows the `SessionStart` and `SessionEnd` commands and `365`.

- [ ] **Step 5: Commit**: `git commit -am "catch-up skill, SessionStart/SessionEnd hooks, 365-day retention, README"`

### Task 5: Install on this laptop, verify, ship

- [ ] **Step 1:** From the worktree, run `pwsh -File install.ps1 -SkipPlugins -SkipFont`. Expected: `DONE: all checks passed`.
- [ ] **Step 2:** Run the first copy in the foreground: `python -S ~/.claude/skills/catch-up/history_sync.py sync`. Then compare file counts between `~/.claude/projects` and `%OneDrive%\Projects\CLI Conversation History\ROTEM\projects`. Expected: the counts are equal, apart from files being written live, and `history-sync.log` shows `errors 0` or a small number.
- [ ] **Step 3:** Confirm the local copy is untouched: the file count and total size of `~/.claude/projects` are the same as before Step 2 (1360 files / 961 MB at planning time, plus this session's growth).
- [ ] **Step 4:** Simulate the other machine. Copy two `C--dev` transcripts into a temporary `…\_TEST\projects\C--dev\`, then run `check` with stdin `{"cwd":"C:\\dev"}`. Expected: `2 new sessions from _TEST …`. Then run `extract`, which should write the digest. Finally delete the `_TEST` folder and `catch-up-state.json`.
- [ ] **Step 5:** Push the branch, open a PR on `Doofess/claude-setup` (body via `mattpocock-skills:pr`), and merge it. Then run `git pull` on `main` in `C:\dev\claude-setup` and remove the worktree.
