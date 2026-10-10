# /// script
# requires-python = ">=3.10"
# ///

"""Unified status line for Claude Code.

Sections (left to right):
    model · effort │ ctx ↔ N% bar used/size │ 5h ↔ N% bar reset │ 7d ↔ N% bar reset │ $cost │ session time │ project › git │ venv │ :ports

Every section after model + ctx is auto-detected and shown only when relevant.
Standalone: no external dependencies.

Compact mode: when ~/.claude/statusline-mode contains "compact" (a companion mod
toggles it on TOGGLE_KEY), exactly one line shows model, ctx/5h/7d as % + bar, cost,
then the health items that need attention and the toggle hint while they fit.

Usage numbers: Claude Code only pipes in the rate limits from *this* session's
last reply, so they lag whenever other sessions (or claude.ai) use the shared
quota. The script also reads the endpoint behind /usage in a background process,
caches it for USAGE_TTL seconds, and shows the higher of the two within a window.
Set STATUSLINE_LIVE_USAGE=0 to turn that off.

Install:
    1. Drop this file at ~/.claude/statusline.py
    2. Add to ~/.claude/settings.json:
           "statusLine": {
               "type": "command",
               "command": "python ~/.claude/statusline.py",
               "refreshInterval": 10
           }
       (Swap "python" for "uv run" if you use uv.)
    3. Restart your Claude Code session.

See https://github.com/roeimichael/claude-code-statusline for docs.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

# subprocess, socket and datetime are imported where they are used: a render with a
# warm probe cache needs none of them, and it runs every second.

# ANSI colors (256-color palette, so macOS Terminal.app renders them too)
def fg(n):
    return f"\033[38;5;{n}m"


MODEL = fg(173)    # Claude orange
PROJECT = fg(141)  # violet
GREEN = fg(114)
AMBER = fg(221)
CYAN = fg(80)
COST = "\033[1;38;5;46m"  # bold bright green
# One color per model family, used for the model name and for subagents on that model.
MODEL_COLORS = {"opus": fg(208), "sonnet": fg(75), "haiku": fg(43), "fable": fg(213)}


def model_color(model_id):
    m = str(model_id or "").lower()
    for family, color in MODEL_COLORS.items():
        if family in m:
            return color
    return MODEL
DIM = fg(252)  # secondary text: the terminal's usual light grey, not a faint dim
RST = "\033[0m"
RED = fg(203)
# Meter colors by percentage: (below this %, color), then RED.
STAGES = ((50, fg(114)), (70, fg(221)), (85, fg(208)))

SEP = f"  {DIM}│{RST}  "
COMPACT_SEP = f" {DIM}│{RST} "  # compact mode: room for three bars on one 120-column line
# Columns kept free at the window's right edge (Claude Code pads the status line).
EDGE = 4
ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def visible_width(s):
    return len(ANSI_RE.sub("", s))


def flow(items, width, sep=SEP):
    """Join items with `sep` into lines no wider than `width`; an item never splits.

    After packing greedily, a last line holding a single item borrows the
    previous line's last item when that still fits, so it does not sit alone.
    """
    lines, cur = [], []
    for item in items:
        if cur and visible_width(sep.join(cur + [item])) > width:
            lines.append(cur)
            cur = []
        cur.append(item)
    if cur:
        lines.append(cur)
    if len(lines) >= 2 and len(lines[-1]) == 1 and len(lines[-2]) >= 3:
        moved = [lines[-2][-1]] + lines[-1]
        if visible_width(sep.join(moved)) <= width:
            lines[-2], lines[-1] = lines[-2][:-1], moved
    return [sep.join(line) for line in lines]


def mid_trunc(s, n):
    """Shorten s to n characters by replacing its middle with '…'."""
    if len(s) <= n:
        return s
    if n <= 1:
        return "…"[:n]
    keep = n - 1
    head = keep // 2
    return s[:head] + "…" + s[len(s) - (keep - head):]
BAR = "\u2588"          # full block: fills the whole cell height
BAR_TRACK = fg(238)      # the empty part of a bar
EFFORT = {"low": DIM, "medium": GREEN, "high": AMBER, "xhigh": fg(209), "max": fg(203)}

# Second line: Claude Code version, plugin reload and MCP server status.
SHOW_HEALTH = True
# Extra line listing running subagents (model, effort, context tokens). Off by default:
# the agent list under the prompt is the better place, see the companion mod.
SHOW_AGENTS = False

# Edit this list to match the dev ports you care about.
COMMON_PORTS = [3000, 3001, 5173, 5174, 8000, 8080, 8081, 8086, 9086, 9087, 54321]

# Live usage (the data /usage shows). Seconds between background fetches.
USAGE_TTL = 60
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
USAGE_CACHE = CLAUDE_DIR / "statusline-usage.json"
USAGE_LOCK = CLAUDE_DIR / "statusline-usage.lock"
WINDOWS = ("five_hour", "seven_day")

# Layout mode: a companion mod writes "compact" or "full" to CLAUDE_DIR/statusline-mode
# when you press TOGGLE_KEY. Missing, unreadable or anything else means full.
MODE_FILE_NAME = "statusline-mode"
TOGGLE_KEY = "ctrl+alt+s"

# Release check: newest Claude Code on your update channel. Seconds between fetches.
RELEASE_TTL = 3600
RELEASE_URL = "https://registry.npmjs.org/-/package/@anthropic-ai/claude-code/dist-tags"
NATIVE_VERSIONS = Path.home() / ".local" / "share" / "claude" / "versions"

# Icons. "none" uses plain text; "nerd" needs a Nerd Font in the terminal
# (e.g. CaskaydiaMono Nerd Font). Pick with --icons nerd or STATUSLINE_ICONS=nerd.
# Plain mode also serves the classic Windows console (Consolas), so only glyphs it has.
PLAIN_ICONS = {"ok": "\u2713", "up": "\u2191", "warn": "\u25b2", "reload": "~", "toggle": "\u2192"}
NERD_ICONS = {
    "model": "\U000F167A",    # md-robot_outline
    "ctx": "\U000F0830",      # md-poker_chip (tokens)
    "five_hour": "\U000F051F",  # md-timer_sand
    "seven_day": "\U000F0A33",  # md-calendar_week
    "cost": "\U000F01C1",     # md-currency_usd
    "duration": "\U000F0150",  # md-clock_outline
    "project": "\U000F024B",  # md-folder
    "branch": "\ue725",       # dev-git_branch
    "venv": "\U000F0320",     # md-language_python
    "ports": "\U000F0318",    # md-lan_connect
    "cc": "",           # cod-claude: the Claude logo
    "plugins": "\U000F0431",  # md-puzzle
    "skills": "\U000F140B",   # md-lightning_bolt
    "mcp": "\U000F048D",      # md-server_network
    "agents": "\U000F171A",   # md-robot_happy_outline
    "ok": "\U000F05E0",       # md-check_circle
    "up": "\U000F0CE1",       # md-arrow_up_circle
    "reload": "\U000F0453",   # md-reload
    "warn": "\U000F0026",     # md-alert
    "toggle": "→",       # plain arrow: CaskaydiaMono has no dashed one (U+21E2)
    "keyboard": "\U000F030C",  # md-keyboard: compact mode's toggle hint
    "segment": "",  # powerline slants: one tilted full-height bar segment
}
ICON = dict(PLAIN_ICONS)


def console_window_class():
    """Window class of this process's console on Windows ('' when it has none), else None.

    The classic console host is 'ConsoleWindowClass'; Windows Terminal's ConPTY is
    'PseudoConsoleWindow'.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return ""
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return None


def effective_icons(mode):
    """The requested icon set, unless this terminal cannot draw it.

    The classic Windows console shows Nerd Font glyphs as boxes (and miscounts their
    width), so 'nerd' falls back to 'none' there. A console without a window counts
    too, unless Windows Terminal (WT_SESSION) or another terminal (TERM_PROGRAM) set
    its mark. STATUSLINE_FORCE_ICONS=1 skips the check.
    """
    if mode != "nerd" or os.environ.get("STATUSLINE_FORCE_ICONS"):
        return mode
    cls = console_window_class()
    if cls == "ConsoleWindowClass":
        return "none"
    if cls == "" and not os.environ.get("WT_SESSION") and not os.environ.get("TERM_PROGRAM"):
        return "none"
    return mode


def set_icons(mode):
    ICON.clear()
    ICON.update(NERD_ICONS if mode == "nerd" else PLAIN_ICONS)


def ic(name, color=DIM):
    """Icon followed by a space, or '' when the current icon set has none."""
    g = ICON.get(name)
    return f"{color}{g}{RST} " if g else ""


def color_pct(p):
    """Four clear stages: green, yellow from 50%, orange from 70%, red from 85%."""
    for limit, color in STAGES:
        if p < limit:
            return color
    return RED


def bar(p, width=8, segments=5):
    if ICON.get("segment"):
        # Nerd Font: slanted full-height segments, five by default.
        seg, width = ICON["segment"], segments
    else:
        seg = BAR
    # Any usage lights the first segment, so a low reading never looks empty.
    filled = max(1 if p > 0 else 0, min(width, round(p / 100 * width)))
    return f"{color_pct(p)}{seg * filled}{RST}{BAR_TRACK}{seg * (width - filled)}{RST}"


def meter(label, p, suffix="", icon=None, pct_first=False):
    """'label ▰▰▱▱ N% suffix' ('label N% ▰▰▱▱ suffix' with pct_first), or 'label --' when unknown."""
    head = ic(icon, color_pct(p) if p is not None else DIM) if icon else ""
    if p is None:
        return f"{head}{DIM}{label} --{RST}"
    tail = f" {DIM}{suffix}{RST}" if suffix else ""
    pct = f"{color_pct(p)}{p:.0f}%{RST}"
    if pct_first:
        # Usage windows: the label shares the percentage's color, joined by an arrow.
        return f"{head}{color_pct(p)}{label}{RST} {DIM}↔{RST} {pct} {bar(p)}{tail}"
    return f"{head}{DIM}{label}{RST} {bar(p)} {pct}{tail}"


def fmt_duration(ms):
    if not ms or ms <= 0:
        return ""
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, _ = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m"
    return f"{s}s"


def fmt_until(seconds):
    """Compact countdown: 14m, 3h, 3h05m, 5d, 5d2h."""
    if seconds is None or seconds <= 0:
        return ""
    m = int(seconds // 60)
    d, m = divmod(m, 1440)
    h, m = divmod(m, 60)
    if d:
        return f"{d}d{h}h" if h else f"{d}d"
    if h:
        return f"{h}h{m:02d}m" if m else f"{h}h"
    return f"{max(m, 1)}m"


def fmt_tokens(n):
    """Compact token count: 950, 12k, 135k, 1M, 1.2M."""
    if n < 1000:
        return str(n)
    if n < 999_500:
        return f"{round(n / 1000)}k"
    return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"


def context_tokens(cw):
    """'used/size' tokens in the context window, or '' when the size is unknown."""
    size = cw.get("context_window_size")
    if not size:
        return ""
    u = cw.get("current_usage") or {}
    used = sum(int(u.get(k) or 0) for k in
               ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return f"{fmt_tokens(used)}/{fmt_tokens(int(size))}"


def fmt_cost(c):
    amount = f"{c:.2f}"
    if ICON.get("cost"):
        return f"{ic('cost', COST)}{COST}{amount}{RST}"
    return f"{COST}${amount}{RST}"


def run(cmd, timeout=1.0):
    import subprocess
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


# --- probe cache -------------------------------------------------------------
# With a 1-second refreshInterval every render must be cheap, so the slow probes
# (git, port scan, health) keep their results for a few seconds in one JSON file
# shared by all sessions. Only probe results go in: never the mode or anything from
# the stdin payload's live numbers, so a mode switch shows on the very next render.

PROBE_CACHE_NAME = "statusline-probe-cache.json"
GIT_TTL = 3        # git status, per directory
PORTS_TTL = 10     # dev port scan
HEALTH_TTL = 10    # version status, plugins to reload, MCP status, per session and project
SKILLS_TTL = 60    # skill count (a folder scan), per project


class ProbeCache:
    """{key: {"at": epoch, "v": value}} loaded once per render and saved at the end.

    Values come back as JSON, so tuples come back as lists. A missing, corrupt or
    unwritable file only means the probes run again; it never breaks rendering.
    """

    def __init__(self, path, now):
        self.path, self.now, self.dirty = path, now, False
        self.entries = {}
        if path is None:
            return
        try:
            entries = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(entries, dict):
            self.entries = entries

    def get(self, key, ttl, compute):
        """The cached value for key while younger than ttl seconds, else compute() (and keep it)."""
        e = self.entries.get(key)
        if isinstance(e, dict) and "v" in e:
            at = e.get("at")
            if isinstance(at, (int, float)) and 0 <= self.now - at < ttl:
                return e["v"]
        value = compute()
        self.entries[key] = {"at": self.now, "v": value}
        self.dirty = True
        return value

    def save(self):
        """Write atomically (tmp file + os.replace), dropping entries no TTL can still use."""
        if self.path is None or not self.dirty:
            return
        keep = max(GIT_TTL, PORTS_TTL, HEALTH_TTL, SKILLS_TTL)
        entries = {k: e for k, e in self.entries.items() if isinstance(e, dict)
                   and isinstance(e.get("at"), (int, float)) and 0 <= self.now - e["at"] < keep}
        tmp = Path(f"{self.path}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(entries), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:
            try:
                tmp.unlink()
            except OSError:
                pass


def _probe_cache(cache):
    """The render's ProbeCache, or a throwaway one (always probes) when none is given."""
    return cache if cache is not None else ProbeCache(None, time.time())


# --- usage -----------------------------------------------------------------

def _epoch(v):
    """resets_at arrives as epoch seconds (stdin) or ISO 8601 (usage endpoint)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _window(pct, resets_at, now):
    if pct is None:
        return None
    reset = _epoch(resets_at)
    if reset is not None and reset <= now:
        # The window rolled over; this reading says nothing about the new one.
        return None
    return {"pct": float(pct), "resets_at": reset}


def merge_usage(stdin_rl, live, now):
    """Combine this session's rate limits with the account-wide live reading.

    Usage only grows within a window, so for the same window the higher number
    is the fresher one. A window that resets later is a newer window and wins.
    Returns {window: {"pct", "resets_at"} | None}; None means unknown.
    """
    stdin_rl = stdin_rl or {}
    live = live or {}
    out = {}
    for key in WINDOWS:
        s = stdin_rl.get(key) or {}
        l = live.get(key) or {}
        cands = [
            w for w in (
                _window(s.get("used_percentage"), s.get("resets_at"), now),
                _window(l.get("utilization"), l.get("resets_at"), now),
            ) if w
        ]
        if not cands:
            out[key] = None
            continue
        # Same window when resets_at agree to within a minute (the sources round differently).
        latest = max((w["resets_at"] or 0) for w in cands)
        same = [w for w in cands if (w["resets_at"] or 0) >= latest - 60]
        out[key] = max(same, key=lambda w: w["pct"])
    return out


def read_oauth_token():
    """The Claude subscription token, or None (API-key users, expired, unreadable)."""
    raw = None
    try:
        raw = (CLAUDE_DIR / ".credentials.json").read_text(encoding="utf-8")
    except OSError:
        if sys.platform == "darwin":
            raw = run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"], 2.0)
    try:
        oauth = json.loads(raw)["claudeAiOauth"]
    except Exception:
        return None
    expires = oauth.get("expiresAt")
    if expires and expires / 1000 <= time.time():
        return None  # Claude Code refreshes it on its next request.
    return oauth.get("accessToken")


def load_usage_cache():
    try:
        return json.loads(USAGE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def refresh_cache():
    """Fetch whatever is stale into the cache. Runs in a detached child process."""
    import urllib.request  # here, not at the top: ~30ms the render itself never needs
    cache = load_usage_cache()
    now = time.time()
    if now - (cache.get("fetched_at") or 0) >= USAGE_TTL:
        _fetch_usage(cache, now)
    if now - (cache.get("tags_at") or 0) >= RELEASE_TTL:
        cache["tags_at"] = now
        try:
            with urllib.request.urlopen(RELEASE_URL, timeout=5) as r:
                cache["tags"] = json.loads(r.read())
        except Exception:
            pass
    tmp = USAGE_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache), encoding="utf-8")
    os.replace(tmp, USAGE_CACHE)


def _fetch_usage(cache, now):
    import urllib.request
    cache["fetched_at"] = now
    try:
        token = read_oauth_token()
        if not token:
            raise RuntimeError("no oauth token")
        req = urllib.request.Request(USAGE_URL, headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read())
        cache["usage"] = {k: body.get(k) for k in WINDOWS}
        cache["usage_at"] = cache["fetched_at"]
        cache["error"] = None
    except Exception as e:
        cache["error"] = f"{type(e).__name__}: {e}"[:200]


def _take_lock(now):
    for _ in range(2):
        try:
            os.close(os.open(USAGE_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:
                if now - USAGE_LOCK.stat().st_mtime < 30:
                    return False  # a refresh is already running
                USAGE_LOCK.unlink()  # left behind by a killed refresh
            except OSError:
                return False
        except OSError:
            return False
    return False


def maybe_refresh(cache, now):
    """Start a background fetch when anything in the cache is stale. Never blocks."""
    stale = (now - (cache.get("fetched_at") or 0) >= USAGE_TTL
             or now - (cache.get("tags_at") or 0) >= RELEASE_TTL)
    if not stale or not _take_lock(now):
        return
    import subprocess
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
          "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--refresh"], **kw)
    except Exception:
        USAGE_LOCK.unlink(missing_ok=True)


# --- health: version, plugins, MCP ------------------------------------------

def _ver(v):
    try:
        return tuple(int(x) for x in str(v).split("-")[0].split("."))
    except ValueError:
        return ()


def version_status(running, installed, published):
    """('ok'|'restart'|'update'|'unknown', newer version or None)."""
    newest_installed = max(installed, key=_ver, default=None)
    if newest_installed and _ver(newest_installed) > _ver(running):
        return "restart", newest_installed
    if published and _ver(published) > _ver(running):
        return "update", published
    if published or installed:
        return "ok", None
    return "unknown", None


def installed_versions():
    try:
        return [d.name for d in NATIVE_VERSIONS.iterdir() if _ver(d.name)]
    except OSError:
        return []


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def plugins_needing_reload(installed, enabled, loaded_at):
    """Enabled plugins updated on disk after this session loaded its plugins."""
    out = []
    for name, entries in (installed.get("plugins") or {}).items():
        if name not in enabled:
            continue
        updated = max((_epoch(e.get("lastUpdated")) or 0 for e in entries), default=0)
        if updated > loaded_at:
            out.append(name)
    return sorted(out)


def plugins_loaded_at(transcript_path):
    """When this session last loaded plugins: its first entry, or the last /reload-plugins."""
    try:
        raw = Path(transcript_path).read_bytes()
    except (OSError, TypeError):
        return None

    def ts_of(line):
        try:
            return _epoch(json.loads(line).get("timestamp"))
        except ValueError:
            return None

    i = raw.rfind(b"<command-name>/reload-plugins</command-name>")
    if i >= 0:
        start = raw.rfind(b"\n", 0, i) + 1
        end = raw.find(b"\n", i)
        t = ts_of(raw[start:end if end >= 0 else None])
        if t:
            return t
    return _first_timestamp(raw)


def _first_timestamp(raw):
    for line in raw.split(b"\n", 50)[:50]:
        if not line.strip():
            continue
        try:
            t = _epoch(json.loads(line).get("timestamp"))
        except ValueError:
            continue
        if t:
            return t
    return None


def session_started_at(transcript_path):
    """The session's first transcript entry, as epoch seconds."""
    try:
        with open(transcript_path, "rb") as f:
            return _first_timestamp(f.read(65536))
    except (OSError, TypeError):
        return None


def mcp_status(logs, session_id, known_plugins=()):
    """(connected, failed) server names from this session's MCP log events.

    logs: {log dir suffix: [event dicts]}. Only connection events count, so a
    tool call that errors on a connected server is not a server problem.
    """
    ok, failed = [], []
    for server, events in logs.items():
        state = None
        for e in sorted((e for e in events if e.get("sessionId") == session_id),
                        key=lambda e: e.get("timestamp", "")):
            if "Successfully connected" in str(e.get("debug", "")):
                state = True
            elif str(e.get("error", "")).startswith("Connection failed"):
                state = False
        if state is None:
            continue
        (ok if state else failed).append(_mcp_name(server, known_plugins))
    return sorted(ok), sorted(failed)


def _mcp_name(server, known_plugins=()):
    """Log dir suffix to display name: plugin-discord-discord -> discord, claude-ai-Gmail -> Gmail.

    Plugin dirs are plugin-<plugin>-<server>, and both halves may contain hyphens,
    so split where the plugin half is a known plugin or the halves repeat.
    """
    if server.startswith("claude-ai-"):
        return server[10:]
    if not server.startswith("plugin-"):
        return server
    words = server[7:].split("-")
    for i in range(1, len(words)):
        plugin, name = "-".join(words[:i]), "-".join(words[i:])
        if plugin == name or plugin in known_plugins:
            return name
    return server[7:]


def mcp_log_root(project_dir):
    """Claude Code's per-project cache dir, where it writes mcp-logs-<server>/."""
    if not project_dir:
        return None
    key = "".join(c if c.isalnum() else "-" for c in str(project_dir))
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "claude-cli-nodejs" / "Cache"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches" / "claude-cli-nodejs"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "claude-cli-nodejs"
    return base / key


def read_mcp_logs(root, since=None, max_files=30):
    """{server: [events]} from log files written since `since`, or None when there are no logs.

    Every session in a project shares these folders, so the newest files are
    often another session's; read all the recent ones and let mcp_status pick.
    """
    try:
        dirs = [d for d in root.iterdir() if d.name.startswith("mcp-logs-")]
    except (OSError, AttributeError):
        return None
    logs = {}
    for d in dirs:
        events = []
        for f in sorted(d.glob("*.jsonl"), reverse=True)[:max_files]:
            try:
                if since is not None and f.stat().st_mtime < since:
                    continue
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        logs[d.name[9:]] = events
    return logs


def count_skills(installed, enabled, claude_dir, project_dir=None):
    """Skills available to a session: enabled plugins' skills and commands, yours, the project's.

    A plugin whose plugin.json lists "skills" loads exactly those; otherwise
    each skills/<name>/SKILL.md. This matches what /reload-plugins reports,
    plus the user and project skill folders it leaves out.
    """
    n = 0
    for name, entries in (installed.get("plugins") or {}).items():
        if name not in enabled or not entries:
            continue
        root = Path(entries[-1].get("installPath") or "")
        listed = _read_json(root / ".claude-plugin" / "plugin.json").get("skills")
        if isinstance(listed, list):
            n += sum(1 for rel in listed if (root / rel / "SKILL.md").exists())
        else:
            n += len(list(root.glob("skills/*/SKILL.md")))
        n += len(list(root.glob("commands/*.md")))
    n += len(list(Path(claude_dir).glob("skills/*/SKILL.md")))
    if project_dir:
        n += len(list(Path(project_dir).glob(".claude/skills/*/SKILL.md")))
    return n


def format_health(running, version, reload_plugins, mcp, skills=None):
    """Health items: Claude Code version, plugin reload, skills, MCP servers. '' when nothing is known."""
    parts = []
    if running:
        state, newer = version
        cc = f"{ic('cc', MODEL)}{DIM}Claude Code{RST} {running}"  # logo in Claude orange
        if state == "ok":
            parts.append(f"{cc} {GREEN}{ICON['ok']}{RST}")
        elif state == "restart":  # newer build already downloaded; this window still runs the old one
            parts.append(f"{cc} {AMBER}{ICON['up']} restart for {newer}{RST}")
        elif state == "update":
            parts.append(f"{cc} {AMBER}{ICON['up']} {newer} available{RST}")
        else:
            parts.append(cc)
    if reload_plugins is not None:
        label = f"{ic('plugins')}{DIM}plugins{RST}"
        if reload_plugins:
            parts.append(f"{label} {AMBER}{ICON['reload']} {len(reload_plugins)} updated{RST}"
                         f" {DIM}·{RST} run {AMBER}/reload-plugins{RST}")
        else:
            parts.append(f"{label} {GREEN}{ICON['ok']}{RST}")
    if skills:
        parts.append(f"{ic('skills')}{DIM}skills{RST} {skills}")
    if mcp is not None:
        ok, failed = mcp
        if ok or failed:
            bits = [f"{len(ok)} connected"] if ok else []
            if failed:
                more = f" +{len(failed) - 1}" if len(failed) > 1 else ""
                bits.append(f"{RED}{ICON['warn']} {failed[0]}{more} failed{RST}")
            parts.append(f"{ic('mcp')}{DIM}mcp{RST} " + f" {DIM}·{RST} ".join(bits))
    return SEP.join(parts)


def health_line(data, cache=None):
    return format_health(*health_state(data, cache=cache))


def health_state(data, with_skills=True, cache=None):
    """(running, version, reload_plugins, mcp, skills) for format_health / compact_problems.

    with_skills=False skips the skill count (a folder scan) when it will not be shown.
    cache: the render's ProbeCache; the probes are kept HEALTH_TTL seconds per session
    and project (SKILLS_TTL for the skill count, per project).
    """
    cache = _probe_cache(cache)
    running = data.get("version")
    ws = data.get("workspace") or {}
    key = json.dumps([data.get("session_id"), ws.get("project_dir") or data.get("cwd"),
                      data.get("transcript_path"), running])
    version, reload_plugins, mcp = cache.get("health:" + key, HEALTH_TTL, lambda: _health_probe(data))
    skills = None
    if with_skills:
        def skill_count():
            settings, installed = _settings_and_plugins()
            return count_skills(installed, _enabled(settings), CLAUDE_DIR, ws.get("project_dir"))
        skills = cache.get("skills:" + json.dumps(ws.get("project_dir")), SKILLS_TTL, skill_count)
    return running, version, reload_plugins, mcp, skills


def _settings_and_plugins():
    return (_read_json(CLAUDE_DIR / "settings.json"),
            _read_json(CLAUDE_DIR / "plugins" / "installed_plugins.json"))


def _enabled(settings):
    return {k for k, v in (settings.get("enabledPlugins") or {}).items() if v}


def _health_probe(data):
    """[version, reload_plugins, mcp]: the slow part of health_state (it reads the transcript and MCP logs)."""
    settings, installed = _settings_and_plugins()
    running = data.get("version")
    channel = settings.get("autoUpdatesChannel") or "latest"
    published = (load_usage_cache().get("tags") or {}).get(channel)
    version = version_status(running, installed_versions(), published) if running else ("unknown", None)

    reload_plugins = None
    loaded_at = plugins_loaded_at(data.get("transcript_path"))
    if loaded_at and installed:
        reload_plugins = plugins_needing_reload(installed, _enabled(settings), loaded_at)

    ws = data.get("workspace") or {}
    started = session_started_at(data.get("transcript_path"))
    logs = read_mcp_logs(mcp_log_root(ws.get("project_dir") or data.get("cwd")),
                         since=started - 60 if started else None)
    known = {k.split("@")[0] for k in (installed.get("plugins") or {})}
    mcp = mcp_status(logs, data.get("session_id"), known) if logs else None
    return [version, reload_plugins, mcp]


# --- subagents -----------------------------------------------------------------

SUBAGENT_STALE = 600  # seconds without a write before a subagent counts as gone
SUBAGENTS_SHOWN = 3


def fmt_model_id(model_id):
    """claude-haiku-5-5 -> Haiku 5.5; unknown ids pass through."""
    m = str(model_id or "").split("[")[0]
    parts = m.split("-")
    if len(parts) >= 3 and parts[0] == "claude" and all(x.isdigit() for x in parts[2:]):
        return f"{parts[1].capitalize()} {'.'.join(parts[2:])}"
    return m


def subagent_state(entries):
    """Model, effort, context tokens and running flag from a subagent's transcript entries."""
    state = {"model": None, "effort": None, "tokens": 0, "running": True}
    last = None
    for e in entries:
        if e.get("type") not in ("user", "assistant"):
            continue
        last = e
        if e["type"] != "assistant":
            continue
        msg = e.get("message") or {}
        state["model"] = msg.get("model") or state["model"]
        state["effort"] = e.get("effort") or state["effort"]
        u = msg.get("usage") or {}
        state["tokens"] = sum(int(u.get(k) or 0) for k in
                              ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    if last and last["type"] == "assistant" and (last.get("message") or {}).get("stop_reason") == "end_turn":
        state["running"] = False
    return state


def _tail_entries(path, max_bytes=262_144):
    """Parsed JSON lines from the end of a transcript (the first, maybe partial, line is dropped)."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        raw = f.read()
    lines = raw.split(b"\n")
    if size > max_bytes:
        lines = lines[1:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def running_subagents(transcript_path, now):
    """Subagents of this session that are still working, newest first."""
    if not transcript_path:
        return []
    d = Path(str(transcript_path)[:-6] if str(transcript_path).endswith(".jsonl") else transcript_path) / "subagents"
    try:
        files = [(f.stat().st_mtime, f) for f in d.glob("agent-*.jsonl")]
    except OSError:
        return []
    agents = []
    for mtime, f in sorted(files, reverse=True):
        if now - mtime > SUBAGENT_STALE:
            continue
        try:
            state = subagent_state(_tail_entries(f))
        except OSError:
            continue
        if not state["running"]:
            continue
        meta = _read_json(f.with_name(f.name[:-6] + ".meta.json"))
        state["type"] = meta.get("agentType") or f.stem[6:]
        agents.append(state)
    return agents


def format_agents(agents):
    """Third line, shown only while subagents run."""
    if not agents:
        return ""
    parts = [f"{ic('agents')}{DIM}agents{RST} {len(agents)}"]
    for a in agents[:SUBAGENTS_SHOWN]:
        c = model_color(a.get("model"))
        s = f"{c}{a['type']}{RST}"
        if a.get("model"):
            s += f" {c}{fmt_model_id(a['model'])}{RST}"
        if a.get("effort"):
            s += f" {DIM}\u00b7{RST} {EFFORT.get(a['effort'], '')}{a['effort']}{RST}"
        if a.get("tokens"):
            s += f" {DIM}{fmt_tokens(a['tokens'])}{RST}"
        parts.append(s)
    if len(agents) > SUBAGENTS_SHOWN:
        parts.append(f"{DIM}+{len(agents) - SUBAGENTS_SHOWN}{RST}")
    return SEP.join(parts)


# --- workspace probes --------------------------------------------------------

def git_info(cwd, cache=None):
    """(branch, flags) for where_item; None outside a repo, '' without a directory.

    cache: the render's ProbeCache; git status is kept GIT_TTL seconds per directory.
    """
    if not cwd or not Path(cwd).exists():
        return ""
    status = _probe_cache(cache).get("git:" + str(cwd), GIT_TTL, lambda: git_status(cwd))
    if not status:
        return None
    branch, stg, mod, unt = status
    flags = []
    if stg:
        flags.append(f"{GREEN}+{stg}{RST}")
    if mod:
        flags.append(f"{AMBER}~{mod}{RST}")
    if unt:
        flags.append(f"{DIM}?{unt}{RST}")
    return branch, flags


def git_status(cwd):
    """[branch, staged, modified, untracked] from one git call, or None outside a repo."""
    # One git call instead of five: branch plus staged/modified/untracked counts.
    out = run(["git", "-C", cwd, "status", "--porcelain=v2", "--branch", "--untracked-files=all"])
    branch = oid = ""
    stg = mod = unt = 0
    for line in out.splitlines():
        if line.startswith("# branch.head "):
            branch = line[14:]
        elif line.startswith("# branch.oid "):
            oid = line[13:20]
        elif line[:2] in ("1 ", "2 "):
            stg += line[2] != "."
            mod += line[3] != "."
        elif line.startswith("u "):
            mod += 1
        elif line.startswith("? "):
            unt += 1
    if branch == "(detached)":
        branch = oid
    if not branch:
        return None
    return [branch, stg, mod, unt]


MIN_NAME = 8  # a shortened project or branch name keeps at least this many characters


def where_item(proj, git, width=None):
    """'project › branch flags'. When wider than `width`, the longer of project and
    branch loses characters from its middle ('claude-co…statusline') until it fits."""
    branch, flags = git or ("", [])

    def render(p, b):
        where = []
        if p:
            where.append(f"{ic('project', PROJECT)}{PROJECT}{p}{RST}")
        if b:
            color = AMBER if flags else GREEN
            where.append(" ".join([f"{ic('branch', color)}{color}{b}{RST}"] + flags))
        return f"  {DIM}›{RST}  ".join(where)

    p_len, b_len = len(proj), len(branch)
    item = render(proj, branch)
    while width and visible_width(item) > width:
        if b_len >= p_len and b_len > MIN_NAME:
            b_len -= 1
        elif p_len > MIN_NAME:
            p_len -= 1
        elif b_len > MIN_NAME:
            b_len -= 1
        else:
            break  # as short as it gets; it takes a line of its own
        item = render(mid_trunc(proj, p_len), mid_trunc(branch, b_len))
    return item


def line_width():
    """Columns available to the status line, or None when the window width is unknown."""
    try:
        width = int(os.environ.get("COLUMNS") or 0) - EDGE
    except ValueError:
        return None
    return width if width > 20 else None


def venv_tag():
    conda = os.environ.get("CONDA_DEFAULT_ENV")
    if conda and conda != "base":
        return f"{ic('venv', CYAN)}{DIM}env:{RST}{CYAN}{conda}{RST}"
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        return f"{ic('venv', CYAN)}{DIM}venv:{RST}{CYAN}{Path(venv).name}{RST}"
    return ""


def open_ports(ports=None, timeout=0.05):
    """Ports on 127.0.0.1 that accept a connection within `timeout` seconds.

    All at once, with non-blocking connects and select(): on Windows a closed port
    never refuses quickly, so each one waits out the whole timeout. No threads.
    """
    import select
    import socket
    ports = COMMON_PORTS if ports is None else ports
    pending, up, socks = {}, set(), []
    try:
        for port in ports:
            s = socket.socket()
            pending[s] = port
            s.setblocking(False)
            err = s.connect_ex(("127.0.0.1", port))
            if err == 0:
                up.add(port)
            elif err in (10035, 115, 36, 11, 35):  # WSAEWOULDBLOCK, EINPROGRESS, EAGAIN (Linux, macOS)
                socks.append(s)  # still connecting; anything else was refused at once
        deadline = time.monotonic() + timeout
        while socks:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            _, writable, failed = select.select([], socks, socks, left)
            if not writable and not failed:
                break
            for s in set(writable) | set(failed):
                if s not in failed and s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0:
                    up.add(pending[s])
                socks.remove(s)
    except OSError:
        pass
    finally:
        for s in pending:
            s.close()
    return [p for p in ports if p in up]


def ports_tag(cache=None):
    """':3000,5173' for the dev ports that answer. cache: kept PORTS_TTL seconds."""
    up = _probe_cache(cache).get("ports:" + ",".join(map(str, COMMON_PORTS)), PORTS_TTL, open_ports)
    return f"{ic('ports', GREEN)}{GREEN}:{','.join(str(p) for p in up)}{RST}" if up else ""


# --- layout ------------------------------------------------------------------

def read_mode():
    """'compact' or 'full' from the mode file. Never raises: compact unless the file says full."""
    try:
        text = (CLAUDE_DIR / MODE_FILE_NAME).read_text(encoding="utf-8")
    except Exception:
        return "compact"
    return "full" if text.strip().lower() == "full" else "compact"


def toggle_hint(target):
    """'ctrl+alt+s → compact': the key that switches to the other layout."""
    arrow = ICON.get("toggle", "→")
    return f"{DIM}{TOGGLE_KEY} {arrow} {target}{RST}"


def model_head(data):
    """'Opus 5.5 · high' in the model family's color and the effort's color."""
    model = data.get("model", {}) or {}
    name = model.get("display_name", "Claude")
    mc = model_color(model.get("id") or name)
    head = f"{ic('model', mc)}{mc}{name}{RST}"
    level = (data.get("effort") or {}).get("level")
    if level:
        head += f" {DIM}·{RST} {EFFORT.get(level, '')}{level}{RST}"
    return head


def compact_bar(p):
    """Slimmer than full mode's bar (6 cells or 4 segments), so the hint fits at 120 columns."""
    return bar(p, width=6, segments=4)


def compact_hint():
    """Compact mode's always-shown hint: keyboard icon and the key, or 'ctrl+alt+s → full'."""
    if ICON.get("keyboard"):
        return f"{ic('keyboard')}{DIM}{TOGGLE_KEY}{RST}"
    return toggle_hint("full")


def compact_meter(label, p, icon, with_bar=True, suffix=""):
    """'ctx 43% ▰▰▱▱ 430k/1M' with label and value in the stage color, or 'ctx --' (no bar) when unknown."""
    if p is None:
        return meter(label, None, icon=icon)
    c = color_pct(p)
    tail = f" {compact_bar(p)}" if with_bar else ""
    if suffix:
        tail += f" {DIM}{suffix}{RST}"
    return f"{ic(icon, c)}{c}{label}{RST} {c}{p:.0f}%{RST}{tail}"


def compact_problems(version, reload_plugins, mcp):
    """Health items worth showing in compact mode, short: only the ones that need you."""
    out = []
    if mcp is not None and mcp[1]:
        failed = mcp[1]
        more = f" +{len(failed) - 1}" if len(failed) > 1 else ""
        out.append(f"{RED}{ICON['warn']} {failed[0]}{more}{RST}")
    state, _ = version
    if state in ("restart", "update"):
        out.append(f"{AMBER}{ICON['up']} {state}{RST}")
    if reload_plugins:
        out.append(f"{AMBER}{ICON['reload']} reload{RST}")
    return out


def format_compact(data, usage=None, show_usage=True, problems=(), width=None):
    """Items for ONE compact line no wider than `width` (None: no limit), joined by COMPACT_SEP.

    Model, ctx/5h/7d as % + bar (ctx with its tokens), cost, session time, problems,
    then the toggle hint. When it does not fit, things go in this order until it
    does: session time, problems from the last, the hint, the ctx tokens, the bars
    (7d, then 5h, then ctx), cost. Model and the percentages always stay; the line
    never wraps.
    """
    cw = data.get("context_window", {}) or {}
    meters = [("ctx", float(cw.get("used_percentage", 0) or 0), "ctx")]
    if show_usage:
        usage = usage or {}
        for label, key in (("5h", "five_hour"), ("7d", "seven_day")):
            w = usage.get(key)
            meters.append((label, w["pct"] if w else None, key))
    cost = fmt_cost(float((data.get("cost", {}) or {}).get("total_cost_usd", 0.0) or 0.0))

    def fits(items):
        return width is None or visible_width(COMPACT_SEP.join(items)) <= width

    session = compact_session(data)
    tokens = context_tokens(cw)
    problems = list(problems)

    def line(bars, with_session=True, n_problems=len(problems), with_hint=True, with_cost=True,
             with_tokens=True):
        """The line with only the first `bars` meters keeping their bar."""
        items = [model_head(data)] + [
            compact_meter(label, p, icon, with_bar=i < bars, suffix=tokens if i == 0 and with_tokens else "")
            for i, (label, p, icon) in enumerate(meters)]
        if with_cost:
            items.append(cost)
            if with_session and session:
                items.append(session)
        items += problems[:n_problems]
        if with_hint:
            items.append(compact_hint())
        return items

    every = len(meters)
    shrinking = [line(every), line(every, with_session=False)]
    shrinking += [line(every, False, n) for n in range(len(problems) - 1, -1, -1)]
    shrinking.append(line(every, False, 0, with_hint=False))
    shrinking += [line(b, False, 0, False, with_tokens=False) for b in range(every, -1, -1)]
    shrinking.append(line(0, False, 0, False, with_cost=False, with_tokens=False))
    return next((c for c in shrinking if fits(c)), shrinking[-1])


def compact_session(data):
    """Session time: clock icon and number, or 'session 12m' without icons; '' before any time."""
    dur = fmt_duration(int((data.get("cost", {}) or {}).get("total_duration_ms", 0) or 0))
    if not dur:
        return ""
    return f"{ic('duration')}{DIM}{dur}{RST}" if ICON.get("duration") else f"{DIM}session {dur}{RST}"


def format_statusline(data, usage=None, now=None, show_usage=True, workspace=True):
    """usage: merge_usage() result, or None when nothing is known yet.

    workspace=False leaves project, git, venv and ports to workspace_line().
    """
    now = time.time() if now is None else now
    cw = data.get("context_window", {}) or {}
    cost = data.get("cost", {}) or {}

    parts = [model_head(data)]
    parts.append(meter("ctx", float(cw.get("used_percentage", 0) or 0), context_tokens(cw), "ctx",
                       pct_first=True))

    if show_usage:
        usage = usage or {}
        for label, key in (("5h", "five_hour"), ("7d", "seven_day")):
            w = usage.get(key)
            if w is None:
                parts.append(meter(label, None, icon=key))
            else:
                left = w["resets_at"] - now if w["resets_at"] else None
                parts.append(meter(label, w["pct"], fmt_until(left), key, pct_first=True))

    parts.append(fmt_cost(float(cost.get("total_cost_usd", 0.0) or 0.0)))
    dur = fmt_duration(int(cost.get("total_duration_ms", 0) or 0))
    if dur:
        parts.append(f"{ic('duration')}{DIM}session {dur}{RST}")

    if workspace:
        ws_s = workspace_line(data)
        if ws_s:
            parts.append(ws_s)
    return SEP.join(parts)


def workspace_line(data, width=None, cache=None):
    """Project › git branch, then venv and ports. `width` defaults to the window's.

    cache: the render's ProbeCache for the git and port probes.
    """
    ws = data.get("workspace", {}) or {}
    cwd = ws.get("current_dir") or ws.get("project_dir") or data.get("cwd") or os.getcwd()
    proj = Path(cwd).name if cwd else ""
    where = where_item(proj, git_info(cwd, cache), width or line_width())
    parts = [where] if where else []
    for extra in (venv_tag(), ports_tag(cache)):
        if extra:
            parts.append(extra)
    return SEP.join(parts)


def main():
    if "--refresh" in sys.argv:
        try:
            refresh_cache()
        finally:
            USAGE_LOCK.unlink(missing_ok=True)
        return
    mode = os.environ.get("STATUSLINE_ICONS", "none")
    if "--icons" in sys.argv[:-1]:
        mode = sys.argv[sys.argv.index("--icons") + 1]
    set_icons(effective_icons(mode))
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        now = time.time()
        stdin_rl = data.get("rate_limits") or {}
        live = None
        show_usage = bool(stdin_rl)
        if os.environ.get("STATUSLINE_LIVE_USAGE", "1") != "0":
            cache = load_usage_cache()
            live = cache.get("usage")
            if read_oauth_token() or live:
                show_usage = True
                maybe_refresh(cache, now)
        usage = merge_usage(stdin_rl, live, now)
        known = any(usage.values())
        width = line_width()
        compact = read_mode() == "compact"  # read every render, never cached
        probes = ProbeCache(CLAUDE_DIR / PROBE_CACHE_NAME, now)
        if compact:
            # Always exactly one line (Claude Code draws its mode line below it):
            # essentials, then problems and the hint while they fit. No git or port probes.
            problems = []
            if SHOW_HEALTH:
                try:
                    _, version, reload_plugins, mcp, _ = health_state(data, with_skills=False, cache=probes)
                    problems = compact_problems(version, reload_plugins, mcp)
                except Exception:
                    pass
            line = COMPACT_SEP.join(format_compact(data, usage if known else None, show_usage,
                                                   problems, width))
        else:
            # Session and usage first, then workspace and health, packed into as
            # many lines as the window needs: whole items wrap, none get cut off.
            texts = [format_statusline(data, usage if known else None, now, show_usage, workspace=False),
                     workspace_line(data, width, probes)]
            if SHOW_HEALTH:
                try:
                    texts.append(health_line(data, probes))
                except Exception:
                    pass
            items = [item for t in texts if t for item in t.split(SEP)]
            items.append(toggle_hint("compact"))
            line = "\n".join(flow(items, width or 10**6, SEP))
        if SHOW_AGENTS and not compact:
            try:
                agents = format_agents(running_subagents(data.get("transcript_path"), now))
                if agents:
                    line += "\n" + agents
            except Exception:
                pass
        print(line)
        probes.save()  # never raises
    except Exception:
        print("Claude | --")
    sys.exit(0)


if __name__ == "__main__":
    main()
