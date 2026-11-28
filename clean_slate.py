"""Takes the per-user toggles the old installer wrote out of ~/.claude.json and the state file, once (install.ps1's clean slate).

Usage: python clean_slate.py <~/.claude.json> <state.json>

~/.claude.json: deletes the top-level claudeInChromeDefaultEnabled (the old installer set it to false) and
disabledMcpServers from every entry under projects (the old installer put the claude.ai Adobe connector there). Every
other key stays as it is, and the file stays UTF-8.
state.json: deletes the keys the old installer kept there ("claude.ai Adobe", "claudeInChromeDefaultEnabled").
Prints one line per thing removed. A file that is missing, empty (a save cut short) or has nothing to remove is not
written, and counts as cleaned.
"""
import json
import os
import sys
import time

CHROME_KEY = "claudeInChromeDefaultEnabled"
PROJECT_KEY = "disabledMcpServers"
STATE_KEYS = ("claude.ai Adobe", CHROME_KEY)

# Claude Code saves ~/.claude.json under a proper-lockfile lock: a "<file>.lock" directory, stale after 10s.
# Holding it keeps a running session from saving between our read and our write and losing one of the two.
LOCK_TRIES = 50
LOCK_WAIT = 0.1
LOCK_STALE = 10


def clean_config(cfg):
    """Removes the toggles from cfg in place. Returns the lines to print (none when there was nothing to remove)."""
    done = []
    if isinstance(cfg, dict) and CHROME_KEY in cfg:
        del cfg[CHROME_KEY]
        done.append("removed %s from ~/.claude.json" % CHROME_KEY)
    projects = cfg.get("projects") if isinstance(cfg, dict) else None
    count = 0
    if isinstance(projects, dict):
        for project in projects.values():
            if isinstance(project, dict) and PROJECT_KEY in project:
                del project[PROJECT_KEY]
                count += 1
    if count:
        done.append("removed %s from %d project(s) in ~/.claude.json" % (PROJECT_KEY, count))
    return done


def clean_state(state):
    """Removes the old installer's keys from state in place. Returns the lines to print."""
    done = []
    if isinstance(state, dict):
        for key in STATE_KEYS:
            if key in state:
                del state[key]
                done.append("removed %s from the state file" % key)
    return done


def _load(path):
    # utf-8-sig also reads a file a hand edit or Windows PowerShell 5.1 saved with a BOM; _save writes none.
    # An empty file (a save cut short) holds nothing to remove, the same as a missing one, so it is left alone.
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except FileNotFoundError:
        return None
    return json.loads(text) if text.strip() else None


def _dumps(data):
    # Claude Code writes non-ASCII as it is (JSON.stringify); keep that so the file's other values do not change spelling.
    # A lone surrogate cannot be encoded as UTF-8, so that file falls back to \u escapes (the same value).
    text = json.dumps(data, indent=2, ensure_ascii=False)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = json.dumps(data, indent=2)
    return text


def _save(path, data):
    # Write beside the target, then swap, so a running Claude Code never reads half a file. The swap is retried
    # while another process (antivirus, the indexer) briefly holds the target open.
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(_dumps(data))
        for attempt in range(LOCK_TRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == LOCK_TRIES - 1:
                    raise
                time.sleep(LOCK_WAIT)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _lock(path):
    """Takes the lock directory, taking over one older than LOCK_STALE. False when it stays held."""
    lock = path + ".lock"
    for _ in range(LOCK_TRIES):
        try:
            os.mkdir(lock)
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > LOCK_STALE:
                    os.rmdir(lock)
                    continue
            except OSError:
                pass
            time.sleep(LOCK_WAIT)
    return False


def _stamp(lock):
    """The lock directory's mtime in ns, or None when it is gone."""
    try:
        return os.stat(lock).st_mtime_ns
    except OSError:
        return None


def main(argv):
    cfg_path, state_path = argv
    lines = []
    if os.path.exists(cfg_path):
        if not _lock(cfg_path):
            print(f"{cfg_path} stayed locked by Claude Code; run the installer again", file=sys.stderr)
            return 1
        mine = _stamp(cfg_path + ".lock")
        try:
            cfg = _load(cfg_path)
            done = clean_config(cfg)
            if done:
                _save(cfg_path, cfg)
            lines += done
        except ValueError as e:
            print(f"{cfg_path} is not valid JSON ({e}); nothing changed", file=sys.stderr)
            return 1
        finally:
            # During a save slower than LOCK_STALE, Claude Code may take the lock over as stale (a new directory, and
            # proper-lockfile refreshes its mtime): remove it only while it is still the one we made. Gone already is
            # fine too; the save itself still stands.
            if mine is not None and _stamp(cfg_path + ".lock") == mine:
                try:
                    os.rmdir(cfg_path + ".lock")
                except OSError:
                    pass
    try:
        state = _load(state_path)
    except ValueError as e:
        print(f"{state_path} is not valid JSON ({e}); nothing changed", file=sys.stderr)
        return 1
    done = clean_state(state)
    if done:
        _save(state_path, state)
    lines += done
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
