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
        disabled = project.setdefault("disabledMcpServers", [])
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
    # Write beside the target, then swap, so a running Claude Code never reads half a file.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def main(argv):
    cfg_path, state_path, server = argv
    cfg = _load(cfg_path, None)
    if cfg is None:
        return 0
    state = _load(state_path, {})
    done = turn_off(cfg, server, state.get(server, []))
    if done != state.get(server):
        _save(cfg_path, cfg)
        state[server] = done
        _save(state_path, state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
