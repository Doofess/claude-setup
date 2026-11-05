import json
import os
import re
import shutil
import tempfile
import unittest

from test_install import per_engine, read, run_engine

LSP = "6.0.3"
TS = "6.0.3"
INSTALL = "npm install -g --no-fund --no-audit typescript-language-server@%s typescript@%s" % (LSP, TS)
GNU = "stable-x86_64-pc-windows-gnu"
MSVC = "stable-x86_64-pc-windows-msvc"

DRIVER = r"""
param([string]$InFile)
$ErrorActionPreference = 'Stop'
{FUNCTIONS}
$in = [IO.File]::ReadAllText($InFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
$env:FAKE_LOG = [string]$in.log
$env:FAKE_FAIL = [string]$in.fail
$env:FAKE_FAIL_PREFIX = [string]$in.failPrefix
$flag = $env:FAKE_LOG + '.installed'

$fakeNpm = {
  Add-Content -LiteralPath $env:FAKE_LOG -Value ('npm ' + ($args -join ' '))
  if ($args[0] -eq 'prefix') {
    if ($env:FAKE_FAIL_PREFIX) { $global:LASTEXITCODE = 1; return }
    Write-Output 'C:\fake\npm'; $global:LASTEXITCODE = 0; return
  }
  if ($args[0] -eq 'install' -and -not $env:FAKE_FAIL) { Set-Content -LiteralPath ($env:FAKE_LOG + '.installed') -Value 'x' }
  $global:LASTEXITCODE = if ($env:FAKE_FAIL) { 1 } else { 0 }
}
$missingNpm = { & (Join-Path ([IO.Path]::GetDirectoryName($env:FAKE_LOG)) 'no-such-npm') @args }
# The version text `typescript-language-server --version` gives: the command on Path ($dir empty) or npm's global folder.
$fakeProbe = {
  param([string]$dir)
  $installed = Test-Path -LiteralPath $flag
  if ($dir) { if ($installed) { return [string]$in.installedVersion } else { return [string]$in.prefixVersion } }
  if ($installed -and $in.pathAfter) { return [string]$in.pathAfter }
  return [string]$in.pathVersion
}

$fakeRustup = {
  Add-Content -LiteralPath $env:FAKE_LOG -Value ('rustup ' + ($args -join ' '))
  $global:LASTEXITCODE = 0
  if ($args[0] -eq 'toolchain') { foreach ($l in @($in.toolchains)) { Write-Output $l }; return }
  if ($args[0] -eq 'component' -and $args[1] -eq 'list') {
    $t = $args[4]
    foreach ($c in @($in.components.$t)) { Write-Output $c }
    return
  }
  if ($args[0] -eq 'component' -and $args[1] -eq 'add') { if (@($in.failOn) -contains $args[4]) { $global:LASTEXITCODE = 1 } }
}

$result = $null
try {
  switch ($in.mode) {
    'ts' {
      $npm = if ($in.npmMissing) { $missingNpm } else { $fakeNpm }
      $result = [pscustomobject]@{ Result = [string](Install-TypescriptLsp $in.lsp $in.ts $npm $fakeProbe -SkipPath) }
    }
    'ts-default-npm' {
      $env:PATH = [string]$in.shimDir + [IO.Path]::PathSeparator + $env:PATH
      $result = [pscustomobject]@{ Result = [string](Install-TypescriptLsp $in.lsp $in.ts -probe $fakeProbe -SkipPath) }
    }
    'rust' {
      $r = Install-RustAnalyzerComponent $fakeRustup ([bool]$in.available)
      $result = [pscustomobject]@{ Skipped = $r.Skipped; Added = @($r.Added); Present = @($r.Present); Failed = @($r.Failed) }
    }
    'semver' { $result = [pscustomobject]@{ Version = [string](ConvertTo-SemVer $in.text) } }
  }
} catch {
  $result = [pscustomobject]@{ Error = $_.Exception.Message }
}
[Console]::Out.Write(($result | ConvertTo-Json -Compress -Depth 10))
"""


def functions_source():
    source = read("install.ps1").replace("\r\n", "\n")
    out = []
    for name in ("Read-Utf8", "Format-DirKey", "Add-PathEntry", "ConvertTo-SemVer", "Get-TypescriptLspVersionText",
                 "Add-UserPathDir", "Install-TypescriptLsp", "Install-RustAnalyzerComponent"):
        m = re.search(r"^function %s[^\n]*\}$|^function %s.*?^}" % (name, name), source, re.DOTALL | re.MULTILINE)
        assert m is not None, name
        out.append(m.group(0))
    return "\n".join(out)


class LspServersBase:
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
        if os.path.exists(log + ".installed"):
            os.remove(log + ".installed")
        data.setdefault("log", log)
        path = os.path.join(self.tmp, "in.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        r = run_engine(self.engine, self.script, path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(log, encoding="utf-8") as f:
            calls = [l.strip() for l in f if l.strip()]
        return json.loads(r.stdout), calls

    def ts(self, **data):
        data.setdefault("lsp", LSP)
        data.setdefault("ts", TS)
        return self.run_driver(mode="ts", **data)

    def rust(self, **data):
        data.setdefault("available", True)
        return self.run_driver(mode="rust", **data)

    def adds(self, calls):
        return [c for c in calls if c.startswith("rustup component add")]

    # TypeScript language server

    def test_a_missing_server_is_installed_pinned_with_typescript(self):
        out, calls = self.ts(pathVersion="", prefixVersion="", installedVersion=LSP, pathAfter=LSP)
        self.assertEqual(calls, ["npm prefix -g", INSTALL])
        self.assertTrue(out["Result"].startswith("installed %s" % LSP), out)

    def test_an_older_server_on_path_is_installed_over(self):
        out, calls = self.ts(pathVersion="6.0.1", prefixVersion="", installedVersion=LSP, pathAfter=LSP)
        self.assertEqual(calls, ["npm prefix -g", INSTALL])
        self.assertTrue(out["Result"].startswith("installed"), out)

    def test_the_same_version_on_path_makes_no_npm_call(self):
        out, calls = self.ts(pathVersion="typescript-language-server 6.0.3\n")
        self.assertEqual(calls, [])
        self.assertEqual(out["Result"], "already %s on Path" % LSP)

    def test_a_newer_version_on_path_is_left_alone(self):
        out, calls = self.ts(pathVersion="6.1.0")
        self.assertEqual(calls, [])
        self.assertTrue(out["Result"].startswith("already 6.1.0"), out)

    def test_a_newer_major_is_compared_numerically_not_as_text(self):
        # "10.0.0" sorts before "6.0.3" as text.
        out, calls = self.ts(pathVersion="10.0.0")
        self.assertEqual(calls, [])

    def test_a_pinned_copy_in_npms_folder_is_not_reinstalled_and_a_shadowing_older_copy_is_reported(self):
        # This PC: a hand install at 6.0.1 sits in the Node folder (first on Path), npm's own folder holds the pin.
        out, calls = self.ts(pathVersion="6.0.1", prefixVersion=LSP)
        self.assertEqual(calls, ["npm prefix -g"])
        self.assertIn("already %s in C:\\fake\\npm" % LSP, out["Result"])
        self.assertIn("6.0.1 earlier on Path still wins", out["Result"])

    def test_an_install_that_an_older_copy_shadows_says_so(self):
        out, calls = self.ts(pathVersion="6.0.1", prefixVersion="", installedVersion=LSP, pathAfter="6.0.1")
        self.assertEqual(calls, ["npm prefix -g", INSTALL])
        self.assertTrue(out["Result"].startswith("installed"), out)
        self.assertIn("6.0.1 earlier on Path still wins", out["Result"])

    def test_an_install_that_is_not_on_path_yet_says_so(self):
        out, _ = self.ts(pathVersion="", prefixVersion="", installedVersion=LSP, pathAfter="")
        self.assertIn("not on Path yet", out["Result"])

    def test_output_without_a_version_counts_as_missing(self):
        out, calls = self.ts(pathVersion="usage: typescript-language-server", prefixVersion="", installedVersion=LSP, pathAfter=LSP)
        self.assertEqual(calls, ["npm prefix -g", INSTALL])

    def test_a_failed_npm_install_throws_and_names_the_exit_code(self):
        out, calls = self.ts(pathVersion="", prefixVersion="", fail="1")
        self.assertEqual(calls, ["npm prefix -g", INSTALL])
        self.assertEqual(out["Error"], "npm install -g failed with exit code 1")

    def test_a_failed_prefix_lookup_throws_before_any_install(self):
        out, calls = self.ts(pathVersion="", prefixVersion="", failPrefix="1")
        self.assertEqual(calls, ["npm prefix -g"])
        self.assertIn("npm prefix -g failed", out["Error"])

    def test_missing_npm_throws_when_the_command_is_not_good_enough(self):
        out, calls = self.ts(pathVersion="6.0.1", prefixVersion="", npmMissing=True)
        self.assertIn("npm was not found", out["Error"])

    def test_missing_npm_is_irrelevant_when_the_command_already_is_good_enough(self):
        out, calls = self.ts(pathVersion=LSP, npmMissing=True)
        self.assertEqual(out["Result"], "already %s on Path" % LSP)

    def test_the_default_runs_npm_cmd_not_the_npm_ps1_shim(self):
        # npm 11's npm.ps1 rebuilds its arguments from the calling line, so `& npm @args` inside a scriptblock reached
        # it with none (2026-11-04). PowerShell picks npm.ps1 over npm.cmd in the same folder, so the fake npm.ps1 below
        # drops its arguments too.
        shims = os.path.join(self.tmp, "npm-shims")
        os.makedirs(shims, exist_ok=True)
        with open(os.path.join(shims, "npm.ps1"), "w", encoding="utf-8") as f:
            f.write("Add-Content -LiteralPath $env:FAKE_LOG -Value 'npm.ps1 without arguments'\nWrite-Output 'npm <command>'\n")
        with open(os.path.join(shims, "npm.cmd"), "w", encoding="ascii", newline="\r\n") as f:
            f.write('@echo off\necho npm %*>>"%FAKE_LOG%"\nif "%1"=="prefix" echo C:\\fake\\npm\nexit /b 0\n')
        out, calls = self.run_driver(mode="ts-default-npm", lsp=LSP, ts=TS, shimDir=shims, pathVersion="", prefixVersion="")
        self.assertEqual(calls, ["npm prefix -g", INSTALL], out)

    def test_versions_are_read_from_noisy_output(self):
        out, _ = self.run_driver(mode="semver", text="typescript-language-server\n6.0.3 (build 7)\n")
        self.assertEqual(out["Version"], "6.0.3")
        out, _ = self.run_driver(mode="semver", text="no version here")
        self.assertEqual(out["Version"], "")

    # rust-analyzer

    def test_no_rustup_is_a_skip_with_no_calls(self):
        out, calls = self.rust(available=False)
        self.assertTrue(out["Skipped"])
        self.assertEqual(calls, [])

    def test_the_component_is_added_only_to_the_toolchain_that_lacks_it(self):
        out, calls = self.rust(
            toolchains=[GNU, MSVC + " (active, default)"],
            components={GNU: ["cargo-x86_64-pc-windows-gnu", "rustc-x86_64-pc-windows-gnu"],
                        MSVC: ["cargo-x86_64-pc-windows-msvc", "rust-analyzer-x86_64-pc-windows-msvc"]},
        )
        self.assertFalse(out["Skipped"])
        self.assertEqual(self.adds(calls), ["rustup component add rust-analyzer --toolchain %s" % GNU])
        self.assertEqual(out["Added"], [GNU])
        self.assertEqual(out["Present"], [MSVC])
        self.assertEqual(out["Failed"], [])

    def test_every_toolchain_is_checked_not_only_the_default(self):
        out, calls = self.rust(toolchains=[GNU, MSVC + " (active, default)", "1.98.1-x86_64-pc-windows-msvc (override)"],
                               components={})
        self.assertEqual(
            self.adds(calls),
            ["rustup component add rust-analyzer --toolchain %s" % t for t in (GNU, MSVC, "1.98.1-x86_64-pc-windows-msvc")],
        )

    def test_a_rerun_with_every_component_present_makes_no_add_call(self):
        out, calls = self.rust(
            toolchains=[GNU, MSVC + " (active, default)"],
            components={GNU: ["rust-analyzer-x86_64-pc-windows-gnu"], MSVC: ["rust-analyzer-x86_64-pc-windows-msvc"]},
        )
        self.assertEqual(self.adds(calls), [])
        self.assertEqual(out["Present"], [GNU, MSVC])
        self.assertEqual(out["Added"], [])

    def test_a_refused_component_is_reported_and_the_rest_continue(self):
        out, calls = self.rust(toolchains=["nightly-x86_64-pc-windows-msvc", MSVC], components={}, failOn=["nightly-x86_64-pc-windows-msvc"])
        self.assertEqual(out["Failed"], ["nightly-x86_64-pc-windows-msvc"])
        self.assertEqual(out["Added"], [MSVC])

    def test_no_installed_toolchains_makes_no_component_call(self):
        out, calls = self.rust(toolchains=["no installed toolchains"])
        self.assertEqual(calls, ["rustup toolchain list"])
        self.assertEqual(out["Added"] + out["Present"] + out["Failed"], [])


per_engine(LspServersBase, globals())


class LspInstallerTest(unittest.TestCase):
    def setUp(self):
        self.text = read("install.ps1")

    def test_pins(self):
        self.assertIn("$typescriptLspVersion = '%s'" % LSP, self.text)
        self.assertIn("$typescriptVersion = '%s'" % TS, self.text)

    def test_the_steps_run_unless_skip_lsp_and_are_independent_of_skip_plugins(self):
        i = self.text.index("# 4i. TypeScript language server")
        j = self.text.index("# 4j. rust-analyzer")
        self.assertLess(i, j)
        step = self.text[i:self.text.index("# 5. Verify")]
        self.assertIn("if (-not $SkipLsp)", step)
        self.assertNotIn("SkipPlugins", step)
        self.assertIn("Install-TypescriptLsp $typescriptLspVersion $typescriptVersion", step)
        self.assertIn("Install-RustAnalyzerComponent", step)
        self.assertIn("[switch]$SkipLsp", self.text)
        self.assertIn("[switch]$SkipKotlinLsp", self.text)

    def test_the_user_path_is_the_only_path_touched(self):
        body = self.text[self.text.index("function Add-UserPathDir"):self.text.index("function Install-TypescriptLsp")]
        self.assertIn("CurrentUser", body)
        self.assertNotIn("LocalMachine", body)
        self.assertNotIn("'Machine'", body)
        self.assertIn("Add-UserPathDir $prefix", self.text)

    def test_npm_is_called_through_npm_cmd(self):
        self.assertIn("[scriptblock]$npm = { & npm.cmd @args }", self.text)

    def test_the_old_retire_step_is_gone(self):
        self.assertNotIn("Remove-RetiredTypescriptLsp", self.text)
        self.assertNotIn("Retiring the global TypeScript language server", self.text)

    def test_the_template_pins_both_plugins_off_and_the_installer_picks_them_up(self):
        plugins = json.loads(read("settings.json"))["enabledPlugins"]
        for name in ("typescript-lsp", "rust-analyzer-lsp"):
            self.assertIs(plugins.get("%s@claude-plugins-official" % name), False, name)


if __name__ == "__main__":
    unittest.main()
