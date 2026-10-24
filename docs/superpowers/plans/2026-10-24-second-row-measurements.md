# Second row: measured columns (Claude Code 2.1.310, Windows Terminal, 120 columns)

Captured 2026-10-24 with PrintWindow from demo windows started with `--permission-mode bypassPermissions`, `default`
and `plan`; the cell grid is 10 px from x = 16 (the prompt rule spans x 16..1215 for 120 cells).

| Constant | Value | Evidence |
|---|---|---|
| `STATUS_X` | 2 | the status line's first glyph (repo icon) is lit from cell 2 in all three modes |
| `HINT_X` | 2 | the mode label (`⏵⏵`, `⏸`) and the default hint (`?`) start in cell 2 |

`LABEL_CELLS` is `symbol + " " + indicator + " on" + " · "`, from the engine's own strings (`_Tt="⏵⏵"` for every
mode but plan, `qAe="⏸"` for plan and default; the footer draws `[ModeLabel, Text(" · "), PromptHintSite]`):

| Mode | Label | Cells | Checked live |
|---|---|---|---|
| `default` | none | 0 | yes: hint starts in cell 2 |
| `acceptEdits` | `⏵⏵ accept edits on · ` | 21 | |
| `auto` | `⏵⏵ auto mode on · ` | 18 | |
| `bypassPermissions` | `⏵⏵ bypass permissions on · ` | 27 | yes: the hint's shield is in cell 29 = 2 + 27 |
| `dontAsk` | `⏵⏵ don't ask on · ` | 18 | |
| `plan` | `⏸ plan mode on · ` | 17 | yes: the hint's shield is in cell 19 = 2 + 17 (`⏸` is one cell) |
