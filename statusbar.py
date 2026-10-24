"""A one-line status bar for Claude Code (Claude Code's own mode line below it makes two).

Usage: Claude Code runs `python statusbar.py` and pipes its session JSON to stdin; `--demo` prints
sample data instead and `--demo-json` prints that sample as the JSON Claude Code would send. Column width comes from the COLUMNS environment variable (default 120).

The line reads left to right: repo (owner/name), git branch │ model, a bolt, effort │ a context
meter with tokens used out of the auto-compact point │ the 5-hour and 7-day plan usage meters with the
time until each resets, each named 5H or 7D beside its icon │ cost │ how long the session has run. Each piece has a Nerd Font icon in front; `--labels` swaps the icons for
short words (ctx, 5H, 7D, session) so the bar also reads in a font without the glyphs (the installer adds the flag
on a machine with no Nerd Font). Colours are the terminal's own 16-colour palette, so the bar follows the
terminal's scheme: cost green, each model (Opus in Claude orange, Fable a gold gradient) and each effort level its own colour (xhigh and max
held still as the /effort picker animates them: a violet shimmer and a rainbow). Everything else is sent as
exact 24-bit colours, never the terminal's default foreground (a light grey in most schemes): the chrome
(separators, the place and model icons, branch name, reset times) in pure white, the branch icon in the meters' yellow; the repo name and the session time with its clock in the
violet Claude Code highlights with (its dark theme's `permission` colour, rgb 177,185,249); and the three
8-cell meters, whose icon, figures, filled blocks and (darker) unfilled blocks all take the meter's level:
green below 50%, yellow from 50, orange from 70, red from 90. Nothing is grey.

Width fitting: the line may use COLUMNS minus a small margin that Claude Code keeps for itself. Each
piece (a segment) has a priority. While the line is too wide, the piece with the highest priority
number is dropped: the session time first, then cost, then the 7-day and 5-hour reset times, then
the 7-day and 5-hour meters; the repo, the branch, the model with its effort and the context meter always stay. Once
the line fits, dropped pieces that still fit come back, most important first, so no room is left unused.
When even the pieces that always stay are too wide, the repo gives up the difference: its owner goes
first, then its name is cut with an ellipsis.

The 33k headroom: the context meter does not run to the full context window but to the point where
Claude Code auto-compacts. That point is the auto-compact window (from the environment or the
settings files, else the model's own window) minus 33,000 tokens, which is the 13,000 tokens Claude
Code keeps free plus the 20,000 it reserves for the reply. A meter at 100% means compaction is due.

Overflow: the pieces a narrow terminal dropped are written, per session, to
`~/.claude/statusbar-overflow/<session_id>.json`, each piece a list of spans `{"text", "colour", "bold"}`
(colour a terminal name such as `green`/`redBright`, a hex value for the 24-bit ones, or null). The record
says where the `session-cards` mod draws each one on Claude Code's own hint line: `under` holds a reset time
whose bar stayed, without its arrow, at the screen column of the bar's first block; `bars` holds each moved
meter with its reset time, the first one's first block under the last bar left on the top row (or a separator
after the reset times there), the next one a separator after it; `right` holds the rest, right-aligned, each
with its drop priority as `rank` so the mod drops the least important first when the hint needs the room.
`label` is the width of the mode label in front of the hint (`⏵⏵ bypass permissions on · `), read from the last
`permission-mode` entry near the end of the session transcript; `pieces` keeps the old flat list for an older
mod. Files older than a day are removed on each run; a session with no id writes nothing.

Standard library only. The branch is read straight from .git/HEAD, with no git subprocess. On any error
the bar prints one plain `statusbar: <error>` row.
"""
import json
import os
import re
import sys
import time
from typing import NamedTuple

GREEN = 32
YELLOW = 33
RED = 31
BOLD = 1
UNDERLINE = 4
# Claude Code's own highlight colour (the dark theme's `permission` token), 24-bit so it matches exactly: the repo name.
VIOLET = "38;2;177;185;249"
# The chrome: pure white, 24-bit, because the terminal's default foreground is a light grey in most schemes.
WHITE = "38;2;255;255;255"
# Opus is Claude orange (the dark theme's `claude` token), 24-bit so it matches exactly.
CLAUDE_ORANGE = "38;2;215;119;87"
# High effort is the red of `bypass permissions on` (the dark theme's `error` token), 24-bit so it matches exactly.
ERROR_RED = "38;2;255;107;128"
# Fable is a gold gradient across its name, first letter to last (linear in RGB); the icon takes the first colour.
FABLE_FROM = (255, 215, 0)  # #FFD700
FABLE_TO = (255, 140, 0)  # #FF8C00
FABLE_GOLD = "38;2;255;215;0"
# One colour per model family and per effort level, from the terminal's 16 (Opus aside). Magenta, blue and red are their bright
# variants: the plain ones are too dark to read on a black background (Campbell's blue is #0037DA).
MODEL_COLOURS = {"opus": CLAUDE_ORANGE, "sonnet": 94, "haiku": 36, "fable": FABLE_GOLD, "mythos": 92}  # Claude orange, bright blue, cyan, gold gradient, bright green
# xhigh and max are still frames of the /effort picker's animations (dark theme, 24-bit): xhigh's autoAccept violet
# shimmer with the light on its middle letter, and max's rainbow, which starts at the bolt and runs on through the word.
AUTO_ACCEPT = "38;2;175;135;255"
SHIMMER = "38;2;208;180;255"
RAINBOW = ["38;2;235;95;87", "38;2;245;139;87", "38;2;250;195;95", "38;2;145;200;130"]  # red, orange, yellow, green
EFFORT_COLOURS = {"low": GREEN, "medium": YELLOW, "high": ERROR_RED, "xhigh": AUTO_ACCEPT, "max": RAINBOW[0]}  # the bolt's colour
BLOCK = "█"
# Meter levels: (filled colour, unfilled colour) as 24-bit SGR parameters. The unfilled part is the same hue at
# a third of the brightness, drawn with the same solid block, so the bar reads as one coloured bar with a dark
# track rather than a dotted texture. The level also colours the meter's icon and figures.
LEVELS = {
    "green": ("38;2;76;200;110", "38;2;25;67;37"),
    "yellow": ("38;2;235;200;60", "38;2;78;67;20"),
    "orange": (CLAUDE_ORANGE, "38;2;72;40;29"),  # Opus's Claude orange
    "red": (ERROR_RED, "38;2;85;36;43"),  # the red of `bypass permissions on`
}

SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
COLOUR_NAMES = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
OVERFLOW_DIR = os.path.join(".claude", "statusbar-overflow")
OVERFLOW_MAX_AGE = 86_400  # seconds a session's overflow file is kept after its last write


def sgr(code: int | str, text: str) -> str:
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
    """Time until a usage window resets: 45m, 2h10m, 3d4h, 5d. Under a minute or already past is now."""
    minutes = int(resets_at - now) // 60  # rounded down to the minute
    if minutes < 1:
        return "→now"
    if minutes < 60:
        return f"→ {minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"→ {hours}h{minutes % 60}m"
    days, hours = divmod(hours, 24)
    return f"→ {days}d" + (f"{hours}h" if hours else "")  # minutes would be noise this far out, and 0h is too


def fmt_elapsed(ms: float) -> str:
    """How long the session has run: 0m, 12m, 1h33m, 1d2h, 1d, with no space between the units, as the reset times."""
    minutes = int(ms) // 60_000
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h{minutes % 60}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours}h" if hours else f"{days}d"


def meter(pct: float, cells: int) -> str:
    """A bar of `cells` solid blocks filled to pct: the filled part in the level colour, the rest in its dark shade."""
    filled = max(0, min(cells, _round_half_up(pct / 100 * cells)))
    fill, track = level_colours(pct)
    return (sgr(fill, BLOCK * filled) if filled else "") + (sgr(track, BLOCK * (cells - filled)) if cells > filled else "")


def level_colours(pct: float) -> tuple[str, str]:
    """(filled, unfilled) colours for a meter at pct: green below 50, yellow from 50, orange from 70, red from 90."""
    name = "red" if pct >= 90 else "orange" if pct >= 70 else "yellow" if pct >= 50 else "green"
    return LEVELS[name]


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


def _remote_url(config_text: str) -> str | None:
    """The url of [remote "origin"] in a git config file's text (a line parser: configparser chokes on subsections)."""
    in_origin = False
    for line in config_text.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_origin = re.fullmatch(r'\[\s*remote\s+"origin"\s*\]', line) is not None
        elif in_origin:
            key, _, value = line.partition("=")
            if key.strip().lower() == "url" and value.strip():
                return value.strip()
    return None


def origin_remote(cwd: str, stop_dir: str | None = None) -> tuple[str, str] | None:
    """(host kind, "owner/name") of the origin remote, read from the git config without git; None on any failure.

    host kind is "github", "gitlab" (gitlab.com or a host with "gitlab" in its name) or "other". A linked worktree's
    .git file leads to its gitdir and that gitdir's commondir, which holds the config. stop_dir ends the walk up
    from cwd after looking there (tests use it)."""
    try:
        here = os.path.abspath(cwd)
        stop = os.path.abspath(stop_dir) if stop_dir else None
        while not os.path.exists(os.path.join(here, ".git")):
            parent = os.path.dirname(here)
            if parent == here or here == stop:
                return None
            here = parent
        git = os.path.join(here, ".git")
        if os.path.isfile(git):
            pointer = _read_small(git) or ""
            if not pointer.startswith("gitdir:"):
                return None
            git = os.path.join(here, pointer[len("gitdir:"):].strip())
            common = _read_small(os.path.join(git, "commondir"))
            if common:
                git = os.path.join(git, common)
        with open(os.path.join(git, "config"), encoding="utf-8", errors="replace") as f:
            url = _remote_url(f.read())
        match = url and (re.fullmatch(r"[\w+.-]+://(?:[^@/]*@)?([^/:]+)(?::\d+)?/(.+)", url)
                         or re.fullmatch(r"(?:[^@/:]+@)?([^/:]+):(?!//)(.+)", url))
        if not match:
            return None
        host, path = match.group(1).lower(), match.group(2).strip("/").removesuffix(".git")
        if not path:
            return None
        kind = "github" if host == "github.com" else "gitlab" if host == "gitlab.com" or "gitlab" in host else "other"
        return kind, path
    except (OSError, ValueError):
        return None


MARGIN = 4  # cells Claude Code keeps for its own spacing around the status line
STATUS_X = 2  # screen column of the status line's first cell (measured on 2.1.310)
# Cells of the mode label Claude Code draws before its hint: symbol, space, indicator, " on", " · " (measured on 2.1.310).
LABEL_CELLS = {"default": 0, "acceptEdits": 21, "auto": 18, "bypassPermissions": 27, "dontAsk": 18, "plan": 17}
LABEL_TAIL = 65_536  # bytes read from the end of the transcript to find the permission mode
DEFAULT_COLUMNS = 120
SEPARATOR = sgr(WHITE, " │ ")  # separators, icons and labels are explicit white: no grey text

class Segment(NamedTuple):
    """One piece of the line, its text with colours. priority 0 never drops, a higher number drops sooner; segments
    of one group sit together and groups are joined by a separator. role names the meters and reset times the
    overflow places by their bar: "meter:ctx", "meter:5h", "reset:5h", "meter:7d", "reset:7d", or "" for the rest."""
    text: str
    priority: int
    group: int
    role: str = ""


# Drop order, least important first (the user's call: session time, cost, then reset times, then the rest). The repo
# never drops: it always opens the line, like the branch, the model with its effort (they stay together) and the
# context meter. Claude Code draws the PR badge itself, so the bar has no PR piece.
P_TIME, P_COST, P_7D_RESET, P_5H_RESET, P_7D, P_5H = 6, 5, 4, 3, 2, 1
G_PLACE, G_MODEL, G_CONTEXT, G_5H, G_7D, G_COST, G_TIME = range(7)
GROUP_JOIN = {G_MODEL: " "}  # "Opus <bolt> high", or "Opus · high" under --labels; every other group joins its pieces with two spaces

# Markers before a piece: a Nerd Font glyph (the default) or, with --labels, a short word for fonts without the
# glyphs (then the repo, branch and model carry no marker: they read on their own). Every glyph is followed
# by a space because the non-Mono Nerd Font variants draw it wider than one cell and it would overlap the text.
ICONS = {"repo": "\uf09b", "branch": "\ue0a0", "model": "󰚩", "effort": "", "ctx": "\uf1c0", "5h": "\uf017", "7d": "\uf073",
         "time": "󰅐"}  # time: md-clock-outline, since fa-clock-o is the 5-hour window's
LABELS = {"effort": "·", "ctx": "ctx", "5h": "5H", "7d": "7D", "time": "session"}
GITLAB = "38;2;252;109;38"  # #FC6D26, GitLab's orange
# The repo piece's icon and colour by host kind (origin_remote): GitHub, GitLab, and the plain git glyph for the rest.
REPO_LOOKS = {"github": (ICONS["repo"], VIOLET), "gitlab": ("", GITLAB), "other": ("", VIOLET)}
ICONS_RE = re.compile("[" + "".join(ICONS.values()) + "".join(icon for icon, _ in REPO_LOOKS.values()) + "]")


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _num(value, default: float = 0) -> float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _mark(markers: dict, key: str, text: str, colour: int | str | None = None) -> str:
    """text with its marker (icon or label) in front, or bare when this marker set has none for key.
    The marker (and its space) is drawn in colour, white by default."""
    marker = markers.get(key)
    if not marker:
        return text
    return sgr(colour or WHITE, marker + " ") + text


def model_colour(name: str) -> int | str | None:
    """SGR colour for a model display name or id (Opus, claude-sonnet-5-5, Fable 5.1); None when unknown."""
    lowered = name.lower()
    return next((code for family, code in MODEL_COLOURS.items() if family in lowered), None)


def gradient(text: str, start: tuple[int, int, int], end: tuple[int, int, int]) -> str:
    """text with each character its own 24-bit colour, linear in RGB from start (first) to end (last); one reset at the end."""
    last = max(len(text) - 1, 1)
    parts = []
    for i, char in enumerate(text):
        r, g, b = (round(a + (z - a) * i / last) for a, z in zip(start, end))
        parts.append(f"[38;2;{r};{g};{b}m{char}")
    return "".join(parts) + "[0m"


def model_text(name: str) -> str:
    """The model name in bold, in its family colour: Fable's name as its gold gradient."""
    colour = model_colour(name)
    if colour == FABLE_GOLD:
        return sgr(BOLD, gradient(name, FABLE_FROM, FABLE_TO))
    return sgr(BOLD, _coloured(name, colour))


def effort_colour(level: str) -> int | str | None:
    return EFFORT_COLOURS.get(level.lower())


def effort_text(level: str) -> str:
    """The effort level in its colour; xhigh and max letter by letter, as the /effort picker draws them, held still."""
    lowered = level.lower()
    if lowered == "xhigh":
        middle = len(level) // 2
        return "".join(sgr(SHIMMER if i == middle else AUTO_ACCEPT, char) for i, char in enumerate(level))
    if lowered == "max":
        return "".join(sgr(RAINBOW[1 + i % 3], char) for i, char in enumerate(level))
    return _coloured(level, effort_colour(level))


def _coloured(text: str, colour: int | str | None) -> str:
    return sgr(colour, text) if colour else text


def _repo_name(repo) -> str | None:
    if isinstance(repo, dict):
        repo = f"{repo.get('owner')}/{repo.get('name')}" if repo.get("owner") and repo.get("name") else None
    return repo if isinstance(repo, str) and repo else None


def short_repo(repo: str, room: int) -> str:
    """repo in at most room cells: whole, then without its owner, then cut with an ellipsis (one letter at least)."""
    if cells(repo) <= room:
        return repo
    name = repo.rsplit("/", 1)[-1]
    if cells(name) <= room:
        return name
    return name[:max(room - 1, 1)] + "…"


def _meter_piece(marks: dict, key: str, pct: float, cells: int, detail: str = "", name: str = "") -> str:
    """icon, bar and figures of one meter, the icon and figures in the bar's level colour.

    name: a word drawn before the bar when the marker is an icon (5H, 7D), so the window is named
    even for a reader who does not know the glyphs; under --labels the marker is that word already."""
    fill = level_colours(pct)[0]
    figures = f" {_round_half_up(pct)}%" + (f"  {detail}" if detail else "")
    bar = (sgr(fill, name) + " " if name and marks is ICONS else "") + meter(pct, cells)
    return _mark(marks, key, bar, fill) + sgr(fill, figures)


def segments(data: dict, env: dict, now: float, files: list[dict], branch_name: str | None, icons: bool = True,
             repo_shrink: int = 0) -> list[Segment]:
    """The whole line as segments, in display order; icons=False uses the text labels.
    repo_shrink: cells the repo must give up (see short_repo), for a terminal too narrow for the never-dropped pieces."""
    out: list[Segment] = []
    marks = ICONS if icons else LABELS
    workspace = _dict(data.get("workspace"))
    repo = _repo_name(workspace.get("repo"))
    remote = origin_remote(str(workspace.get("current_dir") or os.getcwd()))
    repo = repo or (remote[1] if remote else None)
    kind = remote[0] if remote else "github"  # Claude Code fills workspace.repo for GitHub only
    model = _dict(data.get("model"))
    name = model.get("display_name") or model.get("id")
    effort = _dict(data.get("effort")).get("level")
    if repo:
        icon, colour = REPO_LOOKS[kind]
        repo = short_repo(repo, cells(repo) - repo_shrink) if repo_shrink > 0 else repo
        out.append(Segment(_mark({"repo": icon} if marks is ICONS else marks, "repo", sgr(colour, repo), colour), 0, G_PLACE))
    if branch_name:
        # The branch icon is the meters' yellow; the name stays white.
        out.append(Segment(_mark(marks, "branch", sgr(WHITE, branch_name), LEVELS["yellow"][0]), 0, G_PLACE))
    if name:
        colour = model_colour(str(name))
        out.append(Segment(_mark(marks, "model", model_text(str(name)), colour), 0, G_MODEL))
        if effort:
            level = effort_colour(str(effort))
            # The bolt takes the level's colour; the --labels dot stays white.
            out.append(Segment(_mark(marks, "effort", effort_text(str(effort)), level if marks is ICONS else None), 0, G_MODEL))

    window = _dict(data.get("context_window"))
    used = int(_num(window.get("total_input_tokens")))
    size = int(_num(window.get("context_window_size"))) or 200_000
    limit = ceiling(compact_window(str(model.get("id") or ""), size, env, files))
    pct = used / limit * 100 if used > 0 and limit > 0 else 0
    out.append(Segment(_meter_piece(marks, "ctx", pct, 8, f"{fmt_tokens(used)}/{fmt_tokens(max(limit, 0))}"), 0, G_CONTEXT, "meter:ctx"))

    for key, mark, group, meter_priority, reset_priority in (
        ("five_hour", "5h", G_5H, P_5H, P_5H_RESET),
        ("seven_day", "7d", G_7D, P_7D, P_7D_RESET),
    ):
        usage = _dict(_dict(data.get("rate_limits")).get(key))
        if not isinstance(usage.get("used_percentage"), (int, float)):
            continue  # no such window for this plan: leave the segment out
        used_pct = usage["used_percentage"]
        out.append(Segment(_meter_piece(marks, mark, used_pct, 8, name=LABELS[mark]), meter_priority, group, f"meter:{mark}"))
        if isinstance(usage.get("resets_at"), (int, float)):
            out.append(Segment(sgr(WHITE, fmt_reset(usage["resets_at"], now)), reset_priority, group, f"reset:{mark}"))

    cost = _dict(data.get("cost"))
    if isinstance(cost.get("total_cost_usd"), (int, float)):
        out.append(Segment(sgr(GREEN, f"${cost['total_cost_usd']:.2f}"), P_COST, G_COST))
    elapsed = cost.get("total_duration_ms")
    if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and 0 <= elapsed < float("inf"):
        out.append(Segment(_mark(marks, "time", sgr(VIOLET, fmt_elapsed(elapsed)), VIOLET), P_TIME, G_TIME))
    return out


def _join(segments: list[Segment]) -> str:
    groups: dict[int, list[str]] = {}
    for segment in segments:
        groups.setdefault(segment.group, []).append(segment.text)
    return SEPARATOR.join(GROUP_JOIN.get(group, "  ").join(texts) for group, texts in groups.items())


def layout(segments: list[Segment], width: int) -> tuple[str, list[Segment]]:
    """The line fitted to width cells, and the pieces it left out in display order: drops the
    highest-priority-number piece until the line fits, then puts back, most important first, each dropped piece
    that still fits, so a wide piece that had to go does not leave room unused (a reset time only beside its meter,
    since the overflow draws a moved reset under its bar). A line whose never-dropped
    pieces are still too wide is returned as it is."""
    kept = list(segments)
    dropped: list[Segment] = []
    while cells(_join(kept)) > width:
        droppable = [s for s in kept if s.priority > 0]
        if not droppable:
            break
        victim = max(droppable, key=lambda s: s.priority)
        kept.remove(victim)
        dropped.append(victim)
    for candidate in sorted(dropped, key=lambda s: s.priority):
        kind, _, window = candidate.role.partition(":")
        if kind == "reset" and not any(s.role == f"meter:{window}" for s in kept):
            continue
        trial = [s for s in segments if s in kept or s is candidate]  # display order
        if cells(_join(trial)) <= width:
            kept = trial
    return _join(kept), [s for s in segments if s not in kept]


def fit(segments: list[Segment], width: int) -> str:
    """The line `layout` fits to width cells."""
    return layout(segments, width)[0]


def spans(text: str) -> list[dict]:
    """text split into runs of one style, each `{"text", "colour", "bold"}` (plus `"underline": true` where underlined), for the mod to draw: the colour is
    a terminal name (`green`, `redBright`), a hex value for a 24-bit colour, or None for the default."""
    out: list[dict] = []
    colour: str | None = None
    bold = underline = False
    pos = 0
    for match in SGR_RE.finditer(text):
        _add_span(out, text[pos:match.start()], colour, bold, underline)
        pos = match.end()
        params = match.group()[2:-1]
        if params in ("", "0"):
            colour, bold, underline = None, False, False
        elif params == "1":
            bold = True
        elif params == "4":
            underline = True
        elif params.startswith("38;2;"):
            r, g, b = (int(v) for v in params.split(";")[2:5])
            colour = f"#{r:02x}{g:02x}{b:02x}"
        elif params.isdigit() and 30 <= int(params) <= 37:
            colour = COLOUR_NAMES[int(params) - 30]
        elif params.isdigit() and 90 <= int(params) <= 97:
            colour = COLOUR_NAMES[int(params) - 90] + "Bright"
    _add_span(out, text[pos:], colour, bold, underline)
    return out


def _add_span(out: list[dict], text: str, colour: str | None, bold: bool, underline: bool = False) -> None:
    """Appends a run, merged into the last one when the style is the same; `underline` is only written when set."""
    if not text:
        return
    span = {"text": text, "colour": colour, "bold": bold} | ({"underline": True} if underline else {})
    if out and {**out[-1], "text": text} == span:
        out[-1]["text"] += text
    else:
        out.append(span)


def _to_block(text: str) -> int:
    """Cells of text before its first meter block (all of it when it has none)."""
    return cells(text.split(BLOCK, 1)[0])


def overflow_record(kept: list[Segment], dropped: list[Segment], columns: int, now: float, label: int) -> dict:
    """What the overflow file holds: when it was written, the terminal width the line was fitted to, the dropped
    pieces as spans in display order (`pieces`), the mode label's width (`label`), and where the mod draws each one:
    `under` a kept meter (its reset time without the arrow, at the screen column of the meter's first block),
    `bars` (a dropped meter with its reset, the first one's first block under the last kept meter's, each next one a
    separator's width after the one before), or `right` (the rest). bars and right carry their drop priority as rank."""
    def first_block(meter: Segment) -> int:  # screen column of a kept meter's first block
        upto = kept[:kept.index(meter) + 1]  # a meter is its group's first piece, so this joined line ends with it
        return STATUS_X + cells(_join(upto)) - cells(meter.text) + _to_block(meter.text)

    meters = {s.role.partition(":")[2]: s for s in kept if s.role.startswith("meter:")}
    last = next((s for s in reversed(kept) if s.role.startswith("meter:")), None)
    resets = {s.role.partition(":")[2]: s for s in dropped if s.role.startswith("reset:")}
    under: list[dict] = []
    bars: list[dict] = []
    widths: list[int] = []
    right: list[dict] = []
    for s in dropped:
        kind, _, window = s.role.partition(":")
        if kind == "reset" and window in meters:
            under.append({"col": first_block(meters[window]), "spans": spans(re.sub("→ ?", "", s.text, count=1))})
        elif kind == "meter" and last:
            text = s.text + ("  " + resets[window].text if window in resets else "")
            # The first one lines up under the last kept meter, unless that meter's own reset is there: then it
            # starts a separator after the reset times.
            clear = max((u["col"] + cells("".join(span["text"] for span in u["spans"])) + 3 for u in under), default=0)
            col = bars[-1]["col"] + widths[-1] + 3 if bars else max(first_block(last) - _to_block(s.text), clear)
            bars.append({"col": col, "rank": s.priority, "spans": spans(text)})
            widths.append(cells(text))
        elif kind == "reset" and last:
            continue  # drawn after its meter in bars
        else:
            right.append({"rank": s.priority, "spans": spans(s.text)})
    return {"written_at": now, "columns": columns, "pieces": [spans(s.text) for s in dropped], "label": label,
            "under": under, "bars": bars, "right": right}


def mode_label_cells(transcript_path: str | None) -> int:
    """Cells of the permission-mode label Claude Code draws before its hint (`⏵⏵ bypass permissions on · `), for the
    mode in the last `permission-mode` entry of the transcript's last LABEL_TAIL bytes. With no transcript, no such
    entry or a mode it does not know, the bypass width."""
    mode = None
    try:
        with open(transcript_path, "rb") as f:  # type: ignore[arg-type]  # None raises TypeError, caught below
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - LABEL_TAIL))
            tail = f.read().decode("utf-8", "replace")
        for line in reversed(tail.splitlines()):
            if "permission-mode" not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # the line the tail cut, or one half written
            if isinstance(entry, dict) and entry.get("type") == "permission-mode":
                mode = entry.get("permissionMode")
                break
    except (OSError, TypeError, ValueError):
        pass
    return LABEL_CELLS[mode] if isinstance(mode, str) and mode in LABEL_CELLS else LABEL_CELLS["bypassPermissions"]


def prune_overflow(folder: str, now: float) -> None:
    """Removes the overflow files not written for OVERFLOW_MAX_AGE: sessions that ended."""
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        try:
            if name.endswith(".json") and os.path.getmtime(path) < now - OVERFLOW_MAX_AGE:
                os.remove(path)
        except OSError:
            pass


def write_overflow(home: str, session_id: str, record: dict) -> None:
    """Writes record to home/.claude/statusbar-overflow/<session_id>.json in one step (a temp file renamed over
    it), so the mod never reads half a file, and prunes the folder's stale files."""
    folder = os.path.join(home, OVERFLOW_DIR)
    os.makedirs(folder, exist_ok=True)
    prune_overflow(folder, record["written_at"])
    path = os.path.join(folder, re.sub(r"[^\w.-]", "_", session_id) + ".json")
    temp = f"{path}.{os.getpid()}.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(record, f)
    os.replace(temp, path)


def plain(text: str) -> str:
    """Text without colour codes and with each icon as one space, to read or test without the font."""
    return ICONS_RE.sub(" ", SGR_RE.sub("", text))


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return _dict(json.load(f))
    except (OSError, ValueError):
        return {}


def compose(data: dict, env: dict, now: float, icons: bool = True) -> tuple[str, list[Segment], list[Segment], int]:
    """The fitted line, the pieces it kept and those it left out, and the terminal width it was fitted for."""
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
    row = segments(data, env, now, files, branch_name, icons)
    line, dropped = layout(row, width)
    if cells(line) > width:  # the never-dropped pieces alone are too wide: the repo gives up the difference
        row = segments(data, env, now, files, branch_name, icons, cells(line) - width)
        line, dropped = layout(row, width)
    return line, [s for s in row if s not in dropped], dropped, columns


def render(data: dict, env: dict, now: float, icons: bool = True) -> str:
    return compose(data, env, now, icons)[0]


# The demo is rendered at this fixed time so its reset countdowns read 2h10m and 3d4h whenever it runs.
DEMO_NOW = 1_700_000_000
DEMO = {
    "workspace": {"current_dir": ".", "repo": "Doofess/claude-setup", "branch": "main"},
    "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
    "effort": {"level": "high"},
    "context_window": {"total_input_tokens": 112_000, "context_window_size": 300_000, "used_percentage": 37},
    "rate_limits": {
        "five_hour": {"used_percentage": 23, "resets_at": DEMO_NOW + 2 * 3600 + 10 * 60},
        "seven_day": {"used_percentage": 41, "resets_at": DEMO_NOW + 3 * 86400 + 4 * 3600},
    },
    "cost": {"total_cost_usd": 1.23, "total_duration_ms": 5_580_000},
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
    icons = "--labels" not in argv  # --labels: words instead of Nerd Font glyphs, for any monospace font
    try:
        if "--demo" in argv:
            # The environment outranks every settings file, so pinning the window here makes the demo
            # read the same on every machine (300k window, 267k auto-compact point).
            print(render(DEMO, {**os.environ, "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "300000"}, DEMO_NOW, icons))
        elif "--demo-json" in argv:
            print(json.dumps(demo_sample(time.time())))
        else:
            data = _dict(json.loads(sys.stdin.read()))
            now = time.time()
            line, kept, dropped, columns = compose(data, os.environ, now, icons)
            print(line)
            session_id = data.get("session_id")
            if isinstance(session_id, str) and session_id:
                try:
                    label = mode_label_cells(data.get("transcript_path"))
                    write_overflow(os.path.expanduser("~"), session_id, overflow_record(kept, dropped, columns, now, label))
                except Exception:  # the line is already printed; a lost overflow file costs nothing visible
                    pass
    except Exception as error:  # the bar must never crash Claude Code's UI
        print("statusbar:", error)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
