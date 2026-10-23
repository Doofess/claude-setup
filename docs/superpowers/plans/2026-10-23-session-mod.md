# Session mod Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code mod, `session-cards`, that draws your prompts as an accent-orange card headed `You prompted · 14:32`, slash-command output as a violet card headed by the command, and every tool call as a white icon-and-words row in the engine's own position and weight.

**Architecture:** One hooks module with four `ui.render` hooks (`UserMessage`, `CommandOutput`, `ToolUse`, `PromptHint`) and one `prompt.submit` hook that notes the time each prompt was handed over. The `PromptHint` hook draws the status bar's overflow (what `statusbar.py` dropped from its line, read from `~/.claude/statusbar-overflow/<session_id>.json`) after the engine's own hint text. Colours are theme tokens only (`claude`, `permission`, `text`, `error`), so the cards follow Claude Code's own theme. The mod lives in this repo under `mods/session-cards` and loads through `CLAUDE_CODE_PLUGIN_DIRS` set by `settings.json`, as the installer expands `<repo>`.

**Tech Stack:** Claude Code plugin API (`claude-code` types), TSX, `claude plugin validate` and `claude plugin test`; PowerShell for the installer.

**Spec:** The design agreed in chat on 2026-10-23, recorded in the Spec section below. The old mod (tag `visual-v1`, `mods/readable-session`) may be read for its plain-words tool descriptions only; its drawing, colours and band are not a reference.

## Spec

**Prompt card** (`UserMessage` rows whose `origin.kind` is `composer`, terminal surface only):

```
╭──────────────────────────────────╮
│  You prompted · 14:32           │
│ the text as typed                 │
╰──────────────────────────────────╯
```

Round border and header in the theme's `claude` colour (Claude Code's own orange), header bold, icon `\uf007` (user) before `You prompted`. The time is `HH:MM`, 24-hour, local time, the moment `prompt.submit` saw the prompt; ` · HH:MM` is left out when the mod has no time for that text (a row from before the mod loaded, a resumed session). The text shown is `e.props.text` with Claude Code's `<pasted_content …>` and `</pasted_content …>` wrapper lines removed. Other `UserMessage` rows (task notifications, peers, channels) and other surfaces stay the engine's.

**Command card** (`CommandOutput`, terminal surface): the same card in the theme's `permission` colour (the violet Claude Code uses for inline code and permission prompts), headed by icon `\uf120` + `/command args`, the engine's own output drawn inside (`next(e)`). An errored command draws the border and header in `error`. A row the engine drew empty stays empty.

**Tool rows** (`ToolUse`, terminal surface): the engine's row is replaced by one line, `<icon> <Verb> <detail>`, everything in the theme's `text` colour (white on the dark theme), the verb bold like the engine's bold tool name, the icon where the engine's `⏺` sits, no parentheses. The verb is present tense while `isRunning` and past tense once done; a failed call (`isErrored`) adds ` ✗` in `error`; an interrupted one adds ` (stopped)` in `text`. The detail is cut to the row width with `…`. Rows in an expanded group or with `isExpanded` pass to the engine (`next(e)`) so ctrl+o shows everything. Agent and Task rows pass to the engine (their nested progress is the engine's).

| Tool | Icon | Running → done | Detail |
|---|---|---|---|
| Bash | `\uf120` | Running → Ran | `description` when given, else the command's first line |
| PowerShell | `\uf120` | Running → Ran | same |
| Edit, MultiEdit | `\uf040` | Editing → Edited | the path relative to `cwd` |
| Write | `\uf15c` | Writing → Wrote | relative path |
| NotebookEdit | `\uf15c` | Editing → Edited | relative path |
| Read | `\uf0f6` | Reading → Read | relative path |
| Glob, Grep | `\uf002` | Searching → Searched | pattern, then ` in <path>` when given |
| Skill | `\uf0e7` | Using skill → Used skill | skill name |
| AskUserQuestion | `\uf059` | Asking you → Asked you | the first question's text |
| WebFetch, WebSearch | `\uf0ac` | Fetching → Fetched / Searching → Searched | URL or query |
| mcp__* | `\uf1e6` | Calling → Called | `<server> <tool>` from the name |
| anything else | `\uf111` | Using → Used | tool name, then the first string input under 60 characters |

Paths: forward slashes, relative to `cwd` when under it, else as given.

**Agent rows** (`ToolUse` rows whose tool is `Agent`, terminal surface; decided 2026-10-23 from a screenshot of the engine's row `> ( ) worker  Searching reference.md for cwd   1m 0s · ↓ 72.0k tokens`): one line in the same style as the tool rows, rebuilt by the mod because the engine hands a mod none of the live part. `<icon> <Verb> <type> · <Model> · <effort>  <action>   <elapsed> · <tokens>`: icon `` and the verb (`Running` → `Ran`, `✗` on error, `(stopped)` when interrupted) in `text` with the verb bold; the agent type (`worker`, `Explore`) in `text`; the model's short name in the model's colour and the effort level in its colour, the same colours as the status bar (`MODEL_COLOURS` and `EFFORT_COLOURS` in `statusbar.py`, as colour names: Opus `magenta`, Sonnet `blue`, Haiku `cyan`, Fable `yellowBright`, Mythos `greenBright`; low `green`, medium `yellow`, high `red`, xhigh `magentaBright`, max `whiteBright`); the action is the subagent's latest tool call in present tense as `describeTool` words it (`Searching reference.md for cwd` style), or the Agent call's `description` before its first call, or `done` once finished; elapsed `1m 0s` from the spawn to now (or to the finish); tokens the sum of the subagent's steps' input and output tokens as `72k`. The ` · <effort>` part is left out until a step has reported one, and the model part until the spawn resolved. The row redraws on every change and once a second while the agent runs.

**Install:** `settings.json` `env.CLAUDE_CODE_PLUGIN_DIRS` is `<repo>/mods/session-cards`; the installer's existing `<repo>` expansion handles the path. The retired-setup step keeps removing only `readable-session` entries.

## Global Constraints

- Mod folder `mods/session-cards` with `.claude-plugin/plugin.json` (`name` `session-cards`, `version` `0.1.0`), `hooks/hooks.json` (`{ "modules": ["./register.tsx"] }`), `hooks/register.tsx`, `types/index.d.ts` declaring `$.state` for the mod, `tests/*.test.tsx`.
- Before writing any mod code, load the `plugin-authoring` skill in the implementing session and read its reference for `ui.render`, `prompt.submit`, `$.state` and `claude plugin test`.
- Colours are theme tokens only: `claude`, `permission`, `text`, `error`. No hex, no ANSI. The one exception is the overflow (Task 4), whose spans carry the status bar's own colours as data (`green`, `redBright`, `#4cc86e`): the mod passes each span's `colour` through to `Text` unchanged, so the two lines match.
- Every hook returns `next(e)` for `e.surface !== 'terminal'`.
- `claude plugin validate mods/session-cards` passes and `claude plugin test mods/session-cards` passes before each commit.
- Commit after each task with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. Two identical prompts in one session: each row must show a time, the later row the later time (Task 1 test `test_repeated_prompt_keeps_both_times`; the time store keeps a queue per text, and a row takes the earliest unclaimed entry at first draw).
2. A prompt pasted with `<pasted_content>` wrappers: the card shows the text without the wrapper lines (Task 1 test `test_paste_wrapper_lines_are_hidden`).
3. A tool call that fails: the row keeps its words and adds the mark, in `error`, instead of the engine's red block (Task 3 test `test_failed_call_adds_a_mark`).
4. A Bash command of several lines with no description: the row shows the first line cut to the width, never a wrapped block (Task 3 test `test_long_command_is_cut_to_the_row`).
5. The mod loads from a repo path with spaces or a different drive on the laptop: `install.ps1` must print the loaded folder from the installed settings and `claude plugin validate` must pass there (Task 6 step 7).
8. A second PC after `git pull; .\install.ps1`: the same font, terminal colour scheme, Claude Code theme, status line, mod and tool versions, verified by the installer's `Same experience` step, not by eye (Task 6 steps 4 to 6).
6. The overflow file is missing, half-written or from a wider terminal: the hint line stays the engine's own, never an error row or a wrapped line (Task 4 tests `test_no_overflow_file_passes_to_the_engine`, `test_overflow_is_cut_to_the_room`).
7. An Agent row drawn before the mod saw its spawn (a resumed session, a hot reload mid-run): the row shows the call's description with no model, effort or figures, never a crash or an empty row (Task 5 test `test_unknown_agent_row_shows_the_description`).

---

### Task 1: Scaffold and the prompt card

**Files:**
- Create: `mods/session-cards/.claude-plugin/plugin.json`, `mods/session-cards/hooks/hooks.json`, `mods/session-cards/hooks/register.tsx`, `mods/session-cards/types/index.d.ts`, `mods/session-cards/tsconfig.json` (extends the laid `.claude-plugin/types/tsconfig.json`)
- Create: `mods/session-cards/tests/cards.test.tsx`

**Interfaces:**
- Produces: `export const register: Register`; `export function promptText(text: string): string`; `export function clock(ms: number): string` (`HH:MM` local); `$.state` under `session-cards`: `promptTimes: Record<string, number[]>` (text → submission times, oldest first).

- [ ] **Step 1: Load `plugin-authoring`, lay the files, write the failing tests**

```tsx
test('a prompt is an accent card headed You prompted and the time', async ($, on) => {
  await $.prompt.submit({ text: 'hello', wait: false })  // or raise prompt.submit the way the kit does; the reference says which
  const ui = await $.ui.mount({ plugin: 'session-cards', surface: 'terminal', component: 'UserMessage',
    props: { text: 'hello', origin: { kind: 'composer' }, isExpanded: false } })
  const box = await ui.find({ type: 'Box' })
  expect(box?.props.borderColor).toBe('claude')
  const head = await ui.find({ type: 'Text', text: /You prompted · \d\d:\d\d/ })
  expect(head?.props.bold).toBe(true)
})

test('a row with no recorded time has no clock', ...)         // header is exactly '\uf007  You prompted'
test('test_repeated_prompt_keeps_both_times', ...)           // submit 'x' at t1 and t2 (mock.clock); two mounts show t1 then t2
test('test_paste_wrapper_lines_are_hidden', () => {
  expect(promptText('see:\n<pasted_content id="a1">\nline\n</pasted_content id="a1">\nthanks')).toBe('see:\nline\nthanks')
})
test('other origins and other surfaces are the engine\'s', ...) // task-notification row and desktop surface: next(e) called
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `claude plugin test mods/session-cards`
Expected: the test file loads and every test fails (no hooks registered yet).

- [ ] **Step 3: Implement `register` with the `prompt.submit` and `UserMessage` hooks**

`prompt.submit`: push `Date.now()` (the kit's clock in tests) onto `promptTimes[e.text]`, then `next(e)`. `UserMessage`: on first draw of a row, shift the earliest time for `e.props.text` and remember it for that draw (keep a `WeakMap`/id keyed by the props object is not stable: keep a per-text cursor instead, documented in the module). Card: `Box flexDirection="column" borderStyle="round" borderColor="claude" paddingX={1}`, header `Text color="claude" bold`, body `Text` with `promptText`.

- [ ] **Step 4: Run the tests and validation**

Run: `claude plugin test mods/session-cards && claude plugin validate mods/session-cards`
Expected: all pass; validation passed.

- [ ] **Step 5: Commit**

```bash
git add mods/session-cards
git commit -m "session-cards: prompt card with the time it was handed over"
```

### Task 2: Command card

**Files:**
- Modify: `mods/session-cards/hooks/register.tsx`
- Modify: `mods/session-cards/tests/cards.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
test('a slash command is a violet card headed by the command and its arguments', ...) // borderColor 'permission', header '\uf120  /review ultra', the engine's inner tree inside
test('an errored command is bordered in error', ...)
test('a command the engine drew empty stays empty', ...)   // inner Box with no children is returned as is
```

- [ ] **Step 2: Run to verify they fail** — `claude plugin test mods/session-cards`

- [ ] **Step 3: Implement the `CommandOutput` hook** (`const inner = await next(e)` first; wrap unless empty).

- [ ] **Step 4: Run tests and validation** — both pass.

- [ ] **Step 5: Commit** — `git commit -m "session-cards: violet command card"`

### Task 3: Tool rows

**Files:**
- Modify: `mods/session-cards/hooks/register.tsx`
- Create: `mods/session-cards/tests/tools.test.tsx`

**Interfaces:**
- Produces: `export function describeTool(tool: string, input: unknown, cwd: string): { icon: string; verb: [string, string]; detail: string }`; `export function rowText(d, state: 'running' | 'done' | 'failed' | 'stopped', width: number): string` (plain text for tests, `…` cut).

- [ ] **Step 1: Write the failing tests**

```tsx
test('describeTool names each tool in plain words', () => {
  expect(describeTool('Bash', { command: 'git status', description: 'Show status' }, 'C:/dev')).toEqual({ icon: '\uf120', verb: ['Running', 'Ran'], detail: 'Show status' })
  expect(describeTool('Edit', { file_path: 'C:/dev/a/b.py' }, 'C:/dev').detail).toBe('a/b.py')
  expect(describeTool('Grep', { pattern: 'foo', path: 'src' }, 'C:/dev').detail).toBe('foo in src')
  expect(describeTool('mcp__plugin_context7_context7__query-docs', {}, 'C:/dev').detail).toBe('plugin_context7_context7 query-docs')
  expect(describeTool('AskUserQuestion', { questions: [{ question: 'Which?' }] }, 'C:/dev').detail).toBe('Which?')
})
test('test_long_command_is_cut_to_the_row', () => {
  const d = describeTool('Bash', { command: 'a'.repeat(200) + '\nsecond' }, 'C:/dev')
  expect(rowText(d, 'done', 40).length).toBeLessThanOrEqual(40)
  expect(rowText(d, 'done', 40).endsWith('…')).toBe(true)
  expect(rowText(d, 'done', 40)).not.toContain('second')
})
test('a running row and a done row', ...)          // mount ToolUse isRunning true → 'Running', then false → 'Ran'; verb Text bold, color 'text'
test('test_failed_call_adds_a_mark', ...)          // isErrored → a Text ' ✗' with color 'error' after the detail
test('expanded rows, agents and other surfaces are the engine\'s', ...)
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement `describeTool`, `rowText` and the `ToolUse` hook**

Row: `Box flexDirection="row"` with `Text color="text"` icon + space, `Text color="text" bold` verb, `Text color="text"` ` detail`, state marks. Width from the engine's columns as the reference says (`e` or `$.ui` gives the columns; otherwise 120).

- [ ] **Step 4: Run tests and validation** — both pass.

- [ ] **Step 5: Commit** — `git commit -m "session-cards: white icon-and-words tool rows"`

### Task 4: Status bar overflow on the hint line

**Files:**
- Modify: `mods/session-cards/hooks/register.tsx` (a `ui.render` hook on `{ component: 'PromptHint' }`)
- Modify: `mods/session-cards/types/index.d.ts` (`overflowTick: number`)
- Test: `mods/session-cards/tests/overflow.test.tsx`

**Interfaces:**
- Consumes: the file `statusbar.py` writes, `<home>/.claude/statusbar-overflow/<session_id>.json`: `{ written_at: number, columns: number, pieces: Span[][] }`, `Span = { text: string, colour: string | null, bold: boolean }`. Home is `$.env.get("HOME")`, else `$.env.get("USERPROFILE")`; the session id is `$.session.id()`. The file is absent when the script has not run for this session, and holds `pieces: []` when nothing was dropped.
- Produces: nothing other tasks use.

The engine's hint line (`PromptHint`) reads `⏵⏵ bypass permissions on (shift+tab to cycle)` or `? for shortcuts`; `e.props.hint` is that text. The hook draws its own tree: the engine's hint as the engine draws it (dim), two spaces, then the overflow pieces joined by ` │ ` in the status bar's own colours, bold where the span says so. The pieces are cut to the room: with `columns = e.viewport?.columns ?? 80` (`viewport` is optional on the render input), the hook takes pieces in file order while `hint + "  " + joined` fits in `columns - 4` cells, and stops at the first that does not. A piece's width is its text's cells with each Nerd Font glyph (U+E000–U+F8FF) counted as 1. When no piece fits, or the file is absent, unreadable, not JSON or has no `pieces` array, the hook returns `next(e)`: the engine's own line, pills live. Drawing a tree replaces the engine's live pills, so this is the one cost of the feature and is noted in the README.

The file changes once a minute (the status line refreshes every 60 s) and the hint only redraws on its own events, so `session.start` sets `$.clock.every(60_000, …)` to `update($, overflowTick, n => n + 1)`; the hook reads the atom so the tick redraws it.

- [ ] **Step 1: Write the failing tests** in `overflow.test.tsx` with the test harness the `plugin-authoring` reference describes (a fixture home folder with the file written by the test; `$.env` answered from a set, `$.session.id()` fixed):
  - `test_overflow_is_drawn_after_the_hint`: pieces `[[{text: "$1.23", colour: "green", bold: false}]]`, columns 160, hint `? for shortcuts` → the tree's text is `? for shortcuts  $1.23`, the `$1.23` run has `color: "green"`.
  - `test_overflow_is_cut_to_the_room`: two pieces of 20 cells each, columns 50, hint of 30 cells → only the first piece is drawn (`30 + 2 + 20 = 52 > 46` means none; choose widths so exactly one fits) and the line has no `│` after it.
  - `test_no_overflow_file_passes_to_the_engine`: no file → the result is what `next(e)` returned.
  - `test_bad_overflow_file_passes_to_the_engine`: the file holds `{` → `next(e)`.
  - `test_other_surfaces_pass`: `surface: 'desktop'` → `next(e)`.

- [ ] **Step 2: Run** `claude plugin test mods/session-cards` — Expected: the five fail (no `PromptHint` hook registered).

- [ ] **Step 3: Implement** the hook and the tick in `register.tsx`; declare `overflowTick: number` in `types/index.d.ts`.

- [ ] **Step 4: Run** `claude plugin validate mods/session-cards` and `claude plugin test mods/session-cards` — Expected: both pass, all tests green.

- [ ] **Step 5: README** — in the `mods/session-cards` row: the hint line shows the status bar's overflow; while it does, the engine's shortcut pills on that line are plain text.

- [ ] **Step 6: Commit** — `git commit -m "session-cards: draw the status bar's overflow on the hint line"`

### Task 5: Agent rows with the subagent's model, effort and live activity

**Files:**
- Modify: `mods/session-cards/hooks/register.tsx` (the `ToolUse` hook stops passing `Agent` rows; `agent.spawn`, `turn.step`, `tool.call` and `turn.complete` hooks feed a module-level map; an `agentTick` atom redraws)
- Modify: `mods/session-cards/types/index.d.ts` (`agentTick: number`)
- Test: `mods/session-cards/tests/agents.test.tsx`

**Interfaces:**
- Consumes: `describeTool` and the row style from Task 3. From the types: `agent.spawn` input `{ tool_use_id, description, subagentType, model?, parentModel }` and result `{ model, agentId }` (hook: `const r = await next(e)`, then record); `turn.step` input with `agentId`, `model`, `effort?` and `usage` (input and output tokens); `tool.call` input with `agentId`, `tool`, `input`; `turn.complete` input with `agentId`. Grep `TurnStepInput`, `TurnUsage`, `AgentLoop`, `ToolCallInput` for the exact field names before writing the tests.
- Produces: `export function modelColour(model: string): string | undefined` and `export function effortColour(level: string): string | undefined` (colour names as in the Spec); `export function agentRow(a: AgentRecord, now: number): { verb: string; type: string; model?: string; effort?: string; action: string; elapsed: string; tokens?: string }`; `export function fmtElapsed(ms: number): string` (`0s`, `48s`, `1m 0s`, `12m 5s`, `1h 2m`); `export function fmtTokens(n: number): string` (`950`, `72k`, `1.2M`, as the status bar does).

- [ ] **Step 1: Write the failing tests** in `agents.test.tsx`:
  - `modelColour` and `effortColour` return the Spec's names for `claude-opus-5-5`, `Sonnet`, `haiku`, `claude-fable-5-1`, `Mythos`, `other` (undefined) and for the five levels.
  - `fmtElapsed` and `fmtTokens` for the values listed in Interfaces.
  - `test_agent_row_shows_type_model_effort_and_action`: raise `agent.spawn` for a `worker` with description `Implement Task 1` (its `next` answering `{ model: 'claude-sonnet-5-5', agentId: 'a1' }`), a `turn.step` for `a1` with effort `high` and usage 40k in, 32k out, and a `tool.call` for `a1` of `Grep { pattern: 'cwd', path: 'reference.md' }`; mount the `Agent` `ToolUse` row with that `tool_use_id`, `isRunning: true` → the row's text reads ` Running worker · Sonnet · high  Searching cwd in reference.md   <elapsed> · 72k`, the `Sonnet` Text has `color: 'blue'`, the `high` Text `color: 'red'`, the verb bold, everything else `color: 'text'`.
  - `test_finished_agent_row`: after `turn.complete` for `a1` and `isRunning: false` → `Ran worker · Sonnet · high  done   <elapsed> · 72k`; with `isErrored` → ` ✗` in `error`.
  - `test_unknown_agent_row_shows_the_description`: a row whose `tool_use_id` the map does not know → `Running worker  <the call's description from e.props.input>` and nothing else.
  - `test_other_surfaces_and_expanded_rows_pass`.

- [ ] **Step 2: Run** `claude plugin test mods/session-cards` — Expected: the new tests fail (no exports, Agent rows still pass to the engine).

- [ ] **Step 3: Implement.** Module map `agents: Map<toolUseId, AgentRecord>` plus `byAgentId: Map<agentId, toolUseId>`; `AgentRecord = { type, description, model?, effort?, startedAt, finishedAt?, tokens, action? }`. Each feeding hook updates the record, calls `update($, agentTick, n => n + 1)` and returns `next(e)` (for `agent.spawn`, the result of the `next` it awaited). A `$.clock.every(1000, …)` set in `session.start` ticks the atom only while some record has no `finishedAt`. The `ToolUse` hook, for `e.props.tool === 'Agent'` on the terminal with `isExpanded` not true, reads the atom and `$.clock.now()` and draws the row; Task 3's Agent/Task pass-through is removed for `Agent` (Task and other tools keep their Task 3 behaviour).

- [ ] **Step 4: Run** `claude plugin test mods/session-cards` and `claude plugin validate mods/session-cards` — Expected: both pass, 19 earlier tests plus Task 4's still green.

- [ ] **Step 5: README** — add the agent row to the `mods/session-cards` row.

- [ ] **Step 6: Commit** — `git commit -m "session-cards: agent rows with the subagent's model, effort and live activity"`

### Task 6: Install on every machine

**Files:**
- Modify: `settings.json` (`env.CLAUDE_CODE_PLUGIN_DIRS`: `<repo>/mods/session-cards`)
- Modify: `install.ps1` (restore a `CLAUDE_CODE_PLUGIN_DIRS` union in the env merge so another machine's own entries survive; add a step `Session cards mod` before `MCP health`)
- Modify: `README.md`

- [ ] **Step 1: settings.json** — add the env entry.

- [ ] **Step 2: install.ps1** — in `Merge-ClaudeSettings`, `CLAUDE_CODE_PLUGIN_DIRS` is unioned (`;`-separated, compared with forward slashes, case-insensitive, ours added once). New step: read `env.CLAUDE_CODE_PLUGIN_DIRS` from the installed `$settingsPath`; fail unless it contains `<repo>/mods/session-cards` (forward slashes); run `claude plugin validate <that folder>` and fail on a non-zero exit; print `<claude --version> loads <folder>`.

- [ ] **Step 3: README** — table row for `mods/session-cards` (what the hooks draw; replace the row Task 4 wrote, which says the installer does not load the mod) and the merge rule for `CLAUDE_CODE_PLUGIN_DIRS`.

The same experience on another PC (asked 2026-10-23): everything that shapes what the person sees is either in this repo or verified by the installer, so `git pull; .\install.ps1` on the laptop gives the identical screen. What shapes it: the Nerd Font and its glyph widths; the Windows Terminal colour scheme (the bar's and the mod's colours are the terminal's own 16, so a different scheme is a different bar); Claude Code's theme; the status line command; the mod folder; the Claude Code, Python and Git Bash versions.

- [ ] **Step 4: Record this PC's terminal look** — measured 2026-10-23 from this PC's Windows Terminal `settings.json`: `profiles.defaults.font` is `{ "face": "JetBrainsMono Nerd Font", "cellHeight": "1.25" }`, no `colorScheme` is set anywhere (so every profile runs the built-in `Campbell` scheme), no custom `schemes`, and Claude Code's `theme` is unset (its default, `dark`). New file `terminal/profile.json`: `{ "font": { "face": "JetBrainsMono Nerd Font", "cellHeight": "1.25" }, "colorScheme": "Campbell" }`, with a `terminal/README.md` of three lines saying it is what `install.ps1` writes into `profiles.defaults` and why (the bar's and the mod's colours are the scheme's own 16).

- [ ] **Step 5: install.ps1 applies it** — the `Nerd Font` step sets `profiles.defaults.font` to `terminal/profile.json`'s whenever it differs (face or cellHeight), instead of only when none is set; `-KeepFont` keeps the machine's own. A new `Terminal scheme` step sets `profiles.defaults.colorScheme` to `Campbell` whenever it differs or is unset, and removes a `colorScheme` set on the default profile itself so the default applies; `-KeepScheme` keeps the machine's own. Both print what they changed, or `already set`. `settings.json` in the repo pins `"theme": "dark"` so the merge carries it.

- [ ] **Step 6: install.ps1 `Same experience` step** — after `Session cards mod`, before `MCP health`: a table of `name  expected  actual  ok|FAIL` for: Nerd Font file present; Windows Terminal `profiles.defaults.font` face and cellHeight; Windows Terminal `profiles.defaults.colorScheme` (`Campbell`) with none set on the default profile; Claude Code `theme` (`dark`) in the installed settings; `statusLine.command` (ends with `statusbar.py` or `statusbar.py --labels`); `CLAUDE_CODE_PLUGIN_DIRS` contains the mod folder; `claude --version` at least `2.1.308`; `python --version` at least 3.10; Git Bash found. Any FAIL fails the install with the row named. `-KeepFont` and `-KeepScheme` turn their rows into `kept` instead of FAIL.

- [ ] **Step 7: Run the installer**

Run: `pwsh -NoProfile -File C:\dev\claude-setup\install.ps1 -SkipPlugins 2>&1 | Select-String 'Session cards|Same experience|FAIL|DONE' -Context 0,10`
Expected: `==> Session cards mod` then `2.1.308 (Claude Code) loads C:/dev/claude-setup/mods/session-cards`; `==> Same experience` with every row `ok`; `DONE: all checks passed`.

- [ ] **Step 8: Tests** — `tests/test_install.py` (Python, no PowerShell needed): `terminal/profile.json` parses, its `font.face` ends with `Nerd Font`, its `font.cellHeight` is `"1.25"` and its `colorScheme` is `Campbell`; the repo `settings.json` has `"theme": "dark"` and `env.CLAUDE_CODE_PLUGIN_DIRS` ending in `mods/session-cards`; `install.ps1` mentions `Same experience`, `-KeepFont` and `-KeepScheme`. Run `python -m unittest discover -s tests` → all pass (the status bar's 59 included).

- [ ] **Step 9: Commit** — `git commit -m "session-cards: install and verify the same experience on every machine"`

### Task 7: Live check and PR

- [ ] **Step 1:** Restart Claude Code in `C:\dev\claude-setup`; type a prompt, run `/context`, let a Bash and an Edit run, and dispatch one background `Explore` agent. Compare with the engine's rows: same column, same weight; the card time matches the clock. The agent row must show the model and effort in colour and the live action; if the engine's background-agent line (the one with `>` and the live figures) is not the `Agent` `ToolUse` row and stays the engine's, record that as a ruling and say so in the PR. Narrow the terminal to about 100 columns: the cost and reset times leave the status line and appear, in colour, after the permissions text on the hint line; narrower still, they disappear from there too. Fix differences and add a test for each.
- [ ] **Step 2:** `gh pr create` from branch `session-cards` with the attribution footer; merge; `git checkout main; git pull`.
- [ ] **Step 3:** Laptop: `git pull; .\install.ps1`; the `Session cards mod` step must print the laptop's folder.
