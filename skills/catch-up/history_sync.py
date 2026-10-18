"""Copies ~/.claude/projects into OneDrive (one folder per machine) and digests other machines' sessions.

  sync [--detach]                      copy new and changed files; never deletes, never writes to ~/.claude/projects
  check                                SessionStart hook: one line when other machines have new sessions here
  extract [--cwd PATH] [--limit N]     write those sessions' prompts and replies to ~/.claude/catch-up-digest.md
  mark                                 record the extracted sessions as read

Stdlib only: hooks run it as `python -S`.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

CLAUDE_DIR = Path.home() / ".claude"
LOCK_STALE_S = 2 * 3600
MTIME_SLACK_NS = 2_000_000_000   # OneDrive and FAT round mtimes; a copy is "changed" only past this
DEFAULT_LIMIT = 10
MSG_CAP = 800                    # chars per prompt or reply
SESSION_CAP, HEAD, TAIL = 8000, 2000, 6000   # a longer session keeps its start and its end
NOTHING = "Nothing new from other machines for this project."
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


class Session(NamedTuple):
    key: str        # path under the sync root, forward slashes: DESKTOP/projects/C--dev/<id>.jsonl
    path: Path
    machine: str
    mtime_ns: int


def sync_root():
    """<OneDrive>/Projects/CLI Conversation History, or None when OneDrive is unset or has no Projects folder."""
    onedrive = os.environ.get("OneDrive")
    if not onedrive or not (Path(onedrive) / "Projects").is_dir():
        return None
    return Path(onedrive) / "Projects" / "CLI Conversation History"


def machine_name():
    return os.environ.get("COMPUTERNAME") or platform.node() or "unknown"


# ---- sync ----

def copy_new(src, dst):
    """Copies files under src that are missing in dst, differ in size, or are newer. Returns (copied, errors)."""
    copied = errors = 0
    for dirpath, _dirs, files in os.walk(src):
        rel = Path(dirpath).relative_to(src)
        for name in files:
            s, d = Path(dirpath) / name, dst / rel / name
            part = d.with_name(d.name + ".part")
            try:
                st = s.stat()
                try:
                    dt = d.stat()
                    if dt.st_size == st.st_size and st.st_mtime_ns <= dt.st_mtime_ns + MTIME_SLACK_NS:
                        continue
                except FileNotFoundError:
                    pass
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, part)
                os.replace(part, d)
                copied += 1
            except OSError:
                errors += 1
                try:
                    part.unlink()
                except OSError:
                    pass
    return copied, errors


def take_lock(path):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            if time.time() - path.stat().st_mtime < LOCK_STALE_S:
                return False
            path.unlink()
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def detach():
    """Re-runs `sync` in a process that outlives the hook, so a session never waits for the copy."""
    cmd = [sys.executable, "-I", "-S", os.path.abspath(__file__), "sync"]
    io = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if os.name != "nt":
        subprocess.Popen(cmd, start_new_session=True, **io)
        return
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:   # leave Claude Code's job object too, when it allows that, so closing the terminal doesn't kill the copy
        subprocess.Popen(cmd, creationflags=flags | 0x01000000, **io)   # CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        subprocess.Popen(cmd, creationflags=flags, **io)


def cmd_sync(background):
    root = sync_root()
    if root is None:
        return 0
    if background:
        detach()
        return 0
    lock = CLAUDE_DIR / "history-sync.lock"
    if not take_lock(lock):
        return 0
    try:
        copied, errors = copy_new(CLAUDE_DIR / "projects", root / machine_name() / "projects")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        (CLAUDE_DIR / "history-sync.log").write_text(f"{stamp} copied {copied} errors {errors}\n", encoding="utf-8")
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    return 0


# ---- finding other machines' sessions ----

def mangle(path):
    """Claude Code's project folder name for a path: every char outside [A-Za-z0-9] becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def match_project_dirs(projects, cwd):
    """The project folder for cwd; when the other machine keeps the repo elsewhere, folders ending in its last segment."""
    try:
        dirs = [d for d in projects.iterdir() if d.is_dir()]
    except OSError:
        return []
    cwd = re.sub(r"^/([A-Za-z])(/|$)", r"\1:/", cwd)   # Git Bash form /c/dev means C:/dev
    exact = mangle(cwd).lower()
    hits = [d for d in dirs if d.name.lower() == exact]
    if hits:
        return hits
    last = re.split(r"[\\/]", cwd.rstrip("\\/"))[-1]
    if not last or last.endswith(":"):
        return []
    base = mangle(last).lower()
    return sorted(d for d in dirs if d.name.lower() == base or d.name.lower().endswith("-" + base))


def new_sessions(root, me, cwd, read):
    out = []
    try:
        machines = [m for m in root.iterdir() if m.is_dir() and m.name.lower() != me.lower()]
    except OSError:
        return []
    for m in sorted(machines):
        for proj in match_project_dirs(m / "projects", cwd):
            for f in sorted(proj.glob("*.jsonl")):
                try:
                    mtime = f.stat().st_mtime_ns
                except OSError:
                    continue
                key = f.relative_to(root).as_posix()
                if read.get(key) != mtime:
                    out.append(Session(key, f, m.name, mtime))
    return out


def load_state():
    try:
        state = json.loads((CLAUDE_DIR / "catch-up-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    return {"read": dict(state.get("read") or {}), "pending": dict(state.get("pending") or {})}


def save_state(state):
    (CLAUDE_DIR / "catch-up-state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")


def machines_of(sessions):
    return ", ".join(sorted({s.machine for s in sessions}))


def hook_cwd():
    data = {}
    if not sys.stdin.isatty():
        try:
            data = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            pass
    return (data.get("cwd") if isinstance(data, dict) else None) or os.getcwd()


def cmd_check(cwd):
    root = sync_root()
    if root is None:
        return 0
    sessions = new_sessions(root, machine_name(), cwd, load_state()["read"])
    if len(sessions) == 1:
        print(f"1 new session from {machines_of(sessions)} in this project since your last catch-up. "
              "Run /catch-up to read it.")
    elif sessions:
        print(f"{len(sessions)} new sessions from {machines_of(sessions)} in this project since your last catch-up. "
              "Run /catch-up to read them.")
    return 0


# ---- digest ----

def clip(text, cap):
    return text if len(text) <= cap else text[:cap] + " […]"


def record_texts(r):
    content = (r.get("message") or {}).get("content")
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return []


def digest_session(path):
    """The session's prompts and replies, without tool calls, tool output, thinking or injected reminders."""
    lines, first, last = [], None, None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                r = json.loads(raw)
            except ValueError:
                continue
            kind = r.get("type") if isinstance(r, dict) else None
            if kind not in ("user", "assistant") or r.get("isMeta") or r.get("isSidechain"):
                continue
            for text in record_texts(r):
                text = REMINDER.sub("", text).strip()
                command = re.search(r"<command-name>(.*?)</command-name>", text)
                if command:
                    args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
                    text = (command.group(1) + " " + (args.group(1) if args else "")).strip()
                elif text.startswith("<local-command"):
                    continue
                if not text:
                    continue
                lines.append(("USER: " if kind == "user" else "CLAUDE: ") + clip(text, MSG_CAP))
                first = first or r.get("timestamp")
                last = r.get("timestamp") or last
    body = "\n".join(lines) or "(no prompts)"
    if len(body) > SESSION_CAP:
        body = body[:HEAD] + f"\n[… {len(body) - HEAD - TAIL} chars cut …]\n" + body[-TAIL:]
    return f"## {path.stem} · {first or '?'} → {last or '?'}\n{body}"


def cmd_extract(cwd, limit):
    root = sync_root()
    if root is None:
        print("No OneDrive history folder (OneDrive unset or no OneDrive\\Projects).")
        return 0
    state = load_state()
    sessions = sorted(new_sessions(root, machine_name(), cwd, state["read"]), key=lambda s: s.mtime_ns)
    if not sessions:
        print(NOTHING)
        return 0
    chosen = sessions[-limit:]
    digest = CLAUDE_DIR / "catch-up-digest.md"
    parts = [f"# {s.machine} · {s.path.parent.name}\n{digest_session(s.path)}" for s in chosen]
    digest.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    state["pending"] = {s.key: s.mtime_ns for s in sessions}
    save_state(state)
    line = f"digest: {digest}; {len(chosen)} session{'s' if len(chosen) != 1 else ''} from {machines_of(chosen)}"
    if len(sessions) > len(chosen):
        line += f" ({len(sessions) - len(chosen)} older not included)"
    print(line)
    return 0


def cmd_mark():
    state = load_state()
    state["read"].update(state["pending"])
    n, state["pending"] = len(state["pending"]), {}
    save_state(state)
    print(f"marked {n} sessions read")
    return 0


def option(args, name, default):
    return args[args.index(name) + 1] if name in args[:-1] else default


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    cmd = args[0] if args else ""
    if cmd in ("sync", "check"):
        try:   # hooks: never fail or print an error into a session
            return cmd_sync("--detach" in args) if cmd == "sync" else cmd_check(hook_cwd())
        except Exception:
            return 0
    if cmd == "extract":
        return cmd_extract(option(args, "--cwd", os.getcwd()), int(option(args, "--limit", DEFAULT_LIMIT)))
    if cmd == "mark":
        return cmd_mark()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
