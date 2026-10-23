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
        self.assertEqual(statusbar.meter(42, 8), "\x1b[32m███░░░░░\x1b[0m")
        self.assertTrue(statusbar.meter(75, 5).startswith("\x1b[33m"))
        self.assertTrue(statusbar.meter(90, 5).startswith("\x1b[31m"))
        self.assertEqual(statusbar.meter(100, 5).count("█"), 5)
        self.assertEqual(statusbar.meter(0, 5).count("░"), 5)

    def test_cells_ignores_colour_codes(self):
        self.assertEqual(statusbar.cells(statusbar.sgr(statusbar.BOLD, "Fable") + " · high"), 12)


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

    def demo_row(self, **changes):
        data = json.loads(json.dumps(statusbar.DEMO))
        for k, v in changes.items():
            data[k] = v
        return statusbar.segments(data, {}, self.NOW, [{"autoCompactWindow": 300_000}], "main")

    def test_one_row_places_everything(self):
        row = statusbar.plain(statusbar.fit(self.demo_row(), 200))
        # Dim text labels, no icon glyphs: every monospace font has █ ░ │ → and ·, so the bar reads the same in any font.
        self.assertEqual(row, "Doofess/claude-setup  main  #12 │ Opus · high │ ctx ███░░░░░ 42%  112k/267k │ 5h █░░░░ 23%  →2h10m │ 7d ██░░░ 41%  →3d4h │ $1.23")

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
        self.assertEqual(statusbar.plain(statusbar.fit(row, 200)), "Doofess/claude-setup  main │ Opus │ ctx ░░░░░░░░ 0%  0/267k")

    def test_cost_model_and_effort_are_coloured(self):
        raw = statusbar.fit(self.demo_row(), 200)
        self.assertIn("[32m$1.23", raw)
        self.assertIn("[35mOpus", raw)
        self.assertIn("[31mhigh", raw)

    def test_model_colours(self):
        for name, code in [("Opus", 35), ("claude-sonnet-5-5", 34), ("Haiku", 36), ("Fable 5.1", 95), ("Mythos", 95), ("Other", None)]:
            self.assertEqual(statusbar.model_colour(name), code, name)

    def test_effort_colours(self):
        for level, code in [("low", 32), ("medium", 33), ("high", 31), ("xhigh", 91), ("max", 91), ("odd", None)]:
            self.assertEqual(statusbar.effort_colour(level), code, level)

    def test_only_common_characters(self):
        # No private-use (Nerd Font) code points: the bar must read the same in Consolas or Cascadia Mono.
        row = statusbar.plain(statusbar.fit(self.demo_row(), 200))
        self.assertEqual([c for c in row if ord(c) > 0x2FFF], [])

    def test_colours_come_from_the_sixteen(self):
        text = statusbar.fit(self.demo_row(), 200)
        allowed = {"0", "1"} | {str(c) for c in range(30, 38)} | {str(c) for c in range(90, 98)}
        self.assertEqual(set(re.findall(r"\[(\d+)m", text)) - allowed, set())


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

    def test_bad_stdin_prints_an_error_row(self):
        code, out = self.run_bar("not json")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("statusbar:"), out)

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
