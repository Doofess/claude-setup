# Second Row Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay out the pieces the status bar moves onto the hint row by the user's rules. A reset time whose bar stayed on the top row sits exactly under that bar's first block, without its arrow. A whole meter that moves lines its bar up under the last bar left on the top row. Every other moved piece sits right-aligned, and the mode label and hint keep the left.

**Architecture:** `statusbar.py` already writes the moved pieces to `~/.claude/statusbar-overflow/<session>.json`. It will now also write where each one goes. "Under" pieces carry the absolute screen column of their bar's first block. "Bars" (moved meters with their resets) carry the screen column that puts their first block under the last top-row bar's first block. "Right" pieces are in display order, each with its drop rank. The record also carries the mode label's width, which `statusbar.py` reads from the session transcript's last `permission-mode` entry. The session-cards mod's `PromptHint` hook draws the row from that: the hint, spaces up to each under piece and bar, then spaces up to the right group, dropping right pieces on a collision.

**Tech Stack:** Python 3.10+ (`statusbar.py`, unittest), TypeScript/TSX mod (`claude plugin test mods/session-cards`, bun test).

**Spec:** the user's rules and answers, 2026-10-24 (this session):
- A reset time sticks to its bar by default: it sits beside it on the top row with its `→`.
- A reset time that has to move to the second row while its bar stays on the top row sits exactly under the bar's **first block**. Its `→` is hidden on the second row.
- A whole meter that moves to the second row takes its reset time with it, beside it with the `→` (for example `7D ███░░░░░ 41%  → 3d4h`). A meter never moves without its reset time.
- A moved meter lines up with the top row (user, after #33): the first moved meter's first block sits exactly under the first block of the **last bar kept on the top row** (the context bar when both plan meters move), and a second moved meter follows it with the usual ` │ `. Where that cannot fit (it would start inside the label and hint, or run past the right margin), the moved meters join the right-aligned group instead, as before.
- The other pieces on the second row stick to the right. The mode label stays on the left.
- Collision: reset times and moved bars keep their places, and right-aligned pieces drop, least important first (session time, then cost, …), until nothing touches. A dropped piece is not shown.
- Mode label width: read from the transcript. It is exact in every mode; after Shift+Tab it can be off until that turn ends.
- Already decided (PR #29): model and effort never move; the bar has no PR piece.

## Global Constraints

- Mode labels are `<symbol> <indicator> on · `, with indicators from Claude Code 2.1.310: `acceptEdits` "accept edits", `auto` "auto mode", `bypassPermissions` "bypass permissions", `dontAsk` "don't ask", `plan` "plan mode". The symbol is `⏵⏵` for all of them except `plan`, whose symbol is the one `default` uses (probably `⏸`). `default` mode draws no label at all (its hint is `? for shortcuts`). Bypass is 27 cells, matching the mod's `MODE_LABEL`. Task 1 measures the real widths; they are not assumed.
- Widths are terminal cells, as `statusbar.cells()` counts them. The mod's `widthOf` counts by code point, and both must agree on every piece the bar can emit (Nerd Font icons are 1 cell).
- The overflow record keeps `written_at`, `columns` and `pieces` (the old flat list) beside the new keys. A mod older than this change keeps working, and the new mod falls back to `pieces` when `under` and `right` are absent: `install.ps1` copies `statusbar.py`, but the mod loads straight from the repo.
- Reading the transcript is best effort. Read only the last 64 KiB, take the last line containing `"type":"permission-mode"`, and fall back to `bypassPermissions` when there is no transcript, no such line, or an unknown mode. It must never fail the bar.
- Since PR #34 the hook draws `<shield> <hint>` (U+F0BC5 and a space, 2 cells) whenever a mode label is in front; `hintCells` counts the shield. Since PR #35 effort xhigh/max are per-letter runs; spans already carry one colour per run.
- Tests: `python -m unittest discover -s tests` OK and `claude plugin test mods/session-cards` all pass. Never run a worktree's `install.ps1`.
- Start from main after PRs #27, #29 and #30 are merged; they change `statusbar.py` and its tests.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- **A long hint that runs past an under column** (`esc to interrupt · ctrl+t to hide todos`): the hint wins. An under piece that would overlap the label plus hint is not drawn, and the other under pieces keep their places. Task 3 tests this.
- **Layout's put-back pass keeping a reset time whose meter was dropped:** a narrow meter dropped while its short reset time gets put back would break "a meter never moves without its reset time". Put-back may keep a reset only when its meter is kept. Task 2 tests this.
- **The status row's and the hint row's first columns differ** (for example if Claude Code pads the status line by 1 or 2 columns): under columns are computed as `status_x + offset in line`, and the mod subtracts `hint_x + label + …`. Task 1 measures both, and Task 3 uses the measured constants.
- **A window narrower than label + hint + one under piece:** draw the hint as the engine does (`next(e)`) rather than a broken row. Task 3 tests this.
- **The session's first turn before any `permission-mode` line exists, or a transcript of several MB:** the bypass fallback, and a read capped at 64 KiB. Task 2 tests both.

---

### Task 1: Measure the columns live

**Files:**
- Create: `docs/superpowers/plans/2026-10-24-second-row-measurements.md` (results only)

**Interfaces:**
- Produces: the constants Task 2 and Task 3 use:
  - `STATUS_X`, the screen column of the status line's first cell.
  - `HINT_X`, the screen column where the engine starts the mode label (or the hint, in default mode).
  - `LABEL_CELLS: dict[mode, int]` for the six modes.

- [ ] **Step 1:** Start a demo Claude Code window the way the `demo-session-screenshots` memory describes: strip `NO_COLOR` and the session env, find the window with EnumWindows, and capture it with PrintWindow, killing only the demo `claude.exe` afterwards. Use `COLUMNS` 120.
- [ ] **Step 2:** In default, bypass (`--dangerously-skip-permissions`), accept-edits, plan and auto mode (switch with Shift+Tab), capture the bottom rows. Count the cells from the left edge to the first status-line glyph and to the first label glyph. Count each label up to the start of the hint text.
- [ ] **Step 3:** Write the numbers and the screenshots' paths into the measurements file. Commit it with the message `second row: measured columns of the status and hint rows`.

### Task 2: `statusbar.py` writes where each moved piece goes

**Files:**
- Modify: `statusbar.py`: `layout` (put-back rule), the reset segments (they know their meter), `overflow_record`, and a new `mode_label_cells`.
- Test: `tests/test_statusbar.py`

**Interfaces:**
- Consumes: Task 1's `STATUS_X` and `LABEL_CELLS`, as module constants.
- Produces:
  - `mode_label_cells(transcript_path: str | None) -> int` returns `LABEL_CELLS[mode]`, with `bypassPermissions` as the fallback, and 0 for `default`.
  - `overflow_record(kept: list[Segment], dropped: list[Segment], columns: int, now: float, label: int) -> dict` returns `{"written_at", "columns", "pieces", "label": int, "under": [{"col": int, "spans": [...]}], "bars": [{"col": int, "rank": int, "spans": [...]}], "right": [{"rank": int, "spans": [...]}]}`:
    - `under` holds every dropped reset time whose meter is kept. Its spans are the time text without `→ ` (`2h10m`), and `col = STATUS_X + cells(line up to the meter's first block)`.
    - `bars` holds each dropped meter as one entry: the meter's spans, two spaces, then its reset's spans with the `→`. The first entry's `col = STATUS_X + cells(line up to the last kept meter's first block) - cells(the moved meter's text before its first block)`, so the two first blocks share a column; each later entry's `col` is the previous `col + cells(previous) + 3` (the ` │ `). With no meter kept on the top row, `bars` is empty and the moved meters go in `right`.
    - `right` holds every other dropped piece in display order.
    - `rank` is the piece's drop priority (a higher number means less important; drop first). For a merged meter and reset, it is the meter's.
  - How a reset knows its meter: segments become a NamedTuple `Segment(text, priority, group, role)`, where `role` is one of `"meter:5h"`, `"reset:5h"`, `"meter:7d"`, `"reset:7d"` or `""`. Keep tuple unpacking working, since tests unpack three fields: use a 4-field NamedTuple and update the unpacking sites.

- [ ] **Step 1: Write the failing tests:**
  - `test_reset_under_its_meter`: at a width where the 7D reset drops but the meter stays, `under` has one entry. Its text is `3d4h` with no `→`, and its `col` equals `STATUS_X + cells(plain line up to the first █ of the 7D meter)`.
  - `test_meter_and_reset_move_together`: at a width where the 7D meter drops, `bars` has one entry whose plain text is `7D ███░░░░░ 41%  → 3d4h` (with the icon under the icon marks), and no `under` or `right` entry names 7D.
  - `test_moved_bar_lines_up_under_the_last_top_bar`: with the context meter kept and 7D dropped, `bars[0].col + cells(7D text before its first █)` equals `STATUS_X + cells(plain line up to the context meter's first █)`. With 5H and 7D both dropped, `bars[1].col == bars[0].col + cells(bars[0]) + 3`.
  - `test_put_back_never_keeps_a_reset_without_its_meter`: build segments where the 7D meter is too wide to put back but its reset would fit. The reset is not on the line.
  - `test_right_pieces_carry_rank`: the session time's rank is greater than the cost's.
  - `test_mode_label_from_transcript`: a temp transcript whose last `permission-mode` line is `plan` gives `LABEL_CELLS["plan"]`. Without the file, the result is the bypass width. A 5 MB file with the line in its last 10 KiB still gives the right answer, and only the tail is read (assert by patching `open` or timing well under 50 ms).
  - Keep `pieces` asserted equal to today's flat list.
- [ ] **Step 2:** Run `python -m unittest tests.test_statusbar -q`. Expected: FAIL.
- [ ] **Step 3:** Implement it. In `main`, pass `data.get("transcript_path")` to `mode_label_cells`. Update the module docstring's overflow paragraph.
- [ ] **Step 4:** Run `python -m unittest discover -s tests`. Expected: OK.
- [ ] **Step 5:** Commit with the message `statusbar: overflow says where each piece goes (under its bar or right) and the mode label's width`.

### Task 3: The mod draws the row

**Files:**
- Modify: `mods/session-cards/hooks/register.tsx`: `parseOverflow` and the `PromptHint` hook. Replace `fitPieces` with `placeRow`, and drop the `MODE_LABEL` guess when the record has `label`.
- Test: `mods/session-cards/tests/overflow.test.tsx`

**Interfaces:**
- Consumes: Task 2's record. `HINT_X` comes from Task 1, as a constant beside `SEPARATOR`.
- Produces: `placeRow(record: Overflow, hintCells: number, columns: number): Array<{ col: number; spans: Span[] }> | null`. It returns the pieces to draw, each with its offset inside the hook's own tree, or null when nothing should change. The engine draws the mode label first and the tree starts right after it, at screen column `HINT_X + label`, where `label` is the record's `label`, or 0 when the hint starts with `? for shortcuts`. Its rules:
  1. The tree's left edge is `hintCells + 2`: the hint, then two spaces.
  2. Each under piece goes at tree offset `col - HINT_X - label`. Drop one that starts before the left edge or overlaps an earlier under piece.
  3. Bars go at tree offset `col - HINT_X - label`, like under pieces. If any bar would start before the left edge or end past `columns - 4 - HINT_X - label`, all bars join the right group instead (in order, keeping their ranks).
  4. The right pieces are joined with `SEPARATOR` and end at tree offset `columns - 4 - HINT_X - label`, the same `columns - 4` margin the current code keeps. While they overlap the last under piece or bar, or the left edge, drop the right piece with the highest `rank` and retry.
  5. If no under, bar or right pieces remain, return null, and the hook returns `next(e)`.
  - With only `pieces` in the record (an old bar), keep today's behaviour: a left-packed `fitPieces`, kept as a fallback.
  - Draw it as today: one `<Text wrap="truncate-end">`, with the hint dim and runs of spaces between the pieces.

- [ ] **Step 1: Write the failing tests** in `overflow.test.tsx`, with fixtures built in the test:
  - `under piece lands at its column`: one under piece at screen column 60, `label` 27 and a 120-column row puts the time at tree offset `60 - HINT_X - 27`. With the same record and the `? for shortcuts` hint (label 0), the offset is `60 - HINT_X`.
  - `right pieces end at the margin`: `$1.23 │ 1h 33m` ends at `columns - 4`.
  - `right pieces drop by rank on collision`: an under piece at a column that hits the right group drops the session time first, then the cost.
  - `moved bar lines up`: a bar at screen column 70 with label 27 lands at tree offset `70 - HINT_X - 27`, and a right piece still ends at the margin.
  - `bar that cannot line up goes right`: a bar whose col falls inside the hint joins the right group, ending at `columns - 4`.
  - `hint wins over an under piece`: a 50-cell hint and an under piece at 20 means that piece is not drawn.
  - `old record falls back`: a record with only `pieces` renders as today (reuse the existing expectations).
  - `too narrow returns engine line`.
- [ ] **Step 2:** Run `claude plugin test mods/session-cards`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement `placeRow` and the hook change. Keep `MODE_LABEL` only for the fallback path.
- [ ] **Step 4:** Run `claude plugin test mods/session-cards` (all pass) and `claude plugin validate mods/session-cards` (passes, with only the existing author and icon warnings).
- [ ] **Step 5:** Commit with the message `session-cards: reset times under their bars, the rest of the second row on the right`.

### Task 4: Docs and live check

**Files:**
- Modify: `README.md`. The narrow-window paragraph (around "When the window is narrow…") and the `hint-overflow.png` caption describe the new placement. Retake `docs/images/hint-overflow.png` at 104 columns.
- Modify: the `session-cards-mod-live-check` memory: the mode width now comes from the transcript.

- [ ] **Step 1:** Merge to main, then run main's `install.ps1`. Expected: `DONE: all checks passed`.
- [ ] **Step 2:** Run a demo window at 104 and 90 columns in bypass and in plan mode. With a PrintWindow capture, check:
  - each moved reset time starts in the same column as its bar's first block;
  - no `→` appears on the second row except beside a moved meter;
  - a moved meter's first block sits in the same column as the last top-row bar's first block;
  - the cost and the session time touch the right margin.
  Save the 104-column capture over `docs/images/hint-overflow.png`.
- [ ] **Step 3:** Commit with the message `README: the second row's layout, new picture`.
