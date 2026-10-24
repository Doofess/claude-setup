import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "advisor-switch", "advisor.py")


class AdvisorSwitchTest(unittest.TestCase):
    def setUp(self):
        self.project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        subprocess.run(["git", "init", "-q", self.project], check=True)
        self.local = os.path.join(self.project, ".claude", "settings.local.json")

    def run_switch(self, *args, cwd=None):
        env = {**os.environ, "HOME": self.home, "USERPROFILE": self.home}
        return subprocess.run([sys.executable, SCRIPT, *args], cwd=cwd or self.project, env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def settings(self):
        with open(self.local, encoding="utf-8") as f:
            return json.load(f)

    def test_on_writes_the_projects_local_settings(self):
        r = self.run_switch("opus")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.settings(), {"advisorModel": "opus"})
        self.assertIn("opus", r.stdout)

    def test_found_from_a_subfolder(self):
        sub = os.path.join(self.project, "a", "b")
        os.makedirs(sub)
        self.assertEqual(self.run_switch("fable", cwd=sub).returncode, 0)
        self.assertEqual(self.settings(), {"advisorModel": "fable"})

    def test_other_keys_survive_and_off_removes_only_the_advisor(self):
        os.makedirs(os.path.dirname(self.local))
        with open(self.local, "w", encoding="utf-8") as f:
            json.dump({"permissions": {"allow": ["Bash(ls:*)"]}, "advisorModel": "fable"}, f)
        self.assertEqual(self.run_switch("opus").returncode, 0)
        self.assertEqual(self.settings(), {"permissions": {"allow": ["Bash(ls:*)"]}, "advisorModel": "opus"})
        self.assertEqual(self.run_switch("off").returncode, 0)
        self.assertEqual(self.settings(), {"permissions": {"allow": ["Bash(ls:*)"]}})

    def test_off_without_a_file_writes_nothing(self):
        self.assertEqual(self.run_switch("off").returncode, 0)
        self.assertFalse(os.path.exists(self.local))

    def test_a_broken_file_is_left_alone(self):
        os.makedirs(os.path.dirname(self.local))
        with open(self.local, "w", encoding="utf-8") as f:
            f.write("{not json")
        r = self.run_switch("opus")
        self.assertNotEqual(r.returncode, 0)
        with open(self.local, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{not json")

    def test_unknown_choice_is_refused(self):
        r = self.run_switch("haiku")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.local))

    def test_status_names_the_projects_and_the_users_value(self):
        self.run_switch("opus")
        os.makedirs(os.path.join(self.home, ".claude"))
        with open(os.path.join(self.home, ".claude", "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"advisorModel": "fable"}, f)
        out = self.run_switch("status").stdout
        self.assertIn("project: opus", out)
        self.assertIn("user: fable", out)

    def test_local_settings_are_kept_out_of_git(self):
        self.run_switch("opus")
        r = subprocess.run(["git", "check-ignore", "-q", ".claude/settings.local.json"], cwd=self.project)
        self.assertEqual(r.returncode, 0)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.project, capture_output=True, text=True).stdout
        self.assertEqual(status, "")


if __name__ == "__main__":
    unittest.main()
