"""Turns an MCP server off by default in every project Claude Code knows, once per project.

Usage: python mcp_off.py <~/.claude.json> <state.json> <server name as /mcp shows it>

A deny list cannot do this: deniedMcpServers entries union across every settings source, so a
denied server cannot be turned back on for one session. The per-project toggle in /mcp can, and it
lives in ~/.claude.json as projects[<dir>].disabledMcpServers. This adds the server there for each
project not yet handled and records the project in the state file, so a server turned back on
with /mcp stays on when the installer runs again. A project first opened after the last run starts
with the server on until the next run.
"""
import json
import os
import sys
import time

# Claude Code saves ~/.claude.json under a proper-lockfile lock: a "<file>.lock" directory, stale after 10s.
# Holding it keeps a running session from saving between our read and our write and losing one of the two.
LOCK_TRIES = 50
LOCK_WAIT = 0.1
LOCK_STALE = 10


def turn_off(cfg, server, done):
    """Adds server to disabledMcpServers in each project of cfg not listed in done, unless the
    project enabled it explicitly. Returns the new done list (every project in cfg, plus done)."""
    handled = list(done)
    for path, project in (cfg.get("projects") or {}).items():
        if path in handled:
            continue
        handled.append(path)
        if not isinstance(project, dict) or server in (project.get("enabledMcpServers") or []):
            continue
        disabled = project.get("disabledMcpServers")
        if not isinstance(disabled, list):
            disabled = project["disabledMcpServers"] = []
        if server not in disabled:
            disabled.append(server)
    return handled


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _save(path, data):
    # Write beside the target, then swap, so a running Claude Code never reads half a file. The swap is retried
    # while another process (antivirus, the indexer) briefly holds the target open.
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            json.dump(data, f, indent=2)
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
    cfg_path, state_path, server = argv
    if not os.path.exists(cfg_path):
        return 0
    if not _lock(cfg_path):
        print(f"{cfg_path} stayed locked by Claude Code; run the installer again", file=sys.stderr)
        return 1
    try:
        cfg = _load(cfg_path, None)
        state = _load(state_path, {})
        done = turn_off(cfg, server, state.get(server, []))
        if done != state.get(server):
            _save(cfg_path, cfg)
            state[server] = done
            _save(state_path, state)
    finally:
        os.rmdir(cfg_path + ".lock")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
