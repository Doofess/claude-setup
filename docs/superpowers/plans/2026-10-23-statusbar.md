# Status bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A two-row Claude Code status line, built from scratch, that shows where you are (repo, branch, PR, model, effort) and how much room is left (context to auto-compact, 5-hour and 7-day plan usage, cost and lines changed), installed identically on every machine by `install.ps1`.

**Architecture:** One Python file, `statusbar.py`, with no dependencies: it reads Claude Code's JSON from stdin, computes the auto-compact point the way Claude Code does, builds each row as a list of prioritised segments, drops the lowest-priority segments until the row fits `COLUMNS`, and prints two rows with ANSI colours from the terminal's 16-colour palette. `install.ps1` copies it, sets `statusLine` in settings, then runs the exact installed command with sample data and fails the install when the rows are wrong.

**Tech Stack:** Python 3.10+ standard library (`json`, `os`, `re`, `sys`, `time`), `unittest`; PowerShell 7 for the installer.

> **Revised after the live check (2026-10-23, PR #13):** the bar is one line, not two, so the footer with Claude Code's own mode line is two lines in total. Lines changed are gone, cost is green, each model and effort level has its own colour, and pieces drop in this order on a narrow terminal: cost, 7-day reset, 5-hour reset, PR, repo, effort, 7-day meter, 5-hour meter. Once the line fits, dropped pieces that still fit come back, most important first, so no room is left unused. Nerd Font icons stay (each followed by a space, since the non-Mono font variants draw them wide); `--labels` swaps them for dim words (`ctx`, `5h`, `7d`), and the installer adds that flag on a machine with no Nerd Font. The tasks below describe the first, two-row build.

**Spec:** The design agreed in chat on 2026-10-23, recorded in the Spec section below. The old status line (tag `visual-v1`) is not a reference: this is a fresh design.

## Spec

**Rows** (each a row of segments separated by `  ` and `│`; icons are JetBrainsMono Nerd Font glyphs, one cell wide):

```
 owner/name  main  #12  │   Fable · high
 ████░░░░ 42%  112k/267k  │   ███░░ 23% →2h10m  │   ████░ 41% →3d4h  │  $1.23 +156 −23
```

Row 1, left to right: repo `\uf09b` + `owner/name` (from `workspace.repo`, absent outside a repo with an origin); branch `\ue0a0` + name (read from `.git/HEAD`); PR `\uf407` + `#number` when `pr` is present; separator; model `\uf2db` + `model.display_name`, then ` · ` + `effort.level` when present.

Row 2: context `\uf1c0` + 8-cell meter + `NN%` + `used/ceiling` tokens; 5-hour `\uf017` + 5-cell meter + `NN%` + `→reset`; 7-day `\uf073` + 5-cell meter + `NN%` + `→reset`; `$` + cost with two decimals; `+added −removed` lines.

**Meters:** filled cell `█`, empty `░`. Colour by fill: under 70% green (SGR 32), 70–89% yellow (33), 90% and over red (31). Icons and separators bright black (90); numbers default foreground; model name bold (1). No colour outside SGR 1, 31, 32, 33, 90 and reset 0, so the status line follows the terminal's own scheme.

**Context meter:** `used` = `context_window.total_input_tokens` (0 before the first reply). `ceiling` = auto-compact window − 33,000. Window resolution, highest first: `CLAUDE_CODE_AUTO_COMPACT_WINDOW` env; settings files in the order user `~/.claude/settings.json`, project `<project_dir>/.claude/settings.json`, local `<project_dir>/.claude/settings.local.json`, managed (`C:\ProgramData\ClaudeCode\managed-settings.json` on Windows, `/Library/Application Support/ClaudeCode/managed-settings.json` on macOS, `/etc/claude-code/managed-settings.json` on Linux), later files winning, where each file contributes `modelSettings[<model key>].autoCompactWindow` and `autoCompactWindow`, a file's top-level value discarding the per-model values of earlier files; else `context_window.context_window_size`. `"auto"` means the model's own window. The window is capped at `context_window_size`. Model key: `model.id` with a trailing `-YYYYMMDD` and a `[1m]` suffix removed. Why 33k: Claude Code 2.1.308 compacts at `window − 13000` measured against the context plus its 20k reply room; this session's transcript shows auto-compaction at 269,168 tokens with a 300k window.

**Reset time:** `→45m` under an hour, `→2h10m` under a day, `→3d4h` otherwise; minutes dropped when hours are shown past a day. A window that reset already shows `→now`.

**Width:** the row must fit `COLUMNS − 4` cells (`MARGIN = 4` for Claude Code's own spacing). Every character counts one cell. When a row is too wide, segments drop in priority order until it fits: row 1 drops PR, then repo, then effort; branch and model stay. Row 2 drops lines, then cost, then the 7-day reset time, then the 5-hour reset time, then the 7-day meter, then the 5-hour meter; context stays. `COLUMNS` unset means 120.

**Absent data:** no `rate_limits` window → that segment is left out; `context_window.used_percentage` null or `total_input_tokens` 0 → `0%` and `0/267k`; no repo → no repo segment; no `.git` → no branch segment; no `effort` → model alone; no `cost` → no cost or lines segments.

**Timer:** `refreshInterval` 60 so the reset countdowns move while the session is idle.

**Install guarantee:** `install.ps1` copies `statusbar.py` to `~/.claude/statusbar.py`, sets `statusLine` (the settings merge replaces it: repo wins), and runs the exact command from the installed settings with sample JSON and `COLUMNS=120`; the install fails unless the output has two rows containing `Opus`, `main`, `42%` and `$1.23`. It also fails when `python` is not a real Python 3.10+ (the Windows Store alias prints nothing). It then prints the two rows so each machine's result is seen.

## Global Constraints

- Python 3.10+ standard library only; one file `statusbar.py`; tests in `tests/test_statusbar.py` with `unittest` like `tests/test_mcp_off.py`.
- The file name is `statusbar.py`, never `statusline.py`: `install.ps1`'s "Removing the retired visual setup" step deletes `~/.claude/statusline.py` and removes a `statusLine` whose command contains `statusline`.
- Colours: SGR 0, 1, 31, 32, 33, 90 only.
- The script must never raise on odd input: missing keys, nulls, unreadable files, an empty stdin. On any failure it prints one plain row `statusbar: <error>` and exits 0.
- No subprocesses (no `git`): the branch comes from reading `.git/HEAD`.
- Nothing is cached on disk.
- Commit after each task with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. `.git` is a file (`gitdir: <path>`) in a linked worktree: the branch must come from that gitdir's `HEAD` (Task 2 test `test_branch_in_a_linked_worktree`).
2. A detached HEAD holds a sha, not a ref: show its first 7 characters (Task 2 test `test_detached_head_shows_short_sha`).
3. `COLUMNS` of 60: both rows must still fit and keep context and model (Task 3 test `test_narrow_window_keeps_context_and_model`).
4. `rate_limits.five_hour.resets_at` in the past (Claude Code may send it for a moment): `→now`, not a negative time (Task 1 test `test_reset_already_passed`).
5. Stdin empty or not JSON (Claude Code cancelled a run): a `statusbar:` row, exit 0 (Task 3 test `test_bad_stdin_prints_an_error_row`).

---

### Task 1: Formatting helpers

**Files:**
- Create: `statusbar.py`
- Create: `tests/test_statusbar.py`

**Interfaces:**
- Produces: `fmt_tokens(n: int) -> str` (`950`, `12k`, `135k`, `267k`, `1M`, `1.2M`); `fmt_reset(resets_at: float, now: float) -> str` (`→45m`, `→2h10m`, `→3d4h`, `→now`); `meter(pct: float, cells: int) -> str` (`pct` filled cells rounded, SGR colour by fill, reset at the end); `sgr(code: int, text: str) -> str`; `cells(text: str) -> int` (width with SGR sequences removed); constants `GREEN = 32`, `YELLOW = 33`, `RED = 31`, `DIM = 90`, `BOLD = 1`, `FILLED = "█"`, `EMPTY = "░"`.

- [ ] **Step 1: Write the failing tests**

Test module header like `tests/test_mcp_off.py`: `ROOT` is the repo root, `sys.path` gets it, `import statusbar`; imports `json`, `os`, `re`, `subprocess`, `sys`, `tempfile`, `unittest`.

```python
class FormatTest(unittest.TestCase):
    def test_tokens(self):
        for n, s in [(950, "950"), (12_345, "12k"), (135_000, "135k"), (267_000, "267k"), (1_000_000, "1M"), (1_234_567, "1.2M")]:
            self.assertEqual(statusbar.fmt_tokens(n), s)

    def test_reset_times(self):
        now = 1_700_000_000
        self.assertEqual(statusbar.fmt_reset(now + 45 * 60, now), "→45m")
        self.assertEqual(statusbar.fmt_reset(now + 2 * 3600 + 10 * 60, now), "→2h10m")
        self.assertEqual(statusbar.fmt_reset(now + 3 * 86400 + 4 * 3600 + 20 * 60, now), "→3d4h")

    def test_reset_already_passed(self):
        self.assertEqual(statusbar.fmt_reset(1_700_000_000 - 5, 1_700_000_000), "→now")

    def test_meter_fill_and_colour(self):
        self.assertEqual(statusbar.meter(42, 8), "\x1b[32m███░░░░░\x1b[0m")
        self.assertTrue(statusbar.meter(75, 5).startswith("\x1b[33m"))
        self.assertTrue(statusbar.meter(90, 5).startswith("\x1b[31m"))
        self.assertEqual(statusbar.meter(100, 5).count("█"), 5)
        self.assertEqual(statusbar.meter(0, 5).count("░"), 5)

    def test_cells_ignores_colour_codes(self):
        self.assertEqual(statusbar.cells(statusbar.sgr(statusbar.BOLD, "Fable") + " · high"), 12)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_statusbar -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'statusbar'`

- [ ] **Step 3: Implement the helpers in `statusbar.py`**

Module docstring: what the bar shows and the two rows from the Spec. `meter` rounds `pct / 100 * cells` to the nearest cell and clamps 0–cells. `fmt_reset` rounds down to the minute; `→3d4h` drops minutes.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_statusbar -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add statusbar.py tests/test_statusbar.py
git commit -m "statusbar: formatting helpers"
```

### Task 2: Auto-compact ceiling and branch

**Files:**
- Modify: `statusbar.py`
- Modify: `tests/test_statusbar.py`

**Interfaces:**
- Produces: `model_key(model_id: str) -> str`; `compact_window(model_id: str, window_size: int, env: dict, files: list[dict]) -> int` (files are the parsed settings objects in precedence order, lowest first; unreadable files are passed as `{}`); `settings_files(home: str, project_dir: str, platform: str) -> list[str]` (the four paths in order user, project, local, managed; `platform` is `sys.platform`); `ceiling(window: int) -> int` (`window − HEADROOM`, `HEADROOM = 33_000`); `branch(start_dir: str) -> str | None` (walks up from `start_dir` to the first `.git`, follows a `gitdir:` file, reads `HEAD`: `ref: refs/heads/x` → `x`, a sha → its first 7 characters, nothing found → `None`).

- [ ] **Step 1: Write the failing tests**

```python
class CompactWindowTest(unittest.TestCase):
    def test_model_key_strips_date_and_1m(self):
        self.assertEqual(statusbar.model_key("claude-opus-5-5-20260101"), "claude-opus-5-5")
        self.assertEqual(statusbar.model_key("claude-fable-5-1[1m]"), "claude-fable-5-1")

    def test_env_wins_and_is_capped_at_the_model_window(self):
        self.assertEqual(statusbar.compact_window("m", 200_000, {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "150000"}, [{"autoCompactWindow": 300_000}]), 150_000)
        self.assertEqual(statusbar.compact_window("m", 200_000, {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "500000"}, []), 200_000)

    def test_later_file_wins_and_a_top_level_value_resets_per_model(self):
        files = [{"modelSettings": {"m": {"autoCompactWindow": 150_000}}}, {"autoCompactWindow": 300_000}]
        self.assertEqual(statusbar.compact_window("m", 1_000_000, {}, files), 300_000)
        files = [{"autoCompactWindow": 300_000}, {"modelSettings": {"m": {"autoCompactWindow": 150_000}}}]
        self.assertEqual(statusbar.compact_window("m", 1_000_000, {}, files), 150_000)

    def test_auto_and_nothing_mean_the_model_window(self):
        self.assertEqual(statusbar.compact_window("m", 200_000, {}, [{"autoCompactWindow": "auto"}]), 200_000)
        self.assertEqual(statusbar.compact_window("m", 200_000, {}, []), 200_000)

    def test_ceiling_is_33k_below_the_window(self):
        self.assertEqual(statusbar.ceiling(300_000), 267_000)

    def test_settings_files_order_on_windows(self):
        paths = statusbar.settings_files("C:/u", "C:/p", "win32")
        self.assertEqual([p.replace("\\", "/") for p in paths], ["C:/u/.claude/settings.json", "C:/p/.claude/settings.json", "C:/p/.claude/settings.local.json", "C:/ProgramData/ClaudeCode/managed-settings.json"])


class BranchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def write(self, rel, text):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def test_branch_from_a_subdirectory(self):
        self.write("repo/.git/HEAD", "ref: refs/heads/feature/x\n")
        os.makedirs(os.path.join(self.tmp, "repo/src"))
        self.assertEqual(statusbar.branch(os.path.join(self.tmp, "repo/src")), "feature/x")

    def test_branch_in_a_linked_worktree(self):
        self.write("main/.git/worktrees/wt/HEAD", "ref: refs/heads/wt-branch\n")
        self.write("wt/.git", "gitdir: " + os.path.join(self.tmp, "main/.git/worktrees/wt") + "\n")
        self.assertEqual(statusbar.branch(os.path.join(self.tmp, "wt")), "wt-branch")

    def test_detached_head_shows_short_sha(self):
        self.write("repo/.git/HEAD", "0123456789abcdef0123456789abcdef01234567\n")
        self.assertEqual(statusbar.branch(os.path.join(self.tmp, "repo")), "0123456")

    def test_no_repo(self):
        self.assertIsNone(statusbar.branch(self.tmp))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_statusbar -v`
Expected: FAIL with `AttributeError: module 'statusbar' has no attribute 'model_key'` (and the others)

- [ ] **Step 3: Implement the functions in `statusbar.py`**

`compact_window`: parse the env value as an int, or `Nk`/`NM` (`200k`, `1M`), or a bare number under 1000 as thousands; ignore it when unparsable. Fold the files as Claude Code does: a file with `autoCompactWindow` sets the default and replaces the per-model map with its own; otherwise its per-model entries merge in. Choose `byModel[key]` when present, else default; `"auto"` or nothing → `window_size`; result `min(value, window_size)`. `branch` reads at most 200 bytes of `HEAD` and `.git` files.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_statusbar -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add statusbar.py tests/test_statusbar.py
git commit -m "statusbar: auto-compact ceiling and branch"
```

### Task 3: Rows, fitting and the program

**Files:**
- Modify: `statusbar.py`
- Modify: `tests/test_statusbar.py`

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces: `Segment` (text with colours, priority: 0 never drops, higher drops first; group number); `rows(data: dict, env: dict, now: float, files: list[dict], branch_name: str | None) -> list[list[Segment]]`; `fit(segments: list[Segment], width: int) -> str` (joins with `  │  ` between groups and one space inside a group, dropping the highest-priority segment until `cells(result) <= width`); `plain(text: str) -> str` (SGR sequences removed, each Nerd Font icon replaced by one space); `render(data: dict, env: dict, now: float) -> str` (reads the settings files and branch itself, returns two lines joined by `\n`); `main(argv: list[str]) -> int`; `DEMO: dict` sample data (Opus, `Doofess/claude-setup`, branch `main`, PR 12, effort high, 112,000 input tokens of a 300k window, 5h 23% resetting in 2h10m, 7d 41% resetting in 3d4h, cost 1.23, +156 −23).
- Priorities, row 1: PR 3, repo 2, effort 1 (its own segment, text `· high`), branch 0, model 0. Row 2: lines 6, cost 5, 7-day reset 4, 5-hour reset 3, 7-day meter 2, 5-hour meter 1, context 0.
- Segment grouping for separators: row 1 groups `[repo, branch, PR]` and `[model, effort]`; row 2 groups `[context]`, `[5h meter, 5h reset]`, `[7d meter, 7d reset]`, `[cost, lines]`. A group whose segments all dropped vanishes with its separator. `Segment` carries its group: `Segment = tuple[str, int, int]` (text, priority, group).

- [ ] **Step 1: Write the failing tests**

```python
class RowsTest(unittest.TestCase):
    NOW = 1_700_000_000

    def demo_rows(self, **changes):
        data = json.loads(json.dumps(statusbar.DEMO))
        for k, v in changes.items():
            data[k] = v
        return statusbar.rows(data, {}, self.NOW, [{"autoCompactWindow": 300_000}], "main")

    def test_row_one_places_and_colours(self):
        r1 = statusbar.plain(statusbar.fit(self.demo_rows()[0], 120))
        self.assertEqual(r1, " Doofess/claude-setup  main  #12  │   Opus · high")

    def test_row_two_meters(self):
        r2 = statusbar.plain(statusbar.fit(self.demo_rows()[1], 120))
        self.assertEqual(r2, " ████░░░░ 42%  112k/267k  │   ███░░ 23% →2h10m  │   ████░ 41% →3d4h  │  $1.23 +156 −23")

    def test_narrow_window_keeps_context_and_model(self):
        r1, r2 = (statusbar.plain(statusbar.fit(r, 56)) for r in self.demo_rows())
        self.assertLessEqual(len(r1), 56)
        self.assertLessEqual(len(r2), 56)
        self.assertIn("Opus", r1)
        self.assertIn("main", r1)
        self.assertNotIn("#12", r1)
        self.assertIn("42%", r2)
        self.assertNotIn("+156", r2)

    def test_absent_data(self):
        r1, r2 = self.demo_rows(rate_limits={}, pr=None, effort=None, cost=None, context_window={"total_input_tokens": 0, "context_window_size": 300_000})
        self.assertEqual(statusbar.plain(statusbar.fit(r1, 120)), " Doofess/claude-setup  main  │   Opus")
        self.assertEqual(statusbar.plain(statusbar.fit(r2, 120)), " ░░░░░░░░ 0%  0/267k")

    def test_colours_come_from_the_sixteen(self):
        text = "\n".join(statusbar.fit(r, 120) for r in self.demo_rows())
        self.assertEqual(set(re.findall(r"\x1b\[(\d+)m", text)) - {"0", "1", "31", "32", "33", "90"}, set())


class ProgramTest(unittest.TestCase):
    def run_bar(self, stdin, columns="120"):
        env = dict(os.environ, COLUMNS=columns)
        p = subprocess.run([sys.executable, "-I", "-S", os.path.join(ROOT, "statusbar.py")], input=stdin, capture_output=True, text=True, encoding="utf-8", env=env)
        return p.returncode, p.stdout

    def test_demo_prints_two_rows(self):
        code, out = self.run_bar(json.dumps(statusbar.DEMO))
        self.assertEqual(code, 0)
        self.assertEqual(len(out.rstrip("\n").split("\n")), 2)
        self.assertIn("42%", out)

    def test_bad_stdin_prints_an_error_row(self):
        code, out = self.run_bar("not json")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("statusbar:"), out)

    def test_demo_flag(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "statusbar.py"), "--demo"], capture_output=True, text=True, encoding="utf-8")
        self.assertIn("267k", p.stdout)
```

`plain(text: str) -> str` strips SGR sequences and replaces each Nerd Font icon with one space, so the expected strings above are checkable without the font (icons in the Spec are `\uf09b`, `\ue0a0`, `\uf407`, `\uf2db`, `\uf1c0`, `\uf017`, `\uf073`). The leading space in each expected row is that replaced icon.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_statusbar -v`
Expected: FAIL with `AttributeError: module 'statusbar' has no attribute 'rows'`

- [ ] **Step 3: Implement `rows`, `fit`, `plain`, `render`, `main` and `DEMO` in `statusbar.py`**

`main`: `--demo` prints `render(DEMO, os.environ, time.time())` with stdout reconfigured to UTF-8; otherwise reads all of stdin, `json.loads`, `render`, prints; any exception → `print("statusbar:", error)` and `return 0`. `render` finds `project_dir = workspace.project_dir or cwd`, reads the settings files (a missing or invalid file is `{}`), calls `branch(workspace.current_dir)`, uses `COLUMNS` (default 120) minus `MARGIN = 4`. Guard `sys.stdout.reconfigure(encoding="utf-8")` for Windows. `if __name__ == "__main__": sys.exit(main(sys.argv[1:]))`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s tests -v 2>&1 | tail -3`
Expected: `OK`

- [ ] **Step 5: Look at it**

Run: `python statusbar.py --demo` in Windows Terminal at full width, then with `COLUMNS=70` set. Expected: two rows, icons visible as glyphs, meters green/green/green, nothing cut mid-segment.

- [ ] **Step 6: Commit**

```bash
git add statusbar.py tests/test_statusbar.py
git commit -m "statusbar: rows, width fitting and the program"
```

### Task 4: Settings, installer and README

**Files:**
- Modify: `settings.json` (add the `statusLine` key)
- Modify: `install.ps1` (header list, step 1 backup list at line 343, step 2 copy at lines 349–360, a new verify step before `MCP health` at line 505)
- Modify: `README.md` (table row, Daily habits)

**Interfaces:**
- Consumes: `statusbar.py --demo` and the stdin contract from Task 3.
- Produces: `settings.json` entry `"statusLine": {"type": "command", "command": "python -I -S ~/.claude/statusbar.py", "refreshInterval": 60}`; installer function `Test-StatusBar([string]$command, [string]$sample) -> pscustomobject{Ok, Output}` that runs `$command` through `bash -lc` with the sample JSON on stdin and `COLUMNS=120`, exactly as Claude Code does on Windows with Git Bash.

- [ ] **Step 1: Add the `statusLine` key to `settings.json`**

Place it after `env`. Forward slashes and `~` only (the docs: backslashes are eaten by Git Bash).

- [ ] **Step 2: Installer changes**

1. Header: add `statusbar.py` to the list of copied files; add a line for the verify step.
2. Step 1 backup list: add `statusbar.py`.
3. Step 2: `Copy-Item (Join-Path $repo 'statusbar.py') $claudeDir -Force`; step text `Copying CLAUDE.md, statusbar.py, skills/, agents/`.
4. New step `Write-Step 'Status bar check'` before `MCP health`:
   - `$py = & python -c "import sys;print(sys.version_info[:2]>=(3,10))" 2>&1`; unless it prints `True`, `$failures += "python is not Python 3.10+ (the Windows Store alias?): $py"` and skip the rest.
   - Read `statusLine.command` from the installed `$settingsPath` (not the repo copy: the check proves what the machine will run).
   - `$sample` = the JSON of `python statusbar.py --demo-json` … no: keep one source of truth, so `Test-StatusBar` pipes the output of `python -I -S $repo/statusbar.py --demo-json` (add that flag in `statusbar.py`: prints `json.dumps(DEMO)`) into the installed command.
   - Fail unless the output has exactly 2 lines and contains `Opus`, `main`, `42%`, `$1.23`; on success `Write-Host` both lines indented by four spaces so the user sees the bar.
5. `Test-StatusBar`: `$env:COLUMNS = '120'`; `$out = $sample | & bash -lc $command 2>&1`; restore `COLUMNS`; return `[pscustomobject]@{ Ok = ($LASTEXITCODE -eq 0); Output = ($out -join "`n") }`.

- [ ] **Step 3: Add `--demo-json` to `statusbar.py` with a test**

```python
    def test_demo_json_round_trips(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "statusbar.py"), "--demo-json"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(json.loads(p.stdout), statusbar.DEMO)
```

Run: `python -m unittest discover -s tests 2>&1 | tail -1` → `OK`

- [ ] **Step 4: README**

Table row for `statusbar.py` → `~/.claude/statusbar.py`: one sentence per row of the bar, the 33k headroom, and that the installer runs the installed command with sample data and prints the result. Daily habits: `/clear` when the context meter nears 100%.

- [ ] **Step 5: Run the installer and verify**

Run: `pwsh -NoProfile -File C:\dev\claude-setup\install.ps1 -SkipPlugins 2>&1 | Select-String 'Status bar|DONE' -Context 0,2`
Expected: the `Status bar check` step followed by the two demo rows, then `DONE: all checks passed`.

Then: `Get-Content ~/.claude/settings.json | ConvertFrom-Json | Select-Object -Expand statusLine` → the command above with `refreshInterval` 60; `Test-Path ~/.claude/statusbar.py` → True. Run `install.ps1 -SkipPlugins` a second time: same output.

Negative check: temporarily set `statusLine.command` in `~/.claude/settings.json` to `python -I -S ~/.claude/missing.py`, run the installer, expect `DONE WITH FAILURES` naming the status bar; then run it again normally and expect it fixed (the merge restores the command).

- [ ] **Step 6: Commit**

```bash
git add settings.json install.ps1 README.md statusbar.py tests/test_statusbar.py
git commit -m "statusbar: install, verify on every machine, README"
```

### Task 5: Live check and PR

- [ ] **Step 1:** Restart Claude Code in `C:\dev\claude-setup` and compare the real bar with `--demo`: icons, two rows, the context meter moving after a reply. Fix anything that differs and add a test for it.
- [ ] **Step 2:** `gh pr create` from branch `statusbar` with the attribution footer; merge; `git checkout main; git pull`.
- [ ] **Step 3:** Laptop: `git pull; .\install.ps1`; the `Status bar check` step must print the same two rows as here.
