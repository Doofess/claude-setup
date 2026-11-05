import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chrome_off
import mcp_off

KEY = "claudeInChromeDefaultEnabled"


def write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class MainTest(unittest.TestCase):
    def paths(self, d):
        return os.path.join(d, "claude.json"), os.path.join(d, "state.json")

    def test_first_run_turns_true_into_false(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path, state_path = self.paths(d)
            write(cfg_path, {KEY: True, "oauthAccount": {"x": 1}})
            self.assertEqual(chrome_off.main([cfg_path, state_path]), 0)
            self.assertEqual(read(cfg_path), {KEY: False, "oauthAccount": {"x": 1}})
            self.assertEqual(read(state_path), {KEY: "off-once"})

    def test_first_run_with_the_key_absent_writes_false(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path, state_path = self.paths(d)
            write(cfg_path, {"projects": {}})
            self.assertEqual(chrome_off.main([cfg_path, state_path]), 0)
            self.assertEqual(read(cfg_path), {"projects": {}, KEY: False})

    def test_second_run_keeps_the_users_choice(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path, state_path = self.paths(d)
            write(cfg_path, {})
            chrome_off.main([cfg_path, state_path])
            write(cfg_path, {KEY: True})
            self.assertEqual(chrome_off.main([cfg_path, state_path]), 0)
            self.assertEqual(read(cfg_path), {KEY: True})

    def test_other_state_keys_survive(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path, state_path = self.paths(d)
            write(cfg_path, {})
            write(state_path, {"claude.ai Adobe": ["C:/dev/a"], "repo": "C:/dev/x", "flags": ["-KeepFont"]})
            chrome_off.main([cfg_path, state_path])
            self.assertEqual(read(state_path), {"claude.ai Adobe": ["C:/dev/a"], "repo": "C:/dev/x",
                                                "flags": ["-KeepFont"], KEY: "off-once"})

    def test_missing_config_is_not_an_error_and_writes_no_state(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path, state_path = self.paths(d)
            self.assertEqual(chrome_off.main([cfg_path, state_path]), 0)
            self.assertFalse(os.path.exists(state_path))

    def test_leaves_the_file_alone_while_claude_code_holds_its_lock(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path, state_path = self.paths(d)
            write(cfg_path, {KEY: True})
            os.mkdir(cfg_path + ".lock")
            saved = mcp_off.LOCK_TRIES, mcp_off.LOCK_WAIT
            mcp_off.LOCK_TRIES, mcp_off.LOCK_WAIT = 2, 0.01
            try:
                self.assertEqual(chrome_off.main([cfg_path, state_path]), 1)
            finally:
                mcp_off.LOCK_TRIES, mcp_off.LOCK_WAIT = saved
            self.assertEqual(read(cfg_path), {KEY: True})
            self.assertFalse(os.path.exists(state_path))
            self.assertTrue(os.path.isdir(cfg_path + ".lock"))

    def test_releases_its_lock(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path, state_path = self.paths(d)
            write(cfg_path, {})
            chrome_off.main([cfg_path, state_path])
            self.assertFalse(os.path.exists(cfg_path + ".lock"))


if __name__ == "__main__":
    unittest.main()
