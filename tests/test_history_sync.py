import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "catch-up"))

import history_sync as hs  # noqa: E402


def write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def rec(kind, content, **extra):
    return json.dumps({"type": kind, "timestamp": extra.pop("ts", "2026-10-18T09:00:00Z"),
                       "message": {"content": content}, **extra})


class Env(unittest.TestCase):
    """A temp ~/.claude and a temp OneDrive with Projects/, this machine named ROTEM."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.claude = self.tmp / "claude"
        (self.claude / "projects").mkdir(parents=True)
        self.onedrive = self.tmp / "OneDrive"
        (self.onedrive / "Projects").mkdir(parents=True)
        self.root = self.onedrive / "Projects" / "CLI Conversation History"
        for p in (mock.patch.object(hs, "CLAUDE_DIR", self.claude),
                  mock.patch.dict(os.environ, {"OneDrive": str(self.onedrive), "COMPUTERNAME": "ROTEM"})):
            p.start()
            self.addCleanup(p.stop)

    def run_main(self, args, stdin=""):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin)), redirect_stdout(out):
            code = hs.main(args)
        return code, out.getvalue().strip()

    def other_session(self, name, lines, machine="DESKTOP", project="C--dev"):
        return write(self.root / machine / "projects" / project / f"{name}.jsonl", "\n".join(lines) + "\n")


class CopyTest(Env):
    def setUp(self):
        super().setUp()
        self.src, self.dst = self.tmp / "src", self.tmp / "dst"

    def test_copies_new_files_keeping_tree(self):
        write(self.src / "C--dev" / "a.jsonl", "aaa")
        write(self.src / "C--dev" / "s1" / "subagents" / "b.jsonl", "bbb")
        self.assertEqual(hs.copy_new(self.src, self.dst), (2, 0))
        self.assertEqual((self.dst / "C--dev" / "a.jsonl").read_text(), "aaa")
        self.assertEqual((self.dst / "C--dev" / "s1" / "subagents" / "b.jsonl").read_text(), "bbb")

    def test_second_run_copies_nothing(self):
        write(self.src / "a.jsonl")
        hs.copy_new(self.src, self.dst)
        self.assertEqual(hs.copy_new(self.src, self.dst), (0, 0))

    def test_updates_grown_file(self):
        f = write(self.src / "a.jsonl", "one\n")
        hs.copy_new(self.src, self.dst)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write("two\n")
        self.assertEqual(hs.copy_new(self.src, self.dst), (1, 0))
        self.assertEqual((self.dst / "a.jsonl").read_text(), "one\ntwo\n")

    def test_same_size_rewrite_soon_after_copy_is_copied(self):
        f = write(self.src / "a.md", "aaa")
        hs.copy_new(self.src, self.dst)
        t = f.stat().st_mtime_ns + 1_000_000_000
        f.write_text("bbb")
        os.utime(f, ns=(t, t))
        self.assertEqual(hs.copy_new(self.src, self.dst), (1, 0))
        self.assertEqual((self.dst / "a.md").read_text(), "bbb")

    def test_never_deletes_extra_destination_files(self):
        write(self.src / "a.jsonl")
        old = write(self.dst / "old.jsonl")
        hs.copy_new(self.src, self.dst)
        self.assertTrue(old.exists())

    def test_never_writes_to_source(self):
        write(self.src / "a.jsonl", "aaa")
        before = sorted((p.relative_to(self.src), p.stat().st_mtime_ns) for p in self.src.rglob("*"))
        hs.copy_new(self.src, self.dst)
        after = sorted((p.relative_to(self.src), p.stat().st_mtime_ns) for p in self.src.rglob("*"))
        self.assertEqual(before, after)

    def test_missing_source_file_counts_error_no_part_left(self):
        write(self.src / "a.jsonl")
        write(self.src / "b.jsonl")
        real = shutil.copy2

        def flaky(s, d, *a, **k):
            if Path(s).name == "b.jsonl":
                Path(d).write_text("partial")
                raise FileNotFoundError(s)
            return real(s, d, *a, **k)

        with mock.patch.object(hs.shutil, "copy2", flaky):
            self.assertEqual(hs.copy_new(self.src, self.dst), (1, 1))
        self.assertTrue((self.dst / "a.jsonl").exists())
        self.assertEqual(list(self.dst.rglob("*.part")), [])

    def test_sync_root_none_without_onedrive(self):
        with mock.patch.dict(os.environ):
            del os.environ["OneDrive"]
            self.assertIsNone(hs.sync_root())
        with mock.patch.dict(os.environ, {"OneDrive": str(self.tmp / "empty")}):
            self.assertIsNone(hs.sync_root())

    def test_sync_copies_into_machine_folder(self):
        write(self.claude / "projects" / "C--dev" / "a.jsonl", "aaa")
        self.assertEqual(self.run_main(["sync"])[0], 0)
        self.assertEqual((self.root / "ROTEM" / "projects" / "C--dev" / "a.jsonl").read_text(), "aaa")
        self.assertIn("copied 1 errors 0", (self.claude / "history-sync.log").read_text())
        self.assertFalse((self.claude / "history-sync.lock").exists())

    def test_sync_exits_zero_when_no_root(self):
        with mock.patch.dict(os.environ, {"OneDrive": str(self.tmp / "nowhere")}):
            self.assertEqual(self.run_main(["sync"]), (0, ""))
        self.assertFalse((self.tmp / "nowhere").exists())

    def test_lock_blocks_second_sync(self):
        write(self.claude / "projects" / "a.jsonl")
        lock = write(self.claude / "history-sync.lock", "123")
        self.run_main(["sync"])
        self.assertFalse((self.root / "ROTEM").exists())
        old = time.time() - 3 * 3600
        os.utime(lock, (old, old))
        self.run_main(["sync"])
        self.assertTrue((self.root / "ROTEM" / "projects" / "a.jsonl").exists())


    def test_locked_sync_asks_holder_to_run_again(self):
        write(self.claude / "history-sync.lock", "123")
        self.run_main(["sync"])
        self.assertTrue((self.claude / "history-sync.rerun").exists())
        (self.claude / "history-sync.lock").unlink()
        calls = []
        with mock.patch.object(hs, "copy_new", lambda s, d: calls.append(1) or (0, 0)):
            self.run_main(["sync"])
        self.assertEqual(len(calls), 2)
        self.assertFalse((self.claude / "history-sync.rerun").exists())


class CheckTest(Env):
    def test_mangle(self):
        self.assertEqual(hs.mangle(r"C:\Users\HighL\.claude"), "C--Users-HighL--claude")
        self.assertEqual(hs.mangle(r"C:\dev"), "C--dev")

    def test_match_exact_first(self):
        (self.tmp / "p" / "C--dev").mkdir(parents=True)
        (self.tmp / "p" / "C--dev-bookandry").mkdir()
        self.assertEqual([d.name for d in hs.match_project_dirs(self.tmp / "p", r"C:\dev")], ["C--dev"])
        self.assertEqual([d.name for d in hs.match_project_dirs(self.tmp / "p", "/c/dev")], ["C--dev"])

    def test_match_falls_back_to_last_segment(self):
        (self.tmp / "p" / "C--dev-bookandry").mkdir(parents=True)
        self.assertEqual([d.name for d in hs.match_project_dirs(self.tmp / "p", r"D:\work\bookandry")],
                         ["C--dev-bookandry"])
        self.assertEqual(hs.match_project_dirs(self.tmp / "p", r"D:\work\other"), [])
        self.assertEqual(hs.match_project_dirs(self.tmp / "p", "D:\\"), [])

    def test_new_sessions_excludes_this_machine_case_insensitive(self):
        self.other_session("a", ["{}"], machine="ROTEM")
        self.other_session("b", ["{}"])
        got = hs.new_sessions(self.root, "rotem", r"C:\dev", {})
        self.assertEqual([(s.machine, s.path.stem) for s in got], [("DESKTOP", "b")])

    def test_new_sessions_only_top_level_jsonl(self):
        proj = self.root / "DESKTOP" / "projects" / "C--dev"
        write(proj / "s1" / "subagents" / "x.jsonl")
        write(proj / "memory" / "m.md")
        self.assertEqual(hs.new_sessions(self.root, "ROTEM", r"C:\dev", {}), [])

    def test_new_sessions_skips_already_read(self):
        f = self.other_session("b", ["{}"])
        key = "DESKTOP/projects/C--dev/b.jsonl"
        self.assertEqual(hs.new_sessions(self.root, "ROTEM", r"C:\dev", {key: f.stat().st_mtime_ns}), [])
        self.assertEqual(len(hs.new_sessions(self.root, "ROTEM", r"C:\dev", {key: 1})), 1)

    def test_check_prints_notice(self):
        self.other_session("b", ["{}"])
        code, out = self.run_main(["check"], json.dumps({"cwd": "C:\\dev"}))
        self.assertEqual(code, 0)
        self.assertEqual(out, "1 new session from DESKTOP in this project since your last catch-up. "
                              "Run /catch-up to read it.")
        self.other_session("c", ["{}"], machine="WORK")
        _, out = self.run_main(["check"], json.dumps({"cwd": "C:\\dev"}))
        self.assertEqual(out, "2 new sessions from DESKTOP, WORK in this project since your last catch-up. "
                              "Run /catch-up to read them.")

    def test_check_silent_when_nothing_or_no_root(self):
        self.assertEqual(self.run_main(["check"], json.dumps({"cwd": "C:\\dev"})), (0, ""))
        self.other_session("b", ["{}"])
        with mock.patch.dict(os.environ):
            del os.environ["OneDrive"]
            self.assertEqual(self.run_main(["check"], json.dumps({"cwd": "C:\\dev"})), (0, ""))


class DigestTest(Env):
    def test_digest_keeps_prompts_and_replies(self):
        f = self.other_session("s1", [
            rec("user", "fix the login bug", ts="2026-10-17T10:00:00Z"),
            rec("assistant", [{"type": "text", "text": "Fixed it in auth.py"}], ts="2026-10-17T10:05:00Z"),
        ])
        out = hs.digest_session(f)
        self.assertIn("## s1 · 2026-10-17T10:00:00Z → 2026-10-17T10:05:00Z", out)
        self.assertIn("USER: fix the login bug", out)
        self.assertIn("CLAUDE: Fixed it in auth.py", out)

    def test_digest_skips_noise(self):
        f = self.other_session("s1", [
            rec("user", "keep <system-reminder>SECRET-REMINDER</system-reminder>me"),
            rec("user", [{"type": "tool_result", "content": "TOOL-OUTPUT"}]),
            rec("assistant", [{"type": "thinking", "thinking": "THINKING"},
                              {"type": "tool_use", "name": "Bash", "input": {"command": "TOOL-CALL"}}]),
            rec("user", "META", isMeta=True),
            rec("assistant", [{"type": "text", "text": "SIDECHAIN"}], isSidechain=True),
            rec("attachment", "ATTACHMENT"),
        ])
        out = hs.digest_session(f)
        self.assertIn("USER: keep me", out)
        for noise in ("SECRET-REMINDER", "TOOL-OUTPUT", "THINKING", "TOOL-CALL", "META", "SIDECHAIN", "ATTACHMENT"):
            self.assertNotIn(noise, out)

    def test_digest_survives_bad_lines(self):
        f = self.other_session("s1", [rec("user", "first"), "not json", rec("user", "second"), '{"type": "us'])
        out = hs.digest_session(f)
        self.assertIn("USER: first", out)
        self.assertIn("USER: second", out)

    def test_digest_caps_long_session(self):
        f = self.other_session("s1", [rec("user", f"prompt {i} " + "y" * 500) for i in range(40)])
        out = hs.digest_session(f)
        body = out.split("\n", 1)[1]
        self.assertLess(len(body), hs.SESSION_CAP + 100)
        self.assertRegex(body, r"\[… \d+ chars cut …\]")
        self.assertIn("prompt 0 ", body)
        self.assertIn("prompt 39 ", body)

    def test_extract_limits_and_leaves_older_unread(self):
        for i in range(20):
            f = self.other_session(f"s{i:02d}", [rec("user", f"task {i}")])
            os.utime(f, (1_000_000 + i, 1_000_000 + i))
        code, out = self.run_main(["extract", "--cwd", r"C:\dev", "--limit", "15"])
        self.assertEqual(code, 0)
        self.assertIn("15 sessions from DESKTOP", out)
        self.assertIn("(5 older left for the next /catch-up)", out)
        digest = (self.claude / "catch-up-digest.md").read_text(encoding="utf-8")
        self.assertNotIn("task 4\n", digest)
        self.assertLess(digest.index("task 5"), digest.index("task 19"))
        self.assertEqual(len(hs.load_state()["pending"]), 15)
        self.run_main(["mark"])
        _, out = self.run_main(["extract", "--cwd", r"C:\dev", "--limit", "15"])
        self.assertIn("5 sessions from DESKTOP", out)
        self.assertIn("task 0", (self.claude / "catch-up-digest.md").read_text(encoding="utf-8"))

    def test_mark_moves_pending_to_read(self):
        self.other_session("s1", [rec("user", "hello")])
        self.run_main(["extract", "--cwd", r"C:\dev"])
        self.run_main(["mark"])
        self.assertEqual(hs.load_state()["pending"], {})
        self.assertEqual(self.run_main(["check"], json.dumps({"cwd": "C:\\dev"})), (0, ""))

    def test_extract_nothing_new(self):
        code, out = self.run_main(["extract", "--cwd", r"C:\dev"])
        self.assertEqual((code, out), (0, "Nothing new from other machines for this project."))
        self.assertFalse((self.claude / "catch-up-digest.md").exists())


if __name__ == "__main__":
    unittest.main()
