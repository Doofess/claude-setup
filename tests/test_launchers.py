import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
STUB = "$PSVersionTable.PSEdition\n$args -join '|'\nexit 3\n"


def find_git_bash():
    # Port of install.ps1's Get-GitBash.
    override = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if override and os.path.exists(override):
        return override
    git = shutil.which("git")
    if git:
        d = os.path.dirname(git)
        for root in (d, os.path.dirname(d), os.path.dirname(os.path.dirname(d))):
            candidate = os.path.join(root, "bin", "bash.exe")
            if root and os.path.exists(candidate):
                return candidate
    return None


class LauncherTest(unittest.TestCase):
    def setUp(self):
        if os.name != "nt":
            self.skipTest("Windows only")
        self.tmp = tempfile.mkdtemp(prefix="launch test ")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name in ("install.cmd", "install.sh"):
            shutil.copy(os.path.join(ROOT, name), self.tmp)
        with open(os.path.join(self.tmp, "install.ps1"), "w", encoding="ascii", newline="\n") as f:
            f.write(STUB)

    def run_cmd(self, env):
        r = subprocess.run(
            ["cmd", "/c", os.path.join(self.tmp, "install.cmd"), "-Check", "-Json"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        return r.returncode, r.stdout + r.stderr

    def test_cmd_runs_the_script_with_its_args(self):
        code, out = self.run_cmd(os.environ.copy())
        self.assertIn("-Check|-Json", out)
        self.assertEqual(code, 3, out)

    def test_cmd_prefers_pwsh(self):
        if not shutil.which("pwsh"):
            self.skipTest("pwsh not installed")
        code, out = self.run_cmd(os.environ.copy())
        self.assertIn("Core", out)
        self.assertEqual(code, 3, out)

    def test_cmd_falls_back_to_windows_powershell(self):
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join([SYSTEM32, os.path.join(SYSTEM32, "WindowsPowerShell", "v1.0")])
        if not shutil.which("powershell", path=env["PATH"]) or shutil.which("pwsh", path=env["PATH"]):
            self.skipTest("need powershell.exe and no pwsh on the trimmed PATH")
        env["PSModulePath"] = r"C:\Program Files\PowerShell\7\Modules"  # a parent pwsh's value; the launcher must clear it
        code, out = self.run_cmd(env)
        self.assertIn("Desktop", out)
        self.assertIn("-Check|-Json", out)
        self.assertEqual(code, 3, out)

    def test_sh_runs_from_git_bash(self):
        bash = find_git_bash()
        if not bash:
            self.skipTest("Git Bash not found")
        r = subprocess.run([bash, "./install.sh", "-Check"], cwd=self.tmp, capture_output=True, text=True, timeout=120)
        self.assertIn("-Check", r.stdout + r.stderr)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
