"""A one-line status bar for Claude Code (Claude Code's own mode line below it makes two).

Usage: Claude Code runs `python statusbar.py` and pipes its session JSON to stdin; `--demo` prints
sample data instead and `--demo-json` prints that sample as the JSON Claude Code would send. Column width comes from the COLUMNS environment variable (default 120).

The line reads left to right: repo (owner/name), git branch, PR number │ model · effort │ a context
meter with tokens used out of the auto-compact point │ the 5-hour and 7-day plan usage meters with the
time until each resets, each named 5H or 7D beside its icon │ cost. Each piece has a Nerd Font icon in front; `--labels` swaps the icons for
short words (ctx, 5H, 7D) so the bar also reads in a font without the glyphs (the installer adds the flag
on a machine with no Nerd Font). Colours are the terminal's own 16-colour palette, so the bar follows the
terminal's scheme: cost green, each model and each effort level its own colour. Everything else is sent as
exact 24-bit colours, never the terminal's default foreground (a light grey in most schemes): the chrome
(separators, the place and model icons, branch, PR number, reset times) in pure white; the repo name in the
violet Claude Code highlights with (its dark theme's `permission` colour, rgb 177,185,249); and the three
8-cell meters, whose icon, figures, filled blocks and (darker) unfilled blocks all take the meter's level:
green below 50%, yellow from 50, orange from 70, red from 90. Nothing is grey.

Width fitting: the line may use COLUMNS minus a small margin that Claude Code keeps for itself. Each
piece (a segment) has a priority. While the line is too wide, the piece with the highest priority
number is dropped: cost first, then the 7-day and 5-hour reset times, the PR number, the repo, the
effort, then the 7-day and 5-hour meters; the branch, the model and the context meter always stay. Once
the line fits, dropped pieces that still fit come back, most important first, so no room is left unused.

The 33k headroom: the context meter does not run to the full context window but to the point where
Claude Code auto-compacts. That point is the auto-compact window (from the environment or the
settings files, else the model's own window) minus 33,000 tokens, which is the 13,000 tokens Claude
Code keeps free plus the 20,000 it reserves for the reply. A meter at 100% means compaction is due.

Overflow: the pieces a narrow terminal dropped are written, per session, to
`~/.claude/statusbar-overflow/<session_id>.json` as `{"written_at", "columns", "pieces"}`, each piece a
list of spans `{"text", "colour", "bold"}` (colour a terminal name such as `green`/`redBright`, a hex
value for the 24-bit ones, or null). The `session-cards` mod draws them on Claude Code's own hint line,
to the right of the permissions text, so a piece only disappears when both lines are full. Files older
than a day are removed on each run; a session with no id writes nothing.

Standard library only. The branch is read straight from .git/HEAD, with no git subprocess. On any error
the bar prints one plain `statusbar: <error>` row.
"""
import json
import os
import re
import sys
import time

GREEN = 32
YELLOW = 33
RED = 31
BOLD = 1
# Claude Code's own highlight colour (the dark theme's `permission` token), 24-bit so it matches exactly: the repo name.
VIOLET = "38;2;177;185;249"
# The chrome: pure white, 24-bit, because the terminal's default foreground is a light grey in most schemes.
WHITE = "38;2;255;255;255"
# One colour per model family and per effort level, from the terminal's 16. Magenta, blue and red are their bright
# variants: the plain ones are too dark to read on a black background (Campbell's blue is #0037DA).
MODEL_COLOURS = {"opus": 95, "sonnet": 94, "haiku": 36, "fable": 93, "mythos": 92}  # bright magenta, bright blue, cyan, gold, bright green
EFFORT_COLOURS = {"low": GREEN, "medium": YELLOW, "high": 91, "xhigh": 95, "max": 97}  # a heat ramp: green, yellow, bright red, bright magenta, white-hot
BLOCK = "█"
# Meter levels: (filled colour, unfilled colour) as 24-bit SGR parameters. The unfilled part is the same hue at
# a third of the brightness, drawn with the same solid block, so the bar reads as one coloured bar with a dark
# track rather than a dotted texture. The level also colours the meter's icon and figures.
LEVELS = {
    "green": ("38;2;76;200;110", "38;2;25;67;37"),
    "yellow": ("38;2;235;200;60", "38;2;78;67;20"),
    "orange": ("38;2;255;140;40", "38;2;85;47;13"),
    "red": ("38;2;240;80;80", "38;2;80;27;27"),
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
    """Time until a usage window resets: 45m, 2h10m, 3d4h. Under a minute or already past is now."""
    minutes = int(resets_at - now) // 60  # rounded down to the minute
    if minutes < 1:
        return "→now"
    if minutes < 60:
        return f"→ {minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"→ {hours}h{minutes % 60}m"
    return f"→ {hours // 24}d{hours % 24}h"  # minutes would be noise this far out


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


MARGIN = 4  # cells Claude Code keeps for its own spacing around the status line
DEFAULT_COLUMNS = 120
SEPARATOR = sgr(WHITE, " │ ")  # separators, icons and labels are explicit white: no grey text

# (text with colours, priority, group): priority 0 never drops, a higher number drops sooner;
# segments of one group sit together and groups are joined by a separator.
Segment = tuple[str, int, int]
# Drop order, least important first (the user's call: cost, then reset times, then the rest).
P_COST, P_7D_RESET, P_5H_RESET, P_PR, P_REPO, P_EFFORT, P_7D, P_5H = 8, 7, 6, 5, 4, 3, 2, 1
G_PLACE, G_MODEL, G_CONTEXT, G_5H, G_7D, G_COST = range(6)
GROUP_JOIN = {G_MODEL: sgr(WHITE, " · ")}  # "Opus · high"; every other group joins its pieces with two spaces

# Markers before a piece: a Nerd Font glyph (the default) or, with --labels, a short word for fonts without the
# glyphs (then the repo, branch, PR and model carry no marker: they read on their own). Every glyph is followed
# by a space because the non-Mono Nerd Font variants draw it wider than one cell and it would overlap the text.
ICONS = {"repo": "\uf09b", "branch": "\ue0a0", "pr": "\uf407", "model": "\uf2db", "ctx": "\uf1c0", "5h": "\uf017", "7d": "\uf073"}
LABELS = {"ctx": "ctx", "5h": "5H", "7d": "7D"}
ICONS_RE = re.compile("[" + "".join(ICONS.values()) + "]")


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


def model_colour(name: str) -> int | None:
    """SGR colour for a model display name or id (Opus, claude-sonnet-5-5, Fable 5.1); None when unknown."""
    lowered = name.lower()
    return next((code for family, code in MODEL_COLOURS.items() if family in lowered), None)


def effort_colour(level: str) -> int | None:
    return EFFORT_COLOURS.get(level.lower())


def _coloured(text: str, colour: int | None) -> str:
    return sgr(colour, text) if colour else text


def _repo_name(repo) -> str | None:
    if isinstance(repo, dict):
        repo = f"{repo.get('owner')}/{repo.get('name')}" if repo.get("owner") and repo.get("name") else None
    return repo if isinstance(repo, str) and repo else None


def _meter_piece(marks: dict, key: str, pct: float, cells: int, detail: str = "", name: str = "") -> str:
    """icon, bar and figures of one meter, the icon and figures in the bar's level colour.

    name: a word drawn before the bar when the marker is an icon (5H, 7D), so the window is named
    even for a reader who does not know the glyphs; under --labels the marker is that word already."""
    fill = level_colours(pct)[0]
    figures = f" {_round_half_up(pct)}%" + (f"  {detail}" if detail else "")
    bar = (sgr(fill, name) + " " if name and marks is ICONS else "") + meter(pct, cells)
    return _mark(marks, key, bar, fill) + sgr(fill, figures)


def segments(data: dict, env: dict, now: float, files: list[dict], branch_name: str | None, icons: bool = True) -> list[Segment]:
    """The whole line as segments, in display order; icons=False uses the text labels."""
    out: list[Segment] = []
    marks = ICONS if icons else LABELS
    repo = _repo_name(_dict(data.get("workspace")).get("repo"))
    number = _dict(data.get("pr")).get("number")
    model = _dict(data.get("model"))
    name = model.get("display_name") or model.get("id")
    effort = _dict(data.get("effort")).get("level")
    if repo:
        out.append((_mark(marks, "repo", sgr(VIOLET, repo), VIOLET), P_REPO, G_PLACE))
    if branch_name:
        out.append((_mark(marks, "branch", sgr(WHITE, branch_name)), 0, G_PLACE))
    if number:
        out.append((_mark(marks, "pr", sgr(WHITE, f"#{number}")), P_PR, G_PLACE))
    if name:
        colour = model_colour(str(name))
        out.append((_mark(marks, "model", sgr(BOLD, _coloured(str(name), colour)), colour), 0, G_MODEL))
        if effort:
            out.append((_coloured(str(effort), effort_colour(str(effort))), P_EFFORT, G_MODEL))

    window = _dict(data.get("context_window"))
    used = int(_num(window.get("total_input_tokens")))
    size = int(_num(window.get("context_window_size"))) or 200_000
    limit = ceiling(compact_window(str(model.get("id") or ""), size, env, files))
    pct = used / limit * 100 if used > 0 and limit > 0 else 0
    out.append((_meter_piece(marks, "ctx", pct, 8, f"{fmt_tokens(used)}/{fmt_tokens(max(limit, 0))}"), 0, G_CONTEXT))

    for key, mark, group, meter_priority, reset_priority in (
        ("five_hour", "5h", G_5H, P_5H, P_5H_RESET),
        ("seven_day", "7d", G_7D, P_7D, P_7D_RESET),
    ):
        usage = _dict(_dict(data.get("rate_limits")).get(key))
        if not isinstance(usage.get("used_percentage"), (int, float)):
            continue  # no such window for this plan: leave the segment out
        used_pct = usage["used_percentage"]
        out.append((_meter_piece(marks, mark, used_pct, 8, name=LABELS[mark]), meter_priority, group))
        if isinstance(usage.get("resets_at"), (int, float)):
            out.append((sgr(WHITE, fmt_reset(usage["resets_at"], now)), reset_priority, group))

    cost = _dict(data.get("cost"))
    if isinstance(cost.get("total_cost_usd"), (int, float)):
        out.append((sgr(GREEN, f"${cost['total_cost_usd']:.2f}"), P_COST, G_COST))
    return out


def _join(segments: list[Segment]) -> str:
    groups: dict[int, list[str]] = {}
    for text, _, group in segments:
        groups.setdefault(group, []).append(text)
    return SEPARATOR.join(GROUP_JOIN.get(group, "  ").join(texts) for group, texts in groups.items())


def layout(segments: list[Segment], width: int) -> tuple[str, list[Segment]]:
    """The line fitted to width cells, and the pieces it left out in display order: drops the
    highest-priority-number piece until the line fits, then puts back, most important first, each dropped piece
    that still fits, so a wide piece that had to go does not leave room unused. A line whose never-dropped
    pieces are still too wide is returned as it is."""
    kept = list(segments)
    dropped: list[Segment] = []
    while cells(_join(kept)) > width:
        droppable = [s for s in kept if s[1] > 0]
        if not droppable:
            break
        victim = max(droppable, key=lambda s: s[1])
        kept.remove(victim)
        dropped.append(victim)
    for candidate in sorted(dropped, key=lambda s: s[1]):
        trial = [s for s in segments if s in kept or s is candidate]  # display order
        if cells(_join(trial)) <= width:
            kept = trial
    return _join(kept), [s for s in segments if s not in kept]


def fit(segments: list[Segment], width: int) -> str:
    """The line `layout` fits to width cells."""
    return layout(segments, width)[0]


def spans(text: str) -> list[dict]:
    """text split into runs of one style, each `{"text", "colour", "bold"}`, for the mod to draw: the colour is
    a terminal name (`green`, `redBright`), a hex value for a 24-bit colour, or None for the default."""
    out: list[dict] = []
    colour: str | None = None
    bold = False
    pos = 0
    for match in SGR_RE.finditer(text):
        _add_span(out, text[pos:match.start()], colour, bold)
        pos = match.end()
        params = match.group()[2:-1]
        if params in ("", "0"):
            colour, bold = None, False
        elif params == "1":
            bold = True
        elif params.startswith("38;2;"):
            r, g, b = (int(v) for v in params.split(";")[2:5])
            colour = f"#{r:02x}{g:02x}{b:02x}"
        elif params.isdigit() and 30 <= int(params) <= 37:
            colour = COLOUR_NAMES[int(params) - 30]
        elif params.isdigit() and 90 <= int(params) <= 97:
            colour = COLOUR_NAMES[int(params) - 90] + "Bright"
    _add_span(out, text[pos:], colour, bold)
    return out


def _add_span(out: list[dict], text: str, colour: str | None, bold: bool) -> None:
    if not text:
        return
    if out and out[-1]["colour"] == colour and out[-1]["bold"] == bold:
        out[-1]["text"] += text
    else:
        out.append({"text": text, "colour": colour, "bold": bold})


def overflow_record(dropped: list[Segment], columns: int, now: float) -> dict:
    """What the overflow file holds: when it was written, the terminal width the line was fitted to, and the
    dropped pieces as spans, in display order."""
    return {"written_at": now, "columns": columns, "pieces": [spans(text) for text, _, _ in dropped]}


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


def compose(data: dict, env: dict, now: float, icons: bool = True) -> tuple[str, list[Segment], int]:
    """The fitted line, the pieces it left out, and the terminal width it was fitted for."""
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
    line, dropped = layout(segments(data, env, now, files, branch_name, icons), width)
    return line, dropped, columns


def render(data: dict, env: dict, now: float, icons: bool = True) -> str:
    return compose(data, env, now, icons)[0]


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
    "cost": {"total_cost_usd": 1.23},
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
            line, dropped, columns = compose(data, os.environ, now, icons)
            print(line)
            session_id = data.get("session_id")
            if isinstance(session_id, str) and session_id:
                try:
                    write_overflow(os.path.expanduser("~"), session_id, overflow_record(dropped, columns, now))
                except Exception:  # the line is already printed; a lost overflow file costs nothing visible
                    pass
    except Exception as error:  # the bar must never crash Claude Code's UI
        print("statusbar:", error)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
