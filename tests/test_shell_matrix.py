import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shell_matrix


def result(**over):
    r = {
        "missing": False,
        "exit": 0,
        "rows": [
            {"name": "Python version", "expected": "3.x", "actual": "3.13", "status": "ok"},
            {"name": "Font", "expected": "Nerd", "actual": "Nerd", "status": "kept"},
        ],
        "claude": "2.1.310 (Claude Code)",
        "python": "C:/Python/python.exe 3.13.1",
        "bar_text": "model  ctx 10%",
        "bar_sgr": ["0", "38;5;75"],
        "errors": [],
    }
    r.update(over)
    return r


def matrix(**per_shell):
    return {s: per_shell.get(s, result()) for s in ("powershell", "pwsh", "git-bash", "cmd")}


def row(status):
    return [{"name": "Python version", "expected": "3.x", "actual": "?", "status": status}]


class CompareTest(unittest.TestCase):
    def test_identical_results_match(self):
        self.assertEqual(shell_matrix.compare(matrix()), [])

    def test_status_difference_named(self):
        lines = shell_matrix.compare(matrix(cmd=result(rows=row("FAIL")), pwsh=result(rows=row("ok"))))
        mine = [l for l in lines if "Python version" in l]
        self.assertEqual(len(mine), 1)
        self.assertIn("pwsh", mine[0])
        self.assertIn("cmd", mine[0])

    def test_failing_everywhere_is_still_reported(self):
        bad = result(rows=row("FAIL"))
        lines = shell_matrix.compare(matrix(**{s: bad for s in shell_matrix.SHELLS}))
        self.assertTrue(any("Python version" in l and "FAIL" in l for l in lines))

    def test_missing_shell_is_a_failure(self):
        lines = shell_matrix.compare(matrix(cmd={"missing": True}))
        self.assertEqual(len(lines), 1)
        self.assertIn("cmd", lines[0])
        self.assertIn("missing", lines[0])

    def test_status_bar_text_difference(self):
        lines = shell_matrix.compare(matrix(cmd=result(bar_sgr=["0"])))
        self.assertEqual(len(lines), 1)
        self.assertIn("status bar colours differ", lines[0])

    def test_claude_and_python_differences(self):
        lines = shell_matrix.compare(matrix(cmd=result(claude="1.0", python="x 3.9")))
        self.assertTrue(any("claude" in l for l in lines))
        self.assertTrue(any("python" in l for l in lines))


def probe_with(check_reply, **kw):
    """probe('cmd') with run_in faked: the install check gets check_reply, everything else succeeds quietly."""
    def fake(shell, command, timeout=shell_matrix.TIMEOUT):
        return check_reply if "-Check" in command else (0, "", "")

    with mock.patch.dict(shell_matrix.SHELLS, {"cmd": ["cmd", "/c"]}), mock.patch.object(shell_matrix, "run_in", fake):
        return shell_matrix.probe("cmd", **kw)


class FailuresTest(unittest.TestCase):
    def test_failures_without_a_row_are_reported(self):
        bad = result(failures=["status bar: x"])
        lines = shell_matrix.compare(matrix(**{s: bad for s in shell_matrix.SHELLS}))
        self.assertTrue(any("status bar: x" in l for l in lines), lines)

    def test_failure_line_names_the_shells_it_occurs_in(self):
        lines = shell_matrix.compare(matrix(cmd=result(failures=["session cards mod: broke"])))
        mine = [l for l in lines if "session cards mod: broke" in l]
        self.assertEqual(len(mine), 1)
        self.assertIn("cmd", mine[0])
        self.assertNotIn("pwsh", mine[0])

    def test_same_experience_failures_are_not_repeated(self):
        bad = result(rows=row("FAIL"), exit=1, failures=["same experience: Python version: expected 3.x, got ?"])
        lines = shell_matrix.compare(matrix(**{s: bad for s in shell_matrix.SHELLS}))
        self.assertFalse(any("expected 3.x, got" in l for l in lines), lines)
        self.assertFalse(any("exit" in l for l in lines), lines)

    def test_nonzero_exit_without_a_reason_is_reported(self):
        lines = shell_matrix.compare(matrix(cmd=result(exit=1)))
        self.assertTrue(any("cmd" in l and "exit" in l for l in lines), lines)

    def test_probe_keeps_the_failures(self):
        res = probe_with((1, '{"rows": [], "failures": ["status bar: x"]}', ""))
        self.assertEqual(res["failures"], ["status bar: x"])


class FlagsTest(unittest.TestCase):
    def test_recorded_flags_reach_every_install_command(self):
        for shell in ("powershell", "pwsh", "git-bash", "cmd"):
            cmd = shell_matrix.commands(shell, ["-KeepFont"])["install"]
            self.assertTrue(cmd.endswith("-Check -Json -KeepFont"), cmd)

    def test_no_flags_leaves_the_command_alone(self):
        self.assertTrue(shell_matrix.commands("cmd")["install"].endswith("-Check -Json"))

    def test_only_the_three_keep_flags_pass_through(self):
        got = shell_matrix.known_flags(["-KeepFont", "-Evil; calc", "-KeepScheme", "-SkipFont", "-SkipPlugins", 3])
        self.assertEqual(got, ["-KeepFont", "-KeepScheme", "-SkipFont"])

    def test_state_file_flags_are_read(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"repo": "C:/x", "flags": ["-KeepScheme"]}, f)
            self.assertEqual(shell_matrix.recorded_flags(path), ["-KeepScheme"])
            self.assertEqual(shell_matrix.recorded_flags(os.path.join(d, "missing.json")), [])


class RunInTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cmd"), "cmd is missing")
    def test_timeout_kills_a_hung_grandchild(self):
        start = time.time()
        with self.assertRaises(subprocess.TimeoutExpired):
            shell_matrix.run_in("cmd", "ping -n 30 127.0.0.1", timeout=2)
        self.assertLess(time.time() - start, 10)


class ReasonTest(unittest.TestCase):
    def test_missing_json_line_carries_the_stderr_reason(self):
        res = probe_with((1, "", "boom\n'python' not found on PATH\n"))
        self.assertTrue(any("'python' not found on PATH" in e for e in res["errors"]), res["errors"])


class FormatTest(unittest.TestCase):
    def test_table_all_match(self):
        out = shell_matrix.format_table(matrix(), [])
        self.assertIn("Python version", out)
        self.assertTrue(out.rstrip().endswith("shell matrix: all 4 shells match"))

    def test_table_differences_listed(self):
        res = matrix(cmd=result(claude="1.0"))
        diffs = shell_matrix.compare(res)
        out = shell_matrix.format_table(res, diffs).rstrip().splitlines()
        self.assertIn("shell matrix: 1 difference(s)", out)
        self.assertIn(diffs[0], out[-1])


class LiveTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("CLAUDE_SETUP_LIVE") == "1", "set CLAUDE_SETUP_LIVE=1 (after install from main)")
    def test_matrix_live(self):
        self.assertEqual(shell_matrix.main([]), 0)


if __name__ == "__main__":
    unittest.main()
