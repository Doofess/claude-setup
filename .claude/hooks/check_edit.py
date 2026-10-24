"""PostToolUse hook: lint the file Claude just edited. Exit 2 + stderr = feedback; a missing tool = silent exit 0."""

import json
import os
import shutil
import subprocess
import sys

MAX_LINES = 30
RUFF_WINGET = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Microsoft",
    "WinGet",
    "Packages",
    "astral-sh.ruff_Microsoft.Winget.Source_8wekyb3d8bbwe",
    "ruff.exe",
)
PS_SCRIPT = (
    "$e=$null;$t=$null;"
    "[void][System.Management.Automation.Language.Parser]::ParseFile($env:CHECK_EDIT_FILE,[ref]$t,[ref]$e);"
    "foreach($x in $e){'{0}:{1}: {2}' -f $env:CHECK_EDIT_FILE,$x.Extent.StartLineNumber,$x.Message}"
)


def run(cmd, cwd=None, env=None):
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=50)
    except (OSError, subprocess.SubprocessError):
        return None


def repo_root(path):
    p = run(["git", "-C", os.path.dirname(path), "rev-parse", "--show-toplevel"])
    if p and p.returncode == 0 and p.stdout.strip():
        return os.path.normpath(p.stdout.strip())
    return None


def findings(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) > MAX_LINES:
        lines = [*lines[: MAX_LINES - 1], "... (%d more lines)" % (len(lines) - MAX_LINES + 1)]
    return "\n".join(lines)


def check_ps(path):
    ps = shutil.which("powershell.exe") or shutil.which("powershell")
    if not ps:
        return 0, ""
    env = dict(os.environ, CHECK_EDIT_FILE=path)
    p = run([ps, "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT], env=env)
    if p and p.stdout.strip():
        return 2, findings(p.stdout)
    return 0, ""


def check_py(path, root):
    ruff = shutil.which("ruff") or (RUFF_WINGET if os.path.isfile(RUFF_WINGET) else None)
    if not ruff:
        return 0, ""
    p = run([ruff, "check", "--quiet", "--output-format", "concise", path], cwd=root)
    if p and p.returncode == 1 and (p.stdout.strip() or p.stderr.strip()):
        return 2, findings(p.stdout or p.stderr)
    return 0, ""


def check_mod(path, root):
    biome = os.path.join(root, "node_modules", "@biomejs", "biome", "bin", "biome")
    node = shutil.which("node")
    if not node or not os.path.isfile(biome):
        return 0, ""
    # Errors only (what makes the exit code), one line each, so the 30-line cap keeps them.
    p = run([node, biome, "lint", "--diagnostic-level=error", "--reporter=concise", path], cwd=root)
    if p and p.returncode != 0 and (p.stdout.strip() or p.stderr.strip()):
        return 2, findings(p.stdout + p.stderr)
    return 0, ""


def check(path, root):
    """Return (exit code, stderr text) for one edited file."""
    if not path or not os.path.isfile(path):
        return 0, ""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".ps1", ".psm1"):
        return check_ps(path)
    if ext == ".py":
        return check_py(path, root)
    if ext in (".ts", ".tsx"):
        mods = os.path.normcase(os.path.join(os.path.abspath(root), "mods")) + os.sep
        if os.path.normcase(os.path.abspath(path)).startswith(mods):
            return check_mod(path, root)
    return 0, ""


def main():
    try:
        data = json.load(sys.stdin)
        path = (data.get("tool_input") or {}).get("file_path") or ""
    except (ValueError, AttributeError):
        return 0
    if not path:
        return 0
    if not os.path.isabs(path):
        path = os.path.join(data.get("cwd") or os.getcwd(), path)
    path = os.path.normpath(path)
    root = repo_root(path)
    if not root:  # a scratch file outside any git repo is not project code
        return 0
    code, text = check(path, root)
    if code:
        print(text, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
