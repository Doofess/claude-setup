"""A two-row status line for Claude Code.

Usage: Claude Code runs `python statusbar.py` and pipes its session JSON to stdin; `--demo` prints
sample data instead. Column width comes from the COLUMNS environment variable (default 120).

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
import os
import re

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


def branch(start_dir: str) -> str | None:
    """Current branch (or the first 7 characters of a detached sha), read from .git/HEAD without git."""
    here = os.path.abspath(start_dir)
    while not os.path.exists(os.path.join(here, ".git")):
        parent = os.path.dirname(here)
        if parent == here:
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
