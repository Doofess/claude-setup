import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class TerminalProfileTest(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(read("terminal", "profile.json"))

    def test_font_is_a_nerd_font(self):
        self.assertTrue(self.profile["font"]["face"].split(",")[0].strip().endswith("Nerd Font"))

    def test_segoe_ui_symbol_is_the_glyph_fallback(self):
        self.assertEqual(self.profile["font"]["face"], "JetBrainsMono Nerd Font")

    def test_cell_height(self):
        self.assertEqual(self.profile["font"]["cellHeight"], "1.25")

    def test_colour_scheme(self):
        self.assertEqual(self.profile["colorScheme"], "Campbell")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.settings = json.loads(read("settings.json"))

    def test_theme_is_pinned(self):
        self.assertEqual(self.settings["theme"], "custom:clear")

    def test_clear_theme_is_dark_with_a_clear_prompt_background(self):
        # Claude Code 2.1.310 draws the sticky prompt line (the last prompt, pinned at the top once it scrolls away) on
        # userMessageBackground; no theme value is transparent, so it is Campbell's own background.
        theme = json.loads(read("themes", "clear.json"))
        self.assertEqual(theme, {"name": "Clear", "base": "dark", "overrides": {"userMessageBackground": "#0c0c0c"}})
        self.assertEqual(json.loads(read("terminal", "profile.json"))["colorScheme"], "Campbell")

    def test_mod_folder_is_loaded(self):
        dirs = self.settings["env"]["CLAUDE_CODE_PLUGIN_DIRS"]
        self.assertTrue(dirs.endswith("mods/session-cards"))
        self.assertTrue(dirs.startswith("<repo>/"))


class InstallerTest(unittest.TestCase):
    def test_status_bar_check_finds_each_piece_in_the_demo_bar(self):
        # The installer runs the demo sample through the bar and looks for these strings in the raw, coloured output.
        line = next(l for l in read("install.ps1").splitlines() if l.strip().startswith("$missing = @("))
        needles = re.findall(r"'([^']*)'", line)
        self.assertIn("Opus", needles)
        bar = os.path.join(ROOT, "statusbar.py")
        sample = subprocess.run(["python", "-I", "-S", bar, "--demo-json"], capture_output=True, text=True, encoding="utf-8").stdout
        env = {**os.environ, "COLUMNS": "160", "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "300000"}  # as Test-StatusBar sets them
        out = subprocess.run(["python", "-I", "-S", bar], input=sample, capture_output=True, text=True, encoding="utf-8", env=env).stdout
        for needle in needles:
            self.assertIn(needle, out)

    def test_installer_names_the_checks_and_switches(self):
        text = read("install.ps1")
        for needle in ("Same experience", "-KeepFont", "-KeepScheme", "Session cards mod", "Terminal scheme"):
            self.assertIn(needle, text)

    def test_installer_copies_the_themes_and_checks_the_file(self):
        text = read("install.ps1")
        self.assertIn(r"Copy-Item (Join-Path $repo 'themes\*.json') $themesDir -Force", text)
        row = [l for l in text.splitlines() if l.startswith("Add-SameRow 'Claude Code theme'")]
        self.assertEqual(len(row), 1)
        self.assertIn("$themeFileOk", row[0])

    def test_installer_copies_the_global_rules_from_global_folder(self):
        text = read("install.ps1")
        self.assertIn(r"Join-Path $repo 'global\CLAUDE.md'", text)
        self.assertNotIn("Join-Path $repo 'CLAUDE.md'", text)
        self.assertTrue(read("global", "CLAUDE.md").startswith("# Global rules"))
        self.assertFalse(read("CLAUDE.md").startswith("# Global rules"))

    def test_font_rows_require_no_font_on_the_default_profile(self):
        rows = [l for l in read("install.ps1").splitlines()
                if l.startswith(("Add-SameRow 'Terminal font face'", "Add-SameRow 'Terminal cellHeight'"))]
        self.assertEqual(len(rows), 2)
        for row, prop in zip(rows, ("ProfileFace", "ProfileCellHeight")):
            self.assertIn("none on the default profile", row)
            self.assertIn("-not $wtLook.%s" % prop, row)


FIXTURES = os.path.join(ROOT, "tests", "fixtures", "terminal")
PWSH = shutil.which("pwsh")
FACE, HEIGHT, SCHEME = "JetBrainsMono Nerd Font", "1.25", "Campbell"


def strip_jsonc(text):
    """Drop // and /* */ comments that sit outside strings. Strict: a trailing comma stays and json.loads rejects it."""
    out, i, n = [], 0, len(text)

    def skip_comment(j):
        if text.startswith("//", j):
            while j < n and text[j] != "\n":
                j += 1
            return j
        return text.index("*/", j + 2) + 2

    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith(("//", "/*"), i):
            i = skip_comment(i)
        else:
            out.append(c)
            i += 1
    return "".join(out)


def load_jsonc(path):
    with open(path, encoding="utf-8") as f:
        return json.loads(strip_jsonc(f.read()))


def installer_helpers():
    """PowerShell source of the Windows Terminal JSONC helpers in install.ps1 (the whole section, from its header up
    to Set-TerminalStartDir, since Find-JsoncKey and friends call the scanners above them) and Write-Utf8NoBom."""
    source = read("install.ps1").replace("\r\n", "\n")
    lines = source.split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("# ---- Windows Terminal settings.json ----"))
    end = next(i for i, l in enumerate(lines) if l.startswith("function Set-TerminalStartDir"))
    while lines[end - 1].startswith("#") or not lines[end - 1].strip():
        end -= 1
    block = "\n".join(lines[start:end])
    for name in ("Find-JsoncKey", "Set-TerminalFont", "Set-TerminalScheme", "Read-TerminalLook"):
        assert "function %s" % name in block, name
    m = re.search(r"^function Write-Utf8NoBom.*?^}", source, re.DOTALL | re.MULTILINE)
    assert m is not None, "Write-Utf8NoBom"
    writer = m.group(0)
    return writer + "\n" + block


LISTFACE = "JetBrainsMono Nerd Font, Segoe UI Symbol"


def font_helpers():
    source = read("install.ps1").replace("\r\n", "\n")
    out = []
    for name in ("Get-NerdFontFiles", "Get-PrimaryFace", "Get-FaceFiles"):
        m = re.search(r"^function %s.*?^}" % name, source, re.DOTALL | re.MULTILINE)
        assert m is not None, name
        out.append(m.group(0))
    return "\n".join(out)


@unittest.skipUnless(PWSH, "pwsh is not on PATH")
class FontCheckTest(unittest.TestCase):
    def run_check(self, face, files):
        with tempfile.TemporaryDirectory() as tmp:
            local = os.path.join(tmp, "local", "Microsoft", "Windows", "Fonts")
            win = os.path.join(tmp, "win", "Fonts")
            os.makedirs(local)
            os.makedirs(win)
            for name in files:
                open(os.path.join(local, name), "w").close()
            script = os.path.join(tmp, "check.ps1")
            with open(script, "w", encoding="utf-8") as f:
                f.write("param([string]$Face)\n$env:LOCALAPPDATA = '%s'\n$env:WINDIR = '%s'\n%s\n"
                        "@(Get-FaceFiles $Face).Count\n" % (os.path.join(tmp, "local"), os.path.join(tmp, "win"), font_helpers()))
            r = subprocess.run([str(PWSH), "-NoProfile", "-NonInteractive", "-File", script, face],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return int(r.stdout.strip().splitlines()[-1])

    def test_installed_check_uses_the_first_face(self):
        self.assertEqual(self.run_check(LISTFACE, ["JetBrainsMonoNerdFont-Regular.ttf"]), 1)

    def test_installed_check_still_fails_without_the_first_face(self):
        self.assertEqual(self.run_check(LISTFACE, ["FiraCodeNerdFont-Regular.ttf"]), 0)

    def test_installer_installs_and_compares_with_the_right_face(self):
        text = read("install.ps1")
        self.assertIn("Get-PrimaryFace $nerdFontFace", text)
        self.assertIn("$wtLook.Face -eq $nerdFontFace", text)


DRIVER = """param([string]$Mode, [string]$Path, [string]$Face, [string]$Height, [string]$Scheme)
$ErrorActionPreference = 'Stop'
{HELPERS}
if ($Mode -eq 'apply') {
  $f = Set-TerminalFont $Path $Face $Height
  $s = Set-TerminalScheme $Path $Scheme
  [pscustomobject]@{ Font = $f; Scheme = $s } | ConvertTo-Json -Depth 5 -Compress
} elseif ($Mode -eq 'font') {
  Set-TerminalFont $Path $Face $Height | ConvertTo-Json -Depth 5 -Compress
} elseif ($Mode -eq 'look') {
  Read-TerminalLook $Path | ConvertTo-Json -Depth 5 -Compress
}
"""


@unittest.skipUnless(PWSH, "pwsh is not on PATH")
class TerminalHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.script = os.path.join(cls.tmp, "driver.ps1")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(DRIVER.replace("{HELPERS}", installer_helpers()))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fixture_copy(self, name):
        dest = os.path.join(self.tmp, "%s-%s.json" % (self._testMethodName, name))
        shutil.copyfile(os.path.join(FIXTURES, name + ".json"), dest)
        return dest

    def run_driver(self, mode, path):
        r = subprocess.run([str(PWSH), "-NoProfile", "-NonInteractive", "-File", self.script, mode, path, FACE, HEIGHT, SCHEME],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def digest(self, path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def text(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def default_profile(self, doc):
        return next(p for p in doc["profiles"]["list"] if p["guid"] == doc["defaultProfile"])

    def check_fixture(self, name):
        path = self.fixture_copy(name)
        self.run_driver("apply", path)
        doc = load_jsonc(path)
        defaults = doc["profiles"]["defaults"]
        self.assertEqual(defaults["font"]["face"], FACE)
        self.assertEqual(defaults["font"]["cellHeight"], HEIGHT)
        self.assertEqual(defaults["colorScheme"], SCHEME)
        profile = self.default_profile(doc)
        self.assertNotIn("colorScheme", profile)
        self.assertNotIn("face", profile.get("font", {}))
        self.assertNotIn("cellHeight", profile.get("font", {}))
        before = self.digest(path)
        again = self.run_driver("apply", path)
        self.assertEqual(again["Font"]["Result"], "already set")
        self.assertEqual(again["Scheme"]["Result"], "already set")
        self.assertEqual(self.digest(path), before, "a second run changed the file")
        return path

    def test_a_comma_list_face_is_written_verbatim(self):
        path = self.fixture_copy("A_realistic")
        r = subprocess.run([str(PWSH), "-NoProfile", "-NonInteractive", "-File", self.script, "font", path, LISTFACE, HEIGHT, SCHEME],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(load_jsonc(path)["profiles"]["defaults"]["font"]["face"], LISTFACE)
        r = subprocess.run([str(PWSH), "-NoProfile", "-NonInteractive", "-File", self.script, "font", path, LISTFACE, HEIGHT, SCHEME],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(json.loads(r.stdout)["Result"], "already set")

    def test_a_realistic(self):
        path = self.check_fixture("A_realistic")
        self.assertIn("// font for everything", self.text(path))
        self.assertEqual(load_jsonc(path)["profiles"]["defaults"]["font"]["size"], 11)

    def test_b_empty_defaults(self):
        self.check_fixture("B_empty_defaults")

    def test_c_comment_only_defaults(self):
        path = self.check_fixture("C_comment_only_defaults")
        self.assertIn("// Put settings here", self.text(path))

    def test_d_last_key_after_comment(self):
        path = self.check_fixture("D_last_key_after_comment")
        self.assertIn("// mine", self.text(path))

    def test_e_profile_font_override(self):
        path = self.check_fixture("E_profile_font_override")
        self.assertNotIn("font", self.default_profile(load_jsonc(path)))

    def test_f_scheme_object_on_profile_last(self):
        self.check_fixture("F_scheme_object_on_profile_last")

    def test_g_comment_with_quote(self):
        text = self.text(self.check_fixture("G_comment_with_quote"))
        self.assertIn('the user\'s "favourite" setup', text)
        self.assertIn('block "comment" with { brace', text)

    def test_font_step_clears_the_default_profile_font(self):
        path = self.fixture_copy("E_profile_font_override")
        before = self.run_driver("look", path)
        self.assertEqual(before["Face"], FACE)
        self.assertEqual(before["ProfileFace"], "Cascadia Mono")
        r = self.run_driver("font", path)
        self.assertEqual(r["Result"], "set")
        self.assertTrue(any("Cascadia Mono" in c and "default profile" in c for c in r["Changed"]), r["Changed"])
        after = self.run_driver("look", path)
        self.assertEqual(after["Face"], FACE)
        self.assertEqual(after["CellHeight"], HEIGHT)
        self.assertIsNone(after["ProfileFace"])
        self.assertIsNone(after["ProfileCellHeight"])

    def test_font_step_keeps_other_font_keys_on_the_default_profile(self):
        path = self.fixture_copy("E_profile_font_override")
        text = self.text(path).replace(
            '"font": { "face": "Cascadia Mono" }',
            '"font": { "size": 12, // mine\n "face": "Cascadia Mono", "cellHeight": "1.0" }')
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.run_driver("font", path)
        doc = load_jsonc(path)
        self.assertEqual(self.default_profile(doc)["font"], {"size": 12})
        self.assertIn("// mine", self.text(path))
        self.assertEqual(doc["profiles"]["defaults"]["font"]["face"], FACE)

    def test_look_reports_the_scheme_on_the_default_profile(self):
        look = self.run_driver("look", self.fixture_copy("A_realistic"))
        self.assertEqual(look["ProfileScheme"], "Tango Dark")
        self.assertIsNone(look["ProfileFace"])


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(PWSH, "pwsh is not on PATH")
class UserAdvisorTest(unittest.TestCase):
    """The advisor is per project (skills/advisor-switch); the installer takes it out of the user settings."""

    def run_remove(self, settings):
        source = read("install.ps1").replace("\r\n", "\n")
        m = re.search(r"^function Remove-UserAdvisor.*?^}", source, re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(m, "Remove-UserAdvisor")
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "remove.ps1")
            with open(script, "w", encoding="utf-8") as f:
                f.write("param([string]$Json)\n%s\n$c = $Json | ConvertFrom-Json\n$done = Remove-UserAdvisor $c\n"
                        "[pscustomobject]@{ Settings = $c; Done = @($done) } | ConvertTo-Json -Depth 10 -Compress\n" % m.group(0))
            r = subprocess.run([str(PWSH), "-NoProfile", "-NonInteractive", "-File", script, json.dumps(settings)],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return json.loads(r.stdout)

    def test_user_advisor_is_removed(self):
        out = self.run_remove({"advisorModel": "opus", "theme": "custom:clear"})
        self.assertEqual(out["Settings"], {"theme": "custom:clear"})
        self.assertEqual(out["Done"], ["advisorModel opus"])

    def test_nothing_to_remove(self):
        out = self.run_remove({"theme": "custom:clear"})
        self.assertEqual(out["Settings"], {"theme": "custom:clear"})
        self.assertEqual(out["Done"], [])

    def test_the_template_has_no_advisor(self):
        self.assertNotIn("advisorModel", json.loads(read("settings.json")))
        self.assertIn("Remove-UserAdvisor $current", read("install.ps1"))
