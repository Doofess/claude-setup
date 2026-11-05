"""The settings.json template keeps built-in tools and skills off at user level (projects switch them on)."""
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Superpowers skills once listed in skillOverrides. Plugin skills ignore skillOverrides (bare or plugin:skill keys),
# so these entries did nothing; CLAUDE.md carries the rules instead.
SUPERPOWERS_SKILLS = (
    "brainstorming", "diagnosing-superpowers", "dispatching-parallel-agents", "receiving-code-review",
    "requesting-code-review", "verification-before-completion", "writing-skills",
)


def template():
    with open(os.path.join(ROOT, "settings.json"), encoding="utf-8") as f:
        return json.load(f)


class TemplatePolicyTest(unittest.TestCase):
    def test_built_in_tools_are_off_at_user_level(self):
        t = template()
        self.assertIs(t["enableArtifact"], False)
        self.assertIs(t["enableWorkflows"], False)
        self.assertEqual(t["feedbackDrafts"], "off")
        self.assertIs(t["enabledPlugins"]["humanizer@synced"], False)

    def test_skill_overrides_name_bare_skills_only(self):
        overrides = template()["skillOverrides"]
        for key, value in overrides.items():
            self.assertNotIn(":", key, "skillOverrides takes bare skill names; plugin skills ignore it")
            self.assertIn(value, {"on", "name-only", "user-invocable-only", "off"}, key)
        for name in SUPERPOWERS_SKILLS:
            self.assertNotIn(name, overrides, "plugin skills ignore skillOverrides")

    def test_unused_bundled_skills_are_hidden_from_claude(self):
        overrides = template()["skillOverrides"]
        for name in ("loop", "schedule", "init", "security-review", "simplify", "keybindings-help", "update-config",
                     "fewer-permission-prompts", "plugin-authoring"):
            self.assertEqual(overrides.get(name), "user-invocable-only", name)
        for name in ("dataviz", "claude-api", "artifact-design", "artifact-diagramming", "artifact-capabilities"):
            self.assertEqual(overrides.get(name), "off", name)
        for name in ("code-review", "run", "workflow-authoring"):
            self.assertNotIn(name, overrides, name)


if __name__ == "__main__":
    unittest.main()
