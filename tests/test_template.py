"""The settings.json template is a clean slate: no plugin, marketplace, hook, MCP rule or skill override (Claude Code's defaults)."""
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Keys the template once held and no longer may: each is back at Claude Code's default.
REMOVED_KEYS = (
    "enabledPlugins", "extraKnownMarketplaces", "hooks", "deniedMcpServers", "skillOverrides", "modelSettings",
    "enableArtifact", "enableWorkflows",
)
REMOVED_ENV = ("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_DISABLE_FAST_MODE")


def template():
    with open(os.path.join(ROOT, "settings.json"), encoding="utf-8") as f:
        return json.load(f)


class TemplatePolicyTest(unittest.TestCase):
    def test_none_of_the_removed_keys_is_present(self):
        t = template()
        for key in REMOVED_KEYS:
            self.assertNotIn(key, t)
        self.assertNotIn("deny", t["permissions"])
        for name in REMOVED_ENV:
            self.assertNotIn(name, t["env"])

    def test_the_keys_are_exactly_these(self):
        t = template()
        self.assertEqual(sorted(t), sorted([
            "permissions", "model", "theme", "env", "statusLine", "autoCompactWindow", "feedbackDrafts",
            "autoUpdatesChannel", "skipDangerousModePermissionPrompt", "switchModelsOnFlag", "agentPushNotifEnabled",
            "tui", "editorMode", "remoteControlAtStartup",
        ]))
        self.assertEqual(t["permissions"], {"defaultMode": "bypassPermissions"})
        self.assertEqual(sorted(t["env"]), ["CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION", "CLAUDE_CODE_NATIVE_CURSOR", "CLAUDE_CODE_PLUGIN_DIRS"])
        self.assertEqual(t["statusLine"], {"type": "command", "command": "python -I -S ~/.claude/statusbar.py", "refreshInterval": 60})

    def test_the_kept_pieces_are_wired(self):
        t = template()
        self.assertEqual(t["theme"], "custom:clear")
        self.assertEqual(t["env"]["CLAUDE_CODE_PLUGIN_DIRS"], "<repo>/mods/session-cards")
        self.assertEqual(t["feedbackDrafts"], "off")

    def test_the_repo_holds_no_project_settings_or_hooks(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, ".claude", "settings.json")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, ".claude", "hooks")))


if __name__ == "__main__":
    unittest.main()
