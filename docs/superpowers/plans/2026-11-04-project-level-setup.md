# Project-level Claude Code setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** plugins, MCP servers, LSPs, hooks and skills are switched on per project, not for the user. The user level keeps only the workflow core. Tools that nothing on this PC has ever used are uninstalled.

**Architecture:**
- The user level (claude-setup's `settings.json` template, merged into `~/.claude/settings.json`) keeps:
  - plugins: only `superpowers@claude-plugins-official` and `remember@claude-plugins-official`;
  - skills: `advisor-switch`, `codex` and `setup-check`;
  - agents: `worker` and `Explore`;
  - the status line, permissions, mods and the global `CLAUDE.md`.
- Every other plugin is `false` at user level and is switched on in a project's `.claude/settings.json`.
- claude-setup becomes a plugin marketplace (`.claude-plugin/marketplace.json` at the repo root). It ships the photo skill as the plugin `photo-edit`, which only the desktop PC's photo project switches on.
- install.ps1 uninstalls the retired plugins and retired user skills, and drops step 4i (the global `typescript-language-server`).

**Tech Stack:** PowerShell 7 and Windows PowerShell 5.1 (`install.ps1`), Python `unittest` (tests), the Claude Code plugin CLI.

**Spec:** the user's answers of 2026-11-04 in the omnichannel-platform session:
- "Workflow core only" at user level, with claude-setup as the marketplace;
- only omnichannel-platform is set up now;
- "remove it entirely from this pc" for the photo skill (its project is on the desktop PC only);
- "if a tool isn't used anywhere, remove it entirely";
- in omnichannel-platform, keep frontend-design, context7, Playwright and security-guidance, "make sure that the options i picked are actually used", and remove dbhub, chrome-devtools, mattpocock-skills and hookify.

## Global Constraints

- **Usage evidence** (tool_use and Skill calls in every `~/.claude/projects/*` transcript, 2026-11-04):
  - **never used anywhere, so uninstalled** (user scope):
    - `chrome-devtools-mcp`, `hookify`, `mcp-server-dev`, `claude-code-setup`, `claude-md-management`, `claude-security`, `cloudflare`, `code-review`, `code-simplifier`, `feature-dev`, `github`, `ralph-loop`, `shopify-ai-toolkit`, `skill-creator`, `telegram`, `vercel`, `pyright-lsp`, `rust-analyzer-lsp` and `typescript-lsp`, all `@claude-plugins-official`;
    - `expo@claude-plugins-official` (project scope, recorded for the deleted worktree `C:\dev\omni-wt-ccsetup`);
    - the duplicate copies `superpowers`, `frontend-design`, `context7` and `playwright`, all `@anthropic-plugin-directory`.
  - **used somewhere, so kept installed but `false` at user level:**
    - `playwright`, `context7`, `frontend-design`, `mattpocock-skills`, `modern-web-guidance`, `supabase`, `adobe-for-creativity`, `kotlin-lsp` and `security-guidance`, all `@claude-plugins-official`;
    - `good-css@good-css`.
  - **user skills removed:** `underwater-photoshop` (it moves to the `photo-edit` plugin) and `find-skills` (never used). `synced` belongs to claude.ai: leave it.
- **The template's `enabledPlugins` lists every kept plugin explicitly**: `true` for the two core plugins, and `false` for each of the 10 above and for `claude-md-management@anthropic-plugin-directory`. "Enabling a plugin by name also flips on a same-named copy" (install.ps1, step 4), so the `false` entries pin those copies off.
- **Retired plugin ids in one list** `$retiredPlugins`. install.ps1 runs `claude plugin uninstall <id> --scope user` for each id still in `claude plugin list --json`, and removes the id from `~/.claude/settings.json` `enabledPlugins`, because the merge keeps keys the template no longer has.
- **Retired skills:** `$retiredSkills = @('underwater-photoshop', 'find-skills')`, deleted from `~/.claude/skills`. install.ps1 stops copying `skills/underwater-photoshop`, which moves to `plugins/photo-edit/skills/underwater-photoshop/`.
- **Marketplace name:** `claude-setup`. The plugin is `photo-edit` with source `./plugins/photo-edit`. A project switches it on with:
  - `"extraKnownMarketplaces": {"claude-setup": {"source": {"source": "github", "repo": "Doofess/claude-setup"}}}` (the repo is public);
  - `"enabledPlugins": {"photo-edit@claude-setup": true}`.
- **Step 4i comes out:** `Install-TypescriptLsp`, `-SkipTypescriptLsp`, header item 17, `$typescriptLspVersion`/`$typescriptVersion`, `tests/test_typescript_lsp.py` and the README section. A retire step runs `npm uninstall -g typescript-language-server typescript` only when `npm ls -g` lists them at the exact pinned 6.0.3 that step 4i installed.
- **Global `CLAUDE.md`** (`global/CLAUDE.md`):
  - drop "## Photo editing (paid work)"; its text moves into the photo skill's `SKILL.md` if not already there;
  - line 35 becomes: "Styles in any form: where the project switches on `frontend-design`, it decides the look; where it switches on `good-css`, read its skill before writing the declarations.";
  - under Defaults add: "Plugins, LSPs, MCP servers and hooks are per project: switch them on in the repo's `.claude/settings.json` (MCP in `.mcp.json`). The user level holds only superpowers, remember, the advisor-switch/codex/setup-check skills and the worker/Explore agents.".
- **Commits:**
  - trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` from a worker, `Claude Opus 5.5` from the main session;
  - claude-setup work happens in `C:/dev/claude-setup-wt-project-level` on `feat/project-level-setup`.
- **Tests:** `python -m unittest discover -s tests -q` in claude-setup. The known failure `MergeParityTest.test_merge_is_the_same_on_both_engines` (a `\u2714` encoding difference, also failing on main) is the only failure allowed.

## Review Focus

1. **Re-running install.ps1 on a PC where everything is already retired.** It makes no uninstall calls, prints nothing alarming and does not reinstall or re-copy anything. Test: Task 2 runs the retire functions twice against fakes.
2. **A retired plugin id still in `~/.claude/settings.json`** (the merge keeps keys the template dropped). After the merge it is gone from `enabledPlugins`. Test: Task 2.
3. **The desktop photo project after the update.** The skill is gone from `~/.claude/skills`, and the project gets it back from `photo-edit@claude-setup`. README steps and a `setup-check` hint cover it; `claude plugin validate .` passes on the marketplace. Test: Task 1.
4. **A session outside omnichannel-platform** (for example `C:\dev\marshell`) loads none of the project plugins. A session inside it has the LSP for `.ts`, `.kt` and `.sql`, plus frontend-design, context7 and security-guidance. Test: Task 4, headless sessions.
5. **The global `typescript-language-server` was installed by hand at another version.** The retire step leaves it alone. Test: Task 2.

---

### Task 1: claude-setup marketplace with the photo-edit plugin

**Files:**
- Create: `.claude-plugin/marketplace.json`, `plugins/photo-edit/.claude-plugin/plugin.json`
- Move: `skills/underwater-photoshop/` to `plugins/photo-edit/skills/underwater-photoshop/` (`git mv`)
- Modify: `install.ps1` (the skill copy loop near line 1113 skips nothing new; the moved folder is simply no longer under `skills/`), `README.md` ("Project-level plugins" section with the desktop photo project's `.claude/settings.json` block), `skills/setup-check/SKILL.md` (a check: when the cwd is a photo project, `photo-edit@claude-setup` is on), this plan
- Test: `tests/test_marketplace.py`

- [ ] **Step 1: Write the failing tests** in `tests/test_marketplace.py`:
  - `marketplace.json` parses, `name == "claude-setup"`, and has one plugin `photo-edit` whose `source` is `./plugins/photo-edit`, a folder that exists;
  - `plugins/photo-edit/skills/underwater-photoshop/SKILL.md` exists, and `skills/underwater-photoshop` does not;
  - `claude plugin validate .` exits 0 (skip the test when `claude` is not on PATH).
- [ ] **Step 2:** Run `python -m unittest tests.test_marketplace -v`. Expected: FAIL.
- [ ] **Step 3:** Create the files and move the skill. If the global CLAUDE.md photo text adds anything, make sure `SKILL.md` carries it: local Photoshop via COM, never Adobe cloud tools for the edit, nothing uploaded.
- [ ] **Step 4:** Run the new tests and the full suite. Expected: the new tests pass; the suite has only the known failure.
- [ ] **Step 5:** Commit `feat: claude-setup is a plugin marketplace; the photo skill ships as photo-edit`.

### Task 2: User level reduced to the workflow core; retired plugins, skills and step 4i

**Files:**
- Modify: `settings.json` (`enabledPlugins` per Global Constraints; drop the anthropic-plugin-directory `true` entries and the three LSP `true` entries); `install.ps1` (`$retiredPlugins` and `$retiredSkills`, `Remove-RetiredPlugins`, `Remove-RetiredSkills`, `Remove-RetiredSettingsPlugins`, removal of step 4i and the `typescript-language-server` retire step); `global/CLAUDE.md` (per Global Constraints); `README.md` (the step 4i section removed, a "User level vs project level" section listing what stays and why); `skills/setup-check/SKILL.md` (the expected user-level set)
- Delete: `tests/test_typescript_lsp.py`
- Test: `tests/test_retire.py`; update `tests/test_install.py` where it asserts the old `enabledPlugins` or step 4i

**Interfaces:**
- Produces:
  - `Remove-RetiredPlugins([string[]]$ids, [scriptblock]$claude)`: returns the ids it uninstalled. `$claude` is injectable for tests and defaults to the real CLI.
  - `Remove-RetiredSkills([string[]]$names, [string]$skillsDir)`: returns the names it removed.
  - `Remove-RetiredSettingsPlugins($settings, [string[]]$ids)`: returns the removed ids.
  - `Remove-RetiredTypescriptLsp([scriptblock]$npm)`: returns `removed` or `kept <reason>`.

- [ ] **Step 1: Write the failing tests** in `tests/test_retire.py`, on both PowerShell engines as the other tests do, with fakes for `claude` and `npm`:
  - a fake `plugin list --json` holding two retired ids and one kept id: uninstall is called for exactly the two;
  - a second run with none installed makes no calls (Review Focus 1);
  - settings whose `enabledPlugins` hold `pyright-lsp@claude-plugins-official: true` lose that key (Review Focus 2);
  - a skills dir with `find-skills/` and `codex/`: only `find-skills` is removed;
  - npm listing `typescript-language-server@6.0.3` and `typescript@6.0.3`: both are uninstalled; at `5.0.0`: kept (Review Focus 5); npm missing: kept;
  - the template `settings.json` `enabledPlugins` has exactly two `true` values, `superpowers@claude-plugins-official` and `remember@claude-plugins-official`.
- [ ] **Step 2:** Run `python -m unittest tests.test_retire -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. The retire calls run in step 4, after the merge and before installs. `-SkipPlugins` skips them too. Remove step 4i and its test file.
- [ ] **Step 4:** Run the full suite, then `ruff check .`. Expected: only the known failure; ruff clean.
- [ ] **Step 5:** Commit `feat: user level holds only the workflow core; retire unused plugins, skills and the global TS server`. Push, open a PR and arm `gh pr merge --auto --merge`.

### Task 3: omnichannel-platform project setup (main session)

**Files** (omnichannel-platform, branch `chore/ts-native-lsp`, PR #62):
- `.claude/settings.json`:
  - `enabledPlugins` is exactly `kotlin-lsp@claude-plugins-official`, `ts-native-lsp@omni-local`, `pg-lsp@omni-local`, `frontend-design@claude-plugins-official`, `context7@claude-plugins-official` and `security-guidance@claude-plugins-official`, all `true`; the redundant `false` entries are dropped;
  - the `enabledMcpjsonServers` key is removed.
- Delete `.mcp.json` and `.claude/dbhub.toml`.
- Create `.claude/rules/tools.md` (always loaded; no `paths`), which says when each kept tool is used:
  - frontend-design before any styling or layout change in `apps/desktop` or `apps/android`;
  - context7 before relying on a library API that is newer than mid-2026 or whose signature is unsure (Compose, Hono, Drizzle, electron-vite, Robolectric, Zod, the Supabase CLI);
  - security-guidance as a passive edit hook whose warnings are read, not dismissed;
  - the LSP for `.kt`, `.ts` and `.sql` navigation and type checks;
  - workers are told the same.
- `.claude/rules/environment.md` (the code-intelligence line is unchanged);
- `docs/WORKLOG.md` entry; `FILE_MANIFEST.json`.

Playwright is not switched on here: its only real use in this project was a one-off check in the retired Expo app (D296). The API host has no UI, and the desktop app's end-to-end tests run through `@playwright/test` (`apps/desktop/e2e`) without the MCP. That follows the user's "make sure that the options i picked are actually used". It stays installed, because greenback uses it.

- [ ] **Step 1:** Make the edits and commit `chore: project-level Claude Code setup (plugins, rules), dbhub removed`.

### Task 4: Apply on this PC and verify (main session, after the plan 37 workflow has finished)

- [ ] **Step 1:** Once the Task 2 PR has merged, `git -C C:/dev/claude-setup pull`, then run `install.ps1` with the PowerShell tool. Expected: no failed steps, apart from known ones that are reported.
- [ ] **Step 2: Verify:**
  - `claude plugin list --json`: user-enabled is exactly `{superpowers, remember}` (official), and no retired id is installed;
  - `ls ~/.claude/skills`: `advisor-switch`, `codex`, `setup-check` and `synced`;
  - `npm ls -g`: no `typescript-language-server`.
- [ ] **Step 3: Isolation (Review Focus 4):**
  - a headless `claude -p --model haiku --debug` session in omnichannel-platform: the LSP answers for `.ts`, `.kt` and `.sql`, and the frontend-design and context7 skills or tools are listed;
  - the same in `C:/dev/marshell`: none of them are listed;
  - record each debug log's `Plugin loading errors` lines. The claude.ai-managed `claude-md-management` may remain, and is reported as such.
- [ ] **Step 4:** Remove the worktrees `claude-setup-wt-tslsp` and `claude-setup-wt-project-level` once merged, and tell the user the desktop steps: `git pull` and `install.ps1` there, then the photo project's `.claude/settings.json` block from the README.
