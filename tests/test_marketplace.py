import json
import os
import shutil
import subprocess
import unittest

from test_install import ROOT, read


class MarketplaceTest(unittest.TestCase):
    def setUp(self):
        self.market = json.loads(read(".claude-plugin", "marketplace.json"))

    def test_marketplace_name(self):
        self.assertEqual(self.market["name"], "claude-setup")

    def test_one_plugin_photo_edit_with_an_existing_source(self):
        plugins = self.market["plugins"]
        self.assertEqual([p["name"] for p in plugins], ["photo-edit"])
        self.assertEqual(plugins[0]["source"], "./plugins/photo-edit")
        self.assertTrue(os.path.isdir(os.path.join(ROOT, "plugins", "photo-edit")))

    def test_plugin_manifest_names_the_plugin(self):
        manifest = json.loads(read("plugins", "photo-edit", ".claude-plugin", "plugin.json"))
        self.assertEqual(manifest["name"], "photo-edit")

    def test_photo_skill_moved_into_the_plugin(self):
        moved = os.path.join(ROOT, "plugins", "photo-edit", "skills", "underwater-photoshop", "SKILL.md")
        self.assertTrue(os.path.isfile(moved))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "skills", "underwater-photoshop")))

    @unittest.skipUnless(shutil.which("claude"), "claude is not on PATH")
    def test_claude_plugin_validate_passes(self):
        r = subprocess.run(
            [shutil.which("claude"), "plugin", "validate", "."],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
