import json
import os
import re
import subprocess
import sys
import tempfile
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
