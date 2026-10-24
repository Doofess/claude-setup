# Session-cards colour round Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Colour the turn-end line, give slash commands their own card, recolour Opus, stop the hint line from wrapping, and draw ✔ in the font's own style.

**Architecture:** Most of the work is in the `session-cards` mod (`mods/session-cards/hooks/register.tsx`), which already redraws prompts, command output, agent rows and the hint line. Opus's colour lives in two places, `statusbar.py` and the mod's `FAMILY_COLOURS`, and both change. The ✔ fix is a Windows Terminal font fallback in `terminal/profile.json`, which `install.ps1` writes.

**Tech Stack:** Claude Code mod API 2.1.310 (TSX, `claude plugin test`), Python 3 (`statusbar.py`, unittest), PowerShell (`install.ps1`).

**Spec:** the choices the user made in session 44706be6 on 2026-10-24, restated in Global Constraints below.

## Global Constraints

- The turn-end line keeps the engine's words and order: `✻ <Word> for <duration> · done <time> · <N shell(s)> still running`. Colours: `✻` `claude`; `<Word> for` dim; the duration bold `text` (white); `done <time>` `success` (green); `<N shells> still running` `warning` (yellow), drawn only while a shell runs.
- `next(e)` (the engine's own line) whenever `isExpanded` is true, `waitingFor` is present, the surface isn't `terminal`, or the mod has no record for the row (a `/resume`, or a row drawn before the mod loaded).
- Slash command card: border and header in `permission` (#B1B9F9). Header: `<icon>  You ran · HH:MM`, using the same icon and clock as `You prompted`. The body is the command as typed.
- Opus is Claude orange in both places: `38;2;215;119;87` in `statusbar.py`, the theme key `claude` in the mod. The other families and all efforts keep their colours.
- ✔ comes from Claude Code's figures (`tick: "✔"`). JetBrainsMono Nerd Font has U+2713 but not U+2714, U+2718 or U+2139, so Windows Terminal falls back to the colour emoji font. Segoe UI Symbol has all three. Windows Terminal 1.21+ accepts a comma-separated `font.face`, later faces as glyph fallbacks.
- Never run a worktree's `install.ps1`, because it repoints `CLAUDE_CODE_PLUGIN_DIRS`. After the merge, run main's `install.ps1`.
- The uncommitted `settings.json` change on main isn't part of this branch.

## Review Focus

- A shell started and finished inside one turn: that turn's line says nothing about shells, and a later turn's line doesn't either. (Task 1)
- A subagent's `turn.complete` (`e.agentId` set) must not store a record or bump the shell snapshot. (Task 1)
- Two turns with the same `durationMs`: each row takes its own record, oldest first, the way `claimed`/`taken` pair prompts. (Task 1)
- A slash command typed with arguments over several lines: the body is drawn whole and the header says `You ran`. (Task 2)
- The hint line at 80 columns with the longest hint (`… · /tasks to see subagents`): it never wraps, and pieces that don't fit are dropped. (Task 4)

---

### Task 0: Live probe (inline, no worker)

Two facts aren't readable from the minified binary, so a probe settles them before Task 1 is briefed.

- [ ] **Step 1:** Copy `.claude-plugin`, `hooks` and `types` of `mods/session-cards` into `~/.claude/dev-mods/<session id>/session-cards/`, then add a `ui.render` hook on `TurnDuration` that calls `$.ui.log(JSON.stringify({ requestId: e.requestId, props: e.props }))` and returns `next(e)`. Add a `turn.complete` hook that logs `durationMs`, `agentId` and `$.clock.now()`.
- [ ] **Step 2:** After the reload, run a turn with a background `sleep 120` shell, then a turn without one. Record: whether `requestId` is stable across redraws; whether `turn.complete`'s `durationMs` equals the row's `durationMs`; when `done <time>` shows (always, or only past a threshold); its exact format (`12:34 PM`); and the shell wording for 1 and 2 (`1 shell`, `2 shells`, and whether monitors count).
- [ ] **Step 3:** Delete the dev-mods copy, so a restart doesn't load the mod twice.

### Task 1: Coloured turn-end line

**Files:**
- Modify: `mods/session-cards/hooks/register.tsx`
- Modify: `mods/session-cards/types/index.d.ts`
- Create: `mods/session-cards/tests/turn.test.tsx`

**Interfaces:**
- Produces: `export function turnLine(r: TurnRecord, word: string): { duration: string; done: string; shells: string | null }`, which holds the words only. `export type TurnRecord = { durationMs: number; endedAt: number; shells: number }`. State key `turns: TurnRecord[]` in `PluginState['session-cards']`.
- Produces: `export function fmtTurn(ms: number): string`. It formats like the engine (`3s`, `1m 4s`, `16m 56s`, and hours as Task 0 found). Reuse `fmtElapsed` if Task 0 shows the same format.
- Shell count: a module `Set` of running background shell ids. Add an id on `tool.call` for `Bash`/`PowerShell` when the result says it went to the background: `run_in_background`, or the ctrl+b case already handled for rows in #21. Remove it on the `UserMessage` task-notification for that id, and on a `TaskStop`/`KillShell` call result. At `turn.complete` with no `agentId`, append `{ durationMs, endedAt: now, shells: set.size }` to `turns`.
- Match a row to its record by `durationMs`. A module `claimed` map, keyed by `requestId`, pins each row to the first unclaimed record with that duration. No match: `next(e)`.

- [ ] **Step 1: Write the failing tests** in `tests/turn.test.tsx`, mounting `TurnDuration` like `cards.test.tsx` mounts `UserMessage`:
  - `a finished turn is coloured`: the record `{durationMs: 1_016_000, endedAt: <12:34 PM>, shells: 0}` with word `Brewed` gives Text runs `✻` (color `claude`), `Brewed for` (dimColor), `16m 56s` (bold, color `text`), ` · done 12:34 PM` (color `success`), and no run matching `/still running/`.
  - `one shell running`: the same with `shells: 1` adds a run ` · 1 shell still running` (color `warning`). `shells: 2` reads `2 shells`.
  - `no record falls back`: no `turns` entry, so the tree is the engine's (`<Text>engine</Text>`).
  - `expanded and waiting fall back`: `isExpanded: true`, and separately `waitingFor` set, both give the engine's tree.
  - `a subagent's end stores nothing`: `turn.complete` with `agentId: 'a1'` leaves `turns` empty.
  - `equal durations pair in order`: two records with `durationMs: 3000` and rows `r1` and `r2` show the first and second `endedAt`.
- [ ] **Step 2:** Run `claude plugin test mods/session-cards`. Expected: the new tests FAIL and the old ones pass.
- [ ] **Step 3:** Implement the hooks and helpers above. The line is a `Box` `flexDirection="row"` with a `minWidth={2}` cell for `✻`, as the engine lays it out, and Text runs after it.
- [ ] **Step 4:** Run `claude plugin test mods/session-cards` and `claude plugin validate mods/session-cards`. Expected: all pass, and validate reports no refusals.
- [ ] **Step 5:** Commit `session-cards: the turn-end line in colour, shells counted by the mod`.

### Task 2: Slash command card

**Files:**
- Modify: `mods/session-cards/hooks/register.tsx` (the `UserMessage` hook)
- Modify: `mods/session-cards/tests/cards.test.tsx`

**Interfaces:**
- Produces: `export function isSlashCommand(text: string): boolean`. It is true when `promptText(text).trimStart()` matches `/^\/[A-Za-z0-9:_-]+(\s|$)/`. A path such as `/c/dev …`, which has a second slash before the first space, is false.

- [ ] **Step 1: Write the failing tests:** `a slash command is a violet card headed You ran`. Submitting `/code-review high` gives a Box with `borderColor` `permission`, a header equal to `${ICON}  You ran · ${clock(now)}` with color `permission` and bold, and the body `/code-review high`. Also `isSlashCommand`: `/model` true, `/code-review high` true, `/c/dev/x is a path` false, `hello /model` false.
- [ ] **Step 2:** Run `claude plugin test mods/session-cards`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement `isSlashCommand` and branch colour and verb in the `UserMessage` hook.
- [ ] **Step 4:** Run `claude plugin test mods/session-cards`. Expected: all pass.
- [ ] **Step 5:** Commit `session-cards: slash commands are a violet You ran card`.

### Task 3: Opus in Claude orange

**Files:**
- Modify: `statusbar.py:53-56` (`MODEL_COLOURS`) and `model_colour`'s return type (`int | str | None`)
- Modify: `tests/test_statusbar.py:212,221,226`
- Modify: `mods/session-cards/hooks/register.tsx` (`FAMILY_COLOURS.opus = 'claude'`)
- Modify: `mods/session-cards/tests/agents.test.tsx` and `tests/overflow.test.tsx`, wherever they pin `magenta` for Opus
- Modify: `README.md` and `statusbar.py`'s header comment, wherever they name Opus's colour

- [ ] **Step 1:** Change the tests first: Opus is `38;2;215;119;87` in `test_statusbar.py`, and `claude` in the mod tests. When an Opus piece is in the overflow file, its span colour is `#D77757`. Check how `statusbar.py` turns a `38;2` code into a span colour and pin that.
- [ ] **Step 2:** Run `python -m unittest tests.test_statusbar -q` and `claude plugin test mods/session-cards`. Expected: the Opus tests FAIL.
- [ ] **Step 3:** Change the two colour tables and the docs lines.
- [ ] **Step 4:** Run both test commands again. Expected: all pass. The "no two models the same hue" test still passes.
- [ ] **Step 5:** Commit `statusbar, session-cards: Opus in Claude orange`.

### Task 4: The hint line never wraps (systematic-debugging)

**Files:**
- Modify: `mods/session-cards/hooks/register.tsx` (the `PromptHint` hook, `fitPieces`)
- Modify: `mods/session-cards/tests/overflow.test.tsx`

- [ ] **Step 1: Find the cause.** With the dev-mods copy, log `e.props.hint`, `hint.length`, `e.viewport.columns` and the fitted pieces' total width while a subagent runs (the hint then ends `· /tasks to see subagents`). Compare the logged hint with what is drawn. Candidates: the drawn hint is wider than `hint.length` (multi-cell glyphs such as `⏵⏵`, or parts the screen-reader text joins with one space), or the footer row is narrower than `viewport.columns - 4`.
- [ ] **Step 2: Write the failing test** with the logged hint and width: `the longest hint at <columns> fits without wrapping`, asserting that the fitted line's width ≤ the room the cause shows.
- [ ] **Step 3:** Fix it at the cause. Also draw the row with `wrap="truncate"` on the hint Text and `flexShrink={0}` on the pieces, so a measuring error cuts the line instead of wrapping it.
- [ ] **Step 4:** Run `claude plugin test mods/session-cards`. Expected: all pass. Then check live at the width from the screenshot.
- [ ] **Step 5:** Commit `session-cards: the hint line fits the footer and never wraps`.

### Task 5: ✔ in the font's own style

**Files:**
- Modify: `terminal/profile.json` (`"face": "JetBrainsMono Nerd Font, Segoe UI Symbol"`)
- Modify: `install.ps1`. Every use of `$nerdFontFace` that looks up or installs the font, or compares it with Windows Terminal's face, must use the first face for the font lookup and the whole string for the comparison and the write.
- Modify: `tests/test_install.py`, `terminal/README.md`

- [ ] **Step 1: Write the failing test** in `test_install.py`: the face string with a fallback still passes the installed-font check, and is written to `profiles.defaults.font.face` verbatim.
- [ ] **Step 2:** Run `python -m unittest tests.test_install -q`. Expected: FAIL.
- [ ] **Step 3:** Implement it, and add one line to `terminal/README.md` on why Segoe UI Symbol is there.
- [ ] **Step 4:** Run `python -m unittest tests.test_install -q`. Expected: PASS.
- [ ] **Step 5:** Commit `terminal: Segoe UI Symbol as glyph fallback, so ✔ is drawn in the text colour`.

### Task 7: GitLab repos get their own icon and colour

Claude Code's status line JSON carries `workspace.repo` only for GitHub ("GitHub owner/repo when available"), so the status bar reads the host from the repo's `origin` remote itself.

**Files:**
- Modify: `statusbar.py` (`ICONS`, the repo piece around line 298, a new `remote_host`)
- Modify: `tests/test_statusbar.py`, `README.md`

**Interfaces:**
- Produces: `def origin_remote(cwd: str) -> tuple[str, str] | None`, returning `(host_kind, "owner/name")`, where `host_kind` is `"github"`, `"gitlab"` or `"other"`. It reads `.git/config` without a subprocess, walking up from `cwd`. A `.git` file (a worktree) is followed to its `gitdir` and then that gitdir's `commondir`. It takes `[remote "origin"] url`, in both `https://host/owner/name(.git)` and `git@host:owner/name(.git)` forms, with GitLab subgroups kept (`group/sub/name`). `"gitlab"` when the host is `gitlab.com` or contains `gitlab`, `"github"` for `github.com`, otherwise `"other"`.
- Repo piece: `workspace.repo` when present, with the host kind from `origin_remote`. Without it, the name comes from `origin_remote`. GitHub keeps `` and `VIOLET`. GitLab gets `` and `38;2;252;109;38` (#FC6D26). Other hosts get the git glyph `` and `VIOLET`. Under `--labels`, the label word stays `repo`.

- [ ] **Step 1: Write the failing tests** with temp dirs holding a `.git/config`: `https://gitlab.com/grp/sub/proj.git` gives `("gitlab", "grp/sub/proj")`; `git@github.com:Doofess/claude-setup.git` gives `("github", "Doofess/claude-setup")`; `https://gitlab.example.org/a/b` gives gitlab; `https://bitbucket.org/a/b` gives other; a worktree `.git` file resolves through `commondir`; no repo gives `None`. A rendered line for a GitLab repo with no `workspace.repo` contains `sgr("38;2;252;109;38", " ")` and the name in that colour.
- [ ] **Step 2:** Run `python -m unittest tests.test_statusbar -q`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement it, and add a README line.
- [ ] **Step 4:** Run `python -m unittest tests.test_statusbar -q`. Expected: all pass.
- [ ] **Step 5:** Commit `statusbar: GitLab repos get GitLab's icon and orange, read from the origin remote`.

### Task 6: Merge and install (inline)

- [ ] Run all suites: `python -m unittest discover tests -q`, `claude plugin test mods/session-cards`, `claude plugin validate mods/session-cards`, `tsc -p mods/session-cards`.
- [ ] Open the PR, merge it, run main's `install.ps1`, and confirm in a restarted session: the turn-end line is coloured, a slash command card is violet, Opus is orange, and the hint line doesn't wrap. ✔ in Windows Terminal needs a terminal restart.
- [ ] Remove `advisorModel` from `~/.claude/settings.json`.
