"""Copies ~/.claude/projects into OneDrive (one folder per machine) and digests other machines' sessions.

  sync [--detach]                      copy new and changed files; never deletes, never writes to ~/.claude/projects
  check                                SessionStart hook: one line when other machines have new sessions here
  extract [--cwd PATH] [--limit N]     write those sessions' prompts and replies to ~/.claude/catch-up-digest.md
  mark                                 record the extracted sessions as read

Projects match across machines by path, or by git remote when the repo lives elsewhere: each sync writes
<MACHINE>/projects-index.json with every project folder's working directory and origin URL, read from .git/config
(git is never run, and no repo is written to).

Stdlib only: hooks run it as `python -I -S`.
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
DEFAULT_LIMIT = 10
MSG_CAP = 800                    # chars per prompt or reply
SESSION_CAP, HEAD, TAIL = 8000, 2000, 6000   # a longer session keeps its start and its end
NOTHING = "Nothing new from other machines for this project."
REMINDER = re.compile(r"<system-reminder>.*?(?:</system-reminder>|\Z)", re.S)   # an unclosed one runs to the end
CWD = re.compile(r'"cwd":\s*"((?:[^"\\]|\\.)*)"')


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
    """Copies files under src that are missing in dst or differ in size or mtime (copy2 keeps mtime). Returns (copied, errors)."""
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
                    if dt.st_size == st.st_size and dt.st_mtime_ns == st.st_mtime_ns:
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
    """An OS lock on path's first byte, or None when another sync holds it. The OS drops it when the holder exits,
    so a crashed sync never leaves a stale lock behind."""
    fh = open(path, "a+b")
    try:
        fh.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def release(fh):
    try:
        fh.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    fh.close()


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
    rerun = CLAUDE_DIR / "history-sync.rerun"
    lock = take_lock(CLAUDE_DIR / "history-sync.lock")
    if lock is None:
        rerun.touch()   # the running copy may have passed files this session has since written
        return 0
    try:
        mine = root / machine_name()
        copied, errors = copy_new(CLAUDE_DIR / "projects", mine / "projects")
        if rerun.exists():
            rerun.unlink()
            more = copy_new(CLAUDE_DIR / "projects", mine / "projects")
            copied, errors = copied + more[0], errors + more[1]
        try:
            write_index(CLAUDE_DIR / "projects", mine / "projects-index.json")
        except OSError:
            errors += 1
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        (CLAUDE_DIR / "history-sync.log").write_text(f"{stamp} copied {copied} errors {errors}\n", encoding="utf-8")
    finally:
        release(lock)
    return 0


# ---- finding other machines' sessions ----

def mangle(path):
    """Claude Code's project folder name for a path: every char outside [A-Za-z0-9] becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def native(cwd):
    return re.sub(r"^/([A-Za-z])(/|$)", r"\1:/", cwd) if os.name == "nt" else cwd   # Git Bash /c/dev is C:/dev


def last_segment(path):
    return re.split(r"[\\/]", (path or "").rstrip("\\/"))[-1]


def normalize_remote(url):
    """host/owner/repo, lowercase, for any of git's URL forms (ssh, scp-style, https with or without .git)."""
    u = re.sub(r"\.git$", "", url.strip().lower().rstrip("/"))
    u = re.sub(r"^[a-z][a-z0-9+.-]*://", "", u)
    u = re.sub(r"^[^@/]*@", "", u)
    return re.sub(r"^([^/:]+):(?!\d+/)", r"\1/", u)


def repo_remote(path):
    """origin's normalized URL for the git repo holding path (worktrees included), or None. Reads files only."""
    try:
        p = Path(path).resolve()
        for d in (p, *p.parents):
            dot = d / ".git"
            if dot.is_dir():
                gitdir = dot
                break
            if dot.is_file():
                m = re.match(r"gitdir:\s*(.+)", dot.read_text(encoding="utf-8", errors="replace").strip())
                if not m:
                    return None
                gitdir = (d / m.group(1).strip()).resolve()
                common = gitdir / "commondir"
                if common.is_file():
                    gitdir = (gitdir / common.read_text(encoding="utf-8").strip()).resolve()
                break
        else:
            return None
        config = (gitdir / "config").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    section = re.search(r'^\s*\[remote\s+"origin"\]\s*$(.*?)(?=^\s*\[|\Z)', config, re.M | re.S)
    url = section and re.search(r"^\s*url\s*=\s*(.+?)\s*$", section.group(1), re.M)
    return normalize_remote(url.group(1)) if url else None


def project_cwd(proj):
    """The working directory recorded in the project folder's transcripts, or None before the first one."""
    for f in sorted(proj.glob("*.jsonl"))[:3]:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for _, raw in zip(range(50), fh):
                    m = CWD.search(raw)
                    if m:
                        return json.loads('"' + m.group(1) + '"')
        except (OSError, ValueError):
            continue
    return None


def load_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def write_index(projects, path):
    """{folder: {cwd, remote}} for this machine's project folders. Known folders keep their entry; the file is
    rewritten only when a folder is added or its working directory first shows up, so OneDrive uploads it rarely."""
    old = load_json(path)
    new = {}
    for d in sorted(d for d in projects.iterdir() if d.is_dir()):
        entry = old.get(d.name)
        if isinstance(entry, dict) and entry.get("cwd"):
            new[d.name] = entry
        else:
            cwd = project_cwd(d)
            new[d.name] = {"cwd": cwd, "remote": repo_remote(cwd) if cwd else None}
    if new != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, new)


def match_project_dirs(projects, cwd, index=None, remote=None):
    """The other machine's folders for this project. Same path (unless both sides are repos with different remotes),
    plus every folder of the same git repo wherever it lives, worktrees included. Outside a repo, where the paths
    differ: folders, also outside a repo, whose recorded path ends in the same folder name."""
    index = index or {}
    try:
        dirs = sorted(d for d in projects.iterdir() if d.is_dir())
    except OSError:
        return []
    cwd = native(cwd)
    exact = mangle(cwd).lower()

    def theirs(d):
        entry = index.get(d.name)
        return entry if isinstance(entry, dict) else {}

    hits = [d for d in dirs
            if (d.name.lower() == exact and not (remote and theirs(d).get("remote") not in (None, remote)))
            or (remote and theirs(d).get("remote") == remote)]
    if hits or remote:
        return hits
    last = last_segment(cwd).lower()
    if not last or last.endswith(":"):
        return []
    return [d for d in dirs if theirs(d).get("cwd") and not theirs(d).get("remote")
            and last_segment(theirs(d)["cwd"]).lower() == last]


def new_sessions(root, me, cwd, read):
    out = []
    try:
        machines = [m for m in root.iterdir() if m.is_dir() and m.name.lower() != me.lower()]
    except OSError:
        return []
    remote = repo_remote(native(cwd))
    for m in sorted(machines):
        for proj in match_project_dirs(m / "projects", cwd, load_json(m / "projects-index.json"), remote):
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
    state = load_json(CLAUDE_DIR / "catch-up-state.json")
    return {"read": dict(state.get("read") or {}), "pending": dict(state.get("pending") or {})}


def save_state(state):
    write_json(CLAUDE_DIR / "catch-up-state.json", state)


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
    indexes = {m: load_json(root / m / "projects-index.json") for m in {s.machine for s in chosen}}

    def where(s):   # the other machine's path for the project, so its file paths aren't read as this machine's
        entry = indexes[s.machine].get(s.path.parent.name)
        return (entry.get("cwd") if isinstance(entry, dict) else None) or s.path.parent.name

    parts = [f"# {s.machine} · {where(s)}\n{digest_session(s.path)}" for s in chosen]
    digest.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    state["pending"] = {s.key: s.mtime_ns for s in chosen}   # the rest stay unread
    save_state(state)
    line = f"digest: {digest}; {len(chosen)} session{'s' if len(chosen) != 1 else ''} from {machines_of(chosen)}"
    if len(sessions) > len(chosen):
        line += f" ({len(sessions) - len(chosen)} older left for the next /catch-up)"
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
        return cmd_extract(option(args, "--cwd", os.getcwd()), max(1, int(option(args, "--limit", DEFAULT_LIMIT))))
    if cmd == "mark":
        return cmd_mark()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
