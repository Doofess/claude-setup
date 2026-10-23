"""A two-row status line for Claude Code.

Usage: Claude Code runs `python statusbar.py` and pipes its session JSON to stdin; `--demo` prints
sample data instead and `--demo-json` prints that sample as the JSON Claude Code would send. Column width comes from the COLUMNS environment variable (default 120).

Row 1 says where you are: repo (owner/name), git branch, PR number, then the model and its effort.
Row 2 says how much room is left: a context meter with tokens used out of the auto-compact point,
the 5-hour and 7-day plan usage meters with the time until each resets, then cost and lines changed.
Icons are Nerd Font glyphs, one cell wide. Colours are the terminal's own 16-colour palette
(green, yellow, red, bright black, bold), so the bar follows whatever scheme the terminal uses.

Width fitting: a row may use COLUMNS minus a small margin that Claude Code keeps for itself. Each
piece of a row (a segment) has a priority. While the row is too wide, the piece with the highest
priority number is dropped, so cost, lines and reset times go first, then the usage meters; the
branch, the model and the context meter always stay.

The 33k headroom: the context meter does not run to the full context window but to the point where
Claude Code auto-compacts. That point is the auto-compact window (from the environment or the
settings files, else the model's own window) minus 33,000 tokens, which is the 13,000 tokens Claude
Code keeps free plus the 20,000 it reserves for the reply. A meter at 100% means compaction is due.

Standard library only. The branch is read straight from .git/HEAD, with no git subprocess, and
nothing is written to disk. On any error the bar prints one plain `statusbar: <error>` row.
"""
import json
import os
import re
import sys
import time

GREEN = 32
YELLOW = 33
RED = 31
DIM = 90  # bright black: icons and separators
BOLD = 1
FILLED = "█"
EMPTY = "░"

SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def sgr(code: int, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m"


def cells(text: str) -> int:
    """Width in terminal cells: every character counts one, colour codes count none."""
    return len(SGR_RE.sub("", text))


def _round_half_up(x: float) -> int:
    return int(x + 0.5)


def fmt_tokens(n: int) -> str:
    """950 -> 950, 12345 -> 12k, 1234567 -> 1.2M."""
    if n < 1000:
        return str(n)
    if _round_half_up(n / 1000) < 1000:
        return f"{_round_half_up(n / 1000)}k"
    return f"{n / 1_000_000:.1f}".removesuffix(".0") + "M"


def fmt_reset(resets_at: float, now: float) -> str:
    """Time until a usage window resets: 45m, 2h10m, 3d4h. Under a minute or already past is now."""
    minutes = int(resets_at - now) // 60  # rounded down to the minute
    if minutes < 1:
        return "→now"
    if minutes < 60:
        return f"→{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"→{hours}h{minutes % 60}m"
    return f"→{hours // 24}d{hours % 24}h"  # minutes would be noise this far out


def meter(pct: float, cells: int) -> str:
    """A bar of `cells` cells filled to pct, coloured by how full it is."""
    filled = max(0, min(cells, _round_half_up(pct / 100 * cells)))
    colour = RED if pct >= 90 else YELLOW if pct >= 70 else GREEN
    return sgr(colour, FILLED * filled + EMPTY * (cells - filled))


# Claude Code compacts at (auto-compact window - 13,000), measured against the context plus the 20,000
# tokens it keeps for the reply. Counted against the context alone, that is window - 33,000.
HEADROOM = 33_000
ENV_WINDOW = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"


def model_key(model_id: str) -> str:
    """Key of modelSettings: the model id without a [1m] suffix and a trailing -YYYYMMDD."""
    return re.sub(r"-\d{8}$", "", re.sub(r"\[1m\]$", "", model_id))


def _parse_window(value) -> int | str | None:
    """A window setting as tokens, "auto", or None when it is absent or unusable.
    Strings may be 200k or 1M; a bare number under 1000 in a string means thousands."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text == "auto":
        return "auto"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)", text)
    if not m:
        return None
    number = float(m.group(1))
    n = number * {"k": 1_000, "m": 1_000_000}.get(m.group(2), 1_000 if number < 1000 else 1)
    return int(n) if n > 0 else None


def compact_window(model_id: str, window_size: int, env: dict, files: list[dict]) -> int:
    """The auto-compact window in tokens. files are parsed settings objects, lowest precedence first."""
    default = None
    by_model: dict = {}
    for f in files:
        if not isinstance(f, dict):
            continue
        top = _parse_window(f.get("autoCompactWindow"))
        if top is not None:
            default, by_model = top, {}  # a top-level value discards earlier per-model values
        per_model = f.get("modelSettings")
        for key, entry in (per_model.items() if isinstance(per_model, dict) else []):
            w = _parse_window(entry.get("autoCompactWindow")) if isinstance(entry, dict) else None
            if w is not None:
                by_model[key] = w
    value = _parse_window(env.get(ENV_WINDOW))
    if value is None:
        value = by_model.get(model_key(model_id), default)
    return window_size if value is None or value == "auto" else min(value, window_size)


def ceiling(window: int) -> int:
    return window - HEADROOM


def settings_files(home: str, project_dir: str, platform: str) -> list[str]:
    """Settings files in precedence order, lowest first: user, project, local, managed."""
    managed = {
        "win32": r"C:\ProgramData\ClaudeCode\managed-settings.json",
        "darwin": "/Library/Application Support/ClaudeCode/managed-settings.json",
    }.get(platform, "/etc/claude-code/managed-settings.json")
    return [
        os.path.join(home, ".claude", "settings.json"),
        os.path.join(project_dir, ".claude", "settings.json"),
        os.path.join(project_dir, ".claude", "settings.local.json"),
        managed,
    ]


def _read_small(path: str) -> str | None:
    """First 200 bytes of a file as text, or None when it cannot be read."""
    try:
        with open(path, "rb") as f:
            return f.read(200).decode("utf-8", "replace").strip()
    except OSError:
        return None


def branch(start_dir: str, stop_dir: str | None = None) -> str | None:
    """Current branch (or the first 7 characters of a detached sha), read from .git/HEAD without git.

    The walk up from start_dir ends at the drive root, or at stop_dir after looking there (tests use it)."""
    here = os.path.abspath(start_dir)
    stop = os.path.abspath(stop_dir) if stop_dir else None
    while not os.path.exists(os.path.join(here, ".git")):
        parent = os.path.dirname(here)
        if parent == here or here == stop:
            return None
        here = parent
    git = os.path.join(here, ".git")
    if os.path.isfile(git):  # a linked worktree: ".git" is a file pointing at the real git dir
        pointer = _read_small(git) or ""
        if not pointer.startswith("gitdir:"):
            return None
        git = os.path.join(here, pointer[len("gitdir:"):].strip())  # join keeps an absolute path as is
    head = _read_small(os.path.join(git, "HEAD"))
    if not head:
        return None
    if head.startswith("ref:"):
        return head[len("ref:"):].strip().removeprefix("refs/heads/") or None
    return head[:7]


MARGIN = 4  # cells Claude Code keeps for its own spacing around the status line
DEFAULT_COLUMNS = 120
SEPARATOR = sgr(DIM, "  │  ")

# Nerd Font glyphs. Each is followed by a space: the non-Mono Nerd Font variants (the Windows Terminal default
# here is "JetBrainsMono Nerd Font") draw them wider than one cell, and without the space they overlap the text.
ICON_REPO, ICON_BRANCH, ICON_PR, ICON_MODEL = "", "", "", ""
ICON_CONTEXT, ICON_5H, ICON_7D = "", "", ""
ICONS_RE = re.compile("[]")

# (text with colours, priority, group): priority 0 never drops, a higher number drops sooner;
# segments of one group sit together and groups are joined by a separator.
Segment = tuple[str, int, int]


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _num(value, default: float = 0) -> float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _icon(glyph: str, text: str) -> str:
    return sgr(DIM, glyph) + " " + text


def _repo_name(repo) -> str | None:
    if isinstance(repo, dict):
        repo = f"{repo.get('owner')}/{repo.get('name')}" if repo.get("owner") and repo.get("name") else None
    return repo if isinstance(repo, str) and repo else None


def _first_row(data: dict, branch_name: str | None) -> list[Segment]:
    repo = _repo_name(_dict(data.get("workspace")).get("repo"))
    number = _dict(data.get("pr")).get("number")
    model = _dict(data.get("model"))
    name = model.get("display_name") or model.get("id")
    effort = _dict(data.get("effort")).get("level")
    segments: list[Segment] = []
    if repo:
        segments.append((_icon(ICON_REPO, repo), 2, 0))
    if branch_name:
        segments.append((_icon(ICON_BRANCH, branch_name), 0, 0))
    if number:
        segments.append((_icon(ICON_PR, f"#{number}"), 3, 0))
    if name:
        segments.append((_icon(ICON_MODEL, sgr(BOLD, str(name))), 0, 1))
        if effort:
            segments.append((f"· {effort}", 1, 1))
    return segments


def _second_row(data: dict, env: dict, now: float, files: list[dict]) -> list[Segment]:
    window = _dict(data.get("context_window"))
    used = int(_num(window.get("total_input_tokens")))
    size = int(_num(window.get("context_window_size"))) or 200_000
    limit = ceiling(compact_window(str(_dict(data.get("model")).get("id") or ""), size, env, files))
    pct = used / limit * 100 if used > 0 and limit > 0 else 0
    segments: list[Segment] = [
        (_icon(ICON_CONTEXT, f"{meter(pct, 8)} {_round_half_up(pct)}%  {fmt_tokens(used)}/{fmt_tokens(max(limit, 0))}"), 0, 0)
    ]
    # (key, icon, group, meter priority, reset priority)
    for key, glyph, group, meter_priority, reset_priority in (
        ("five_hour", ICON_5H, 1, 1, 3),
        ("seven_day", ICON_7D, 2, 2, 4),
    ):
        usage = _dict(_dict(data.get("rate_limits")).get(key))
        if not isinstance(usage.get("used_percentage"), (int, float)):
            continue  # no such window for this plan: leave the segment out
        used_pct = usage["used_percentage"]
        segments.append((_icon(glyph, f"{meter(used_pct, 5)} {_round_half_up(used_pct)}%"), meter_priority, group))
        if isinstance(usage.get("resets_at"), (int, float)):
            segments.append((fmt_reset(usage["resets_at"], now), reset_priority, group))
    cost = _dict(data.get("cost"))
    if isinstance(cost.get("total_cost_usd"), (int, float)):
        added = int(_num(cost.get("total_lines_added")))
        removed = int(_num(cost.get("total_lines_removed")))
        segments.append((f"${cost['total_cost_usd']:.2f}", 5, 3))
        segments.append((f"+{added} −{removed}", 6, 3))
    return segments


def rows(data: dict, env: dict, now: float, files: list[dict], branch_name: str | None) -> list[list[Segment]]:
    return [_first_row(data, branch_name), _second_row(data, env, now, files)]


def fit(segments: list[Segment], width: int) -> str:
    """Joins the segments, dropping the highest-priority-number one until the row fits width cells.
    A row whose never-dropped segments are still too wide is returned as it is."""
    kept = list(segments)
    while True:
        groups: dict[int, list[str]] = {}
        for text, _, group in kept:
            groups.setdefault(group, []).append(text)
        line = SEPARATOR.join(" ".join(texts) for texts in groups.values())
        droppable = [s for s in kept if s[1] > 0]
        if cells(line) <= width or not droppable:
            return line
        kept.remove(max(droppable, key=lambda s: s[1]))


def plain(text: str) -> str:
    """Text without colour codes and with each icon as one space, to read or test without the font."""
    return ICONS_RE.sub(" ", SGR_RE.sub("", text))


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return _dict(json.load(f))
    except (OSError, ValueError):
        return {}


def render(data: dict, env: dict, now: float) -> str:
    workspace = _dict(data.get("workspace"))
    current = workspace.get("current_dir") or os.getcwd()
    project = workspace.get("project_dir") or current
    files = [_read_json(p) for p in settings_files(os.path.expanduser("~"), project, sys.platform)]
    # workspace.branch is not part of Claude Code's JSON; the demo and the installer's check use it to
    # show a fixed branch instead of whatever the current directory happens to have checked out.
    pinned = workspace.get("branch")
    branch_name = pinned if isinstance(pinned, str) and pinned else branch(current)
    try:
        columns = int(env.get("COLUMNS") or DEFAULT_COLUMNS)
    except ValueError:
        columns = DEFAULT_COLUMNS
    width = max(columns - MARGIN, 1)
    return "\n".join(fit(row, width) for row in rows(data, env, now, files, branch_name))


# The demo is rendered at this fixed time so its reset countdowns read 2h10m and 3d4h whenever it runs.
DEMO_NOW = 1_700_000_000
DEMO = {
    "workspace": {"current_dir": ".", "repo": "Doofess/claude-setup", "branch": "main"},
    "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
    "effort": {"level": "high"},
    "pr": {"number": 12},
    "context_window": {"total_input_tokens": 112_000, "context_window_size": 300_000, "used_percentage": 37},
    "rate_limits": {
        "five_hour": {"used_percentage": 23, "resets_at": DEMO_NOW + 2 * 3600 + 10 * 60},
        "seven_day": {"used_percentage": 41, "resets_at": DEMO_NOW + 3 * 86400 + 4 * 3600},
    },
    "cost": {"total_cost_usd": 1.23, "total_lines_added": 156, "total_lines_removed": 23},
}


def demo_sample(now: float) -> dict:
    """DEMO with its reset times moved so they lie the same distance ahead of `now` as they do of DEMO_NOW.

    The installer feeds this to the real command, which reads the clock, so fixed resets would show →now."""
    shift = now - DEMO_NOW
    limits = {
        name: {**usage, "resets_at": usage["resets_at"] + shift}
        for name, usage in DEMO["rate_limits"].items()
    }
    return {**DEMO, "rate_limits": limits}


def main(argv: list[str]) -> int:
    try:
        for stream in (sys.stdin, sys.stdout):  # Windows would otherwise use the legacy code page
            stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        if "--demo" in argv:
            # The environment outranks every settings file, so pinning the window here makes the demo
            # read the same on every machine (300k window, 267k auto-compact point).
            print(render(DEMO, {**os.environ, "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "300000"}, DEMO_NOW))
        elif "--demo-json" in argv:
            print(json.dumps(demo_sample(time.time())))
        else:
            print(render(_dict(json.loads(sys.stdin.read())), os.environ, time.time()))
    except Exception as error:  # the bar must never crash Claude Code's UI
        print("statusbar:", error)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
