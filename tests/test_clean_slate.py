"""The one-time clean slate: install.ps1's reset functions (both engines, a fake `claude`, scratch folders and a scratch
registry key) and clean_slate.py (the ~/.claude.json and state-file edits)."""
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import uuid
import winreg

from test_install import ROOT, per_engine, read, run_engine

sys.path.insert(0, ROOT)
import clean_slate

PS_FUNCTIONS = (
    "Read-Utf8", "Write-Utf8NoBom", "Test-IsObject", "Test-IsArray", "Merge-Json", "Format-DirKey", "Merge-PluginDirs",
    "Merge-ClaudeSettings", "Get-StateValue", "Set-StateValue", "Remove-StateValue", "Test-CleanSlateStep",
    "Set-CleanSlateStep", "Remove-AllUserPlugins", "Remove-Marketplaces",
    "Remove-ClaudeAgentsAndRules", "Remove-NamedFolders", "Remove-PathEntry", "Remove-UserPathEntry", "Remove-KotlinLsp",
    "Clear-ClaudeJson", "Invoke-CleanSlate",
)


def functions_source():
    source = read("install.ps1").replace("\r\n", "\n")
    out = []
    for name in PS_FUNCTIONS:
        m = re.search(r"^function %s\b.*$" % re.escape(name), source, re.MULTILINE)
        assert m is not None, name
        first = m.group(0)
        if first.count("{") == first.count("}") and first.rstrip().endswith("}"):
            out.append(first)  # a one-line function
        else:
            end = re.compile(r"^}", re.MULTILINE).search(source, m.end())
            out.append(source[m.start():end.end()])
    return "\n".join(out)


DRIVER = r"""
param([string]$InFile)
$ErrorActionPreference = 'Stop'
{FUNCTIONS}
$in = [IO.File]::ReadAllText($InFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
$env:FAKE_LOG = [string]$in.log
$env:FAKE_LIST = [string]$in.list
$env:FAKE_MARKETS = [string]$in.markets
$env:FAKE_MARKETS_FAIL = [string]$in.marketsFail
$env:FAKE_FAIL = [string]$in.fail
$env:FAKE_LIST_EXIT = [string]$in.listExit
$env:PY_EXE = [string]$in.python

$fakeClaude = {
  Add-Content -LiteralPath $env:FAKE_LOG -Value ('claude ' + ($args -join ' '))
  if ($args[0] -eq 'plugin' -and $args[1] -eq 'list') {
    if ($env:FAKE_LIST) { Write-Output $env:FAKE_LIST }
    $global:LASTEXITCODE = if ($env:FAKE_LIST_EXIT) { [int]$env:FAKE_LIST_EXIT } else { 0 }
    return
  }
  if ($args[1] -eq 'marketplace' -and $args[2] -eq 'list') {
    if ($env:FAKE_MARKETS_FAIL) { $global:LASTEXITCODE = 1; return }
    Write-Output $env:FAKE_MARKETS; $global:LASTEXITCODE = 0; return
  }
  $global:LASTEXITCODE = if ($env:FAKE_FAIL -and (($args -join ' ') -match $env:FAKE_FAIL)) { 1 } else { 0 }
}
$fakePython = { & $env:PY_EXE -S @args }

$result = $null
switch ($in.mode) {
  'plugins' {
    $failed = New-Object 'System.Collections.Generic.List[string]'
    $r = Remove-AllUserPlugins $fakeClaude $failed
    $result = [pscustomobject]@{ Removed = @($r.Removed); Elsewhere = @($r.Elsewhere); Failed = @($failed) }
  }
  'markets' {
    $failed = New-Object 'System.Collections.Generic.List[string]'
    $removed = @(Remove-Marketplaces $fakeClaude ([string]$in.known) 'claude-plugins-official' $failed)
    $result = [pscustomobject]@{ Removed = $removed; Failed = @($failed) }
  }
  'files' { $result = [pscustomobject]@{ Removed = @(Remove-ClaudeAgentsAndRules $in.dir) } }
  'folders' { $result = [pscustomobject]@{ Removed = @(Remove-NamedFolders @($in.names) $in.dir) } }
  'pathentry' { $result = [pscustomobject]@{ Path = (Remove-PathEntry $in.current $in.entry) } }
  'kotlin' { $result = [pscustomobject]@{ Done = @(Remove-KotlinLsp $in.root $in.subKey) } }
  'clean' {
    $template = Read-Utf8 (Join-Path $in.repo 'settings.json') | ConvertFrom-Json
    $r = Invoke-CleanSlate '2026-11-28' $in.claudeDir $in.claudeJson $in.state $in.repo $template $in.root `
      (Join-Path $in.repo 'clean_slate.py') $fakeClaude $fakePython $in.subKey
    $result = [pscustomobject]@{ Skipped = $r.Skipped; Lines = @($r.Lines | ForEach-Object { $_.Kind + ': ' + $_.Text }); Failures = @($r.Failures) }
  }
}
[Console]::Out.Write(($result | ConvertTo-Json -Compress -Depth 10))
"""


def plugin_list(*entries):
    out = []
    for e in entries:
        item = {"id": e[0], "scope": e[1], "enabled": True}
        if len(e) > 2:
            item["projectPath"] = e[2]
        out.append(item)
    return json.dumps(out)


MARKETS = json.dumps([
    {"name": "claude-plugins-official", "source": "github"},
    {"name": "good-css", "source": "github"},
    {"name": "marshell", "source": "directory"},
])


class CleanSlateBase:
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.script = os.path.join(cls.tmp, "driver.ps1")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(DRIVER.replace("{FUNCTIONS}", functions_source()))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.work = tempfile.mkdtemp(dir=self.tmp)
        self.log = os.path.join(self.work, "calls.log")
        with open(self.log, "w", encoding="utf-8"):
            pass

    def run_driver(self, **data):
        data.setdefault("log", self.log)
        data.setdefault("python", sys.executable)
        path = os.path.join(self.work, "in.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        r = run_engine(self.engine, self.script, path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout), self.calls()

    def calls(self):
        with open(self.log, encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip()]

    def mkfile(self, *parts, text="x"):
        path = os.path.join(self.work, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    # Plugins

    def test_user_plugins_are_uninstalled_and_the_rest_is_left_or_reported(self):
        listing = plugin_list(
            ("superpowers@claude-plugins-official", "user"),
            ("good-css@good-css", "user"),
            ("good-css@good-css", "project", "C:\\dev\\Airport"),
            ("local-one@mine", "local", "C:\\dev\\Other"),
            ("cc-plugin-privacy@builtin", "user"),
            ("session-cards@inline", "session"),
            ("humanizer@synced", "synced"),
        )
        out, calls = self.run_driver(mode="plugins", list=listing)
        self.assertEqual(sorted(out["Removed"]), ["good-css@good-css", "superpowers@claude-plugins-official"])
        self.assertEqual(
            sorted(c for c in calls if "uninstall" in c),
            ["claude plugin uninstall good-css@good-css --scope user",
             "claude plugin uninstall superpowers@claude-plugins-official --scope user"],
        )
        self.assertEqual(
            sorted((e["Id"], e["Scope"], e["Path"]) for e in out["Elsewhere"]),
            [("good-css@good-css", "project", "C:\\dev\\Airport"), ("local-one@mine", "local", "C:\\dev\\Other")],
        )
        self.assertEqual(out["Failed"], [])

    def test_a_failed_uninstall_is_reported_and_the_rest_continue(self):
        listing = plugin_list(("a@m", "user"), ("b@m", "user"))
        out, calls = self.run_driver(mode="plugins", list=listing, fail="uninstall a@m")
        self.assertEqual(out["Removed"], ["b@m"])
        self.assertEqual(out["Failed"], ["uninstall a@m"])

    def test_an_unreadable_plugin_list_is_a_failure_and_uninstalls_nothing(self):
        out, calls = self.run_driver(mode="plugins", list="not json")
        self.assertEqual(out["Removed"], [])
        self.assertEqual(len(out["Failed"]), 1)
        self.assertEqual([c for c in calls if "uninstall" in c], [])

    def test_an_empty_plugin_list_does_nothing(self):
        out, calls = self.run_driver(mode="plugins", list="[]")
        self.assertEqual((out["Removed"], out["Elsewhere"], out["Failed"]), ([], [], []))

    def test_a_plugin_list_that_fails_or_prints_nothing_is_a_failure(self):
        for case in ({"list": "", "listExit": 1}, {"list": "", "listExit": 0}, {"list": "[]", "listExit": 1}):
            with self.subTest(**case):
                out, calls = self.run_driver(mode="plugins", **case)
                self.assertEqual(out["Removed"], [])
                self.assertEqual(len(out["Failed"]), 1, out)
                self.assertEqual([c for c in calls if "uninstall" in c], [])

    # Marketplaces

    def test_every_marketplace_but_the_official_one_is_removed(self):
        out, calls = self.run_driver(mode="markets", markets=MARKETS)
        self.assertEqual(out["Removed"], ["good-css", "marshell"])
        self.assertEqual(
            [c for c in calls if "marketplace remove" in c],
            ["claude plugin marketplace remove good-css", "claude plugin marketplace remove marshell"],
        )

    def test_the_known_marketplaces_file_is_the_fallback(self):
        known = self.mkfile("known_marketplaces.json", text=json.dumps({"claude-plugins-official": {}, "good-css": {}}))
        out, calls = self.run_driver(mode="markets", marketsFail="1", known=known)
        self.assertEqual(out["Removed"], ["good-css"])
        self.assertEqual(out["Failed"], [])

    def test_no_list_and_no_known_marketplaces_file_is_a_failure(self):
        missing = os.path.join(self.work, "known_marketplaces.json")
        for case in ({"marketsFail": "1"}, {"markets": ""}):
            with self.subTest(**case):
                out, calls = self.run_driver(mode="markets", known=missing, **case)
                self.assertEqual(out["Removed"], [])
                self.assertEqual(len(out["Failed"]), 1, out)
                self.assertEqual([c for c in calls if "remove" in c], [])

    def test_nothing_to_remove_makes_no_remove_call(self):
        out, calls = self.run_driver(mode="markets", markets=json.dumps([{"name": "claude-plugins-official"}]))
        self.assertEqual(out["Removed"], [])
        self.assertEqual([c for c in calls if "remove" in c], [])

    def test_a_failed_marketplace_removal_is_reported(self):
        out, calls = self.run_driver(mode="markets", markets=MARKETS, fail="remove good-css")
        self.assertEqual(out["Removed"], ["marshell"])
        self.assertEqual(out["Failed"], ["marketplace remove good-css"])

    # Files and folders

    def test_agents_and_the_global_rules_are_deleted_and_the_rest_stays(self):
        self.mkfile("agents", "Explore.md")
        self.mkfile("agents", "worker.md")
        self.mkfile("CLAUDE.md")
        self.mkfile("settings.json")
        self.mkfile("skills", "advisor-switch", "SKILL.md")
        out, _ = self.run_driver(mode="files", dir=self.work)
        self.assertEqual(sorted(out["Removed"]), ["CLAUDE.md", "agents/Explore.md", "agents/worker.md"])
        self.assertEqual(os.listdir(os.path.join(self.work, "agents")), [])
        self.assertTrue(os.path.exists(os.path.join(self.work, "settings.json")))
        self.assertTrue(os.path.exists(os.path.join(self.work, "skills", "advisor-switch", "SKILL.md")))
        out, _ = self.run_driver(mode="files", dir=self.work)
        self.assertEqual(out["Removed"], [])

    def test_only_the_named_folders_are_deleted(self):
        for name in ("underwater-photoshop", "codex", "synced", "advisor-switch"):
            self.mkfile("skills", name, "SKILL.md")
        out, _ = self.run_driver(mode="folders", names=["underwater-photoshop", "find-skills", "codex"], dir=os.path.join(self.work, "skills"))
        self.assertEqual(out["Removed"], ["underwater-photoshop", "codex"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, "skills"))), ["advisor-switch", "synced"])

    # Path

    def test_path_entry_goes_whatever_its_slashes_case_or_trailing_slash(self):
        cur = r"C:\a;%USERPROFILE%\bin;c:/Users/X/kotlin-lsp/BIN/;;C:\z"
        out, _ = self.run_driver(mode="pathentry", current=cur, entry=r"C:\Users\x\kotlin-lsp\bin")
        self.assertEqual(out["Path"], r"C:\a;%USERPROFILE%\bin;C:\z")

    def test_path_without_the_entry_keeps_every_other_entry(self):
        out, _ = self.run_driver(mode="pathentry", current=r"C:\a;%USERPROFILE%\bin", entry=r"C:\nope")
        self.assertEqual(out["Path"], r"C:\a;%USERPROFILE%\bin")

    def scratch_key(self):
        sub = r"Software\claude-setup-test-%s" % uuid.uuid4().hex
        winreg.CreateKey(winreg.HKEY_CURRENT_USER, sub).Close()
        self.addCleanup(lambda: winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub))
        return sub

    def set_path(self, sub, value, kind=winreg.REG_EXPAND_SZ):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "Path", 0, kind, value)
            self.addCleanup(lambda: _delete_value(sub))

    def get_path(self, sub):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as k:
            return winreg.QueryValueEx(k, "Path")

    def test_kotlin_folder_and_its_user_path_entry_go_and_nothing_else(self):
        root = os.path.join(self.work, "Programs", "kotlin-lsp")
        self.mkfile("Programs", "kotlin-lsp", "271.2085.0", "bin", "intellij-server.exe")
        self.mkfile("Programs", "kotlin-lsp", "bin", "kotlin-lsp.cmd")
        sub = self.scratch_key()
        before = r"%USERPROFILE%\bin;" + os.path.join(root, "bin") + r";C:\Tools"
        self.set_path(sub, before)
        out, _ = self.run_driver(mode="kotlin", root=root, subKey=sub)
        self.assertEqual(len(out["Done"]), 2)
        self.assertFalse(os.path.exists(root))
        self.assertEqual(self.get_path(sub), (r"%USERPROFILE%\bin;C:\Tools", winreg.REG_EXPAND_SZ))
        out, _ = self.run_driver(mode="kotlin", root=root, subKey=sub)
        self.assertEqual(out["Done"], [])
        self.assertEqual(self.get_path(sub), (r"%USERPROFILE%\bin;C:\Tools", winreg.REG_EXPAND_SZ))

    def test_a_plain_string_path_stays_a_plain_string(self):
        root = os.path.join(self.work, "Programs", "kotlin-lsp")
        sub = self.scratch_key()
        self.set_path(sub, r"C:\a;" + os.path.join(root, "bin"), winreg.REG_SZ)
        self.run_driver(mode="kotlin", root=root, subKey=sub)
        self.assertEqual(self.get_path(sub), (r"C:\a", winreg.REG_SZ))

    def test_a_path_without_the_entry_is_not_written(self):
        sub = self.scratch_key()
        self.set_path(sub, r"%USERPROFILE%\bin", winreg.REG_SZ)
        root = os.path.join(self.work, "Programs", "kotlin-lsp")
        out, _ = self.run_driver(mode="kotlin", root=root, subKey=sub)
        self.assertEqual(out["Done"], [])
        self.assertEqual(self.get_path(sub), (r"%USERPROFILE%\bin", winreg.REG_SZ))

    # The whole reset

    def machine(self):
        """A PC that still has everything the old setup installed. Returns the paths the driver needs."""
        claude_dir = os.path.join(self.work, ".claude")
        repo = os.path.join(self.work, "clone")
        os.makedirs(repo)
        shutil.copy(os.path.join(ROOT, "settings.json"), repo)
        shutil.copy(os.path.join(ROOT, "clean_slate.py"), repo)
        self.mkfile(".claude", "agents", "Explore.md")
        self.mkfile(".claude", "CLAUDE.md")
        for name in ("underwater-photoshop", "find-skills", "codex", "synced", "advisor-switch"):
            self.mkfile(".claude", "skills", name, "SKILL.md")
        self.mkfile(".claude", "photo-edit", "notes.txt")
        self.mkfile(".claude", "settings.json", text=json.dumps({
            "enabledPlugins": {"superpowers@claude-plugins-official": True},
            "hooks": {"PreToolUse": []}, "deniedMcpServers": [{"serverName": "x"}], "skillOverrides": {"docx": "off"},
            "env": {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet", "CLAUDE_CODE_PLUGIN_DIRS": "C:/old/mods/session-cards;C:/mine"},
            "advisorModel": "opus",
        }))
        state = self.mkfile(".claude", "claude-setup-state.json", text=json.dumps({
            "repo": "C:/clone", "flags": ["-KeepFont"], "claude.ai Adobe": ["C:/dev/x"], "claudeInChromeDefaultEnabled": "off-once",
        }))
        claude_json = self.mkfile(".claude.json", text=json.dumps({
            "claudeInChromeDefaultEnabled": False, "numStartups": 7,
            "projects": {"C:/dev/x": {"disabledMcpServers": ["claude.ai Adobe"], "allowedTools": []}, "C:/dev/y": {}},
        }))
        root = os.path.join(self.work, "Programs", "kotlin-lsp")
        self.mkfile("Programs", "kotlin-lsp", "271.2085.0", "bin", "intellij-server.exe")
        return {"claudeDir": claude_dir, "claudeJson": claude_json, "state": state, "repo": repo, "root": root}

    def load(self, *parts):
        with open(os.path.join(self.work, *parts), encoding="utf-8") as f:
            return json.load(f)

    def test_the_reset_runs_once_and_leaves_a_clean_machine(self):
        paths = self.machine()
        sub = self.scratch_key()
        self.set_path(sub, r"C:\a;" + os.path.join(paths["root"], "bin") + r";C:\z")
        listing = plugin_list(("superpowers@claude-plugins-official", "user"), ("x@y", "project", "C:\\dev\\x"))
        out, calls = self.run_driver(mode="clean", list=listing, markets=MARKETS, subKey=sub, **paths)
        self.assertFalse(out["Skipped"])
        self.assertEqual(out["Failures"], [])
        self.assertIn("claude plugin uninstall superpowers@claude-plugins-official --scope user", calls)
        self.assertIn("claude plugin marketplace remove good-css", calls)
        self.assertNotIn("claude plugin marketplace remove claude-plugins-official", calls)
        self.assertEqual([c for c in calls if "uninstall x@y" in c], [])
        self.assertTrue(any(l.startswith("warn: plugin x@y") and "C:\\dev\\x" in l and "--scope project" in l for l in out["Lines"]), out["Lines"])
        # files
        self.assertEqual(os.listdir(os.path.join(self.work, ".claude", "agents")), [])
        self.assertFalse(os.path.exists(os.path.join(self.work, ".claude", "CLAUDE.md")))
        self.assertEqual(sorted(os.listdir(os.path.join(self.work, ".claude", "skills"))), ["advisor-switch", "synced"])
        self.assertFalse(os.path.exists(os.path.join(self.work, ".claude", "photo-edit")))
        self.assertFalse(os.path.exists(paths["root"]))
        self.assertEqual(self.get_path(sub), (r"C:\a;C:\z", winreg.REG_EXPAND_SZ))
        # settings.json: exactly the template, <repo> resolved, none of the old machine keys
        want = json.loads(read("settings.json"))
        want["env"]["CLAUDE_CODE_PLUGIN_DIRS"] = paths["repo"].replace("\\", "/") + "/mods/session-cards"
        self.assertEqual(self.load(".claude", "settings.json"), want)
        # ~/.claude.json and the state file
        self.assertEqual(self.load(".claude.json"), {
            "numStartups": 7, "projects": {"C:/dev/x": {"allowedTools": []}, "C:/dev/y": {}}})
        self.assertEqual(self.load(".claude", "claude-setup-state.json"), {
            "repo": "C:/clone", "flags": ["-KeepFont"], "cleanSlate": "2026-11-28"})

    def test_a_second_run_does_nothing(self):
        paths = self.machine()
        sub = self.scratch_key()
        self.set_path(sub, r"C:\a")
        self.run_driver(mode="clean", list="[]", markets="[]", subKey=sub, **paths)
        settings = os.path.join(self.work, ".claude", "settings.json")
        with open(settings, "w", encoding="utf-8") as f:
            f.write('{"theme": "mine"}')
        with open(self.log, "w", encoding="utf-8"):
            pass
        out, calls = self.run_driver(mode="clean", list=plugin_list(("a@m", "user")), markets=MARKETS, subKey=sub, **paths)
        self.assertTrue(out["Skipped"])
        self.assertEqual(calls, [])
        self.assertEqual(self.load(".claude", "settings.json"), {"theme": "mine"})

    def test_a_failure_blocks_the_state_key_and_the_next_run_repeats_only_the_failed_step(self):
        paths = self.machine()
        sub = self.scratch_key()
        self.set_path(sub, r"C:\a")
        listing = plugin_list(("a@m", "user"), ("b@m", "user"))
        out, calls = self.run_driver(mode="clean", list=listing, markets="[]", fail="uninstall a@m", subKey=sub, **paths)
        self.assertEqual(out["Failures"], ["clean slate: uninstall a@m"])
        self.assertIn("claude plugin uninstall b@m --scope user", calls)
        state = self.load(".claude", "claude-setup-state.json")
        self.assertNotIn("cleanSlate", state)
        self.assertEqual(sorted(state["cleanSlateSteps"]),
                         ["agents", "claudeJson", "kotlin", "marketplaces", "settings", "skills"])   # all but plugins
        self.assertEqual(os.listdir(os.path.join(self.work, ".claude", "agents")), [])   # the other steps still ran
        self.assertNotIn("enabledPlugins", self.load(".claude", "settings.json"))        # settings.json was still reset
        # What is added between the two runs stays: the second run repeats only the plugin step.
        self.mkfile(".claude", "CLAUDE.md", text="new rules")
        self.mkfile(".claude", "agents", "mine.md")
        self.mkfile(".claude", "settings.json", text='{"theme": "mine"}')
        with open(paths["claudeJson"], "w", encoding="utf-8") as f:
            json.dump({"projects": {"C:/dev/x": {"disabledMcpServers": ["chosen since"]}}}, f)
        with open(self.log, "w", encoding="utf-8"):
            pass
        out, calls = self.run_driver(mode="clean", list=listing, markets=MARKETS, subKey=sub, **paths)
        self.assertFalse(out["Skipped"])
        self.assertEqual(out["Failures"], [])
        self.assertIn("claude plugin uninstall a@m --scope user", calls)
        self.assertEqual([c for c in calls if "marketplace" in c], [])
        self.assertEqual(self.load(".claude", "settings.json"), {"theme": "mine"})
        self.assertEqual(os.listdir(os.path.join(self.work, ".claude", "agents")), ["mine.md"])
        self.assertTrue(os.path.exists(os.path.join(self.work, ".claude", "CLAUDE.md")))
        self.assertEqual(self.load(".claude.json"), {"projects": {"C:/dev/x": {"disabledMcpServers": ["chosen since"]}}})
        for label in ("marketplaces", "agents and CLAUDE.md", "skill folders", "Kotlin language server", "clean_slate.py", "settings.json"):
            self.assertIn("none: %s: done by an earlier run" % label, out["Lines"])
        self.assertEqual(self.load(".claude", "claude-setup-state.json"), {
            "repo": "C:/clone", "flags": ["-KeepFont"], "cleanSlate": "2026-11-28"})

    def test_a_clean_pc_prints_nothing_to_reset(self):
        claude_dir = os.path.join(self.work, ".claude")
        os.makedirs(claude_dir)
        repo = os.path.join(self.work, "clone")
        os.makedirs(repo)
        shutil.copy(os.path.join(ROOT, "settings.json"), repo)
        shutil.copy(os.path.join(ROOT, "clean_slate.py"), repo)
        sub = self.scratch_key()
        self.set_path(sub, r"C:\a")
        out, _ = self.run_driver(
            mode="clean", list="[]", markets="[]", subKey=sub, claudeDir=claude_dir, repo=repo,
            claudeJson=os.path.join(self.work, ".claude.json"), state=os.path.join(claude_dir, "claude-setup-state.json"),
            root=os.path.join(self.work, "Programs", "kotlin-lsp"))
        self.assertEqual(out["Failures"], [])
        nones = [l for l in out["Lines"] if l.startswith("none: ")]
        self.assertEqual(len(nones), 5, out["Lines"])
        self.assertEqual(self.load(".claude", "claude-setup-state.json"), {"cleanSlate": "2026-11-28"})


def _delete_value(sub):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "Path")
    except OSError:
        pass


per_engine(CleanSlateBase, globals())


class InstallerWiringTest(unittest.TestCase):
    def test_the_reset_runs_after_the_backup_and_before_the_copy_and_never_in_check_mode(self):
        text = read("install.ps1")
        start = text.index("if (-not $Check) {")
        block = text[start:]
        self.assertLess(block.index("# 1. Backup"), block.index("Invoke-CleanSlate"))
        self.assertLess(block.index("Invoke-CleanSlate"), block.index("# 2. Copy files"))
        self.assertLess(text.index("function Invoke-CleanSlate"), start)

    def test_the_backup_holds_what_the_reset_deletes(self):
        text = read("install.ps1")
        backup = text[text.index("# 1. Backup"):text.index("# 1b. Clean slate")]
        for needle in ("'CLAUDE.md'", "'claude-setup-state.json'", "'agents'", "'.claude.json'",
                       "'known_marketplaces.json'", "'installed_plugins.json'"):
            self.assertIn(needle, backup)

    def test_only_the_user_path_is_touched(self):
        text = read("install.ps1")
        self.assertNotIn("'Machine'", text.split("function Remove-UserPathEntry")[1].split("function Remove-KotlinLsp")[0])
        self.assertIn("CurrentUser.OpenSubKey($subKey, $true)", text)
        self.assertIn("[Microsoft.Win32.RegistryValueKind]::ExpandString", text)


class CleanConfigTest(unittest.TestCase):
    def test_chrome_key_and_every_projects_disabled_servers_go(self):
        cfg = {"claudeInChromeDefaultEnabled": False, "a": 1,
               "projects": {"p1": {"disabledMcpServers": ["x"], "k": 1}, "p2": {"disabledMcpServers": []}, "p3": {}, "p4": None}}
        lines = clean_slate.clean_config(cfg)
        self.assertEqual(cfg, {"a": 1, "projects": {"p1": {"k": 1}, "p2": {}, "p3": {}, "p4": None}})
        self.assertEqual(len(lines), 2)
        self.assertIn("2 project(s)", lines[1])

    def test_nothing_to_remove(self):
        cfg = {"a": 1, "projects": {"p": {"k": 1}}}
        self.assertEqual(clean_slate.clean_config(cfg), [])
        self.assertEqual(cfg, {"a": 1, "projects": {"p": {"k": 1}}})

    def test_no_projects_and_odd_shapes(self):
        self.assertEqual(clean_slate.clean_config({}), [])
        self.assertEqual(clean_slate.clean_config({"projects": []}), [])
        self.assertEqual(clean_slate.clean_config([]), [])

    def test_state_keys_go_and_the_others_stay(self):
        state = {"repo": "r", "flags": [], "claude.ai Adobe": ["p"], "claudeInChromeDefaultEnabled": "off-once"}
        self.assertEqual(len(clean_slate.clean_state(state)), 2)
        self.assertEqual(state, {"repo": "r", "flags": []})
        self.assertEqual(clean_slate.clean_state(state), [])


class MainTest(unittest.TestCase):
    def setUp(self):
        for stream in (contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            stream.__enter__()   # main prints one line per removal, and its errors to stderr
            self.addCleanup(stream.__exit__, None, None, None)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cfg = os.path.join(self.tmp, ".claude.json")
        self.state = os.path.join(self.tmp, "state.json")

    def write(self, path, text):
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def raw(self, path):
        with open(path, "rb") as f:
            return f.read()

    def test_round_trip_keeps_unrelated_keys_and_stays_utf8(self):
        cfg = {"claudeInChromeDefaultEnabled": False, "name": "Ada\u2714 \u00e9", "n": 12345678901234567890, "f": 1.5,
               "nested": {"a": [1, {"b": None}], "t": True},
               "projects": {"C:/dev/\u05d0": {"disabledMcpServers": ["x"], "history": ["\u2713"]}}}
        self.write(self.cfg, json.dumps(cfg, indent=2, ensure_ascii=False))
        self.write(self.state, json.dumps({"repo": "r", "claude.ai Adobe": []}))
        self.assertEqual(clean_slate.main([self.cfg, self.state]), 0)
        raw = self.raw(self.cfg)
        self.assertIn("Ada\u2714 \u00e9".encode("utf-8"), raw)   # not turned into \u escapes
        want = dict(cfg)
        del want["claudeInChromeDefaultEnabled"]
        want["projects"] = {"C:/dev/\u05d0": {"history": ["\u2713"]}}
        self.assertEqual(json.loads(raw.decode("utf-8")), want)
        self.assertEqual(json.loads(self.raw(self.state)), {"repo": "r"})
        self.assertFalse(os.path.exists(self.cfg + ".lock"))

    def test_a_file_with_nothing_to_remove_is_not_rewritten(self):
        text = '{"a":1,   "projects": {}}'
        self.write(self.cfg, text)
        self.write(self.state, '{"repo":"r"}')
        self.assertEqual(clean_slate.main([self.cfg, self.state]), 0)
        self.assertEqual(self.raw(self.cfg), text.encode())
        self.assertEqual(self.raw(self.state), b'{"repo":"r"}')

    def test_missing_files_are_fine(self):
        self.assertEqual(clean_slate.main([self.cfg, self.state]), 0)
        self.assertFalse(os.path.exists(self.cfg))
        self.assertFalse(os.path.exists(self.state))

    def test_empty_files_are_left_alone(self):
        self.write(self.cfg, "")
        self.write(self.state, "  \n")
        self.assertEqual(clean_slate.main([self.cfg, self.state]), 0)
        self.assertEqual(self.raw(self.cfg), b"")
        self.assertEqual(self.raw(self.state), b"  \n")
        self.assertFalse(os.path.exists(self.cfg + ".lock"))

    def test_invalid_json_is_an_error_and_changes_nothing(self):
        self.write(self.cfg, "{not json")
        self.assertEqual(clean_slate.main([self.cfg, self.state]), 1)
        self.assertEqual(self.raw(self.cfg), b"{not json")
        self.assertFalse(os.path.exists(self.cfg + ".lock"))

    def test_leaves_the_files_alone_while_claude_code_holds_its_lock(self):
        text = '{"claudeInChromeDefaultEnabled": false}'
        self.write(self.cfg, text)
        os.mkdir(self.cfg + ".lock")
        saved = (clean_slate.LOCK_TRIES, clean_slate.LOCK_WAIT, clean_slate.LOCK_STALE)
        clean_slate.LOCK_TRIES, clean_slate.LOCK_WAIT, clean_slate.LOCK_STALE = 2, 0.01, 1000
        self.addCleanup(lambda: setattr_all(saved))
        self.assertEqual(clean_slate.main([self.cfg, self.state]), 1)
        self.assertEqual(self.raw(self.cfg), text.encode())
        self.assertTrue(os.path.isdir(self.cfg + ".lock"))   # not ours: left in place

    def test_takes_over_a_stale_lock_and_releases_it(self):
        self.write(self.cfg, '{"claudeInChromeDefaultEnabled": false, "k": 1}')
        os.mkdir(self.cfg + ".lock")
        old = os.path.getmtime(self.cfg + ".lock") - 60
        os.utime(self.cfg + ".lock", (old, old))
        self.assertEqual(clean_slate.main([self.cfg, self.state]), 0)
        self.assertEqual(json.loads(self.raw(self.cfg)), {"k": 1})
        self.assertFalse(os.path.exists(self.cfg + ".lock"))

    def test_a_lone_surrogate_still_writes_valid_utf8(self):
        self.write(self.cfg, '{"claudeInChromeDefaultEnabled": false, "bad": "\\ud800"}')
        self.assertEqual(clean_slate.main([self.cfg, self.state]), 0)
        self.assertEqual(json.loads(self.raw(self.cfg).decode("utf-8")), {"bad": "\ud800"})

    def test_a_file_with_a_bom_is_read_and_written_back_without_one(self):
        self.write(self.cfg, '﻿{"claudeInChromeDefaultEnabled": false, "k": 1}')
        self.write(self.state, '﻿{"repo": "r", "claude.ai Adobe": []}')
        self.assertEqual(clean_slate.main([self.cfg, self.state]), 0)
        self.assertEqual(self.raw(self.cfg)[:1], b"{")
        self.assertEqual(json.loads(self.raw(self.cfg)), {"k": 1})
        self.assertEqual(json.loads(self.raw(self.state)), {"repo": "r"})

    def test_a_lock_taken_over_during_the_save_still_counts_as_done(self):
        # Claude Code may take over the lock as stale while a slow save runs, and release it before ours is removed.
        self.write(self.cfg, '{"claudeInChromeDefaultEnabled": false, "k": 1}')
        real_save = clean_slate._save

        def save_then_lose_the_lock(path, data):
            real_save(path, data)
            if path == self.cfg:
                os.rmdir(self.cfg + ".lock")

        clean_slate._save = save_then_lose_the_lock
        self.addCleanup(setattr, clean_slate, "_save", real_save)
        self.assertEqual(clean_slate.main([self.cfg, self.state]), 0)
        self.assertEqual(json.loads(self.raw(self.cfg)), {"k": 1})

    def test_a_lock_claude_code_took_over_during_the_save_is_left_to_it(self):
        self.write(self.cfg, '{"claudeInChromeDefaultEnabled": false, "k": 1}')
        real_save = clean_slate._save
        lock = self.cfg + ".lock"

        def save_while_claude_code_takes_over(path, data):
            real_save(path, data)
            if path == self.cfg:
                os.rmdir(lock)
                os.mkdir(lock)
                later = time.time() + 5
                os.utime(lock, (later, later))   # proper-lockfile refreshes the mtime of the lock it holds

        clean_slate._save = save_while_claude_code_takes_over
        self.addCleanup(setattr, clean_slate, "_save", real_save)
        self.addCleanup(lambda: os.path.isdir(lock) and os.rmdir(lock))
        self.assertEqual(clean_slate.main([self.cfg, self.state]), 0)
        self.assertTrue(os.path.isdir(lock))   # Claude Code's lock: not ours to remove


def setattr_all(saved):
    clean_slate.LOCK_TRIES, clean_slate.LOCK_WAIT, clean_slate.LOCK_STALE = saved


if __name__ == "__main__":
    unittest.main()
