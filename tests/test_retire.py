import json
import os
import re
import shutil
import tempfile
import unittest

from test_install import per_engine, read, run_engine

DRIVER = r"""
param([string]$InFile)
$ErrorActionPreference = 'Stop'
{FUNCTIONS}
$in = [IO.File]::ReadAllText($InFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
$env:FAKE_LOG = [string]$in.log
$env:FAKE_LIST = [string]$in.list
$env:FAKE_FAIL = [string]$in.fail

$fakeClaude = {
  Add-Content -LiteralPath $env:FAKE_LOG -Value ('claude ' + ($args -join ' '))
  if ($args[0] -eq 'plugin' -and $args[1] -eq 'list') { Write-Output $env:FAKE_LIST; $global:LASTEXITCODE = 0; return }
  $global:LASTEXITCODE = if ($env:FAKE_FAIL) { 1 } else { 0 }
}

$result = $null
switch ($in.mode) {
  'plugins' {
    $failed = New-Object 'System.Collections.Generic.List[string]'
    $first = @(Remove-RetiredPlugins @($in.ids) $fakeClaude $failed)
    $second = @()
    if ($in.twice) { $second = @(Remove-RetiredPlugins @($in.ids) $fakeClaude $failed) }
    $result = [pscustomobject]@{ First = $first; Second = $second; Failed = @($failed) }
  }
  'kept' {
    $failed = New-Object 'System.Collections.Generic.List[string]'
    $installed = @(Install-KeptPlugins @($in.ids) $fakeClaude $failed)
    $result = [pscustomobject]@{ Installed = $installed; Failed = @($failed) }
  }
  'kept-ids' {
    $result = [pscustomobject]@{ Ids = @(Get-KeptPlugins $in.enabledPlugins) }
  }
  'settings' {
    $settings = $in.settings
    $removed = @(Remove-RetiredSettingsPlugins $settings @($in.ids))
    $result = [pscustomobject]@{ Removed = $removed; Settings = $settings }
  }
  'skills' {
    $removed = @(Remove-RetiredSkills @($in.names) $in.dir)
    $result = [pscustomobject]@{ Removed = $removed }
  }
}
[Console]::Out.Write(($result | ConvertTo-Json -Compress -Depth 10))
"""

RETIRED = [
    "chrome-devtools-mcp", "hookify", "mcp-server-dev", "claude-code-setup", "claude-md-management", "claude-security",
    "cloudflare", "code-review", "code-simplifier", "feature-dev", "github", "ralph-loop", "shopify-ai-toolkit",
    "skill-creator", "telegram", "vercel", "pyright-lsp",
]
HOOKIFY = "hookify@claude-plugins-official"
FRONTEND = "frontend-design@claude-plugins-official"
GOOD_CSS = "good-css@good-css"
KEPT = [
    "%s@claude-plugins-official" % n
    for n in ("playwright", "context7", "frontend-design", "mattpocock-skills", "modern-web-guidance", "supabase",
              "adobe-for-creativity", "kotlin-lsp", "typescript-lsp", "rust-analyzer-lsp", "security-guidance")
] + [GOOD_CSS]


def functions_source():
    source = read("install.ps1").replace("\r\n", "\n")
    out = [re.search(r"^function Test-IsObject[^\n]*\}$", source, re.MULTILINE).group(0)]
    for name in ("Remove-RetiredPlugins", "Remove-RetiredSkills", "Remove-RetiredSettingsPlugins",
                 "Get-KeptPlugins", "Install-KeptPlugins"):
        m = re.search(r"^function %s.*?^}" % name, source, re.DOTALL | re.MULTILINE)
        assert m is not None, name
        out.append(m.group(0))
    return "\n".join(out)


def plugin_list(*entries):
    return json.dumps([{"id": i, "scope": s, "enabled": True} for i, s in entries])


class RetireBase:
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.script = os.path.join(cls.tmp, "driver.ps1")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(DRIVER.replace("{FUNCTIONS}", functions_source()))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_driver(self, **data):
        log = os.path.join(self.tmp, "calls.log")
        with open(log, "w", encoding="utf-8"):
            pass
        data.setdefault("log", log)
        path = os.path.join(self.tmp, "in.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        r = run_engine(self.engine, self.script, path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(log, encoding="utf-8") as f:
            calls = [l.strip() for l in f if l.strip()]
        return json.loads(r.stdout), calls

    def uninstalls(self, calls):
        return [c for c in calls if c.startswith("claude plugin uninstall")]

    # Plugins

    def test_uninstalls_exactly_the_retired_ids_that_are_installed(self):
        listing = plugin_list(
            (HOOKIFY, "user"),
            ("vercel@claude-plugins-official", "user"),
            ("superpowers@claude-plugins-official", "user"),
        )
        out, calls = self.run_driver(
            mode="plugins", list=listing,
            ids=[HOOKIFY, "vercel@claude-plugins-official", "telegram@claude-plugins-official"],
        )
        self.assertEqual(sorted(out["First"]), [HOOKIFY, "vercel@claude-plugins-official"])
        self.assertEqual(
            sorted(self.uninstalls(calls)),
            [
                "claude plugin uninstall %s --scope user" % HOOKIFY,
                "claude plugin uninstall vercel@claude-plugins-official --scope user",
            ],
        )
        self.assertEqual(out["Failed"], [])

    def test_a_second_run_with_none_installed_makes_no_uninstall_calls(self):
        out, calls = self.run_driver(
            mode="plugins", list=plugin_list(("superpowers@claude-plugins-official", "user")), ids=[HOOKIFY], twice=True,
        )
        self.assertEqual(out["First"], [])
        self.assertEqual(out["Second"], [])
        self.assertEqual(self.uninstalls(calls), [])

    def test_only_user_scope_entries_are_uninstalled(self):
        listing = plugin_list(("expo@claude-plugins-official", "project"), (HOOKIFY, "project"))
        out, calls = self.run_driver(mode="plugins", list=listing, ids=["expo@claude-plugins-official", HOOKIFY])
        self.assertEqual(out["First"], [])
        self.assertEqual(self.uninstalls(calls), [])

    def test_a_failed_uninstall_is_reported_not_returned(self):
        out, calls = self.run_driver(mode="plugins", list=plugin_list((HOOKIFY, "user")), ids=[HOOKIFY], fail="1")
        self.assertEqual(out["First"], [])
        self.assertEqual(out["Failed"], [HOOKIFY])

    def test_unreadable_plugin_list_does_nothing(self):
        out, calls = self.run_driver(mode="plugins", list="not json", ids=[HOOKIFY])
        self.assertEqual(out["First"], [])
        self.assertEqual(self.uninstalls(calls), [])

    # Kept plugins: pinned off in the template, but installed on every PC so a project can switch one on

    def installs(self, calls):
        return [c for c in calls if c.startswith(("claude plugin install", "claude plugin disable"))]

    def test_a_missing_kept_plugin_is_installed_then_disabled(self):
        # RotemsDesktop, 2026-11-05: frontend-design existed only as the retired anthropic-plugin-directory copy, so an
        # install that only installed `true` plugins left no copy for a project to switch on.
        listing = plugin_list(
            ("frontend-design@anthropic-plugin-directory", "user"), ("superpowers@claude-plugins-official", "user"),
        )
        out, calls = self.run_driver(mode="kept", list=listing, ids=[FRONTEND, GOOD_CSS])
        self.assertEqual(out["Installed"], [FRONTEND, GOOD_CSS])
        self.assertEqual(
            self.installs(calls),
            [
                "claude plugin install %s --scope user" % FRONTEND,
                "claude plugin disable %s --scope user" % FRONTEND,
                "claude plugin install %s --scope user" % GOOD_CSS,
                "claude plugin disable %s --scope user" % GOOD_CSS,
            ],
        )
        self.assertEqual(out["Failed"], [])

    def test_an_installed_kept_plugin_gets_no_install_call(self):
        out, calls = self.run_driver(mode="kept", list=plugin_list((GOOD_CSS, "user")), ids=[GOOD_CSS])
        self.assertEqual(out["Installed"], [])
        self.assertEqual(self.installs(calls), [])

    def test_a_project_scope_copy_still_gets_a_user_install(self):
        out, calls = self.run_driver(mode="kept", list=plugin_list((FRONTEND, "project")), ids=[FRONTEND])
        self.assertEqual(out["Installed"], [FRONTEND])

    def test_a_failed_install_is_reported_and_not_disabled(self):
        out, calls = self.run_driver(mode="kept", list=plugin_list(), ids=[FRONTEND], fail="1")
        self.assertEqual(out["Installed"], [])
        self.assertEqual(out["Failed"], [FRONTEND])
        self.assertEqual(self.installs(calls), ["claude plugin install %s --scope user" % FRONTEND])

    def test_unreadable_plugin_list_installs_nothing(self):
        out, calls = self.run_driver(mode="kept", list="not json", ids=[FRONTEND])
        self.assertEqual(out["Installed"], [])
        self.assertEqual(self.installs(calls), [])

    def test_kept_ids_are_the_templates_false_entries_without_synced_and_directory_copies(self):
        plugins = json.loads(read("settings.json"))["enabledPlugins"]
        out, _ = self.run_driver(mode="kept-ids", enabledPlugins=plugins)
        self.assertEqual(sorted(out["Ids"]), sorted(KEPT))

    # Settings

    def test_retired_plugin_keys_leave_enabled_plugins(self):
        settings = {
            "model": "opus",
            "enabledPlugins": {
                "pyright-lsp@claude-plugins-official": True,
                "superpowers@claude-plugins-official": True,
                "design@synced": False,
            },
        }
        out, _ = self.run_driver(
            mode="settings", settings=settings,
            ids=["pyright-lsp@claude-plugins-official", "vercel@claude-plugins-official"],
        )
        self.assertEqual(out["Removed"], ["pyright-lsp@claude-plugins-official"])
        self.assertEqual(
            out["Settings"]["enabledPlugins"],
            {"superpowers@claude-plugins-official": True, "design@synced": False},
        )
        self.assertEqual(out["Settings"]["model"], "opus")

    def test_settings_without_enabled_plugins_are_left_alone(self):
        out, _ = self.run_driver(mode="settings", settings={"model": "opus"}, ids=[HOOKIFY])
        self.assertEqual(out["Removed"], [])
        self.assertEqual(out["Settings"], {"model": "opus"})

    # Skills

    def test_only_the_named_skill_folder_is_removed(self):
        skills = os.path.join(self.tmp, "skills")
        shutil.rmtree(skills, ignore_errors=True)
        for name in ("find-skills", "codex"):
            os.makedirs(os.path.join(skills, name))
            with open(os.path.join(skills, name, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("x")
        out, _ = self.run_driver(mode="skills", names=["underwater-photoshop", "find-skills"], dir=skills)
        self.assertEqual(out["Removed"], ["find-skills"])
        self.assertEqual(sorted(os.listdir(skills)), ["codex"])
        again, _ = self.run_driver(mode="skills", names=["underwater-photoshop", "find-skills"], dir=skills)
        self.assertEqual(again["Removed"], [])

    def test_missing_skills_folder_is_fine(self):
        out, _ = self.run_driver(mode="skills", names=["find-skills"], dir=os.path.join(self.tmp, "none"))
        self.assertEqual(out["Removed"], [])


per_engine(RetireBase, globals())


class RetireTemplateTest(unittest.TestCase):
    def setUp(self):
        self.plugins = json.loads(read("settings.json"))["enabledPlugins"]

    def test_exactly_two_plugins_are_on(self):
        on = sorted(k for k, v in self.plugins.items() if v is True)
        self.assertEqual(on, ["remember@claude-plugins-official", "superpowers@claude-plugins-official"])

    def test_kept_project_plugins_are_pinned_off(self):
        official = ["playwright", "context7", "frontend-design", "mattpocock-skills", "modern-web-guidance", "supabase",
                    "adobe-for-creativity", "kotlin-lsp", "typescript-lsp", "rust-analyzer-lsp", "security-guidance"]
        for name in official:
            self.assertIs(self.plugins.get("%s@claude-plugins-official" % name), False, name)
        self.assertIs(self.plugins.get("good-css@good-css"), False)
        self.assertIs(self.plugins.get("claude-md-management@anthropic-plugin-directory"), False)

    def test_no_retired_plugin_is_in_the_template(self):
        retired = ["%s@claude-plugins-official" % r for r in RETIRED]
        for key in self.plugins:
            self.assertNotIn(key, retired)


class RetireInstallerTest(unittest.TestCase):
    def setUp(self):
        self.text = read("install.ps1")

    def test_retired_plugin_list(self):
        m = re.search(r"\$retiredPlugins = @\((.*?)\)", self.text, re.DOTALL)
        self.assertIsNotNone(m)
        ids = re.findall(r"'([^']+)'", m.group(1))
        for name in RETIRED:
            self.assertIn("%s@claude-plugins-official" % name, ids)
        for name in ("superpowers", "frontend-design", "context7", "playwright"):
            self.assertIn("%s@anthropic-plugin-directory" % name, ids)
        for kept in ("superpowers@claude-plugins-official", "remember@claude-plugins-official"):
            self.assertNotIn(kept, ids)

    def test_kept_plugins_are_installed_after_the_retire_step_and_before_the_pin_off(self):
        retire = self.text.index("Remove-RetiredPlugins $retiredPlugins")
        kept = self.text.index("Install-KeptPlugins (Get-KeptPlugins $template.enabledPlugins)")
        pin_off = self.text.index("pin the false ones off afterwards")
        self.assertLess(retire, kept)
        self.assertLess(kept, pin_off)

    def test_retired_skills(self):
        m = re.search(r"\$retiredSkills = @\((.*?)\)", self.text)
        self.assertIsNotNone(m)
        self.assertEqual(re.findall(r"'([^']+)'", m.group(1)), ["underwater-photoshop", "find-skills"])

    def test_the_language_server_plugins_are_not_retired(self):
        # typescript-lsp and rust-analyzer-lsp are pinned off in the template and installed disabled on every PC (their
        # binaries come from test_lsp_servers.py's steps), so uninstalling them every run would undo the install.
        m = re.search(r"\$retiredPlugins = @\((.*?)\)", self.text, re.DOTALL)
        ids = re.findall(r"'([^']+)'", m.group(1))
        for name in ("typescript-lsp", "rust-analyzer-lsp"):
            self.assertNotIn("%s@claude-plugins-official" % name, ids)
        self.assertIn("pyright-lsp@claude-plugins-official", ids)
        self.assertNotIn("Remove-RetiredTypescriptLsp", self.text)


if __name__ == "__main__":
    unittest.main()
