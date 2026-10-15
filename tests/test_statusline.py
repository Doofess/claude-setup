import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import statusline  # noqa: E402

WEEK = 7 * 86400
NOW = 1_000_000_000.0


def at(elapsed_pct):
    """resets_at for a window that is elapsed_pct of the way through its week."""
    return NOW + WEEK * (1 - elapsed_pct / 100)


class PaceTest(unittest.TestCase):
    def test_on_pace_within_ten_points(self):
        for used in (40, 50, 60):
            label, level = statusline.pace(used, at(50), NOW)
            self.assertEqual(label, "on pace")
            self.assertEqual(level, "grey")

    def test_ahead_between_ten_and_twenty_five(self):
        label, level = statusline.pace(70, at(50), NOW)
        self.assertEqual((label, level), ("▲ ahead", "amber"))

    def test_far_ahead_above_twenty_five(self):
        label, level = statusline.pace(80, at(50), NOW)
        self.assertEqual((label, level), ("▲▲", "red"))

    def test_nothing_when_well_behind(self):
        self.assertIsNone(statusline.pace(20, at(50), NOW))

    def test_hidden_without_a_reset_time(self):
        self.assertIsNone(statusline.pace(50, None, NOW))

    def test_clamps_a_reset_outside_the_week(self):
        # reset more than a week away: no time has elapsed, 10% used is ahead of 0%
        self.assertEqual(statusline.pace(10, NOW + WEEK * 2, NOW)[0], "on pace")
        # reset already passed: the week is over, 100% elapsed
        self.assertIsNone(statusline.pace(20, NOW - 10, NOW))


class CompactWindowTest(unittest.TestCase):
    def test_env_wins(self):
        self.assertEqual(statusline.compact_window({"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "150000"},
                                                   {"autoCompactWindow": 200000}, 1_000_000), 150000)

    def test_settings_when_no_env(self):
        self.assertEqual(statusline.compact_window({}, {"autoCompactWindow": 200000}, 1_000_000), 200000)

    def test_model_window_when_neither(self):
        self.assertEqual(statusline.compact_window({}, {}, 1_000_000), 1_000_000)

    def test_never_above_the_model_window(self):
        self.assertEqual(statusline.compact_window({}, {"autoCompactWindow": 500000}, 200_000), 200_000)

    def test_ignores_junk(self):
        self.assertEqual(statusline.compact_window({"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "x"},
                                                   {"autoCompactWindow": "y"}, 1_000_000), 1_000_000)
        self.assertIsNone(statusline.compact_window({}, {}, None))


class ContextTest(unittest.TestCase):
    CW = {"context_window_size": 1_000_000, "used_percentage": 8,
          "current_usage": {"input_tokens": 2, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 83_998}}

    def test_percent_is_against_the_compaction_window(self):
        self.assertAlmostEqual(statusline.context_pct(self.CW, 200_000), 42.0, places=1)

    def test_percent_caps_at_100(self):
        cw = dict(self.CW, current_usage={"input_tokens": 300_000})
        self.assertEqual(statusline.context_pct(cw, 200_000), 100.0)

    def test_without_a_window_keeps_claude_codes_figure(self):
        self.assertEqual(statusline.context_pct(self.CW), 8.0)

    def test_tokens_show_used_over_the_window(self):
        self.assertEqual(statusline.context_tokens(self.CW, 200_000), "84k/200k")


class LineTest(unittest.TestCase):
    def render(self, extras=None):
        data = {"model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
                "context_window": ContextTest.CW}
        usage = statusline.merge_usage({"five_hour": {"used_percentage": 10, "resets_at": NOW + 3600},
                                        "seven_day": {"used_percentage": 80, "resets_at": at(50)}}, None, NOW)
        return statusline.format_statusline(data, usage, NOW, True, extras or {"compact": 200_000}, 200)

    def strip(self, s):
        return statusline.ANSI_RE.sub("", s)

    def test_shows_pace_and_compaction_window_no_skills(self):
        line = self.strip(self.render())
        self.assertIn("84k/200k", line)
        self.assertIn("▲▲", line)
        self.assertNotIn("skills", line)

    def test_pace_is_the_first_thing_dropped(self):
        data = {"model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"}, "context_window": ContextTest.CW}
        usage = statusline.merge_usage({"five_hour": {"used_percentage": 10, "resets_at": NOW + 3600},
                                        "seven_day": {"used_percentage": 80, "resets_at": at(50)}}, None, NOW)
        wide = self.strip(statusline.format_statusline(data, usage, NOW, True, {"compact": 200_000}, 200))
        for w in range(len(wide), 40, -1):
            line = self.strip(statusline.format_statusline(data, usage, NOW, True, {"compact": 200_000}, w))
            if "▲▲" not in line:
                self.assertIn("7d", line)
                self.assertIn("84k/200k", line)
                return
        self.fail("pace never dropped")

    def test_demo_has_three_lines_with_the_three_paces(self):
        lines = [self.strip(x) for x in statusline.demo_lines(NOW, 200)]
        self.assertEqual(len(lines), 3)
        self.assertIn("on pace", lines[0])
        self.assertIn("▲ ahead", lines[1])
        self.assertIn("▲▲", lines[2])
        self.assertTrue(all("/200k" in x and "skills" not in x for x in lines))


if __name__ == "__main__":
    unittest.main()
