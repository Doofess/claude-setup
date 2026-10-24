#!/usr/bin/env bash
# Runs install.ps1 from Git Bash through install.cmd (pwsh if present, else Windows PowerShell).
set -e
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
code=0
cmd.exe //c "$(cygpath -w "$dir/install.cmd")" "$@" || code=$?
exit "$code"
