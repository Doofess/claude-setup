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
$env:FAKE_NPM_LS = [string]$in.npmLs
$env:FAKE_NPM_LS_FILE = [string]$in.npmLsFile

$fakeClaude = {
  Add-Content -LiteralPath $env:FAKE_LOG -Value ('claude ' + ($args -join ' '))
  if ($args[0] -eq 'plugin' -and $args[1] -eq 'list') { Write-Output $env:FAKE_LIST; $global:LASTEXITCODE = 0; return }
  $global:LASTEXITCODE = if ($env:FAKE_FAIL) { 1 } else { 0 }
}
$fakeNpm = {
  Add-Content -LiteralPath $env:FAKE_LOG -Value ('npm ' + ($args -join ' '))
  if ($args[0] -eq 'ls') { Write-Output $env:FAKE_NPM_LS; $global:LASTEXITCODE = 0; return }
  $global:LASTEXITCODE = if ($env:FAKE_FAIL) { 1 } else { 0 }
}
$missingNpm = { & (Join-Path ([IO.Path]::GetDirectoryName($env:FAKE_LOG)) 'no-such-npm') @args }

$result = $null
switch ($in.mode) {
  'plugins' {
    $failed = New-Object 'System.Collections.Generic.List[string]'
    $first = @(Remove-RetiredPlugins @($in.ids) $fakeClaude $failed)
    $second = @()
    if ($in.twice) { $second = @(Remove-RetiredPlugins @($in.ids) $fakeClaude $failed) }
    $result = [pscustomobject]@{ First = $first; Second = $second; Failed = @($failed) }
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
  'npm' {
    $npm = if ($in.missing) { $missingNpm } else { $fakeNpm }
    $result = [pscustomobject]@{ Result = [string](Remove-RetiredTypescriptLsp $npm) }
  }
  'npm-default' {
    $env:PATH = [string]$in.shimDir + [IO.Path]::PathSeparator + $env:PATH
    $result = [pscustomobject]@{ Result = [string](Remove-RetiredTypescriptLsp) }
  }
}
[Console]::Out.Write(($result | ConvertTo-Json -Compress -Depth 10))
"""

RETIRED = [
    "chrome-devtools-mcp", "hookify", "mcp-server-dev", "claude-code-setup", "claude-md-management", "claude-security",
    "cloudflare", "code-review", "code-simplifier", "feature-dev", "github", "ralph-loop", "shopify-ai-toolkit",
    "skill-creator", "telegram", "vercel", "pyright-lsp", "rust-analyzer-lsp", "typescript-lsp",
]
HOOKIFY = "hookify@claude-plugins-official"


def functions_source():
    source = read("install.ps1").replace("\r\n", "\n")
    out = [re.search(r"^function Test-IsObject[^\n]*\}$", source, re.MULTILINE).group(0)]
    for name in ("Remove-RetiredPlugins", "Remove-RetiredSkills", "Remove-RetiredSettingsPlugins", "Remove-RetiredTypescriptLsp"):
        m = re.search(r"^function %s.*?^}" % name, source, re.DOTALL | re.MULTILINE)
        assert m is not None, name
        out.append(m.group(0))
    return "\n".join(out)


def plugin_list(*entries):
    return json.dumps([{"id": i, "scope": s, "enabled": True} for i, s in entries])


def ls_json(lsp=None, ts=None):
    deps = {}
    if lsp:
        deps["typescript-language-server"] = {"version": lsp}
    if ts:
        deps["typescript"] = {"version": ts}
    return json.dumps({"name": "node", "dependencies": deps})


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
            ids=["pyright-lsp@claude-plugins-official", "typescript-lsp@claude-plugins-official"],
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

    # npm

    def npm_uninstalls(self, calls):
        return [c for c in calls if c.startswith("npm uninstall")]

    def test_pinned_versions_are_uninstalled(self):
        out, calls = self.run_driver(mode="npm", npmLs=ls_json("6.0.3", "6.0.3"))
        self.assertEqual(out["Result"], "removed")
        self.assertEqual(
            self.npm_uninstalls(calls),
            ["npm uninstall -g --no-fund --no-audit typescript-language-server typescript"],
        )

    def test_a_hand_installed_version_is_kept(self):
        out, calls = self.run_driver(mode="npm", npmLs=ls_json("5.0.0", "6.0.3"))
        self.assertTrue(out["Result"].startswith("kept"), out)
        self.assertEqual(self.npm_uninstalls(calls), [])

    def test_a_different_typescript_version_is_kept(self):
        out, calls = self.run_driver(mode="npm", npmLs=ls_json("6.0.3", "7.0.0"))
        self.assertTrue(out["Result"].startswith("kept"), out)
        self.assertEqual(self.npm_uninstalls(calls), [])

    def test_nothing_installed_is_kept(self):
        out, calls = self.run_driver(mode="npm", npmLs=ls_json())
        self.assertTrue(out["Result"].startswith("kept"), out)
        self.assertEqual(self.npm_uninstalls(calls), [])

    def test_missing_npm_is_kept(self):
        out, calls = self.run_driver(mode="npm", missing=True)
        self.assertTrue(out["Result"].startswith("kept"), out)

    def test_the_default_runs_npm_cmd_not_the_npm_ps1_shim(self):
        # npm 11's npm.ps1 rebuilds its arguments from the calling line, so `& npm @args` inside a scriptblock reached
        # it with none: it printed its usage text and the retire step said "kept (npm not available)" (2026-11-04).
        # PowerShell picks npm.ps1 over npm.cmd in the same folder, so the fake npm.ps1 below drops its arguments too.
        shims = os.path.join(self.tmp, "npm-shims")
        os.makedirs(shims, exist_ok=True)
        ls = os.path.join(self.tmp, "npm-ls.json")
        with open(ls, "w", encoding="utf-8") as f:
            f.write(ls_json("6.0.3", "6.0.3"))
        with open(os.path.join(shims, "npm.ps1"), "w", encoding="utf-8") as f:
            f.write("Add-Content -LiteralPath $env:FAKE_LOG -Value 'npm.ps1 without arguments'\nWrite-Output 'npm <command>'\n")
        with open(os.path.join(shims, "npm.cmd"), "w", encoding="ascii", newline="\r\n") as f:
            f.write('@echo off\necho npm %*>>"%FAKE_LOG%"\nif "%1"=="ls" type "%FAKE_NPM_LS_FILE%"\nexit /b 0\n')
        out, calls = self.run_driver(mode="npm-default", shimDir=shims, npmLsFile=ls)
        self.assertEqual(out["Result"], "removed", calls)
        self.assertEqual(
            self.npm_uninstalls(calls),
            ["npm uninstall -g --no-fund --no-audit typescript-language-server typescript"],
        )

    def test_failed_npm_uninstall_is_kept(self):
        out, calls = self.run_driver(mode="npm", npmLs=ls_json("6.0.3", "6.0.3"), fail="1")
        self.assertTrue(out["Result"].startswith("kept"), out)


per_engine(RetireBase, globals())


class RetireTemplateTest(unittest.TestCase):
    def setUp(self):
        self.plugins = json.loads(read("settings.json"))["enabledPlugins"]

    def test_exactly_two_plugins_are_on(self):
        on = sorted(k for k, v in self.plugins.items() if v is True)
        self.assertEqual(on, ["remember@claude-plugins-official", "superpowers@claude-plugins-official"])

    def test_kept_project_plugins_are_pinned_off(self):
        official = ["playwright", "context7", "frontend-design", "mattpocock-skills", "modern-web-guidance", "supabase",
                    "adobe-for-creativity", "kotlin-lsp", "security-guidance"]
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

    def test_retired_skills(self):
        m = re.search(r"\$retiredSkills = @\((.*?)\)", self.text)
        self.assertIsNotNone(m)
        self.assertEqual(re.findall(r"'([^']+)'", m.group(1)), ["underwater-photoshop", "find-skills"])

    def test_step_4i_is_gone(self):
        for needle in ("Install-TypescriptLsp", "SkipTypescriptLsp", "$typescriptLspVersion", "$typescriptVersion", "4i. TypeScript"):
            self.assertNotIn(needle, self.text, needle)
        here = os.path.dirname(os.path.abspath(__file__))
        self.assertFalse(os.path.exists(os.path.join(here, "test_typescript_lsp.py")))


if __name__ == "__main__":
    unittest.main()
