# Project-level tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Built-in tools and skills follow the same rule as plugins and MCP: off at the user level, switched on in the project (or session) that uses them, so no session pays per-turn tokens for tools it never calls.

**Architecture:** The repo's `settings.json` template carries the user-level switches (the installer merges it into `~/.claude/settings.json`). Claude in Chrome's default lives in `~/.claude.json`, so a new `chrome_off.py` turns it off once (state file, same lock as `mcp_off.py`) and leaves later `/chrome` choices alone. Docs record the rule and the per-project lines.

**Tech Stack:** JSON settings, PowerShell installer (must parse under 5.1), Python 3 stdlib, `unittest`.

**Spec:** the decisions below (user answers of 2026-11-05 and engine checks against Claude Code 2.1.318).

## Decisions (the spec)

- Artifact: user `"enableArtifact": false`. Off everywhere; the engine lets project/local settings only turn it off, so it can't come back per project. Switch the user key on for a stretch of work that needs it.
- Claude in Chrome: `claudeInChromeDefaultEnabled: false` in `~/.claude.json`, set once by the installer; later `/chrome` toggles survive re-runs. Use `claude --chrome` or `/chrome` per session. A project can't turn it on (engine ignores `CLAUDE_CODE_ENABLE_CFC` in project settings).
- Workflows: user `"enableWorkflows": false`. On per session: `claude --settings '{"enableWorkflows":true}'` (verified), or `/config` → Dynamic workflows until the next install. No project lines.
- SendFeedback: user `"feedbackDrafts": "off"` (the engine's own switch; a deny can't be lifted).
- Superpowers: the seven `skillOverrides` entries are no-ops (plugin skills ignore `skillOverrides`, bare or `plugin:skill`; `Skill(...)` deny hides nothing). Remove them, fix the README.
- Bundled skills: `user-invocable-only` for loop, schedule, init, security-review, simplify, keybindings-help, update-config, fewer-permission-prompts, plugin-authoring; `off` for dataviz, claude-api, artifact-design, artifact-diagramming, artifact-capabilities; `name-only` for deep-research. Keep code-review, run.
- humanizer (synced claude.ai plugin, never called or typed): `"humanizer@synced": false`.
- This repo turns `plugin-authoring` back `on` (it builds the session-cards mod).

## Global Constraints

- `install.ps1` must parse under Windows PowerShell 5.1.
- Installer writes to `~/.claude.json` only under its `<file>.lock` directory lock, through a temp file and `os.replace`.
- Merge rule: top-level template keys other than `enabledPlugins`/`env`/`permissions`/`hooks` replace the machine's value.

## Review Focus

- `~/.claude.json` absent: `chrome_off.py` exits 0 and records nothing, so it applies on a later run.
- User turned Chrome back on with `/chrome` after the first run: a re-run leaves `claudeInChromeDefaultEnabled: true`.
- Lock held by a running session: exit 1, file untouched, installer reports `chrome_off.py failed`.
- `chrome_off.py` and `mcp_off.py` share `claude-setup-state.json`: each keeps the other's keys and `Set-StateRepo` runs after both.
- A plugin-qualified or superpowers key creeping back into the template's `skillOverrides`: a test rejects it.

---

### Task 1: Template and this repo's project settings (inline)

**Files:**
- Modify: `settings.json` (enabledPlugins, new keys, skillOverrides)
- Modify: `.claude/settings.json` (skillOverrides: `"plugin-authoring": "on"`)
- Test: `tests/test_template.py` (new class `TemplatePolicyTest`)

- [ ] **Step 1: Write the failing tests** in `TemplatePolicyTest`, reading `settings.json`:
  - `test_built_in_tools_are_off_at_user_level`: `enableArtifact is False`, `enableWorkflows is False`, `feedbackDrafts == "off"`, `enabledPlugins["humanizer@synced"] is False`.
  - `test_skill_overrides_name_bare_skills_only`: no key contains `:`; none of brainstorming, diagnosing-superpowers, dispatching-parallel-agents, receiving-code-review, requesting-code-review, verification-before-completion, writing-skills is a key; every value is in `{"on", "name-only", "user-invocable-only", "off"}`.
- [ ] **Step 2:** `python -m unittest tests.test_template -q` → FAIL.
- [ ] **Step 3:** Edit both settings files per the Decisions.
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5:** Commit `feat: built-in tools and skills off at user level`.

### Task 2: Chrome default off once (worker)

**Files:**
- Create: `chrome_off.py`, `tests/test_chrome_off.py`
- Modify: `install.ps1` (header step 5, step 4c), `tests/test_install.py` (`test_installer_records_repo_inside_the_write_block`)

**Interfaces:**
- Consumes: `mcp_off._lock(path) -> bool`, `mcp_off._load(path, default)`, `mcp_off._save(path, data)`, `mcp_off.LOCK_TRIES/LOCK_WAIT`.
- Produces: `chrome_off.turn_off(cfg: dict, state: dict) -> bool` (sets `cfg["claudeInChromeDefaultEnabled"] = False` and `state["claudeInChromeDefaultEnabled"] = "off-once"` unless the state key is already there; returns whether it changed anything); `chrome_off.main(argv: [cfg_path, state_path]) -> int` (0 ok or no file, 1 when the lock stays held).

- [ ] **Step 1: Write the failing tests** in `tests/test_chrome_off.py` (mirror `tests/test_mcp_off.py`): first run sets `false` from `true` and from absent; second run after the user set `true` keeps `true`; other state keys (`claude.ai Adobe`, `repo`, `flags`) survive; missing `~/.claude.json` → 0 and state not written; held lock → 1 and file unchanged.
- [ ] **Step 2:** `python -m unittest tests.test_chrome_off -q` → FAIL (no module).
- [ ] **Step 3:** Implement `chrome_off.py` (docstring explains why: a project can't turn Chrome on, `/chrome` can; once-only so the user's toggle wins afterwards).
- [ ] **Step 4:** `install.ps1` step 4c: after the `mcp_off.py` call, `Write-Step 'Claude in Chrome off by default, once (/chrome or claude --chrome turns it on)'`, run `python -S chrome_off.py $claudeJson <state>`, add `'chrome_off.py failed'` to `$failures` on non-zero exit; both before `Set-StateRepo`. Update header item 5. Extend the order test: `chrome_off.py` index < `Set-StateRepo` index.
- [ ] **Step 5:** `python -m unittest discover -s tests -q` → only the pre-existing `MergeParityTest` failure; the 5.1 parse hook passes.
- [ ] **Step 6:** Commit `feat: installer turns Claude in Chrome off by default once`.

### Task 3: Rule and docs (inline)

**Files:** `global/CLAUDE.md`, `README.md` (User level vs project level, What goes where, Plugin and MCP policy)

- [ ] **Step 1:** `global/CLAUDE.md` Defaults: one bullet for the rule (tools, skills, plugins, MCP off at user level, on per project or session; Artifact, Chrome, workflows switches).
- [ ] **Step 2:** README: replace the superpowers bullet with the verified fact; add built-in tools and skills to the policy and the per-project table of lines; add `chrome_off.py` to What goes where.
- [ ] **Step 3:** Full test run, commit `docs: project-level rule for built-in tools and skills`.

### Task 4: PR, merge, install, live verification

- [ ] PR, `gh pr merge N --squash --delete-branch` (leave the worktree first), `pwsh -NoProfile -File install.ps1` from main.
- [ ] Fresh headless sessions: scratch folder (Workflow, humanizer, dataviz, claude-api gone; nine skills off the model list) and a project with `skillOverrides.dataviz: on` + `enableWorkflows: true` (both back).
- [ ] Interactive session (`capture.ps1`): Artifact, SendFeedback, Chrome tools and the artifact skills absent; `--chrome` brings Chrome back.
- [ ] `/setup-check` step 4 shell matrix.
- [ ] Report the per-project lines and send the omnichannel-platform session the final settings.
