import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
import winreg

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
    def test_plugin_commands_are_user_scope(self):
        # Without a scope, `claude plugin enable` run in a repo whose .claude/settings.json turns a plugin off
        # writes `true` into that project file instead of the user settings.
        lines = [l for l in read("install.ps1").splitlines() if re.search(r"& claude plugin (install|enable|disable|update) ", l)]
        self.assertEqual(len(lines), 4)
        for line in lines:
            self.assertIn("--scope user", line)

    def test_json_files_are_read_as_utf8(self):
        # Windows PowerShell 5.1's Get-Content reads a BOM-less file in the ANSI code page, so on a PC whose code
        # page is 1252 (not 65001, as on this one) a non-ASCII value in settings.json is garbled and written back.
        text = read("install.ps1")
        self.assertNotRegex(text, r"Get-Content [^\n|]*-Raw")
        self.assertIn("[IO.File]::ReadAllText($path, [Text.Encoding]::UTF8)", text)

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
        for needle in ("Same experience", "-KeepFont", "-KeepScheme", "Session cards mod", "Terminal scheme", "-Check", "-Json"):
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

    NEW_ROWS = ("Terminal profile overrides", "Terminal default profile", "Git Bash profile", "PowerShell 7",
                "Windows PowerShell policy", "PowerShell profiles", "VS Code terminal")

    def test_same_experience_has_the_shell_rows(self):
        lines = [l for l in read("install.ps1").splitlines() if l.startswith("Add-SameRow ")]
        for name in self.NEW_ROWS:
            self.assertTrue(any(l.startswith("Add-SameRow '%s' " % name) for l in lines), name)

    def test_same_experience_rows_never_write(self):
        text = read("install.ps1")
        tail = text[text.index("Write-Step 'Same experience'"):]
        for fn in ("Set-WindowsPowerShellPolicy", "Set-TerminalDefaultProfile", "Add-GitBashProfile", "Set-VsCodeTerminal"):
            calls = [l for l in tail.splitlines() if re.search(r"(?<![\w-])%s(?![\w-])" % fn, l)]
            for l in calls:
                self.assertIn("-DryRun", l, l)


FIXTURES = os.path.join(ROOT, "tests", "fixtures", "terminal")
PWSH = shutil.which("pwsh")
POWERSHELL = shutil.which("powershell")
ENGINE_SPECS = [
    ("pwsh", PWSH, ["-NoProfile", "-NonInteractive", "-File"]),
    ("powershell", POWERSHELL, ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]),
]
# One entry per engine found: (name, command prefix that ends before the script path).
ENGINES = [(n, [str(path)] + args) for n, path, args in ENGINE_SPECS if path]


def engine_env(name):
    """Child environment for an engine. Windows PowerShell 5.1 loses module autoload when a parent pwsh's PSModulePath leaks in."""
    env = dict(os.environ)
    if name == "powershell":
        env.pop("PSModulePath", None)
    return env


def run_engine(engine, script, *args):
    name, cmd = engine
    return subprocess.run(cmd + [script] + list(args), capture_output=True, text=True, encoding="utf-8", env=engine_env(name))


def per_engine(base, module_globals):
    """One TestCase subclass of the mixin `base` per known engine, named <Base>_<engine>; skipped when the engine is missing."""
    for name, path, args in ENGINE_SPECS:
        engine = (name, [str(path)] + args) if path else None
        cls = type("%s_%s" % (base.__name__.replace("Base", "Test"), name), (base, unittest.TestCase), {"engine": engine})
        module_globals[cls.__name__] = unittest.skipUnless(path, "%s is not on PATH" % name)(cls)
FACE, HEIGHT, SCHEME = "JetBrainsMono Nerd Font", "1.25", "Campbell"
VSCODE_JSON = os.path.join(ROOT, "terminal", "vscode.json")
VSCODE_FIXTURES = os.path.join(ROOT, "tests", "fixtures", "vscode")


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


def load_jsonc_lenient(path):
    """load_jsonc that also accepts the trailing commas VS Code's settings may carry (comments are dropped first)."""
    with open(path, encoding="utf-8") as f:
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", strip_jsonc(f.read())))


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
    for name in ("Find-JsoncKey", "Set-TerminalFont", "Set-TerminalScheme", "Read-TerminalLook", "Set-TerminalDefaultProfile", "Add-GitBashProfile", "Set-VsCodeTerminal", "Set-JsoncRaw"):
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


class FontCheckBase:
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
            r = run_engine(self.engine, script, face)
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


DRIVER = """param([string]$Mode, [string]$Path, [string]$Face, [string]$Height, [string]$Scheme, [string]$Guid, [string]$Bash, [string]$GitRoot, [string]$Frag, [string]$Flags, [string]$WantPath)
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
} elseif ($Mode -eq 'defaultprofile') {
  Set-TerminalDefaultProfile $Path $Guid ($Flags -match 'ps7') -DryRun:($Flags -match 'dry') | ConvertTo-Json -Compress
} elseif ($Mode -eq 'gitbash') {
  Add-GitBashProfile $Path $Bash $GitRoot ([string[]]@($Frag)) -DryRun:($Flags -match 'dry') | ConvertTo-Json -Compress
} elseif ($Mode -eq 'vscode') {
  $wantDoc = [IO.File]::ReadAllText($WantPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
  Set-VsCodeTerminal $Path $wantDoc ($Flags -match 'inst') ($Flags -match 'keepfont') ($Flags -match 'keepscheme') -DryRun:($Flags -match 'dry') | ConvertTo-Json -Compress
}
"""


per_engine(FontCheckBase, globals())


class TerminalHelpersBase:
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

    def run_driver(self, mode, path, guid="x", bash="x", root="x", frag="x", flags="x"):
        r = run_engine(self.engine, self.script, mode, path, FACE, HEIGHT, SCHEME, guid, bash, root, frag, flags, VSCODE_JSON)
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
        r = run_engine(self.engine, self.script, "font", path, LISTFACE, HEIGHT, SCHEME, "x", "x", "x", "x", "x")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(load_jsonc(path)["profiles"]["defaults"]["font"]["face"], LISTFACE)
        r = run_engine(self.engine, self.script, "font", path, LISTFACE, HEIGHT, SCHEME, "x", "x", "x", "x", "x")
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

    def no_overrides(self, doc):
        for p in doc["profiles"]["list"]:
            self.assertNotIn("face", p.get("font", {}), p["name"])
            self.assertNotIn("cellHeight", p.get("font", {}), p["name"])
            self.assertNotIn("colorScheme", p, p["name"])

    def test_h_overrides_on_other_profiles(self):
        path = self.fixture_copy("H_overrides_on_other_profiles")
        r = self.run_driver("apply", path)
        self.assertEqual(r["Font"]["Result"], "set")
        self.assertTrue(any("Ubuntu Mono" in c and "Ubuntu" in c for c in r["Font"]["Changed"]), r["Font"]["Changed"])
        self.assertTrue(any("Vintage" in c and "Command Prompt" in c for c in r["Scheme"]["Changed"]), r["Scheme"]["Changed"])
        doc = load_jsonc(path)
        self.no_overrides(doc)
        by_name = {p["name"]: p for p in doc["profiles"]["list"]}
        self.assertEqual(by_name["Ubuntu"]["font"], {"size": 13})
        self.assertNotIn("font", by_name["PowerShell"])
        self.assertIn("// classic prompt", self.text(path))
        self.assertEqual(doc["profiles"]["defaults"]["font"]["face"], FACE)
        before = self.digest(path)
        again = self.run_driver("apply", path)
        self.assertEqual(again["Font"]["Result"], "already set")
        self.assertEqual(again["Scheme"]["Result"], "already set")
        self.assertEqual(self.digest(path), before, "a second run changed the file")

    def test_look_lists_overrides(self):
        look = self.run_driver("look", self.fixture_copy("H_overrides_on_other_profiles"))
        self.assertEqual(sorted(look["Overrides"]), sorted([
            "PowerShell: face Cascadia Code", "Command Prompt: colorScheme Vintage", "Ubuntu: face Ubuntu Mono"]))
        self.assertEqual(look["ProfileFace"], "Cascadia Code")
        applied = self.fixture_copy("H_overrides_on_other_profiles")
        self.run_driver("apply", applied)
        self.assertEqual(list(self.run_driver("look", applied)["Overrides"] or []), [])

    PS7 = "{574e775e-4f2a-5b96-ac1e-a2962a402336}"
    WINPS = "{61c54bbd-c2c6-5271-96e7-009a87ff44bf}"

    def test_default_profile_set_to_ps7(self):
        path = self.fixture_copy("A_realistic")
        self.assertEqual(self.run_driver("defaultprofile", path, guid=self.WINPS), "set")
        self.assertEqual(load_jsonc(path)["defaultProfile"], self.WINPS)
        self.assertEqual(self.run_driver("defaultprofile", path, guid=self.PS7), "set")
        self.assertEqual(load_jsonc(path)["defaultProfile"], self.PS7)
        self.assertIn("// This file was initially generated", self.text(path))
        before = self.digest(path)
        self.assertEqual(self.run_driver("defaultprofile", path, guid=self.PS7), "already set")
        self.assertEqual(self.digest(path), before)

    def test_default_profile_missing_only_without_ps7(self):
        path = self.fixture_copy("I_no_git_bash")
        before = self.digest(path)
        self.assertEqual(self.run_driver("defaultprofile", path, guid=self.PS7), "missing")
        self.assertEqual(self.digest(path), before)
        self.assertEqual(self.run_driver("defaultprofile", path, guid=self.PS7, flags="ps7"), "set")
        self.assertEqual(load_jsonc(path)["defaultProfile"], self.PS7)

    def test_default_profile_dry_run_writes_nothing(self):
        path = self.fixture_copy("A_realistic")
        before = self.digest(path)
        self.assertEqual(self.run_driver("defaultprofile", path, guid=self.WINPS, flags="dry"), "set")
        self.assertEqual(self.digest(path), before)
        self.assertEqual(self.run_driver("defaultprofile", path, guid="{nope}", flags="dry"), "missing")
        self.assertEqual(self.run_driver("defaultprofile", path, guid=self.PS7, flags="dry"), "already set")

    BASH = "C:\\Program Files\\Git\\bin\\bash.exe"
    GITROOT = "C:\\Program Files\\Git"
    GITBASH = "{2ece5bfe-50ed-5f3a-ab87-5cd4baafed2b}"

    def add_git_bash(self, path, flags="x"):
        frag = os.path.join(self.tmp, "no-fragments")   # a folder that does not exist: this PC's fragments don't matter
        return self.run_driver("gitbash", path, bash=self.BASH, root=self.GITROOT, frag=frag, flags=flags)

    def git_bash_profiles(self, doc):
        return [p for p in doc["profiles"]["list"] if p["guid"] == self.GITBASH]

    def rewrite(self, path, text):
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def test_git_bash_added_once(self):
        path = self.fixture_copy("I_no_git_bash")
        self.assertEqual(self.add_git_bash(path), "added")
        doc = load_jsonc(path)
        added = self.git_bash_profiles(doc)
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["name"], "Git Bash")
        self.assertEqual(added[0]["commandline"], '"C:\\Program Files\\Git\\bin\\bash.exe" -i -l')
        self.assertEqual(added[0]["icon"], "C:\\Program Files\\Git\\mingw64\\share\\git\\git-for-windows.ico")
        self.assertIs(added[0]["hidden"], False)
        self.assertEqual([p["name"] for p in doc["profiles"]["list"]], ["Windows PowerShell", "Command Prompt", "Git Bash"])
        self.assertIn("// last profile", self.text(path))
        self.assertIn(r'"commandline": "\"C:\\Program Files\\Git\\bin\\bash.exe\" -i -l"', self.text(path))
        before = self.digest(path)
        self.assertEqual(self.add_git_bash(path), "present")
        self.assertEqual(self.digest(path), before)

    def test_git_bash_after_a_trailing_comma(self):
        path = self.fixture_copy("I_no_git_bash")
        self.rewrite(path, self.text(path).replace("} // last profile", "}, // last profile"))
        self.assertEqual(self.add_git_bash(path), "added")
        self.assertEqual(len(self.git_bash_profiles(load_jsonc(path))), 1)
        self.assertIn("// last profile", self.text(path))

    def test_git_bash_in_an_empty_list(self):
        path = self.fixture_copy("I_no_git_bash")
        self.rewrite(path, re.sub(r'"list": \[.*?\n        \]', '"list": [ // none yet\n        ]', self.text(path), flags=re.DOTALL))
        self.assertEqual(load_jsonc(path)["profiles"]["list"], [])
        self.assertEqual(self.add_git_bash(path), "added")
        self.assertEqual([p["name"] for p in load_jsonc(path)["profiles"]["list"]], ["Git Bash"])
        self.assertIn("// none yet", self.text(path))

    def test_git_bash_present_by_name_or_fragment(self):
        path = self.fixture_copy("I_no_git_bash")
        self.rewrite(path, self.text(path).replace('"Command Prompt"', '"Git Bash"'))
        before = self.digest(path)
        self.assertEqual(self.add_git_bash(path), "present")
        self.assertEqual(self.digest(path), before)
        other = self.fixture_copy("I_no_git_bash")
        frag = os.path.join(self.tmp, "fragments-%s" % self._testMethodName)
        os.makedirs(os.path.join(frag, "Git"))
        r = self.run_driver("gitbash", other, bash=self.BASH, root=self.GITROOT, frag=frag)
        self.assertEqual(r, "present")
        self.assertEqual(self.digest(other), self.digest(os.path.join(FIXTURES, "I_no_git_bash.json")))

    def test_git_bash_dry_run_writes_nothing(self):
        path = self.fixture_copy("I_no_git_bash")
        before = self.digest(path)
        self.assertEqual(self.add_git_bash(path, flags="dry"), "added")
        self.assertEqual(self.digest(path), before)

    def test_git_bash_none_without_a_list(self):
        path = self.fixture_copy("I_no_git_bash")
        self.rewrite(path, '{ "profiles": { "defaults": {} } }')
        self.assertEqual(self.add_git_bash(path), "none")

    # ---- VS Code's terminal ----
    def vscode_copy(self, name):
        dest = os.path.join(self.tmp, "%s-%s.json" % (self._testMethodName, name))
        shutil.copyfile(os.path.join(VSCODE_FIXTURES, name + ".json"), dest)
        return dest

    def vscode_run(self, path, flags="inst"):
        return self.run_driver("vscode", path, flags=flags)

    def vscode_want(self):
        return load_jsonc(VSCODE_JSON)

    def test_vscode_keys_set_and_others_kept(self):
        path = self.vscode_copy("A_has_other_keys")
        r = self.vscode_run(path)
        self.assertEqual(r["Result"], "set")
        doc = load_jsonc_lenient(path)
        want = self.vscode_want()
        for key, value in want.items():
            if key != "workbench.colorCustomizations":
                self.assertEqual(doc[key], value, key)
        colours = doc["workbench.colorCustomizations"]
        for key, value in want["workbench.colorCustomizations"].items():
            self.assertEqual(colours[key], value, key)
        self.assertEqual(doc["editor.fontSize"], 14)
        self.assertEqual(colours["editor.background"], "#1E1E1E")
        self.assertIn("// VS Code user settings", self.text(path))
        self.assertIn("// my size", self.text(path))
        self.assertIn("/* my colours */", self.text(path))
        before = self.digest(path)
        self.assertEqual(self.vscode_run(path), {"Result": "already set", "Changed": []})
        self.assertEqual(self.digest(path), before, "a second run changed the file")

    def test_vscode_file_created(self):
        path = os.path.join(self.tmp, self._testMethodName, "User", "settings.json")   # neither the file nor its folder exists
        self.assertEqual(self.vscode_run(path)["Result"], "set")
        doc = load_jsonc(path)
        want = self.vscode_want()
        self.assertEqual(doc["terminal.integrated.fontFamily"], want["terminal.integrated.fontFamily"])
        self.assertEqual(doc["workbench.colorCustomizations"], want["workbench.colorCustomizations"])
        stand_in = self.vscode_copy("B_missing")   # a file holding {}: the same text comes out
        self.vscode_run(stand_in)
        self.assertEqual(self.text(path).strip(), self.text(stand_in).strip())

    def test_vscode_not_installed_writes_nothing(self):
        path = os.path.join(self.tmp, self._testMethodName, "User", "settings.json")
        self.assertEqual(self.vscode_run(path, flags="x"), {"Result": "no VS Code", "Changed": []})
        self.assertFalse(os.path.exists(os.path.dirname(path)))

    def test_numbers_stay_numbers(self):
        path = self.vscode_copy("B_missing")
        self.vscode_run(path)
        ratio = load_jsonc(path)["terminal.integrated.minimumContrastRatio"]
        self.assertEqual(ratio, 1)
        self.assertIs(type(ratio), int)
        self.assertRegex(self.text(path), r'"terminal\.integrated\.minimumContrastRatio": 1[ ,}]')

    def test_vscode_equal_values_are_already_set(self):
        path = self.vscode_copy("B_missing")
        self.vscode_run(path)
        text = self.text(path)
        text = re.sub(r'"#[0-9A-F]{6}"', lambda m: m.group(0).lower(), text)   # hex colours differ only by case
        text = text.replace('"terminal.integrated.minimumContrastRatio": 1', '"terminal.integrated.minimumContrastRatio"  :\n    1.0')
        self.rewrite(path, text)
        before = self.digest(path)
        self.assertEqual(self.vscode_run(path), {"Result": "already set", "Changed": []})
        self.assertEqual(self.digest(path), before)

    def test_vscode_wrong_type_is_replaced(self):
        path = self.vscode_copy("B_missing")
        self.rewrite(path, '{ "terminal.integrated.minimumContrastRatio": "1", "workbench.colorCustomizations": [] }')
        r = self.vscode_run(path)
        self.assertEqual(r["Result"], "set")
        self.assertTrue(any("workbench.colorCustomizations" in c and "not an object" in c for c in r["Changed"]), r["Changed"])
        doc = load_jsonc(path)
        self.assertEqual(doc["terminal.integrated.minimumContrastRatio"], 1)
        self.assertEqual(doc["workbench.colorCustomizations"], self.vscode_want()["workbench.colorCustomizations"])

    def test_vscode_dry_run_writes_nothing(self):
        path = self.vscode_copy("A_has_other_keys")
        before = self.digest(path)
        r = self.vscode_run(path, flags="inst dry")
        self.assertEqual(r["Result"], "set")
        self.assertTrue(r["Changed"])
        self.assertEqual(self.digest(path), before)
        absent = os.path.join(self.tmp, self._testMethodName, "User", "settings.json")
        self.assertEqual(self.vscode_run(absent, flags="inst dry")["Result"], "set")
        self.assertFalse(os.path.exists(os.path.dirname(absent)))
        self.assertEqual(self.vscode_run(absent, flags="dry")["Result"], "no VS Code")

    def test_vscode_keep_font_skips_the_font(self):
        path = self.vscode_copy("A_has_other_keys")
        r = self.vscode_run(path, flags="inst keepfont")
        doc = load_jsonc_lenient(path)
        self.assertEqual(doc["terminal.integrated.fontFamily"], "Consolas")
        self.assertEqual(doc["terminal.integrated.minimumContrastRatio"], 1)
        self.assertEqual(doc["workbench.colorCustomizations"]["terminal.ansiRed"], "#C50F1F")
        self.assertFalse(any("fontFamily" in c for c in r["Changed"]), r["Changed"])

    def test_vscode_keep_scheme_skips_the_colours(self):
        path = self.vscode_copy("A_has_other_keys")
        self.vscode_run(path, flags="inst keepscheme")
        doc = load_jsonc_lenient(path)
        self.assertEqual(doc["terminal.integrated.fontFamily"], FACE)
        self.assertEqual(doc["terminal.integrated.minimumContrastRatio"], 1)
        self.assertEqual(doc["workbench.colorCustomizations"], {"editor.background": "#1E1E1E", "terminal.ansiRed": "#ff0000"})


if __name__ == "__main__":
    unittest.main()


per_engine(TerminalHelpersBase, globals())


def policy_helpers():
    source = read("install.ps1").replace("\r\n", "\n")
    out = []
    for name in ("Get-PowerShellProfiles", "Set-WindowsPowerShellPolicy"):
        m = re.search(r"^function %s.*?^}" % name, source, re.DOTALL | re.MULTILINE)
        assert m is not None, name
        out.append(m.group(0))
    return "\n".join(out)


POLICY_DRIVER = """param([string]$RegPath, [string]$Policies, [string]$Dry)
$ErrorActionPreference = 'Stop'
{HELPERS}
$p = @($Policies -split ';' | Where-Object { $_ })
if ($Dry -eq '1') { Set-WindowsPowerShellPolicy $RegPath $p -DryRun } else { Set-WindowsPowerShellPolicy $RegPath $p }
"""
POLICY_ROOT = "Software\\claude-setup-test"


class PolicyBase:
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.script = os.path.join(cls.tmp, "policy.ps1")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(POLICY_DRIVER.replace("{HELPERS}", policy_helpers()))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.key = POLICY_ROOT + "\\" + uuid.uuid4().hex
        self.addCleanup(self.drop_keys)
        # the value the function writes lives under .../target; the policy test keys are .../pin0 and .../pin1
        self.target = self.key + "\\target"
        self.pins = [self.key + "\\pin0", self.key + "\\pin1"]

    def drop_keys(self):
        subprocess.run(["reg", "delete", "HKCU\\" + self.key, "/f"], capture_output=True)
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, POLICY_ROOT)   # only succeeds when no sibling test key is left
        except OSError:
            pass

    def put(self, path, value):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
            winreg.SetValueEx(k, "ExecutionPolicy", 0, winreg.REG_SZ, value)

    def get(self, path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                return winreg.QueryValueEx(k, "ExecutionPolicy")[0]
        except FileNotFoundError:
            return None

    def run_policy(self, dry=False):
        paths = ";".join("HKCU:\\" + p for p in self.pins)
        r = run_engine(self.engine, self.script, "HKCU:\\" + self.target, paths, "1" if dry else "0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout.strip().splitlines()[-1]

    def test_policy_set_when_missing(self):
        self.assertEqual(self.run_policy(), "set")
        self.assertEqual(self.get(self.target), "RemoteSigned")
        self.assertEqual(self.run_policy(), "already set")

    def test_policy_left_when_looser(self):
        self.put(self.target, "Unrestricted")
        self.assertEqual(self.run_policy(), "already set")
        self.assertEqual(self.get(self.target), "Unrestricted")

    def test_policy_replaces_all_signed(self):
        for old in ("AllSigned", "Restricted", "Undefined"):
            self.put(self.target, old)
            self.assertEqual(self.run_policy(), "set", old)
            self.assertEqual(self.get(self.target), "RemoteSigned", old)

    def test_policy_reports_pin(self):
        for index, scope in enumerate(("MachinePolicy", "UserPolicy")):
            for strict in ("Restricted", "AllSigned"):
                self.put(self.pins[index], strict)
                self.assertEqual(self.run_policy(), "pinned by " + scope)
                self.assertIsNone(self.get(self.target))
            subprocess.run(["reg", "delete", "HKCU\\" + self.pins[index], "/f"], capture_output=True)

    def test_policy_loose_pin_is_already_set(self):
        for loose in ("RemoteSigned", "Unrestricted", "Bypass"):
            self.put(self.pins[0], loose)
            self.assertEqual(self.run_policy(), "already set", loose)
            self.assertIsNone(self.get(self.target))

    def test_policy_dry_run_writes_nothing(self):
        self.assertEqual(self.run_policy(dry=True), "set")
        self.assertIsNone(self.get(self.target))

    def test_profiles_come_from_my_documents(self):
        body = re.search(r"^function Get-PowerShellProfiles.*?^}", read("install.ps1").replace("\r\n", "\n"), re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(body)
        self.assertIn("GetFolderPath('MyDocuments')", body.group(0))
        self.assertIn("'PowerShell\\Microsoft.PowerShell_profile.ps1'", body.group(0))
        self.assertIn("'WindowsPowerShell\\Microsoft.PowerShell_profile.ps1'", body.group(0))
        self.assertNotIn("$HOME", body.group(0))


per_engine(PolicyBase, globals())


MERGE_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "settings", "current.json")


def merge_helpers():
    source = read("install.ps1").replace("\r\n", "\n")
    out = []
    for name in ("Test-IsObject", "Test-IsArray", "Merge-Json", "Merge-HookEvents", "Format-DirKey", "Merge-PluginDirs", "Merge-ClaudeSettings"):
        m = re.search(r"^function %s.*?(?:^}|\Z)" % name, source, re.DOTALL | re.MULTILINE)
        assert m is not None, name
        out.append(m.group(0))
    return "\n".join(out)


MERGE_DRIVER = """param([string]$Current, [string]$Template, [string]$Repo, [string]$Out)
$ErrorActionPreference = 'Stop'
{HELPERS}
$cur = Get-Content $Current -Raw | ConvertFrom-Json
$tpl = Get-Content $Template -Raw | ConvertFrom-Json
$merged = Merge-ClaudeSettings $cur $tpl $Repo
[IO.File]::WriteAllText($Out, ($merged | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
"""


@unittest.skipUnless(ENGINES, "no PowerShell engine on PATH")
class MergeParityTest(unittest.TestCase):
    def test_merge_is_the_same_on_both_engines(self):
        results = {}
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "merge.ps1")
            with open(script, "w", encoding="utf-8") as f:
                f.write(MERGE_DRIVER.replace("{HELPERS}", merge_helpers()))
            for engine in ENGINES:
                out = os.path.join(tmp, engine[0] + ".json")
                r = run_engine(engine, script, MERGE_FIXTURE, os.path.join(ROOT, "settings.json"), ROOT, out)
                self.assertEqual(r.returncode, 0, engine[0] + ": " + r.stdout + r.stderr)
                with open(out, encoding="utf-8") as f:
                    results[engine[0]] = json.loads(f.read())
        first = next(iter(results.values()))
        for name, doc in results.items():
            self.assertEqual(doc, first, name)
            self.assertIsInstance(doc["permissions"]["allow"], list, name)
            self.assertIn("Bash(ls:*)", doc["permissions"]["allow"], name)
            self.assertEqual(doc["env"]["MACHINE_ONLY_KEY"], "Home Office ✔", name)


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


LIVE = os.environ.get("CLAUDE_SETUP_LIVE") == "1"


def wt_and_claude_settings():
    home = os.path.expanduser("~")
    paths = [os.path.join(home, ".claude", "settings.json")]
    local = os.environ.get("LOCALAPPDATA", "")
    for pattern in ("Packages/Microsoft.WindowsTerminal*/LocalState/settings.json", "Microsoft/Windows Terminal/settings.json"):
        paths += glob.glob(os.path.join(local, pattern))
    return [p for p in paths if os.path.exists(p)]


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class CheckModeTest(unittest.TestCase):
    def run_check(self):
        return subprocess.run([PWSH, "-NoProfile", "-File", os.path.join(ROOT, "install.ps1"), "-Check", "-Json"],
                              capture_output=True, text=True, encoding="utf-8")

    @unittest.skipUnless(LIVE and PWSH, "reads the real machine: set CLAUDE_SETUP_LIVE=1")
    def test_check_changes_nothing(self):
        before = {p: sha(p) for p in wt_and_claude_settings()}
        self.run_check()
        self.assertEqual(before, {p: sha(p) for p in before})

    @unittest.skipUnless(LIVE and PWSH, "reads the real machine: set CLAUDE_SETUP_LIVE=1")
    def test_json_is_one_document(self):
        doc = json.loads(self.run_check().stdout)
        names = [r["name"] for r in doc["rows"]]
        self.assertIn("Terminal font face", names)
        self.assertIn("Python version", names)
        for r in doc["rows"]:
            self.assertIn(r["status"], ("ok", "kept", "FAIL"))

    def test_check_skips_the_install_steps(self):
        text = read("install.ps1")
        start = text.index("if (-not $Check) {")
        depth, end = 0, None
        for j in range(text.index("{", start), len(text)):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        self.assertIsNotNone(end)
        self.assertTrue(start < text.index("Write-Step 'Merging settings.json'") < end)
        self.assertGreater(text.index("Write-Step 'Same experience'"), end)


class SetupCheckStaticTest(unittest.TestCase):
    def test_skill_exists_with_name_and_references(self):
        text = read("skills", "setup-check", "SKILL.md")
        self.assertRegex(text, r"\A---\n(?:.*\n)*?name: setup-check\n(?:.*\n)*?---\n")
        for word in ("shell_matrix.py", "install.cmd", "claude-setup-state.json"):
            self.assertIn(word, text)
        self.assertLess(len(text.splitlines()), 80)

    def test_installer_records_repo_inside_the_write_block(self):
        text = read("install.ps1").replace("\r\n", "\n")
        start = text.index("if (-not $Check) {")
        end = text.index("# 4d.")
        block = text[start:end]
        self.assertRegex(block, r"(?m)^\s*Set-StateRepo\b.*\$repo")
        self.assertLess(block.index("mcp_off.py"), block.index("Set-StateRepo"))

    def test_docs(self):
        self.assertIn("/setup-check", read("README.md"))
        self.assertIn("Check a machine", read("README.md"))
        self.assertIn("- After install.ps1 or on a new PC: `/setup-check`.", read("global", "CLAUDE.md"))


STATE_DRIVER = """param([string]$State, [string]$Repo)
$ErrorActionPreference = 'Stop'
{HELPERS}
Set-StateRepo $State $Repo
"""


def state_helpers():
    source = read("install.ps1").replace("\r\n", "\n")
    out = []
    for name in ("Read-Utf8", "Write-Utf8NoBom", "Set-StateRepo"):
        m = re.search(r"^function %s.*?^}" % name, source, re.DOTALL | re.MULTILINE)
        assert m is not None, name
        out.append(m.group(0))
    return "\n".join(out)


class StateRepoBase:
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.script = os.path.join(cls.tmp, "state.ps1")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(STATE_DRIVER.replace("{HELPERS}", state_helpers()))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_sets_repo_keeps_one_element_list_and_is_idempotent(self):
        path = os.path.join(self.tmp, "state.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"claude.ai Adobe": ["C:/x"]}')
        repo = "C:\\dev\\claude-setup"
        r = run_engine(self.engine, self.script, path, repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(path, "rb") as f:
            first = f.read()
        data = json.loads(first.decode("utf-8"))
        self.assertEqual(data["claude.ai Adobe"], ["C:/x"])
        self.assertEqual(data["repo"], repo)
        self.assertFalse(first.startswith(b"\xef\xbb\xbf"))
        r = run_engine(self.engine, self.script, path, repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), first)

    def test_missing_file_is_created(self):
        path = os.path.join(self.tmp, "new.json")
        r = run_engine(self.engine, self.script, path, "C:\\r")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"repo": "C:\\r"})


per_engine(StateRepoBase, globals())
