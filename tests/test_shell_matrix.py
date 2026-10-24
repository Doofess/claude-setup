import os
import sys
import unittest

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
