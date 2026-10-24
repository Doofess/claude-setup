# Project-level Claude Code setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Claude Code sessions in this repo cheaper and more accurate with project-level config only: a repo-specific CLAUDE.md, hidden unused connectors/skills/plugins, edit and turn-end checks, and a live-check skill.

**Architecture:** Everything lives in the repo's own `.claude/` (committed `settings.json`, `hooks/`, `skills/`) plus a project `CLAUDE.md`. The global rules move to `global/CLAUDE.md`, which `install.ps1` copies to `~/.claude/CLAUDE.md` as before. Hooks are stdlib Python scripts that skip quietly when their tool is missing.

**Tech Stack:** Claude Code 2.1.310 settings and hooks, Python 3.13 stdlib (`unittest`), Windows PowerShell 5.1 parser, ruff 0.17.1 (winget `astral-sh.ruff`), Biome 2.6.3 (`@biomejs/biome`, root devDependency), pwsh.

**Spec:** the user's answers of 2026-10-24 (this session), recorded under Decisions below.

## Decisions (the spec)

1. CLAUDE.md: the global rules' source moves to `global/CLAUDE.md` (install copies it from there); the repo gets a short CLAUDE.md of its own.
2. Hide in this project: claude.ai connectors (`disableClaudeAiConnectors`), unused skills (`skillOverrides` off), context7 and rust-analyzer (`enabledPlugins` false). Playwright stays. `bashOutputMaxChars` stays default.
3. Hooks: PS 5.1 parse check on `.ps1` edits, ruff on `.py` edits, Biome on mod edits, tests at turn end.
4. A project skill `live-check` for the demo-window capture and engine/mod-type lookup.
5. Nothing changes at user level: no edits to `~/.claude/settings.json`; installing the ruff CLI on the PC is in scope (the user asked for CLIs).

## Global Constraints

- Project scope only: `.claude/settings.json` (committed), never `~/.claude/settings.json`. Repo root `settings.json` is the *global* template and is not edited by this plan.
- `install.ps1` must still parse and run under Windows PowerShell 5.1 and pwsh; run it only from main after merge: `pwsh -NoProfile -File install.ps1`. Never run a worktree's `install.ps1`.
- Hook scripts: Python stdlib only, run as `python "$CLAUDE_PROJECT_DIR/.claude/hooks/<name>.py"` (hooks run in Git Bash on Windows). Exit 2 with the problem on stderr = feedback to Claude; a missing tool = exit 0, no output.
- Keep hook output small: at most 30 lines on stderr.
- Tests: `python -m unittest discover -s tests -q` and `claude plugin test mods/session-cards`; both green before each commit.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A Stop hook that loops: failing tests must not block twice in a row (`stop_hook_active` true → exit 0, failures go to `systemMessage`).
2. A Stop hook that runs on every turn: it must run only when code changed since its last run (fingerprint in the git dir, per worktree).
3. Hooks on a machine without ruff/Biome (the desktop before bootstrap): silent exit 0, never an error on every edit.
4. Project `skillOverrides`/`enabledPlugins` replacing instead of merging the user-level ones: the user-level `name-only` skills and enabled plugins must still behave the same apart from this project's changes (probe in Task 2).
5. Paths with spaces and backslashes in `tool_input.file_path` (the user's home is `C:\Users\Home Office`).

---

### Task 1: Global rules move to `global/CLAUDE.md`; project CLAUDE.md

**Files:**
- Move: `CLAUDE.md` → `global/CLAUDE.md` (content unchanged, `git mv`)
- Create: `CLAUDE.md` (project, new content)
- Modify: `install.ps1:662-663` (copy from `global\CLAUDE.md`)
- Modify: `README.md:71,148` (and any other line naming the repo's `CLAUDE.md` as the global source)
- Test: `tests/test_install.py`

- [ ] **Step 1: Failing test** in `InstallerTest`: `test_installer_copies_the_global_rules_from_global_folder` — `install.ps1` text contains `Join-Path $repo 'global\CLAUDE.md'` and not `Join-Path $repo 'CLAUDE.md'`; `global/CLAUDE.md` exists and starts with `# Global rules`; the repo `CLAUDE.md` does not start with `# Global rules`.
- [ ] **Step 2:** `python -m unittest tests.test_install -q` → FAIL on the new test.
- [ ] **Step 3:** `git mv CLAUDE.md global/CLAUDE.md`; change the copy line; update README rows.
- [ ] **Step 4:** Write the project `CLAUDE.md` (≤ 30 lines, headed `# claude-setup (this repo)`), covering exactly:
  - What lives where: root `settings.json`, `global/CLAUDE.md`, `statusbar.py`, `skills/`, `agents/`, `themes/`, `mods/session-cards` are installed globally by `install.ps1`; `.claude/` is this repo's own project config (hooks, skill, settings).
  - Tests: `python -m unittest discover -s tests -q`; `claude plugin test mods/session-cards` and `claude plugin validate mods/session-cards` (its one plugin-directory warning is pre-existing).
  - Install: only main's, `pwsh -NoProfile -File install.ps1`, after merging; a worktree's install repoints `CLAUDE_CODE_PLUGIN_DIRS`. `install.ps1` must parse under Windows PowerShell 5.1 (a hook checks).
  - Flow: worktrees under `.claude/worktrees/`, PR, `gh pr merge N --squash --delete-branch`; leave the worktree directory before merging or its removal fails.
  - Engine facts: binary `$USERPROFILE/.local/share/claude/versions/<version>` searched with `rg -a`; mod API types `$LOCALAPPDATA/Temp/claude/bundled-skills/<version>/*/plugin-authoring/types/claude-code.d.ts`; the `live-check` skill does both and the demo-window capture.
- [ ] **Step 5:** `python -m unittest discover -s tests -q` → OK. `powershell.exe -NoProfile -Command "[void][System.Management.Automation.Language.Parser]::ParseFile('install.ps1',[ref]$null,[ref]$e); $e.Count"` → `0`.
- [ ] **Step 6: Commit** `git add -A && git commit -m "Global rules move to global/CLAUDE.md; the repo gets its own CLAUDE.md"`

### Task 2: Project settings — connectors, skills, plugins

**Files:**
- Create: `.claude/settings.json`

**Interfaces:**
- Produces: `.claude/settings.json` with top-level keys that Tasks 4 and 5 extend with `hooks`.

- [ ] **Step 1: Probe before** (from the worktree): `claude -p --model haiku "List every skill name and every deferred tool name starting with mcp__ you can see, one per line, nothing else" > <scratch>/before.txt`; count `mcp__claude_ai`, `mcp__plugin_context7`, and the skills below.
- [ ] **Step 2:** Write `.claude/settings.json`:
  - `"disableClaudeAiConnectors": true`
  - `"enabledPlugins": {"context7@anthropic-plugin-directory": false, "rust-analyzer-lsp@claude-plugins-official": false}`
  - `"skillOverrides"`: `"off"` for `dataviz`, `artifact-design`, `artifact-diagramming`, `artifact-capabilities`, `docx`, `pdf`, `pptx`, `xlsx`, `docs`, `built-in-browser`, `chrome-browser`, `computer-use`, `underwater-photoshop`, `claude-api`.
- [ ] **Step 3: Probe after**, same prompt → `after.txt`. Expected: 0 `mcp__claude_ai`, 0 `mcp__plugin_context7`, none of the 14 skills; superpowers, frontend-design, playwright tools, `advisor-switch`, `deep-research` still present. Any skill still listed: drop its key and ledger a ruling.
- [ ] **Step 4:** Merge check: run the same probe from a scratch directory outside the repo; user-level behaviour unchanged (connectors and context7 present there).
- [ ] **Step 5: Commit** `git add .claude/settings.json && git commit -m "Project settings: no claude.ai connectors, unused skills or context7 here"`

### Task 3: Lint tools and baselines

**Files:**
- Create: `package.json` (root; `"private": true`, devDependency `"@biomejs/biome": "2.6.3"` exact), `package-lock.json`, `biome.json`, `ruff.toml`
- Modify: `.gitignore` (add `node_modules/`), `README.md` (desktop bootstrap list: `winget install astral-sh.ruff`, `npm install` at repo root)
- Possibly modify: Python and mod files, only for safe lint fixes

- [ ] **Step 1:** `winget install --id astral-sh.ruff -e --accept-source-agreements --accept-package-agreements`; `ruff --version` → `ruff 0.17.1` (new shell may be needed; it lands in WinGet Links).
- [ ] **Step 2:** `ruff.toml`: `line-length = 120`, `target-version = "py313"`, default rule set. `biome.json`: Biome 2.6.3 schema, `files.includes` = `["mods/**/*.ts", "mods/**/*.tsx"]`, linter recommended, formatter disabled (the hook lints only).
- [ ] **Step 3:** `npm install` at root.
- [ ] **Step 4: Baselines** — `ruff check .` and `npx biome lint` must exit 0. Allowed: `ruff check --fix` safe fixes, Biome safe fixes, and rule-level ignores (in config, with a one-line comment each) for findings whose fix would change behaviour. `skills/underwater-photoshop/**` is paid-work code: config ignores only, no edits there.
- [ ] **Step 5:** Both suites green (Global Constraints).
- [ ] **Step 6: Commit** `"Lint tools: ruff and Biome configs, clean baselines"`

### Task 4: Edit hook — PS 5.1 parse, ruff, Biome

**Files:**
- Create: `.claude/hooks/check_edit.py`
- Modify: `.claude/settings.json` (add `hooks.PostToolUse`: matcher `Edit|Write|MultiEdit`, command `python "$CLAUDE_PROJECT_DIR/.claude/hooks/check_edit.py"`, timeout 60)
- Test: `tests/test_hooks.py`

**Interfaces:**
- Consumes: Task 3's `ruff.toml`, `biome.json`, root `node_modules`.
- Produces: `check(path: str, root: str) -> tuple[int, str]` (exit code, stderr text); `main()` reads hook JSON on stdin (`tool_input.file_path`, `cwd`), root = `git -C <dir of file> rev-parse --show-toplevel`.

Behaviour: `.ps1`/`.psm1` → `powershell.exe -NoProfile -NonInteractive -Command` with `Parser::ParseFile`, errors as `<file>:<line>: <message>`; `.py` → `ruff check --quiet --output-format concise <file>` from root; `.ts`/`.tsx` under `<root>/mods/` → the pinned Biome in `<root>/node_modules` (run its JS entry with `node`, not the `.cmd`), `lint` the file; anything else, a missing tool, or a missing file → `(0, "")`. Findings → exit 2, stderr capped at 30 lines.

- [ ] **Step 1: Failing tests** (`unittest`, subprocess with JSON on stdin, temp files under a temp dir whose name contains a space):
  - `test_ps1_with_51_only_syntax_blocks`: file with `$x ??= 1` → exit 2, stderr names line 1.
  - `test_valid_ps1_passes`: `Write-Output 1` → exit 0, empty stderr.
  - `test_python_lint_finding_blocks` (`skipUnless(shutil.which("ruff"))`): `import os\n` → exit 2, stderr contains `F401`.
  - `test_other_files_pass`: `.md` → exit 0.
  - `test_missing_file_passes`.
  - `test_mod_lint_finding_blocks` (skip unless Biome installed): a `.tsx` under a temp `mods/` in a temp git repo with `node_modules` linked or the test pointed at the real root — the implementer picks; must exercise the real Biome.
- [ ] **Step 2:** Run → FAIL (script missing).
- [ ] **Step 3:** Implement; add the settings entry.
- [ ] **Step 4:** Tests pass; both suites green.
- [ ] **Step 5: Commit** `"Edit hook: PS 5.1 parse, ruff and Biome on the edited file"`

### Task 5: Turn-end tests hook

**Files:**
- Create: `.claude/hooks/stop_tests.py`
- Modify: `.claude/settings.json` (add `hooks.Stop`: command `python "$CLAUDE_PROJECT_DIR/.claude/hooks/stop_tests.py"`, timeout 600)
- Test: `tests/test_hooks.py`

**Interfaces:**
- Produces: `fingerprint(root: str) -> str` (sha256 over `git rev-parse HEAD`, `git diff HEAD` and untracked file contents, limited to `*.py`, `*.ps1`, `mods/**`, `tests/**`); `suites(root: str, changed: list[str]) -> list[list[str]]` (Python suite when any `.py`/`.ps1`/`tests/` path changed; `claude plugin test mods/session-cards` when a `mods/` path changed); stamp file `<git rev-parse --git-dir>/claude-stop-tests` (per worktree, never committed).

Behaviour: read hook JSON (`cwd`, `stop_hook_active`). Same fingerprint as the stamp → exit 0, silent. Otherwise run the suites, write the stamp. All pass → exit 0. Failures: `stop_hook_active` false → exit 2, stderr = the failing tests' names and last lines (≤ 30); true → exit 0 with stdout JSON `{"systemMessage": "<same text>"}`. Changed paths = `git diff --name-only HEAD` + untracked, falling back to all suites when the stamp is missing.

- [ ] **Step 1: Failing tests** in a temp git repo (space in path) with a `tests/` folder:
  - `test_fingerprint_ignores_docs`: editing `README.md` keeps the fingerprint; editing a `.py` changes it.
  - `test_suites_pick_the_mod_only_when_it_changed`.
  - `test_unchanged_tree_runs_nothing`: second invocation exits 0 within 1 s and runs no suite (stamp present).
  - `test_failing_suite_blocks_once`: a failing `tests/test_x.py` → exit 2, stderr contains `test_x`; same input with `stop_hook_active: true` → exit 0 and stdout JSON has `systemMessage`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement + settings entry. **Step 4:** Green, both suites. **Step 5: Commit** `"Stop hook: tests at turn end when code changed"`

### Task 6: `live-check` project skill

**Files:**
- Create: `.claude/skills/live-check/SKILL.md`, `.claude/skills/live-check/capture.ps1`, `.claude/skills/live-check/engine.ps1`

Sources: the scratchpad scripts `cap2.ps1`, `cap.ps1`, `wt-settings.json` in `C:\Users\HOMEOF~1\AppData\Local\Temp\claude\C--dev-claude-setup\16157e51-975e-4310-ac85-9a67c2fbe4fc\scratchpad\`, and the memories `session-cards-mod-live-check.md` and `demo-session-screenshots.md` in `C:\Users\Home Office\.claude\projects\C--dev-claude-setup\memory\`.

- `capture.ps1 -Out <png> [-Columns N] [-Prompt word] [-Worktree <path>]`: starts a demo `claude.exe` in a new Windows Terminal window with `NO_COLOR`, `CLAUDECODE` and session env vars stripped; with `-Worktree`, writes a temp `--settings` file pointing `statusLine.command` at the worktree's `statusbar.py` and `env.CLAUDE_CODE_PLUGIN_DIRS` at its mod; finds the window by EnumWindows, captures with PrintWindow, kills only that demo `claude.exe` (never WindowsTerminal.exe).
- `engine.ps1 [-Pattern <regex>] [-Types]`: resolves the running version (`claude --version`), prints the binary and `claude-code.d.ts` paths; with `-Pattern`, `rg -a -o` with 80 characters of context, at most 20 matches.
- `SKILL.md`: frontmatter `name: live-check`, a description that triggers on "live check", "screenshot the status bar/mod", "what does the engine do"; then when to use which script, the dev-mods hot-load route, and the engine surfaces a mod cannot change (from the memory).

- [ ] **Step 1:** `pwsh -NoProfile -File .claude/skills/live-check/engine.ps1 -Pattern disableClaudeAiConnectors` → at least one match line; parse both `.ps1` under PS 5.1 → 0 errors.
- [ ] **Step 2:** `capture.ps1 -Out <scratch>/check.png -Columns 104 -Worktree <this worktree>` → PNG exists; the main thread looks at it (the bar and hint row drawn, demo `claude.exe` gone, the main session alive).
- [ ] **Step 3: Commit** `"live-check skill: demo-window capture and engine lookup"`

### Finish (main thread)

- Final whole-branch review (Opus), PR, `gh pr merge --squash --delete-branch`, main's `install.ps1`, confirm `~/.claude/CLAUDE.md` still equals `global/CLAUDE.md`.
- Update the memories `session-cards-mod-live-check` and `demo-session-screenshots` to point at the skill; advisor off.
