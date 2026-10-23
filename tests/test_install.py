import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class TerminalProfileTest(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(read("terminal", "profile.json"))

    def test_font_is_a_nerd_font(self):
        self.assertTrue(self.profile["font"]["face"].endswith("Nerd Font"))

    def test_cell_height(self):
        self.assertEqual(self.profile["font"]["cellHeight"], "1.25")

    def test_colour_scheme(self):
        self.assertEqual(self.profile["colorScheme"], "Campbell")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.settings = json.loads(read("settings.json"))

    def test_theme_is_pinned(self):
        self.assertEqual(self.settings["theme"], "dark")

    def test_mod_folder_is_loaded(self):
        dirs = self.settings["env"]["CLAUDE_CODE_PLUGIN_DIRS"]
        self.assertTrue(dirs.endswith("mods/session-cards"))
        self.assertTrue(dirs.startswith("<repo>/"))


class InstallerTest(unittest.TestCase):
    def test_installer_names_the_checks_and_switches(self):
        text = read("install.ps1")
        for needle in ("Same experience", "-KeepFont", "-KeepScheme", "Session cards mod", "Terminal scheme"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
