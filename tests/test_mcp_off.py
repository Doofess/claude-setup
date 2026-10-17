import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mcp_off  # noqa: E402

ADOBE = "claude.ai Adobe"


class TurnOffTest(unittest.TestCase):
    def test_adds_to_a_project_seen_for_the_first_time(self):
        cfg = {"projects": {"C:/dev/a": {}}}
        done = mcp_off.turn_off(cfg, ADOBE, [])
        self.assertEqual(cfg["projects"]["C:/dev/a"]["disabledMcpServers"], [ADOBE])
        self.assertEqual(done, ["C:/dev/a"])

    def test_keeps_the_other_disabled_servers(self):
        cfg = {"projects": {"C:/dev/a": {"disabledMcpServers": ["bigquery"]}}}
        mcp_off.turn_off(cfg, ADOBE, [])
        self.assertEqual(cfg["projects"]["C:/dev/a"]["disabledMcpServers"], ["bigquery", ADOBE])

    def test_never_adds_twice(self):
        cfg = {"projects": {"C:/dev/a": {"disabledMcpServers": [ADOBE]}}}
        mcp_off.turn_off(cfg, ADOBE, [])
        self.assertEqual(cfg["projects"]["C:/dev/a"]["disabledMcpServers"], [ADOBE])

    def test_leaves_a_project_already_handled(self):
        # Turned back on with /mcp after an earlier run: that choice stands.
        cfg = {"projects": {"C:/dev/a": {"disabledMcpServers": []}}}
        done = mcp_off.turn_off(cfg, ADOBE, ["C:/dev/a"])
        self.assertEqual(cfg["projects"]["C:/dev/a"]["disabledMcpServers"], [])
        self.assertEqual(done, ["C:/dev/a"])

    def test_leaves_a_project_that_enabled_it(self):
        cfg = {"projects": {"C:/dev/a": {"enabledMcpServers": [ADOBE]}}}
        mcp_off.turn_off(cfg, ADOBE, [])
        self.assertNotIn("disabledMcpServers", cfg["projects"]["C:/dev/a"])

    def test_no_projects(self):
        self.assertEqual(mcp_off.turn_off({}, ADOBE, []), [])


class MainTest(unittest.TestCase):
    def test_round_trip_keeps_unrelated_keys(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path, state_path = os.path.join(d, "claude.json"), os.path.join(d, "state.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({"oauthAccount": {"x": 1}, "projects": {"C:/dev/a": {"allowedTools": []}}}, f)
            self.assertEqual(mcp_off.main([cfg_path, state_path, ADOBE]), 0)
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
            self.assertEqual(cfg["oauthAccount"], {"x": 1})
            self.assertEqual(cfg["projects"]["C:/dev/a"], {"allowedTools": [], "disabledMcpServers": [ADOBE]})
            with open(state_path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {ADOBE: ["C:/dev/a"]})

    def test_missing_config_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(mcp_off.main([os.path.join(d, "none.json"), os.path.join(d, "s.json"), ADOBE]), 0)


if __name__ == "__main__":
    unittest.main()
