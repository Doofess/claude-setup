import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, ".claude", "hooks")
CHECK_EDIT = os.path.join(HOOKS, "check_edit.py")
STOP_TESTS = os.path.join(HOOKS, "stop_tests.py")
BIOME = os.path.join(ROOT, "node_modules", "@biomejs", "biome", "bin", "biome")
RUFF_WINGET = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Microsoft", "WinGet", "Packages", "astral-sh.ruff_Microsoft.Winget.Source_8wekyb3d8bbwe", "ruff.exe",
)
HAS_RUFF = bool(shutil.which("ruff") or os.path.isfile(RUFF_WINGET))
HAS_BIOME = bool(shutil.which("node")) and os.path.isfile(BIOME)
HAS_PS = bool(shutil.which("powershell.exe"))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_hook(script, payload):
    p = subprocess.run([sys.executable, script], input=json.dumps(payload), capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True)


def make_repo(tmp):
    repo = os.path.join(tmp, "my repo")
    os.makedirs(os.path.join(repo, "tests"))
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "commit.gpgsign", "false")
    write(repo, "README.md", "hello\n")
    write(repo, "tests/test_ok.py", "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def write(repo, rel, text):
    path = os.path.join(repo, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as f:
        f.write(text)
    return path


class CheckEditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hook test ")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def edit(self, name, text):
        path = write(self.tmp, name, text)
        return run_hook(CHECK_EDIT, {"tool_input": {"file_path": path}, "cwd": self.tmp})

    @unittest.skipUnless(HAS_PS, "needs powershell.exe")
    def test_ps1_with_51_only_syntax_blocks(self):
        code, _, err = self.edit("bad.ps1", "$x ??= 1\n")
        self.assertEqual(code, 2)
        self.assertIn("bad.ps1:1:", err)

    @unittest.skipUnless(HAS_PS, "needs powershell.exe")
    def test_valid_ps1_passes(self):
        code, _, err = self.edit("good.ps1", "Write-Output 1\n")
        self.assertEqual((code, err), (0, ""))

    @unittest.skipUnless(HAS_RUFF, "needs ruff")
    def test_python_lint_finding_blocks(self):
        code, _, err = self.edit("m.py", "import os\n")
        self.assertEqual(code, 2)
        self.assertIn("F401", err)

    def test_other_files_pass(self):
        self.assertEqual(self.edit("notes.md", "# hi\n")[0], 0)

    def test_missing_file_passes(self):
        path = os.path.join(self.tmp, "nope.py")
        code, _, err = run_hook(CHECK_EDIT, {"tool_input": {"file_path": path}, "cwd": self.tmp})
        self.assertEqual((code, err), (0, ""))

    def test_no_file_path_passes(self):
        self.assertEqual(run_hook(CHECK_EDIT, {"tool_input": {}, "cwd": self.tmp})[0], 0)

    @unittest.skipUnless(HAS_BIOME, "needs node and Biome")
    def test_mod_lint_finding_blocks(self):
        mods = os.path.join(ROOT, "mods", "_hook_test_tmp")
        self.addCleanup(shutil.rmtree, mods, True)
        os.makedirs(mods)
        path = os.path.join(mods, "bad.tsx")
        with open(path, "w", newline="\n") as f:
            f.write("debugger;\n")
        code, _, err = run_hook(CHECK_EDIT, {"tool_input": {"file_path": path}, "cwd": ROOT})
        self.assertEqual(code, 2)
        self.assertIn("noDebugger", err)

    @unittest.skipUnless(HAS_BIOME, "needs node and Biome")
    def test_ts_outside_mods_passes(self):
        code, _, _ = self.edit("x.ts", "debugger;\n")
        self.assertEqual(code, 0)


class StopTestsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stop test ")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = make_repo(self.tmp)
        self.mod = load(STOP_TESTS, "stop_tests")

    def stop(self, active=False):
        return run_hook(STOP_TESTS, {"cwd": self.repo, "stop_hook_active": active})

    def test_fingerprint_ignores_docs(self):
        before = self.mod.fingerprint(self.repo)
        write(self.repo, "README.md", "changed\n")
        self.assertEqual(self.mod.fingerprint(self.repo), before)
        write(self.repo, "tests/test_ok.py", "# edited\n")
        self.assertNotEqual(self.mod.fingerprint(self.repo), before)

    def test_fingerprint_sees_untracked_code(self):
        before = self.mod.fingerprint(self.repo)
        write(self.repo, "new.py", "x = 1\n")
        self.assertNotEqual(self.mod.fingerprint(self.repo), before)

    def test_suites_pick_the_mod_only_when_it_changed(self):
        py = self.mod.suites(self.repo, ["statusbar.py"])
        self.assertEqual(len(py), 1)
        self.assertIn("unittest", py[0])
        both = self.mod.suites(self.repo, ["statusbar.py", "mods/session-cards/x.tsx"])
        self.assertEqual(len(both), 2)
        mod_only = self.mod.suites(self.repo, ["mods/session-cards/x.tsx"])
        self.assertEqual(len(mod_only), 1)
        self.assertIn("plugin", mod_only[0])
        self.assertEqual(self.mod.suites(self.repo, ["README.md"]), [])

    def test_unchanged_tree_runs_nothing(self):
        write(self.repo, "a.py", "x = 1\n")
        self.assertEqual(self.stop()[0], 0)
        # a failing test added now would fail a rerun; the stamp must prevent one
        stamp_dir = subprocess.run(["git", "-C", self.repo, "rev-parse", "--absolute-git-dir"],
                                   capture_output=True, text=True).stdout.strip()
        self.assertTrue(os.path.isfile(os.path.join(stamp_dir, "claude-stop-tests")))
        start = time.monotonic()
        code, out, err = self.stop()
        self.assertEqual((code, out, err), (0, "", ""))
        self.assertLess(time.monotonic() - start, 1.5)

    def test_failing_suite_blocks_once(self):
        write(self.repo, "tests/test_x.py",
              "import unittest\n\n\nclass X(unittest.TestCase):\n    def test_x(self):\n        self.fail('boom')\n")
        code, _, err = self.stop()
        self.assertEqual(code, 2)
        self.assertIn("test_x", err)
        self.assertLessEqual(len(err.strip().splitlines()), 30)
        # fresh change, stop_hook_active true: no block, message to the user
        write(self.repo, "tests/test_y.py", "# touch\n")
        code, out, _ = self.stop(active=True)
        self.assertEqual(code, 0)
        self.assertIn("test_x", json.loads(out)["systemMessage"])


if __name__ == "__main__":
    unittest.main()
