# Same Setup From Every Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fresh Windows PC gets exactly this PC's Claude Code experience whichever shell runs the installer and whichever shell later runs `claude`. That covers Windows PowerShell 5.1, PowerShell 7, Git Bash and cmd, in Windows Terminal or in VS Code's terminal. A `/setup-check` skill lets Claude prove the result and repair any drift.

**Architecture:** `install.ps1` stays the one installer. New launchers run it from any shell, and a new `-Check` switch runs only its checks and can print them as JSON. `shell_matrix.py` runs that check, plus a probe of what `claude` sees, from each of the four shells, and fails on any difference. The new terminal work (every Windows Terminal profile, PowerShell 7 as default, a Git Bash profile, VS Code's terminal, both PowerShell profiles) goes into install.ps1 as new helpers and new rows in the `Same experience` table.

**Tech Stack:** PowerShell (must run unchanged on 5.1 and 7), Python 3.10+ unittest, Windows Terminal and VS Code settings (JSONC, edited as text with the existing `Find-JsoncKey` helpers).

**Spec:** the user's decisions on 2026-10-24 (this session), recorded here:
- Scope: Windows only, all shells (Windows PowerShell 5.1, PowerShell 7, Git Bash, cmd), in Windows Terminal and in VS Code's terminal.
- Claude's check: a `/setup-check` skill that runs the parity checks from every installed shell, reads the table, and fixes drift itself.
- Proof: a local matrix script, run on both PCs.
- 5.1's blocked scripts: an `install.cmd` launcher that runs `install.ps1` with Bypass from any shell, and the installer sets Windows PowerShell's CurrentUser policy to RemoteSigned.
- Default Windows Terminal tab: PowerShell 7 on every PC (installed if missing).
- VS Code: the terminal gets the Nerd Font, Campbell's 16 ANSI colours, and `minimumContrastRatio` 1. No other VS Code key is touched.
- Git Bash: the installer adds a Windows Terminal "Git Bash" profile when none exists.

## Global Constraints

- `install.ps1` keeps `#Requires -Version 5.1`. Every new line must parse and behave the same on 5.1 and 7: no `` `e ``, no `??`, no ternary, no `&&`, and no `-AsHashtable` on `ConvertFrom-Json`.
- Native-command stderr under `$ErrorActionPreference = 'Stop'` aborts 5.1. Wrap native calls the way the plugin step does, with `'Continue'` and captured output.
- JSONC settings files (Windows Terminal and VS Code) are edited as text with the existing helpers, never round-tripped through `ConvertFrom-Json`. Write only when something changed, with `Write-Utf8NoBom`, and back up first (`Backup-TerminalSettings`, or the same pattern for VS Code).
- Never run a worktree's `install.ps1` against the real `~/.claude`, because it repoints `CLAUDE_CODE_PLUGIN_DIRS`. Tests drive the helpers on temp copies; the whole installer runs only from main after merge.
- Tests: `python -m unittest discover -s tests` must print `OK`. PowerShell-driven tests run under every engine present (`pwsh` and `powershell.exe -ExecutionPolicy Bypass`) and skip an engine that is missing.
- When a test launches `powershell.exe`, it removes `PSModulePath` from the child environment. Otherwise a parent pwsh's module path breaks 5.1's module autoload (seen this session: `Get-ExecutionPolicy ... module could not be loaded`).
- Windows Terminal guids: PowerShell 7 is `{574e775e-4f2a-5b96-ac1e-a2962a402336}`. Git Bash uses Git for Windows' own fragment guid `{2ece5bfe-50ed-5f3a-ab87-5cd4baafed2b}`, so a later Git fragment doesn't duplicate it. Verify that guid against Git for Windows' fragment source before relying on it.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- **The launcher started from pwsh with no pwsh-specific env cleanup:** `install.cmd` falls back to `powershell.exe` and must still work, so it clears `PSModulePath` before launching 5.1. Task 1 tests this.
- **A path with a space:** this machine's home is `C:\Users\Home Office`, so every launcher, profile path and Git Bash command line must quote it. Task 1 runs from a temp folder whose name contains a space; Task 5's Git Bash commandline test uses a space path.
- **OneDrive-redirected Documents:** both PowerShell profile paths come from `[Environment]::GetFolderPath('MyDocuments')`, never `$HOME\Documents`. Task 4 asserts the path's source.
- **A profile in `profiles.list` that already has a non-font key in `font` (such as `size`):** only `face` and `cellHeight` are removed, and `size` stays. Task 5 extends the existing fixture test to every profile.
- **A group policy that pins the execution policy (MachinePolicy or UserPolicy set):** the installer must not try to override it. It reports the row as FAIL with the policy's scope. Task 4 tests this.

---

### Task 1: Launchers for every shell

**Files:**
- Create: `install.cmd`, `install.sh`
- Test: `tests/test_launchers.py`
- Modify: `README.md` ("Set up a new machine": step 3 uses `install.cmd`; one line on running it from Git Bash with `./install.sh`)

**Interfaces:**
- Produces: `install.cmd [install.ps1 args]` runs `install.ps1` with the same arguments under `pwsh` when it is on PATH, else under `powershell.exe`. Both run with `-NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"`. It clears `PSModulePath` before calling `powershell.exe` and exits with the script's exit code. `install.sh` does the same from Git Bash by calling `cmd.exe //c` on `install.cmd` with the Windows path from `cygpath -w`. It passes the arguments through and returns the exit code.

- [ ] **Step 1: Write the failing tests.** Copy both launchers and a stub `install.ps1` into a temp folder named `launch test` (with a space). The stub writes `$PSVersionTable.PSEdition`, `$args -join '|'` and `exit 3`. Then test:
  - `test_cmd_runs_the_script_with_its_args`: running `cmd /c "<tmp>\install.cmd" -Check -Json` gives output containing `-Check|-Json` and exit code 3.
  - `test_cmd_prefers_pwsh`: with pwsh on PATH, the edition is `Core`.
  - `test_cmd_falls_back_to_windows_powershell`: with a PATH that keeps System32 but has no pwsh, and `PSModulePath` set to pwsh's value, the edition is `Desktop` and the exit code is 3.
  - `test_sh_runs_from_git_bash`: Git Bash (`Get-GitBash`'s logic, ported: `bin\bash.exe` next to git) running `./install.sh -Check` gives `-Check` and exit code 3.
- [ ] **Step 2:** Run `python -m unittest tests.test_launchers -q`. Expected: FAIL (no launchers).
- [ ] **Step 3:** Write `install.cmd` and `install.sh` per the Interfaces above. Give `install.sh` a `#!/usr/bin/env bash` line and `set -e`.
- [ ] **Step 4:** Run `python -m unittest tests.test_launchers -q`. Expected: OK.
- [ ] **Step 5:** Update the README and commit with the message `install.cmd and install.sh: run the installer from any shell, past 5.1's blocked scripts`.

### Task 2: `-Check` and `-Json`

**Files:**
- Modify: `install.ps1`. Add `[switch]$Check` and `[switch]$Json` to `param`. Move `$template` up to sit with `$terminalLook`. Wrap steps 1 to 4e in `if (-not $Check) { ... }`. Turn sections 5 to `Same experience` into checks that run in both modes.
- Test: `tests/test_install.py` (new class `CheckModeTest`)

**Interfaces:**
- Produces: `install.ps1 -Check` changes no file, runs the status bar check, the mod check and the `Same experience` table, and exits 1 on any failure. `-Check -Json` prints exactly one JSON document to stdout and nothing else: `{"rows": [{"name": str, "expected": str, "actual": str, "status": "ok"|"kept"|"FAIL"}], "failures": [str]}`. It prints it with `ConvertTo-Json -Depth 5 -Compress`, and step headers go to the host only when `-Json` is absent. Task 7 and later rows plug in through the existing `Add-SameRow`.

- [ ] **Step 1: Write the failing tests:**
  - `test_check_changes_nothing`: hash `~/.claude/settings.json` and every Windows Terminal settings file, run `pwsh -NoProfile -File install.ps1 -Check -Json` from the main checkout, and the hashes are unchanged. Skip unless env `CLAUDE_SETUP_LIVE=1`, because it reads the real machine.
  - `test_json_is_one_document`: same skip. The stdout passes `json.loads`, its `rows` names include `Terminal font face` and `Python version`, and each `status` is one of the three values.
  - `test_check_skips_the_install_steps` (static, always runs): in `install.ps1`, the text `Write-Step 'Merging settings.json'` sits inside the `if (-not $Check)` block. Find that block's start and end by brace matching in the test.
- [ ] **Step 2:** Run `python -m unittest tests.test_install -q`. Expected: the static test FAILs.
- [ ] **Step 3:** Implement it. `$failures` handling stays the same. When `-Json` is set, skip `Write-Color` and `Write-Host` (route them through a `$quiet` check in `Write-Color`/`Write-Step` and the status bar echo) and emit the document at the end, before the exit code.
- [ ] **Step 4:** Run the static test (OK), then `$env:CLAUDE_SETUP_LIVE=1; python -m unittest tests.test_install -q` from main's checkout path only (OK).
- [ ] **Step 5:** Commit with the message `install.ps1 -Check [-Json]: run only the checks`.

### Task 3: Same result under 5.1 and 7

**Files:**
- Modify: `tests/test_install.py`. `TerminalHelpersTest` and `FontHelpersTest` take the engine as a class parameter: subclass once per engine found, (`pwsh`, `-NoProfile -NonInteractive -File`) and (`powershell.exe`, `-NoProfile -NonInteractive -ExecutionPolicy Bypass -File`, `PSModulePath` removed from env).
- Create: a merge test that extracts `Merge-Json`, `Merge-HookEvents`, `Format-DirKey`, `Merge-PluginDirs` and `Merge-ClaudeSettings`, in the same way `installer_helpers()` extracts the terminal helpers.
- Modify: `install.ps1`, only where a test proves a 5.1 difference.

**Interfaces:**
- Consumes: the existing `installer_helpers()` and `font_helpers()`.
- Produces: `ENGINES: list[tuple[str, list[str]]]` in `tests/test_install.py`, so later PowerShell-driven tests run on every engine.

- [ ] **Step 1: Write the failing test.** `test_merge_is_the_same_on_both_engines` merges the repo's `settings.json` into a fixture `tests/fixtures/settings/current.json`. The fixture has a machine-only env key, a one-element `permissions.allow` array, an empty `hooks` object and a non-ASCII string (`"Home Office ✔"`). Run the merge on each engine, write the result with `ConvertTo-Json -Depth 20`, and the two results must give equal `json.loads` values. Also assert the one-element array is still a list and the non-ASCII string round-trips.
- [ ] **Step 2:** Run `python -m unittest tests.test_install -q`. Expected: FAIL, or PASS on the first run. If it passes, keep the test as a guard and note in the commit that no fix was needed.
- [ ] **Step 3:** Fix each proven difference in `install.ps1`. Typical fixes are `@(...)` around a value that must stay an array, and an explicit UTF-8 read (`[IO.File]::ReadAllText($p, [Text.Encoding]::UTF8)`) where `Get-Content -Raw` reads ANSI on 5.1.
- [ ] **Step 4:** Run `python -m unittest tests.test_install -q`. Expected: OK, with the terminal fixture tests now run twice.
- [ ] **Step 5:** Commit with the message `install.ps1: same merge and terminal edits on Windows PowerShell 5.1 and PowerShell 7`.

### Task 4: Both PowerShell profiles and the 5.1 policy

**Files:**
- Modify: `install.ps1`, section 4e: the profile block for both profiles, plus a new `Set-WindowsPowerShellPolicy` function next to `Set-ProfileBlock`.
- Test: `tests/test_install.py`

**Interfaces:**
- Produces:
  - `Get-PowerShellProfiles` returns `[string[]]`: `<MyDocuments>\PowerShell\Microsoft.PowerShell_profile.ps1` and `<MyDocuments>\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`, both built from `[Environment]::GetFolderPath('MyDocuments')`.
  - `Set-WindowsPowerShellPolicy([string]$regPath)` returns `'set'`, `'already set'` or `'pinned by <scope>'`. It writes `ExecutionPolicy` = `RemoteSigned` under `$regPath`, which defaults to `HKCU:\Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell`. It writes only when the value is missing, `Undefined` or `Restricted`. When `HKCU:\Software\Policies\Microsoft\Windows\PowerShell` or `HKLM:\...\Policies\Microsoft\Windows\PowerShell` sets `ExecutionPolicy`, it returns `'pinned by UserPolicy'` or `'pinned by MachinePolicy'` and writes nothing. Write the registry directly, because `Set-ExecutionPolicy` from pwsh changes pwsh's config, not 5.1's.
- Same-experience rows (Task 7 adds them): `Windows PowerShell policy` and `PowerShell profiles`.

- [ ] **Step 1: Write the failing tests.** Run them on both engines, against `HKCU:\Software\claude-setup-test\<uuid>` and removed afterwards:
  - `test_policy_set_when_missing`: the result is `set` and the value reads back `RemoteSigned`.
  - `test_policy_left_when_looser`: with the value pre-set to `Unrestricted`, the result is `already set` and the value is unchanged.
  - `test_policy_reports_pin`: pass a policy-key path parameter pointing at a test key that has `ExecutionPolicy`. The result starts with `pinned by` and nothing is written. Give the function a second parameter, `[string[]]$policyPaths`, so the test can inject that path.
  - `test_profiles_come_from_my_documents` (static): `Get-PowerShellProfiles` uses `GetFolderPath('MyDocuments')` and both folder names.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement both functions. In 4e, loop `Set-ProfileBlock` over both profiles with the existing body, back up each existing one, and print each path. Call the policy function and print its result. Update the comment above `$profileStart` to say both profiles.
- [ ] **Step 4:** Run the tests. Expected: OK.
- [ ] **Step 5:** Commit with the message `install.ps1: profile block in both PowerShell profiles, RemoteSigned for Windows PowerShell 5.1`.

### Task 5: Every Windows Terminal profile, PowerShell 7 default, Git Bash profile

**Files:**
- Modify: `install.ps1`. Change `Set-TerminalFont` and `Set-TerminalScheme` to drop `face`, `cellHeight` and `colorScheme` from every object in `profiles.list`, not just the default profile. `Get-WtLayout` gains `Profiles` (all object starts), and `Read-TerminalLook` gains `Overrides`. Add new `Set-TerminalDefaultProfile` and `Add-GitBashProfile` functions, and a PowerShell 7 install step through winget.
- Modify: `tests/test_install.py`, plus new fixtures `tests/fixtures/terminal/H_overrides_on_other_profiles.json` and `I_no_git_bash.json`.

**Interfaces:**
- Produces:
  - `Read-TerminalLook` also returns `Overrides: string[]`, one `"<profile name>: <key> <value>"` per override found on any profile. The existing `ProfileFace`, `ProfileCellHeight` and `ProfileScheme` stay for the default profile.
  - `Set-TerminalDefaultProfile([string]$path, [string]$guid)` returns `'set'`, `'already set'` or `'missing'`. It returns `'missing'` when no profile in `list` has that guid and the PowerShell 7 dynamic profile isn't present; in that case nothing is written.
  - `Add-GitBashProfile([string]$path, [string]$bashExe, [string]$gitRoot)` returns `'added'`, `'present'` or `'none'`. It counts a profile as present when one in `list` has the Git Bash guid or is named `Git Bash`, or when a fragment folder `Git` exists under `%ProgramData%` or `%LOCALAPPDATA%` `\Microsoft\Windows Terminal\Fragments`. When it adds one, the new list object is `{ "guid": "{2ece5bfe-50ed-5f3a-ab87-5cd4baafed2b}", "name": "Git Bash", "commandline": "\"<bashExe>\" -i -l", "icon": "<gitRoot>\\mingw64\\share\\git\\git-for-windows.ico", "hidden": false }`.
  - Constants: `$ps7Guid = '{574e775e-4f2a-5b96-ac1e-a2962a402336}'` and `$gitBashGuid = '{2ece5bfe-50ed-5f3a-ab87-5cd4baafed2b}'`.
  - PowerShell 7 install: when `pwsh` isn't on PATH, run `winget install --id Microsoft.PowerShell -e --silent --accept-package-agreements --accept-source-agreements`. This is best effort, like the font step.

- [ ] **Step 1: Write the failing tests** (on every engine):
  - `test_h_overrides_on_other_profiles`: fixture H has `font.face` on the PowerShell 7 profile, `colorScheme` on cmd, and `font: { face, size }` on Ubuntu. After the font and scheme apply, no profile has `face`, `cellHeight` or `colorScheme`. Ubuntu keeps `font.size`. A second run reports `already set` and leaves the bytes unchanged.
  - `test_look_lists_overrides`: `Read-TerminalLook` on H returns three `Overrides`.
  - `test_default_profile_set_to_ps7`: on fixture A, `defaultProfile` becomes `$ps7Guid` and a second run gives `already set`.
  - `test_git_bash_added_once`: on fixture I with a bash path containing a space, the result is `added`. The new object's `commandline` is `"\"C:\\Program Files\\Git\\bin\\bash.exe\" -i -l"`. A second run gives `present`. The file still passes `load_jsonc`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement it. Reuse `Find-JsoncKey`, `Remove-JsoncKey`, `Get-JsoncObjects` and `Add-JsoncRaw`. Add the list object as raw text after the last element of `profiles.list`, with a comma. Wire it in: the font and scheme steps already loop `$wtSettings`; add a `Terminal profiles` step that calls `Set-TerminalDefaultProfile` and `Add-GitBashProfile`, after installing pwsh. Update comments 4d to 4e and the `.DESCRIPTION` list.
- [ ] **Step 4:** Run the tests. Expected: OK.
- [ ] **Step 5:** Commit with the message `install.ps1: every Windows Terminal profile looks the same, PowerShell 7 opens by default, Git Bash profile`.

### Task 6: VS Code's terminal

**Files:**
- Create: `terminal/vscode.json`: the exact keys to set, as a flat object. `terminal.integrated.fontFamily` is `"JetBrainsMono Nerd Font"`. `terminal.integrated.lineHeight` is `1.25`. `terminal.integrated.minimumContrastRatio` is `1`. `workbench.colorCustomizations` is an object with Campbell's `terminal.background` `#0C0C0C` and `terminal.foreground` `#CCCCCC`, plus the 16 `terminal.ansi*` colours: Black `#0C0C0C`, Red `#C50F1F`, Green `#13A10E`, Yellow `#C19C00`, Blue `#0037DA`, Magenta `#881798`, Cyan `#3A96DD`, White `#CCCCCC`, BrightBlack `#767676`, BrightRed `#E74856`, BrightGreen `#16C60C`, BrightYellow `#F9F1A5`, BrightBlue `#3B78FF`, BrightMagenta `#B4009E`, BrightCyan `#61D6D6`, BrightWhite `#F2F2F2`.
- Modify: `install.ps1`: a new `Set-VsCodeTerminal([string]$path, $want)` function and a `VS Code terminal` step.
- Test: `tests/test_install.py`, plus fixtures `tests/fixtures/vscode/A_has_other_keys.json` (comments, a trailing comma and other colour customizations) and `B_missing.json`, which stands in for a file that does not exist yet.

**Interfaces:**
- Consumes: the JSONC helpers.
- Produces: `Set-VsCodeTerminal` returns `[pscustomobject]@{ Result = 'set'|'already set'|'no VS Code'; Changed = string[] }`. Top-level keys are set as numbers or strings as typed in `vscode.json`. Inside `workbench.colorCustomizations`, only the listed keys are set and others stay. A missing settings file is created as `{}` only when VS Code is installed: `%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe` exists or `code` is on PATH. The settings path is `%APPDATA%\Code\User\settings.json`. Also check `Code - Insiders` when it is installed.

- [ ] **Step 1: Write the failing tests** (on every engine):
  - `test_vscode_keys_set_and_others_kept`: on fixture A, each key in `vscode.json` reads back equal, A's own `editor.fontSize` and its own `workbench.colorCustomizations` `"editor.background"` are kept, and a second run gives `already set` with unchanged bytes.
  - `test_vscode_file_created`: an absent path with installed set to true gives `set`, and the file parses.
  - `test_numbers_stay_numbers`: `minimumContrastRatio` reads back as the JSON number `1`, not `"1"`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement it. Numbers need a raw-value setter beside `Set-JsoncString`: add `Set-JsoncRaw([string]$t, [int]$obj, [string]$key, [string]$raw)`. Respect `-KeepFont` (skip the font key) and `-KeepScheme` (skip the colours).
- [ ] **Step 4:** Run the tests. Expected: OK.
- [ ] **Step 5:** Commit with the message `install.ps1: VS Code's terminal gets the Nerd Font and Campbell, contrast untouched`.

### Task 7: Same-experience rows for the new parts

**Files:**
- Modify: `install.ps1` (`Same experience`), `README.md` ("Same screen on every PC" lists the new rows), `tests/test_install.py`

**Interfaces:**
- Consumes: Tasks 4 to 6's functions. Rows are added through `Add-SameRow`:
  - `Terminal profile overrides`: expects `none`; actual is `Overrides -join '; '` or `none`. Kept under `-KeepFont` and `-KeepScheme` together.
  - `Terminal default profile`: expects `PowerShell 7`; actual is the default profile's name.
  - `Git Bash profile`: expects `present`.
  - `PowerShell 7`: expects `pwsh found`.
  - `Windows PowerShell policy`: expects `RemoteSigned or looser`. The actual value comes from the registry; a pin shows as `pinned by X`, which is a FAIL.
  - `PowerShell profiles`: expects `block in both`; actual lists the profiles missing the block.
  - `VS Code terminal`: expects `set`; actual is `no VS Code` (status `kept`) or the keys that differ.

- [ ] **Step 1: Write the failing test** (static): each of the seven row names appears in an `Add-SameRow` line of `install.ps1`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Add the rows. Compute each actual read-only, so they work under `-Check`.
- [ ] **Step 4:** Run `python -m unittest discover -s tests`. Expected: OK.
- [ ] **Step 5:** Commit with the message `install.ps1: Same experience covers every shell profile, PowerShell, Git Bash and VS Code`.

### Task 8: `shell_matrix.py`

**Files:**
- Create: `shell_matrix.py` (repo root, beside `mcp_off.py`)
- Test: `tests/test_shell_matrix.py`

**Interfaces:**
- Consumes: `install.cmd -Check -Json` (Tasks 1 and 2).
- Produces:
  - `SHELLS: dict[str, list[str]]` holds the argv prefixes for `powershell`, `pwsh`, `git-bash` and `cmd`, with `PSModulePath` removed for `powershell`. A shell that is not installed shows as `missing`, which is a failure, because the decision requires all four.
  - `probe(shell) -> dict`. In that shell it runs:
    1. `install.cmd -Check -Json` (`./install.sh -Check -Json` in Git Bash) and parses the rows.
    2. `claude --version`.
    3. The resolved `python` path and version.
    4. `statusbar.py --demo-json`, piped through the installed `statusLine.command` the way `Test-StatusBar` runs it (Git Bash `-c`, `COLUMNS=160`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW=300000`). The result is the plain text with SGR stripped, plus its SGR codes.
  - `compare(results: dict[str, dict]) -> list[str]` returns one line per difference: a row whose status differs between shells, a row that isn't `ok`/`kept`, or a different `claude` version, python path, status bar text or SGR set. An empty list means the shells match.
  - CLI: `python shell_matrix.py [--json]` prints a table (one column per shell, one line per row plus `claude`, `python` and `status bar`) and exits 1 when `compare` returns anything.

- [ ] **Step 1: Write the failing tests** for `compare` (pure, with no shells):
  - `test_identical_results_match` gives `[]`.
  - `test_status_difference_named`: `Python version` ok in pwsh but FAIL in cmd gives one line naming both shells.
  - `test_missing_shell_is_a_failure`.
  - `test_status_bar_text_difference`: the same text with different SGR sets gives a line saying `status bar colours differ`.
  - Also `test_matrix_live`: skip unless `CLAUDE_SETUP_LIVE=1`; `main([])` returns 0 on this PC after the install.
- [ ] **Step 2:** Run `python -m unittest tests.test_shell_matrix -q`. Expected: FAIL.
- [ ] **Step 3:** Implement it. Use `subprocess.run` with `encoding="utf-8"`, a 300 s timeout per shell, and `-I` when it runs Python.
- [ ] **Step 4:** Run the unit tests (OK). After merging Tasks 1 to 7 to main and running main's `install.cmd`, run `CLAUDE_SETUP_LIVE=1 python -m unittest tests.test_shell_matrix -q`. Expected: OK, quoted.
- [ ] **Step 5:** Commit with the message `shell_matrix.py: prove every shell sees the same setup`.

### Task 9: The `/setup-check` skill

**Files:**
- Create: `skills/setup-check/SKILL.md` (the installer already copies `skills/*` to `~/.claude/skills`)
- Modify: `install.ps1`: record the clone in `~/.claude/claude-setup-state.json` as a top-level `"repo"` key. Merge it into the existing JSON object and keep the `claude.ai Adobe` key. Do it in Python inside `mcp_off.py`'s state handling, or a tiny merge in PowerShell; read how `mcp_off.py` writes the file first and don't fight it.
- Modify: `README.md` (a "Check a machine" subsection: run `/setup-check` in Claude Code), `CLAUDE.md` (one line under Defaults: "After install.ps1 or on a new PC: `/setup-check`.")
- Test: `tests/test_install.py` (static checks on the skill file and the state key)

**Interfaces:**
- Consumes: `shell_matrix.py`, `install.cmd`, and the state file's `repo`.
- Produces a skill with this frontmatter: `name: setup-check`, `description: Use when setting up this Claude Code configuration on a PC, after install.ps1, when the screen or behaviour differs between shells or PCs, or when the user asks whether the setup is right.` Its body is a procedure Claude follows:
  1. Read `repo` from `~/.claude/claude-setup-state.json`. If it is absent, ask the user for the clone path.
  2. Run `git -C <repo> fetch -q` and then `git -C <repo> status -sb`. If main is behind, say so and pull only with the user's yes.
  3. Run `python -I <repo>/shell_matrix.py`. Quote the table's failing lines.
  4. Repair: for any FAIL, run `<repo>/install.cmd` (with `-SkipPlugins` when only terminal rows fail), then run the matrix again. Rows the installer cannot fix are the user's to do; give the exact command. These are: a group-policy pin, a missing shell that winget couldn't install, and a sign-in (`claude` login, `gh auth login`).
  5. Done only when the matrix exits 0. Quote its last line. Restart notes: Windows Terminal picks up profile changes live, and Claude Code needs a restart for `settings.json` changes.
  - Never run a worktree's `install.cmd`. Never change the repo's files from this skill; drift on the machine is fixed by the installer, not by editing the repo.

- [ ] **Step 1: Write the failing tests** (static):
  - The skill exists, its frontmatter `name` is `setup-check`, and its body mentions `shell_matrix.py`, `install.cmd` and `claude-setup-state.json`.
  - `install.ps1` writes `repo` to the state file.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Write the skill (follow `superpowers:writing-skills` conventions for the description; keep it under 80 lines), plus the state write and the docs.
- [ ] **Step 4:** Run `python -m unittest discover -s tests`. Expected: OK.
- [ ] **Step 5:** Commit with the message `/setup-check: Claude proves and repairs the setup on any PC`.

### Task 10: Live run on this PC

- [ ] **Step 1:** Merge the branch to main (PR), then from main run `.\install.cmd`. Expected: `DONE: all checks passed`.
- [ ] **Step 2:** Run `python shell_matrix.py`. Expected: exit 0 and every column identical. Quote the table.
- [ ] **Step 3:** Open a new Windows Terminal tab. It should be PowerShell 7, and the dropdown should list Git Bash. In each of PowerShell 7, Windows PowerShell, cmd and Git Bash, plus VS Code's terminal, run `claude`. Take one screenshot of the status bar in each (PrintWindow per the demo-screenshot memory) and compare them for the same glyphs and colours.
- [ ] **Step 4:** In a new session, run `/setup-check` and confirm the skill loads and ends with the matrix's exit-0 line.
