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
    # Claude Code compacts 33k below the window: 20k kept for the reply, 13k buffer.
    def test_env_wins(self):
        self.assertEqual(statusline.compact_window({"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "150000"},
                                                   {"autoCompactWindow": 200000}, 1_000_000), 117_000)

    def test_settings_when_no_env(self):
        self.assertEqual(statusline.compact_window({}, {"autoCompactWindow": 200000}, 1_000_000), 167_000)

    def test_model_window_when_neither(self):
        self.assertEqual(statusline.compact_window({}, {}, 1_000_000), 967_000)

    def test_never_above_the_model_window(self):
        self.assertEqual(statusline.compact_window({}, {"autoCompactWindow": 500000}, 200_000), 167_000)

    def test_ignores_junk(self):
        self.assertEqual(statusline.compact_window({"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "x"},
                                                   {"autoCompactWindow": "y"}, 1_000_000), 967_000)
        self.assertIsNone(statusline.compact_window({}, {}, None))

    def test_out_of_range_setting_is_ignored(self):
        self.assertEqual(statusline.compact_window({}, {"autoCompactWindow": 50_000}, 1_000_000), 967_000)

    def test_per_model_beats_top_level_in_one_file(self):
        s = {"autoCompactWindow": 300000, "modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 200000}}}
        self.assertEqual(statusline.compact_window({}, s, 1_000_000, "claude-opus-5-5"), 167_000)
        self.assertEqual(statusline.compact_window({}, s, 1_000_000, "claude-sonnet-5-5"), 267_000)

    def test_any_spelling_of_the_model_matches(self):
        s = {"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 200000}}}
        for model in ("claude-opus-5-5[1m]", "claude-opus-5-5-20260101", "us.anthropic.claude-opus-5-5-v1:0"):
            self.assertEqual(statusline.compact_window({}, s, 1_000_000, model), 167_000, model)
        s = {"modelSettings": {"claude-opus-5-5[1m]": {"autoCompactWindow": 300000}}}
        self.assertEqual(statusline.compact_window({}, s, 1_000_000, "claude-opus-5-5"), 267_000)

    def test_higher_layer_wins(self):
        project = {"autoCompactWindow": 400000}
        user = {"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 200000}}}
        self.assertEqual(statusline.compact_window({}, [project, user], 1_000_000, "claude-opus-5-5"), 367_000)
        self.assertEqual(statusline.compact_window({}, [{}, user], 1_000_000, "claude-opus-5-5"), 167_000)

    def test_env_beats_per_model(self):
        s = {"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 200000}}}
        env = {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "150000"}
        self.assertEqual(statusline.compact_window(env, s, 1_000_000, "claude-opus-5-5"), 117_000)

    def test_auto_is_the_model_window(self):
        s = {"autoCompactWindow": 200000, "modelSettings": {"claude-opus-5-5": {"autoCompactWindow": "auto"}}}
        self.assertEqual(statusline.compact_window({}, s, 1_000_000, "claude-opus-5-5"), 967_000)

    def test_pct_override_compacts_earlier(self):
        env = {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "50"}
        self.assertEqual(statusline.compact_window(env, {"autoCompactWindow": 200000}, 1_000_000), 90_000)
        env = {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "100"}  # never later than the usual point
        self.assertEqual(statusline.compact_window(env, {"autoCompactWindow": 200000}, 1_000_000), 167_000)

    def test_disabled_means_no_compaction_point(self):
        for key in ("DISABLE_AUTO_COMPACT", "DISABLE_COMPACT"):
            self.assertIsNone(statusline.compact_window({key: "1"}, {"autoCompactWindow": 200000}, 1_000_000))


def xterm_rgb(n):
    """The RGB an xterm-256 index stands for (the 6x6x6 cube or the grey ramp)."""
    if 16 <= n <= 231:
        levels = (0, 95, 135, 175, 215, 255)
        n -= 16
        return levels[n // 36], levels[n // 6 % 6], levels[n % 6]
    if 232 <= n <= 255:
        v = 8 + (n - 232) * 10
        return v, v, v
    raise ValueError(f"not a cube or grey index: {n}")


def palette_of(rgb):
    """'grey', or 'warm' for the orange, brown, yellow and red palettes (hues 345-65 degrees),
    else None: the only palettes the repo uses."""
    import colorsys
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    if s < 0.12 or v < 0.08:
        return "grey"
    return "warm" if h * 360 <= 65 or h * 360 >= 345 else None


class PaletteTest(unittest.TestCase):
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def assert_palette(self, rgb, where):
        self.assertIsNotNone(palette_of(rgb), f"{where} {rgb} is outside the orange, brown, yellow, red and grey palettes")

    def test_statusline_themes(self):
        for name, theme in statusline.THEMES.items():
            for key, value in theme.items():
                if key == "COST":
                    continue  # the $ cost stays green on purpose
                values = value.values() if isinstance(value, dict) else value if isinstance(value, tuple) else (value,)
                for n in values:
                    self.assert_palette(xterm_rgb(n), f"THEMES[{name}][{key}] {n}")

    def test_each_model_family_has_its_own_colour(self):
        for name, theme in statusline.THEMES.items():
            colours = list(theme["MODEL_COLORS"].values())
            self.assertEqual(len(colours), len(set(colours)), name)

    def test_readable_theme(self):
        import json
        import re
        with open(os.path.join(self.ROOT, "themes", "readable.json"), encoding="utf-8") as f:
            overrides = json.load(f)["overrides"]
        for key, value in overrides.items():
            m = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
            self.assertIsNotNone(m, f"{key}: {value} is not #rrggbb")
            self.assert_palette(tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)), key)

    def test_cost_is_green(self):
        import colorsys
        for name, theme in statusline.THEMES.items():
            h, s, _ = colorsys.rgb_to_hsv(*(c / 255 for c in xterm_rgb(theme["COST"])))
            self.assertTrue(90 <= h * 360 <= 150 and s > 0.3, name)

    def test_diffs_are_dark_tints(self):
        # Light text is drawn on the diff backgrounds: removed lines dark red, added lines dark grey.
        # On the dark-ansi base Claude Code rounds them to xterm-256 (a dark tint like #4E2A2A came
        # out grey), so each must be an exact cube or grey-ramp colour.
        import colorsys
        import json
        with open(os.path.join(self.ROOT, "themes", "readable.json"), encoding="utf-8") as f:
            overrides = json.load(f)["overrides"]
        for side, kind in (("Added", "grey"), ("Removed", "warm")):
            for suffix in ("", "Dimmed", "Word"):
                key = f"diff{side}{suffix}"
                rgb = tuple(int(overrides[key][i:i + 2], 16) for i in (1, 3, 5))
                self.assertEqual(palette_of(rgb), kind, key)
                self.assertIn(rgb, [xterm_rgb(n) for n in range(16, 256)], key)
                self.assertLess(colorsys.rgb_to_hsv(*(c / 255 for c in rgb))[2], 0.55, key)

    def test_theme_names_every_token(self):
        # On the dark-ansi base a token left out takes a terminal colour, so every one is set.
        import json
        with open(os.path.join(self.ROOT, "themes", "readable.json"), encoding="utf-8") as f:
            theme = json.load(f)
        self.assertEqual(theme["base"], "dark-ansi")
        self.assertEqual(len(theme["overrides"]), 72)

    def test_terminal_scheme(self):
        # dark-ansi draws syntax, diff markers and inline code in the terminal's 16 colours.
        import json
        with open(os.path.join(self.ROOT, "terminal", "readable-scheme.json"), encoding="utf-8") as f:
            scheme = json.load(f)
        names = ["black", "red", "green", "yellow", "blue", "purple", "cyan", "white"]
        self.assertTrue(set(names + ["bright" + n.title() for n in names]) <= set(scheme))
        for key, value in scheme.items():
            if key != "name":
                self.assert_palette(tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)), f"scheme {key}")
        self.assertEqual(scheme["brightRed"], "#FF8787")   # − markers: the light red
        self.assertEqual(scheme["brightGreen"], "#E4E4E4")  # + markers: very light grey
        self.assertEqual(scheme["white"], "#FFFFFF")  # removed lines are drawn faint in white: half is #808080

    def test_readable_session_tool_colours(self):
        import re
        with open(os.path.join(self.ROOT, "mods", "readable-session", "hooks", "register.tsx"), encoding="utf-8") as f:
            text = f.read()
        colours = re.findall(r"#([0-9A-Fa-f]{6})\b", text)
        self.assertGreaterEqual(len(colours), 10)  # five tool kinds, dark and light
        for h in colours:
            self.assert_palette(tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)), f"register.tsx #{h}")

    def test_installer_colours(self):
        import re
        with open(os.path.join(self.ROOT, "install.ps1"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("-ForegroundColor", text)  # the 16 console colours have no orange
        indices = [int(n) for n in re.findall(r"Write-Color\s+(?:'[^']*'|\"[^\"]*\")\s+(\d+)", text)]
        self.assertGreaterEqual(len(indices), 9)  # Write-Step and every coloured line
        for n in indices:
            self.assert_palette(xterm_rgb(n), f"install.ps1 Write-Color {n}")


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

    def full(self, width):
        data = {"model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"}, "context_window": ContextTest.CW,
                "cost": {"total_cost_usd": 1.5, "total_lines_added": 1200, "total_lines_removed": 30},
                "repo": {"host": "github.com", "owner": "Doofess", "name": "claude-setup"}}
        extras = {"compact": 200_000, "proj": "claude-setup", "git": ("main", [])}
        return self.strip(statusline.format_statusline(data, None, NOW, False, extras, width))

    def test_spare_room_is_spread_to_the_exact_width(self):
        for w in (120, 150, 200):
            line = self.full(w)
            self.assertEqual(statusline.visible_width(line), w, line)
            self.assertTrue(line.endswith("+1k −30"), line)

    def test_no_width_keeps_single_spaces(self):
        self.assertIn(" │ Doofess/claude-setup │ ", self.full(None))

    def test_lines_changed_and_repo(self):
        line = self.full(None)
        self.assertIn("+1k −30", line)
        self.assertIn("Doofess/claude-setup", line)
        self.assertEqual(statusline.fmt_lines({}), "")
        self.assertEqual(statusline.repo_tag({"repo": {"host": "gitlab.com", "owner": "a", "name": "b"}}), "")

    def test_repo_then_lines_go_first(self):
        wide = self.full(None)
        lost = []
        for w in range(len(wide), 40, -1):
            line = self.full(w)
            for name, text in (("repo", "Doofess/"), ("lines", "+1k")):
                if text not in line and name not in lost:
                    lost.append(name)
                    self.assertIn("$1.50", line)
                    self.assertIn("main", line)
        self.assertEqual(lost, ["repo", "lines"])

    def test_demo_has_three_lines_with_the_three_paces(self):
        lines = [self.strip(x) for x in statusline.demo_lines(NOW, 200)]
        self.assertEqual(len(lines), 3)
        self.assertIn("on pace", lines[0])
        self.assertIn("▲ ahead", lines[1])
        self.assertIn("▲▲", lines[2])
        self.assertTrue(all("/200k" in x and "skills" not in x for x in lines))


if __name__ == "__main__":
    unittest.main()
