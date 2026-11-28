"""Takes the per-user toggles the old installer wrote out of ~/.claude.json and the state file, once (install.ps1's clean slate).

Usage: python clean_slate.py <~/.claude.json> <state.json>

~/.claude.json: deletes the top-level claudeInChromeDefaultEnabled (the old installer set it to false) and
disabledMcpServers from every entry under projects (the old installer put the claude.ai Adobe connector there). Every
other key stays as it is, and the file stays UTF-8.
state.json: deletes the keys the old installer kept there ("claude.ai Adobe", "claudeInChromeDefaultEnabled").
Prints one line per thing removed. A file that is missing or has nothing to remove is not written.
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
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


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


def main(argv):
    cfg_path, state_path = argv
    lines = []
    if os.path.exists(cfg_path):
        if not _lock(cfg_path):
            print(f"{cfg_path} stayed locked by Claude Code; run the installer again", file=sys.stderr)
            return 1
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
            os.rmdir(cfg_path + ".lock")
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
