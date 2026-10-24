"""Proves every shell sees the same setup: runs the installer's check, claude and python in each one.

Usage: python shell_matrix.py [--json] [--print-commands]

For each of Windows PowerShell, PowerShell 7, Git Bash and cmd it starts the shell the way Windows
Terminal does (profiles load, Git Bash as a login shell, plain `cmd /c`) and runs, inside it:
install.cmd -Check -Json (install.sh in Git Bash), `claude --version`, the python that shell
resolves, and the installed status line fed the demo session. It prints one column per shell and
exits 1 when any shell is missing or differs. Run it only from main after install.cmd: the installer's
check is not meant to run from a worktree.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent
TIMEOUT = 300
SGR = re.compile(r"\x1b\[([0-9;]*)m")
OK_STATUSES = ("ok", "kept")
PY_PROBE = 'import sys;print(sys.executable, sys.version.split()[0])'


def find_git_bash():
    """Like install.ps1's Get-GitBash: CLAUDE_CODE_GIT_BASH_PATH, else bin\\bash.exe beside git."""
    env = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if env and os.path.exists(env):
        return env
    git = shutil.which("git")
    if git:
        d = Path(git).parent
        for root in (d, d.parent, d.parent.parent):
            cand = root / "bin" / "bash.exe"
            if cand.exists():
                return str(cand)
    return None


def _pwsh():
    found = shutil.which("pwsh")
    if found:
        return found
    cand = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PowerShell" / "7" / "pwsh.exe"
    return str(cand) if cand.exists() else None


def _prefixes():
    ps = shutil.which("powershell.exe")
    bash = find_git_bash()
    cmd = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
    pwsh = _pwsh()
    return {
        "powershell": [ps, "-NoLogo", "-Command"] if ps else None,
        "pwsh": [pwsh, "-NoLogo", "-Command"] if pwsh else None,
        "git-bash": [bash, "-l", "-c"] if bash else None,
        "cmd": [cmd, "/c"] if cmd else None,
    }


SHELLS = {name: prefix for name, prefix in _prefixes().items() if prefix} or {}
# Shells whose executable is not found stay listed, so they show as missing.
SHELL_NAMES = ("powershell", "pwsh", "git-bash", "cmd")
for _name in SHELL_NAMES:
    SHELLS.setdefault(_name, [])
SHELLS = {n: SHELLS[n] for n in SHELL_NAMES}


def _env(shell):
    env = dict(os.environ)
    if shell == "powershell":
        # A parent pwsh's module path breaks Windows PowerShell 5.1's module autoload.
        env.pop("PSModulePath", None)
    return env


def _fwd(path):
    return str(path).replace("\\", "/")


KEEP_FLAGS = ("-KeepFont", "-KeepScheme", "-SkipFont")
STATE_FILE = Path.home() / ".claude" / "claude-setup-state.json"


def known_flags(flags):
    """Only the installer flags that decide what a check expects; anything else in the state file is ignored."""
    return [f for f in KEEP_FLAGS if isinstance(flags, (list, tuple)) and f in flags]


def recorded_flags(path=None):
    """The flags the last install ran with, from the state file's `flags` key ([] when absent or unreadable)."""
    try:
        doc = json.loads(Path(path or STATE_FILE).read_text(encoding="utf-8-sig"))
        return known_flags(doc.get("flags", []))
    except (OSError, ValueError, AttributeError):
        return []


def commands(shell, flags=()):
    """The command strings run inside the shell: install check, claude, python, status bar child.
    `flags` (the recorded keep flags) are appended to the installer's check so it expects what the install did."""
    repo = str(REPO)
    tail = "".join(" " + f for f in known_flags(list(flags)))
    me = _fwd(REPO / "shell_matrix.py")
    if shell == "git-bash":
        install = f'cd "{_fwd(repo)}" && ./install.sh -Check -Json{tail}'
    elif shell == "cmd":
        install = f'"{repo}\\install.cmd" -Check -Json{tail}'
    else:
        install = f'& "{repo}\\install.cmd" -Check -Json{tail}'
    return {
        "install": install,
        "claude": "claude --version",
        "python": f'python -I -c "{PY_PROBE}"',
        "bar": f'python -I "{me}" --bar-child',
    }


def build_argv(shell, command):
    """argv (or, for cmd, a command line string) that runs one command string in the shell."""
    prefix = SHELLS[shell]
    if shell == "cmd":
        # cmd strips one outer pair of quotes after /c, so quote the whole command line itself.
        return " ".join(f'"{p}"' if " " in p else p for p in prefix) + f' "{command}"'
    return prefix + [command]


def _kill_tree(proc):
    """Kills the shell and everything it started. subprocess's own kill() leaves grandchildren alive on Windows,
    and they keep the output pipes open, so communicate() would wait for them forever."""
    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run_in(shell, command, timeout=TIMEOUT):
    proc = subprocess.Popen(build_argv(shell, command), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", env=_env(shell),
                            cwd=str(REPO))
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise
    return proc.returncode, out or "", err or ""


def last_json(text):
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def _reason(stdout, stderr):
    """The last non-empty stderr line (stdout's when stderr is empty), trimmed: why a command printed no JSON."""
    for text in (stderr, stdout):
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if lines:
            return lines[-1][:200]
    return ""


def probe(shell, flags=None):
    """Runs the checks inside one shell and returns its result dict ({'missing': True} if not installed).
    `flags`: the install flags to check with; the state file's recorded ones by default."""
    if not SHELLS.get(shell):
        return {"missing": True}
    cmds = commands(shell, recorded_flags() if flags is None else flags)
    res = {"missing": False, "exit": -1, "rows": [], "failures": [], "claude": "", "python": "", "bar_text": "", "bar_sgr": [], "errors": []}

    def attempt(label, command):
        try:
            return run_in(shell, command)
        except (subprocess.TimeoutExpired, OSError) as e:
            res["errors"].append(f"{label}: {type(e).__name__}: {e}")
            return None

    out = attempt("install check", cmds["install"])
    if out:
        res["exit"] = out[0]
        doc = last_json(out[1])
        if doc is None:
            why = _reason(out[1], out[2])
            res["errors"].append("install check: no JSON line in the output" + (f": {why}" if why else ""))
        else:
            res["rows"] = doc.get("rows", [])
            res["failures"] = doc.get("failures", [])
    out = attempt("claude", cmds["claude"])
    if out:
        res["claude"] = out[1].strip()
        if out[0] != 0:
            res["errors"].append(f"claude --version exited {out[0]}")
    out = attempt("python", cmds["python"])
    if out:
        res["python"] = out[1].strip()
        if out[0] != 0:
            res["errors"].append(f"python exited {out[0]}")
    out = attempt("status bar", cmds["bar"])
    if out:
        doc = last_json(out[1])
        if doc is None or not doc.get("ok"):
            res["errors"].append("status bar: " + ((doc or {}).get("error") or f"no result (exit {out[0]})"))
        if doc:
            res["bar_text"] = doc.get("text", "")
            res["bar_sgr"] = doc.get("sgr", [])
    return res


def bar_child():
    """Runs inside a probed shell: feeds the demo session to the installed statusLine.command like
    install.ps1's Test-StatusBar (Git Bash -c, COLUMNS=160, pinned compact window) and prints one JSON line."""
    out = {"ok": False}
    try:
        sample = subprocess.run([sys.executable, "-I", str(REPO / "statusbar.py"), "--demo-json"],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=TIMEOUT,
                                stdin=subprocess.DEVNULL).stdout
        settings = json.loads((Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8-sig"))
        command = settings["statusLine"]["command"]
        bash = find_git_bash() or "bash"
        env = dict(os.environ, COLUMNS="160", CLAUDE_CODE_AUTO_COMPACT_WINDOW="300000")
        proc = subprocess.run([bash, "-c", command], input=sample, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=TIMEOUT, env=env)
        text = proc.stdout
        out = {"ok": proc.returncode == 0, "text": SGR.sub("", text).strip(),
               "sgr": sorted(set(SGR.findall(text)))}
        if proc.returncode != 0:
            out["error"] = f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    except Exception as e:  # reported to the parent as a probe error
        out["error"] = f"{type(e).__name__}: {e}"
    print(json.dumps(out, ensure_ascii=True))
    return 0


def _present(results):
    return {s: r for s, r in results.items() if not r.get("missing")}


def compare(results):
    """One line per difference between the shells; an empty list means they match."""
    lines = []
    for shell, r in results.items():
        if r.get("missing"):
            lines.append(f"{shell}: missing (shell not installed)")
    here = _present(results)
    for shell, r in here.items():
        for err in r.get("errors", []):
            lines.append(f"{shell}: {err}")
    # Failures the table has no row for (the status bar check, `claude plugin validate`, mcp_off.py). The
    # "same experience:" ones are rows already.
    seen = {}
    for shell, r in here.items():
        for f in r.get("failures", []):
            if not f.startswith("same experience:"):
                seen.setdefault(f, []).append(shell)
    for f, shells in seen.items():
        lines.append(f"install check failed: {f} (in {', '.join(shells)})")
    for shell, r in here.items():
        if (r.get("exit", 0) > 0 and r.get("rows") and not r.get("failures")
                and not any(rw["status"] == "FAIL" for rw in r["rows"])):
            lines.append(f"{shell}: install check exited {r['exit']} with no failing row")
    names = []
    for r in here.values():
        for rw in r.get("rows", []):
            if rw["name"] not in names:
                names.append(rw["name"])
    for name in names:
        status = {}
        for shell, r in here.items():
            found = [rw["status"] for rw in r.get("rows", []) if rw["name"] == name]
            status[shell] = found[0] if found else "absent"
        if len(set(status.values())) > 1:
            lines.append(f"{name}: status differs: " + ", ".join(f"{s} {v}" for s, v in status.items()))
        elif next(iter(status.values())) not in OK_STATUSES:
            lines.append(f"{name}: {next(iter(status.values()))} in " + ", ".join(status))

    def differs(key, label):
        vals = {s: r.get(key, "") for s, r in here.items()}
        if len({json.dumps(v) for v in vals.values()}) > 1:
            lines.append(f"{label} differs: " + ", ".join(f"{s} {v!r}" for s, v in vals.items()))

    differs("claude", "claude version")
    differs("python", "python")
    differs("bar_text", "status bar text")
    sgrs = {s: sorted(r.get("bar_sgr", [])) for s, r in here.items()}
    if len({json.dumps(v) for v in sgrs.values()}) > 1:
        lines.append("status bar colours differ: " + ", ".join(f"{s} {' '.join(v)!r}" for s, v in sgrs.items()))
    return lines


def format_table(results, diffs):
    shells = list(results)
    names = []
    for r in results.values():
        for rw in r.get("rows", []):
            if rw["name"] not in names:
                names.append(rw["name"])

    def cell(shell, key):
        r = results[shell]
        if r.get("missing"):
            return "missing"
        if key == "claude":
            return r.get("claude", "") or "-"
        if key == "python":
            return r.get("python", "") or "-"
        if key == "status bar":
            return (r.get("bar_text", "") or "-")[:40]
        found = [rw["status"] for rw in r.get("rows", []) if rw["name"] == key]
        return found[0] if found else "absent"

    keys = names + ["claude", "python", "status bar"]
    wk = max(len(k) for k in keys)
    wc = {s: max(len(s), *(len(cell(s, k)) for k in keys)) for s in shells}
    out = ["  ".join(["".ljust(wk)] + [s.ljust(wc[s]) for s in shells])]
    for k in keys:
        out.append("  ".join([k.ljust(wk)] + [cell(s, k).ljust(wc[s]) for s in shells]))
    if diffs:
        out.append(f"shell matrix: {len(diffs)} difference(s)")
        out.extend("  " + d for d in diffs)
    else:
        out.append(f"shell matrix: all {len(shells)} shells match")
    return "\n".join(out) + "\n"


def main(argv):
    if "--bar-child" in argv:
        return bar_child()
    if "--print-commands" in argv:
        for shell in SHELLS:
            print(shell, SHELLS[shell] or "missing")
            if SHELLS[shell]:
                print("  ", build_argv(shell, commands(shell)["bar"]))
        return 0
    with ThreadPoolExecutor(max_workers=len(SHELLS)) as pool:
        results = dict(zip(SHELLS, pool.map(probe, SHELLS)))
    diffs = compare(results)
    if "--json" in argv:
        print(json.dumps({"results": results, "differences": diffs}, indent=2))
    else:
        sys.stdout.write(format_table(results, diffs))
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
