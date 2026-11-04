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
{FUNCTION}
$in = [IO.File]::ReadAllText($InFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
$env:FAKE_NPM_LS = [string]$in.ls
$env:FAKE_NPM_LOG = [string]$in.log
$env:FAKE_NPM_FAIL = [string]$in.fail
try {
  $r = Install-TypescriptLsp '6.0.3' '6.0.3' $in.npm
  $out = [pscustomobject]@{ Result = $r; Error = $null }
} catch {
  $out = [pscustomobject]@{ Result = $null; Error = $_.Exception.Message }
}
[Console]::Out.Write(($out | ConvertTo-Json -Compress))
"""

FAKE_NPM = r"""
Add-Content -LiteralPath $env:FAKE_NPM_LOG -Value ($args -join ' ')
if ($args[0] -eq 'ls') { if ($env:FAKE_NPM_LS) { Write-Output $env:FAKE_NPM_LS }; exit 0 }
if ($env:FAKE_NPM_FAIL) { exit 1 }
exit 0
"""


def ls_json(lsp, ts):
    deps = {}
    if lsp:
        deps["typescript-language-server"] = {"version": lsp}
    if ts:
        deps["typescript"] = {"version": ts}
    return json.dumps({"dependencies": deps})


def function_source():
    source = read("install.ps1").replace("\r\n", "\n")
    m = re.search(r"^function Install-TypescriptLsp.*?^}", source, re.DOTALL | re.MULTILINE)
    assert m is not None
    return m.group(0)


class TypescriptInstallBase:
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.script = os.path.join(cls.tmp, "driver.ps1")
        cls.npm = os.path.join(cls.tmp, "fake-npm.ps1")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(DRIVER.replace("{FUNCTION}", function_source()))
        with open(cls.npm, "w", encoding="utf-8") as f:
            f.write(FAKE_NPM)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_driver(self, ls="", fail="", npm=None):
        log = os.path.join(self.tmp, "npm.log")
        with open(log, "w", encoding="utf-8"):
            pass
        path = os.path.join(self.tmp, "in.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ls": ls, "fail": fail, "log": log, "npm": npm or self.npm}, f)
        r = run_engine(self.engine, self.script, path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(log, encoding="utf-8") as f:
            calls = [l.strip() for l in f if l.strip()]
        return json.loads(r.stdout), calls

    def installs(self, calls):
        return [c for c in calls if c.startswith("install")]

    def test_fresh_install_uses_the_pinned_specs(self):
        out, calls = self.run_driver()
        self.assertEqual(out, {"Result": "installed", "Error": None})
        self.assertEqual(
            self.installs(calls),
            ["install -g --no-fund --no-audit typescript-language-server@6.0.3 typescript@6.0.3"],
        )

    def test_already_pinned_skips_npm_install(self):
        out, calls = self.run_driver(ls=ls_json("6.0.3", "6.0.3"))
        self.assertEqual(out, {"Result": "already 6.0.3", "Error": None})
        self.assertEqual(self.installs(calls), [])

    def test_wrong_typescript_version_reinstalls(self):
        out, calls = self.run_driver(ls=ls_json("6.0.3", "7.0.0"))
        self.assertEqual(out["Result"], "installed")
        self.assertEqual(len(self.installs(calls)), 1)

    def test_wrong_server_version_reinstalls(self):
        out, calls = self.run_driver(ls=ls_json("5.1.0", "6.0.3"))
        self.assertEqual(out["Result"], "installed")
        self.assertEqual(len(self.installs(calls)), 1)

    def test_only_one_package_present_reinstalls(self):
        out, calls = self.run_driver(ls=ls_json("6.0.3", None))
        self.assertEqual(out["Result"], "installed")
        self.assertEqual(len(self.installs(calls)), 1)

    def test_npm_failure_is_reported(self):
        out, calls = self.run_driver(fail="1")
        self.assertIsNone(out["Result"])
        self.assertIn("exit code 1", out["Error"])

    def test_missing_npm_is_reported(self):
        out, calls = self.run_driver(npm=os.path.join(self.tmp, "no-such-npm"))
        self.assertIsNone(out["Result"])
        self.assertIn("npm was not found", out["Error"])
        self.assertEqual(calls, [])


per_engine(TypescriptInstallBase, globals())


class TypescriptInstallerTest(unittest.TestCase):
    def test_pinned_versions_flag_and_step(self):
        text = read("install.ps1")
        self.assertIn("$typescriptLspVersion = '6.0.3'", text)
        self.assertIn("$typescriptVersion = '6.0.3'", text)
        self.assertIn("-SkipTypescriptLsp", text)
        self.assertIn("4i. TypeScript language server", text)
        self.assertIn('$failures += "typescript-lsp: ', text)


if __name__ == "__main__":
    unittest.main()
