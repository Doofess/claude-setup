import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import statusbar  # noqa: E402


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
        # Solid blocks throughout: the filled part in the level colour, the unfilled part in a darker shade of it.
        fill, track = statusbar.level_colours(42)
        self.assertEqual(statusbar.meter(42, 8), statusbar.sgr(fill, "███") + statusbar.sgr(track, "█████"))
        for pct in (0, 42, 100):
            self.assertEqual(statusbar.plain(statusbar.meter(pct, 5)), "█████")
        self.assertEqual(statusbar.meter(0, 5), statusbar.sgr(statusbar.level_colours(0)[1], "█████"))

    def test_four_levels(self):
        # green below 50, yellow from 50, orange from 70, red from 90
        self.assertEqual(statusbar.level_colours(49), statusbar.LEVELS["green"])
        self.assertEqual(statusbar.level_colours(50), statusbar.LEVELS["yellow"])
        self.assertEqual(statusbar.level_colours(70), statusbar.LEVELS["orange"])
        self.assertEqual(statusbar.level_colours(90), statusbar.LEVELS["red"])
        self.assertEqual(len({v for v in statusbar.LEVELS.values()}), 4)

    def test_cells_ignores_colour_codes(self):
        self.assertEqual(statusbar.cells(statusbar.sgr(statusbar.BOLD, "Fable") + " · high"), 12)


class SpanTest(unittest.TestCase):
    # The overflow file carries each dropped piece as spans the mod can draw: text, a colour name or hex, bold.
    def test_spans_split_the_colour_runs(self):
        self.assertEqual(statusbar.spans("$" + statusbar.sgr(32, "1.23")), [
            {"text": "$", "colour": None, "bold": False}, {"text": "1.23", "colour": "green", "bold": False}])
        self.assertEqual(statusbar.spans(statusbar.sgr(1, statusbar.sgr(35, "Opus"))), [{"text": "Opus", "colour": "magenta", "bold": True}])
        self.assertEqual(statusbar.spans(statusbar.sgr(91, "x"))[0]["colour"], "redBright")
        self.assertEqual(statusbar.spans(statusbar.sgr("38;2;76;200;110", "x"))[0]["colour"], "#4cc86e")
        self.assertEqual(statusbar.spans(""), [])

    def test_adjacent_runs_in_one_style_merge(self):
        self.assertEqual(statusbar.spans(statusbar.sgr(32, "a") + statusbar.sgr(32, "b")), [{"text": "ab", "colour": "green", "bold": False}])


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
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

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
        # The walk stops at the temp dir, so a .git above it (a dotfiles repo in the home folder) cannot leak in.
        self.assertIsNone(statusbar.branch(self.tmp, stop_dir=self.tmp))

    def test_walk_stops_at_stop_dir(self):
        self.write("repo/.git/HEAD", "ref: refs/heads/main\n")
        os.makedirs(os.path.join(self.tmp, "repo/src"))
        self.assertIsNone(statusbar.branch(os.path.join(self.tmp, "repo/src"), stop_dir=os.path.join(self.tmp, "repo/src")))


class RowTest(unittest.TestCase):
    NOW = 1_700_000_000
    MARKERS = {  # what to look for in the plain row, in the order the pieces should disappear when the terminal narrows
        "cost": "$1.23", "7d reset": "→3d4h", "5h reset": "→2h10m", "PR": "#12", "repo": "Doofess",
        "effort": "high", "7d meter": "41%", "5h meter": "23%",
    }

    def demo_row(self, icons=True, **changes):
        data = json.loads(json.dumps(statusbar.DEMO))
        for k, v in changes.items():
            data[k] = v
        return statusbar.segments(data, {}, self.NOW, [{"autoCompactWindow": 300_000}], "main", icons=icons)

    def test_one_row_places_everything(self):
        row = statusbar.plain(statusbar.fit(self.demo_row(), 200))
        # Each icon takes a cell and a space (plain() shows the icon as a space): the non-Mono Nerd Font
        # variants draw glyphs wider than one cell, and without the space they overlap the text.
        self.assertEqual(row, "  Doofess/claude-setup    main    #12 │   Opus · high │   ████████ 42%  112k/267k │   ████████ 23%  →2h10m │   ████████ 41%  →3d4h │ $1.23")

    def test_labels_instead_of_icons(self):
        # --labels: dim words for fonts without the Nerd Font glyphs; the rest of the line is the same.
        row = statusbar.plain(statusbar.fit(self.demo_row(icons=False), 200))
        self.assertEqual(row, "Doofess/claude-setup  main  #12 │ Opus · high │ ctx ████████ 42%  112k/267k │ 5h ████████ 23%  →2h10m │ 7d ████████ 41%  →3d4h │ $1.23")

    def test_refills_leftover_space_with_smaller_pieces(self):
        # At 106 cells the repo (24 cells with its join) cannot fit, but the PR number and both reset times can,
        # so they come back after the repo goes: the line uses the width rather than leaving a gap.
        row = statusbar.plain(statusbar.fit(self.demo_row(), 106))
        self.assertLessEqual(len(row), 106)
        self.assertNotIn("Doofess", row)
        self.assertNotIn("$1.23", row)
        for marker in ("#12", "→2h10m", "→3d4h", "high"):
            self.assertIn(marker, row)

    def test_layout_lists_the_dropped_pieces_in_display_order(self):
        line, dropped = statusbar.layout(self.demo_row(), 106)
        self.assertEqual(line, statusbar.fit(self.demo_row(), 106))
        self.assertEqual([statusbar.plain(t).strip() for t, _, _ in dropped], ["Doofess/claude-setup", "$1.23"])
        self.assertEqual(statusbar.layout(self.demo_row(), 200)[1], [])

    def test_overflow_record(self):
        _, dropped = statusbar.layout(self.demo_row(), 106)
        record = statusbar.overflow_record(dropped, 110, self.NOW)
        self.assertEqual(record["columns"], 110)
        self.assertEqual(record["written_at"], self.NOW)
        self.assertEqual(len(record["pieces"]), 2)
        self.assertEqual(record["pieces"][1], [{"text": "$1.23", "colour": "green", "bold": False}])

    def test_lines_changed_are_not_shown(self):
        self.assertNotIn("+156", statusbar.plain(statusbar.fit(self.demo_row(), 200)))

    def test_pieces_drop_by_importance(self):
        gone_at = {}
        for width in range(200, 10, -1):
            row = statusbar.plain(statusbar.fit(self.demo_row(), width))
            for name, marker in self.MARKERS.items():
                if marker not in row:
                    gone_at.setdefault(name, width)
            for marker in ("main", "Opus", "42%", "112k/267k"):
                self.assertIn(marker, row, f"{marker} dropped at width {width}")
        self.assertEqual(list(gone_at), list(self.MARKERS))
        self.assertGreater(len(set(gone_at.values())), 1)

    def test_fits_a_120_column_terminal_with_repo(self):
        row = statusbar.plain(statusbar.fit(self.demo_row(), 116))
        self.assertLessEqual(len(row), 116)
        self.assertIn("Doofess/claude-setup", row)

    def test_absent_data(self):
        row = self.demo_row(rate_limits={}, pr=None, effort=None, cost=None, context_window={"total_input_tokens": 0, "context_window_size": 300_000})
        self.assertEqual(statusbar.plain(statusbar.fit(row, 200)), "  Doofess/claude-setup    main │   Opus │   ████████ 0%  0/267k")

    def test_cost_model_and_effort_are_coloured(self):
        raw = statusbar.fit(self.demo_row(), 200)
        self.assertIn("\x1b[32m$1.23", raw)
        self.assertIn("\x1b[35mOpus", raw)
        self.assertIn("\x1b[31mhigh", raw)

    def test_repo_icon_is_violet_like_the_repo(self):
        raw = statusbar.fit(self.demo_row(), 200)
        self.assertIn(statusbar.sgr(statusbar.VIOLET, statusbar.ICONS["repo"] + " "), raw)

    def test_model_icon_takes_the_model_colour(self):
        raw = statusbar.fit(self.demo_row(), 200)
        self.assertIn(statusbar.sgr(35, statusbar.ICONS["model"] + " "), raw)
        raw = statusbar.fit(self.demo_row(model={"id": "x", "display_name": "Other"}), 200)
        self.assertIn(statusbar.sgr(statusbar.WHITE, statusbar.ICONS["model"] + " "), raw)  # unknown model: white

    def test_model_colours(self):
        for name, code in [("Opus", 35), ("claude-sonnet-5-5", 34), ("Haiku", 36), ("Fable 5.1", 93), ("Mythos", 92), ("Other", None)]:
            self.assertEqual(statusbar.model_colour(name), code, name)
        # every model its own colour, and no two of them the same hue (35 and 95 look alike in most schemes)
        codes = list(statusbar.MODEL_COLOURS.values())
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len({c % 60 for c in codes}), len(codes))

    def test_effort_colours(self):
        for level, code in [("low", 32), ("medium", 33), ("high", 31), ("xhigh", 95), ("max", 97), ("odd", None)]:
            self.assertEqual(statusbar.effort_colour(level), code, level)
        # every level its own colour, no two of them the same hue (31 and 91 look alike in most schemes)
        codes = list(statusbar.EFFORT_COLOURS.values())
        self.assertEqual(len({c % 60 for c in codes}), len(codes))

    def test_only_common_characters(self):
        # No private-use (Nerd Font) code points: the bar must read the same in Consolas or Cascadia Mono.
        row = statusbar.plain(statusbar.fit(self.demo_row(icons=False), 200))
        self.assertEqual([c for c in row if ord(c) > 0x2FFF], [])

    def test_meter_icon_and_text_take_the_level_colour(self):
        raw = statusbar.fit(self.demo_row(), 200)
        fill = statusbar.level_colours(42)[0]
        self.assertIn(statusbar.sgr(fill, statusbar.ICONS["ctx"] + " "), raw)
        self.assertIn(statusbar.sgr(fill, " 42%  112k/267k"), raw)
        raw = statusbar.fit(self.demo_row(icons=False), 200)
        self.assertIn(statusbar.sgr(fill, "ctx "), raw)

    def test_repo_is_violet_and_nothing_is_grey(self):
        raw = statusbar.fit(self.demo_row(), 200)
        self.assertIn(f"\x1b[{statusbar.VIOLET}mDoofess/claude-setup", raw)  # Claude Code's own highlight colour
        self.assertNotIn("\x1b[90m", raw)
        self.assertNotIn("\x1b[2m", raw)

    def test_everything_visible_has_an_explicit_colour(self):
        # The terminal's default foreground is a light grey in most schemes, so the chrome (icons, branch, PR,
        # separators, reset times) is sent as exact white rather than left to the default.
        for icons in (True, False):
            for span in statusbar.spans(statusbar.fit(self.demo_row(icons=icons), 200)):
                if span["text"].strip():
                    self.assertIsNotNone(span["colour"], repr(span["text"]))
        raw = statusbar.fit(self.demo_row(), 200)
        self.assertIn(statusbar.sgr(statusbar.WHITE, "main"), raw)
        self.assertIn(statusbar.sgr(statusbar.WHITE, " │ "), raw)
        self.assertIn(statusbar.sgr(statusbar.WHITE, "→2h10m"), raw)

    def test_colours_are_the_sixteen_or_the_named_ones(self):
        # The terminal's 16, plus the repo's violet (Claude Code's exact theme colour) and the meter levels (24-bit).
        text = statusbar.fit(self.demo_row(), 200)
        allowed = {"0", "1", statusbar.VIOLET, statusbar.WHITE} | {str(c) for c in range(30, 38)} | {str(c) for c in range(90, 98)}
        allowed |= {code for pair in statusbar.LEVELS.values() for code in pair}
        self.assertEqual(set(re.findall(r"\x1b\[([0-9;]+)m", text)) - allowed, set())


class ProgramTest(unittest.TestCase):
    def run_bar(self, stdin, columns="120"):
        # The window is pinned so the rows read the same whatever this machine's settings say.
        env = dict(os.environ, COLUMNS=columns, CLAUDE_CODE_AUTO_COMPACT_WINDOW="300000")
        p = subprocess.run([sys.executable, "-I", "-S", os.path.join(ROOT, "statusbar.py")], input=stdin, capture_output=True, text=True, encoding="utf-8", env=env)
        return p.returncode, p.stdout

    def test_demo_prints_one_row(self):
        code, out = self.run_bar(json.dumps(statusbar.DEMO))
        self.assertEqual(code, 0)
        self.assertEqual(len(out.rstrip("\n").split("\n")), 1)
        self.assertIn("42%", out)
        self.assertIn("267k", out)

    def test_columns_60_keeps_context_and_model(self):
        # Review Focus 3: the real program, COLUMNS parsing and MARGIN included, at a 60-column terminal.
        code, out = self.run_bar(json.dumps(statusbar.DEMO), columns="60")
        self.assertEqual(code, 0)
        row = statusbar.plain(out.rstrip("\n"))
        self.assertNotIn("\n", row)
        self.assertLessEqual(len(row), 56)
        self.assertIn("Opus", row)
        self.assertIn("main", row)
        self.assertIn("42%", row)

    def run_bar_at_home(self, data, home, columns="60"):
        env = dict(os.environ, COLUMNS=columns, CLAUDE_CODE_AUTO_COMPACT_WINDOW="300000", HOME=home, USERPROFILE=home)
        p = subprocess.run([sys.executable, "-I", "-S", os.path.join(ROOT, "statusbar.py")], input=json.dumps(data), capture_output=True, text=True, encoding="utf-8", env=env)
        return p.returncode, p.stdout

    def test_writes_the_dropped_pieces_for_the_session(self):
        # The mod draws these on Claude Code's own hint line, so they go to a file named by the session.
        home = tempfile.mkdtemp()
        try:
            code, out = self.run_bar_at_home(dict(statusbar.DEMO, session_id="abc-123"), home)
            self.assertEqual(code, 0)
            self.assertEqual(len(out.rstrip("\n").split("\n")), 1)
            with open(os.path.join(home, ".claude", "statusbar-overflow", "abc-123.json"), encoding="utf-8") as f:
                record = json.load(f)
            self.assertEqual(record["columns"], 60)
            texts = ["".join(span["text"] for span in piece) for piece in record["pieces"]]
            self.assertIn("$1.23", texts)
            self.assertNotIn("Opus", "".join(texts))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_no_session_id_writes_nothing(self):
        home = tempfile.mkdtemp()
        try:
            code, _ = self.run_bar_at_home(statusbar.DEMO, home)
            self.assertEqual(code, 0)
            self.assertFalse(os.path.exists(os.path.join(home, ".claude")))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_old_overflow_files_are_pruned(self):
        folder = tempfile.mkdtemp()
        try:
            now = time.time()
            for name, age in (("old.json", 90_000), ("new.json", 100)):
                path = os.path.join(folder, name)
                open(path, "w").close()
                os.utime(path, (now - age, now - age))
            statusbar.prune_overflow(folder, now)
            self.assertEqual(sorted(os.listdir(folder)), ["new.json"])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_bad_stdin_prints_an_error_row(self):
        code, out = self.run_bar("not json")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("statusbar:"), out)

    def test_demo_labels_flag(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "statusbar.py"), "--demo", "--labels"], capture_output=True, text=True, encoding="utf-8")
        self.assertIn("ctx", p.stdout)
        self.assertEqual([c for c in p.stdout if ord(c) > 0x2FFF], [])

    def test_demo_flag(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "statusbar.py"), "--demo"], capture_output=True, text=True, encoding="utf-8")
        self.assertIn("267k", p.stdout)

    def test_demo_ignores_the_machines_window(self):
        env = dict(os.environ, CLAUDE_CODE_AUTO_COMPACT_WINDOW="200000")
        p = subprocess.run([sys.executable, os.path.join(ROOT, "statusbar.py"), "--demo"], capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertIn("267k", p.stdout)

    def test_demo_json_resets_count_from_now(self):
        # The installer feeds this JSON to the real command at the real time, so the resets must lie ahead of now.
        before = time.time()
        p = subprocess.run([sys.executable, os.path.join(ROOT, "statusbar.py"), "--demo-json"], capture_output=True, text=True, encoding="utf-8")
        sample = json.loads(p.stdout)
        limits = sample.pop("rate_limits")
        expected = dict(statusbar.DEMO)
        expected.pop("rate_limits")
        self.assertEqual(sample, expected)
        self.assertAlmostEqual(limits["five_hour"]["resets_at"] - before, 2 * 3600 + 10 * 60, delta=30)
        self.assertAlmostEqual(limits["seven_day"]["resets_at"] - before, 3 * 86400 + 4 * 3600, delta=30)
        self.assertEqual(limits["five_hour"]["used_percentage"], 23)
        self.assertEqual(limits["seven_day"]["used_percentage"], 41)
