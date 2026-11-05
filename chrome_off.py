"""Turns Claude in Chrome off by default, once.

Usage: python chrome_off.py <~/.claude.json> <state.json>

A project's settings cannot turn Chrome on (the engine ignores CLAUDE_CODE_ENABLE_CFC there), but
/chrome or `claude --chrome` can. Left on by default it costs about 1.4k tokens a turn. This writes
claudeInChromeDefaultEnabled=false into ~/.claude.json and records that in the state file. It does
this only once, so the "Enabled by default" toggle in /chrome wins on every later run.
"""
import os
import sys

import mcp_off

KEY = "claudeInChromeDefaultEnabled"


def turn_off(cfg, state):
    """Sets the key to false in cfg unless state shows it was done before. True when it changed cfg."""
    if KEY in state:
        return False
    cfg[KEY] = False
    state[KEY] = "off-once"
    return True


def main(argv):
    cfg_path, state_path = argv
    if not os.path.exists(cfg_path):
        return 0
    if not mcp_off._lock(cfg_path):
        print(f"{cfg_path} stayed locked by Claude Code; run the installer again", file=sys.stderr)
        return 1
    try:
        cfg = mcp_off._load(cfg_path, None)
        state = mcp_off._load(state_path, {})
        if turn_off(cfg, state):
            mcp_off._save(cfg_path, cfg)
            mcp_off._save(state_path, state)
    finally:
        os.rmdir(cfg_path + ".lock")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
