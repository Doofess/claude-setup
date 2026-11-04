import json
import os
import re
import shutil
import tempfile
import unittest

from test_install import per_engine, read, run_engine

HASH = "be3bc4ef430cde315e6a83900ffb5d9cc454a36aabe9dd3ba7d4141b2d628164"
BASE = "https://download.jetbrains.com/language-server/kotlin-server/263.7084.0/kotlin-server-263.7084.0"

DRIVER = r"""
param([string]$InFile)
$ErrorActionPreference = 'Stop'
{HELPERS}
$in = [IO.File]::ReadAllText($InFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
$out = switch ($in.mode) {
  'urls' { Get-KotlinLspUrls $in.version $in.arch }
  'hash' { [pscustomobject]@{ Hash = (Get-Sha256FromText $in.text) } }
  'match' { [pscustomobject]@{ Match = (Test-Sha256Match $in.a $in.b) } }
  'path' { [pscustomobject]@{ Path = (Add-PathEntry $in.current $in.entry) } }
}
[Console]::Out.Write(($out | ConvertTo-Json -Compress))
"""


def kotlin_helpers():
    """Format-DirKey, Read-Utf8 and the pure Kotlin LSP helpers of install.ps1 (not Install-KotlinLsp)."""
    source = read("install.ps1").replace("\r\n", "\n")
    out = []
    for name in ("Read-Utf8", "Format-DirKey", "Get-KotlinLspUrls", "Get-Sha256FromText", "Test-Sha256Match", "Add-PathEntry"):
        m = re.search(r"^function %s[^\n]*\}$|^function %s.*?^}" % (name, name), source, re.DOTALL | re.MULTILINE)
        assert m is not None, name
        out.append(m.group(0))
    return "\n".join(out)


class KotlinHelpersBase:
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.script = os.path.join(cls.tmp, "driver.ps1")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(DRIVER.replace("{HELPERS}", kotlin_helpers()))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_driver(self, **args):
        path = os.path.join(self.tmp, "in.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(args, f)
        r = run_engine(self.engine, self.script, path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def test_amd64_picks_the_x64_archive(self):
        for arch in ("AMD64", "amd64", "x64"):
            urls = self.run_driver(mode="urls", version="263.7084.0", arch=arch)
            self.assertEqual(urls, {"Zip": BASE + ".win.zip", "Sha256": BASE + ".win.zip.sha256"})

    def test_arm64_picks_the_aarch64_archive(self):
        urls = self.run_driver(mode="urls", version="263.7084.0", arch="ARM64")
        self.assertEqual(urls, {"Zip": BASE + "-aarch64.win.zip", "Sha256": BASE + "-aarch64.win.zip.sha256"})

    def test_an_unknown_architecture_has_no_urls(self):
        self.assertIsNone(self.run_driver(mode="urls", version="263.7084.0", arch="x86"))

    def test_hash_is_read_from_the_published_file(self):
        text = "%s *kotlin-server-263.7084.0.win.zip\n" % HASH.upper()
        self.assertEqual(self.run_driver(mode="hash", text=text), {"Hash": HASH})
        self.assertEqual(self.run_driver(mode="hash", text=HASH), {"Hash": HASH})

    def test_no_hash_in_the_text(self):
        for text in ("", "<html>Not Found</html>", HASH[:63], HASH + "0"):
            self.assertEqual(self.run_driver(mode="hash", text=text), {"Hash": None}, text)

    def test_match_ignores_case_and_rejects_the_rest(self):
        other = "0" * 64
        self.assertEqual(self.run_driver(mode="match", a=HASH, b=HASH.upper()), {"Match": True})
        self.assertEqual(self.run_driver(mode="match", a=HASH, b=other), {"Match": False})
        self.assertEqual(self.run_driver(mode="match", a="", b=""), {"Match": False})
        self.assertEqual(self.run_driver(mode="match", a="abc", b="abc"), {"Match": False})

    def test_path_entry_is_added_once(self):
        shim = r"C:\Users\x\AppData\Local\Programs\kotlin-lsp\bin"
        r = self.run_driver(mode="path", current=r"C:\a;C:\b", entry=shim)
        self.assertEqual(r, {"Path": r"C:\a;C:\b;" + shim})
        again = self.run_driver(mode="path", current=r["Path"], entry=shim)
        self.assertEqual(again, r)

    def test_path_duplicates_by_case_slash_or_trailing_slash_collapse(self):
        shim = r"C:\Kotlin\bin"
        for dup in (r"c:\kotlin\BIN", "C:/Kotlin/bin", "C:\\Kotlin\\bin\\"):
            r = self.run_driver(mode="path", current=r"C:\a;%s;C:\b;;" % dup, entry=shim)
            self.assertEqual(r, {"Path": r"C:\a;C:\b;" + shim}, dup)

    def test_path_keeps_percent_variables_unexpanded(self):
        r = self.run_driver(mode="path", current=r"%USERPROFILE%\bin", entry=r"C:\k")
        self.assertEqual(r, {"Path": r"%USERPROFILE%\bin;C:\k"})

    def test_empty_path_gets_just_the_entry(self):
        self.assertEqual(self.run_driver(mode="path", current="", entry=r"C:\k"), {"Path": r"C:\k"})


per_engine(KotlinHelpersBase, globals())


class KotlinInstallerTest(unittest.TestCase):
    def test_pinned_version_and_step(self):
        text = read("install.ps1")
        self.assertIn("$kotlinLspVersion = '263.7084.0'", text)
        self.assertIn("-SkipKotlinLsp", text)
        self.assertIn("4h. Kotlin language server", text)

    def test_checksum_is_verified_before_extracting(self):
        body = read("install.ps1")
        body = body[body.index("function Install-KotlinLsp"):]
        self.assertLess(body.index("Test-Sha256Match"), body.index("ExtractToDirectory"))

    def test_extracted_archive_must_hold_product_info(self):
        body = read("install.ps1")
        body = body[body.index("function Install-KotlinLsp"):]
        self.assertLess(body.index("'product-info.json'"), body.index("Move-Item $stage"))

    def test_old_versions_go_but_the_shim_folder_stays(self):
        # The shim folder sits beside the version folders; clearing them must not take it along.
        body = read("install.ps1")
        body = body[body.index("function Install-KotlinLsp"):body.index("# ---- Nerd Font")]
        line = next(l for l in body.splitlines() if "Get-ChildItem $parent -Directory" in l)
        self.assertIn("$shimDir", line)

    def test_user_path_only(self):
        text = read("install.ps1")
        block = text[text.index("function Install-KotlinLsp"):text.index("# ---- Nerd Font")]
        self.assertIn("CurrentUser", block)
        self.assertNotIn("LocalMachine", block)
        self.assertNotIn("'Machine'", block)


if __name__ == "__main__":
    unittest.main()
