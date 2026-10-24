"""Turns Claude Code's advisor on or off for one project.

Usage: python advisor.py opus|fable|off|status

Writes `advisorModel` to <project>/.claude/settings.local.json, where <project> is the git top level of the current
directory (the directory itself outside git). Claude Code reloads the file and uses the advisor from the next prompt;
a project value beats the user one in ~/.claude/settings.json. Other keys in the file stay as they are, a file that is
not valid JSON is left alone, and the file is kept out of git through .git/info/exclude when no ignore rule covers it.
Standard library only.
"""
import json
import os
import subprocess
import sys

CHOICES = ("opus", "fable", "off", "status")
LOCAL = os.path.join(".claude", "settings.local.json")


def git(cwd: str, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def read(path: str) -> dict:
    """The JSON object in path, {} when there is no file; raises ValueError when it is not a JSON object."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.{os.getpid()}.tmp"
    with open(temp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(temp, path)


def keep_out_of_git(root: str) -> None:
    """Adds the local settings file to .git/info/exclude when nothing ignores it, so it never shows as a change."""
    if git(root, "rev-parse", "--git-dir") is None:
        return
    if subprocess.run(["git", "check-ignore", "-q", LOCAL.replace(os.sep, "/")], cwd=root).returncode == 0:
        return
    exclude = git(root, "rev-parse", "--git-path", "info/exclude")
    if not exclude:
        return
    exclude = os.path.join(root, exclude) if not os.path.isabs(exclude) else exclude
    os.makedirs(os.path.dirname(exclude), exist_ok=True)
    with open(exclude, "a", encoding="utf-8") as f:
        f.write("\n.claude/settings.local.json\n")


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in CHOICES:
        print(f"usage: advisor.py {'|'.join(CHOICES)}", file=sys.stderr)
        return 2
    choice = argv[0]
    cwd = os.getcwd()
    root = git(cwd, "rev-parse", "--show-toplevel") or cwd
    path = os.path.join(root, LOCAL)
    try:
        data = read(path)
        user = read(os.path.join(os.path.expanduser("~"), ".claude", "settings.json")).get("advisorModel")
    except (OSError, ValueError) as error:
        print(f"advisor: {error}; nothing changed", file=sys.stderr)
        return 1

    if choice == "status":
        print(f"project: {data.get('advisorModel', 'off')} ({path})\nuser: {user or 'off'}")
        return 0
    if choice == "off":
        if "advisorModel" in data:
            del data["advisorModel"]
            write(path, data)
    else:
        data["advisorModel"] = choice
        write(path, data)
        keep_out_of_git(root)
    shown = data.get("advisorModel", "off")
    note = f"; the user setting ({user}) still applies here" if choice == "off" and user else ""
    print(f"advisor: {shown} for {root}, from the next prompt{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
