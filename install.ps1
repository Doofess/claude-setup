#Requires -Version 5.1
<#
.SYNOPSIS
  Applies this repo's Claude Code config to the current machine. Safe to re-run.

.DESCRIPTION
  1. Backs up ~/.claude/{CLAUDE.md,settings.json,statusbar.py,statusline.py,keybindings.json} to ~/.claude/backups/claude-setup-<stamp>/
  2. Copies CLAUDE.md, statusbar.py, skills/ and agents/ into ~/.claude
  3. Merges settings.json keys into the existing file (machine-local keys survive)
  4. Adds the marketplaces in extraKnownMarketplaces, installs + enables every plugin marked true in enabledPlugins,
     updates them, then disables every plugin marked false
  5. Turns the claude.ai Adobe connector off in each known project once (see mcp_off.py; /mcp turns it back on)
  6. Removes the retired visual setup (custom theme, status line, readable-session mod, keybinding, Windows Terminal
     Readable scheme) from the machine
  7. Installs a Nerd Font through winget when the machine has none, and sets it as the Windows Terminal default
     font when no font is configured there (kept for a later visual rebuild)
  8. Sets the Windows Terminal start folder, and adds a PowerShell 7 profile block that leaves System32 for C:\dev
  9. Runs the status bar command from the installed settings.json on sample data and fails when its line is wrong
 10. Lists MCP health

.PARAMETER SkipPlugins
  Skip the plugin install/update step (faster when only config changed).

.PARAMETER SkipFont
  Do not install a Nerd Font or touch the Windows Terminal font.

#>
[CmdletBinding()]
param([switch]$SkipPlugins, [switch]$SkipFont)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$claudeDir = Join-Path $HOME '.claude'
$settingsPath = Join-Path $claudeDir 'settings.json'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $claudeDir "backups\claude-setup-$stamp"
$failures = @()

# Output colours come from the repo's two palettes, orange and grey (xterm-256 indices):
# 208 orange for steps, 223 peach for success, 228 yellow for warnings, 203 red for failures, 244 grey.
# The 16 Write-Host console colours have no orange, so these are ANSI escapes ([char]27: `e needs PS 6+).
function Write-Color($msg, [int]$color) { Write-Host "$([char]27)[38;5;${color}m$msg$([char]27)[0m" }
function Write-Step($msg) { Write-Color "==> $msg" 208 }
function Write-Utf8NoBom($path, $text) {
  [IO.File]::WriteAllText($path, $text, [Text.UTF8Encoding]::new($false))
}

# ---- settings.json merge helpers (pure functions on parsed JSON, so they can be tested without a machine) ----
function Test-IsObject($v) { $v -is [System.Management.Automation.PSCustomObject] }
function Test-IsArray($v) { $v -is [System.Array] }

# Recursive merge for keys whose machine-local entries must survive (permissions): objects merge per key,
# arrays are unioned (existing entries first, then new repo entries), any other value is taken from the repo.
function Merge-Json($existing, $incoming) {
  if ((Test-IsObject $existing) -and (Test-IsObject $incoming)) {
    foreach ($p in $incoming.PSObject.Properties) {
      $cur = $existing.PSObject.Properties[$p.Name]
      if ($cur) { $val = Merge-Json $cur.Value $p.Value } else { $val = $p.Value }
      $existing | Add-Member -NotePropertyName $p.Name -NotePropertyValue $val -Force
    }
    return $existing
  }
  if ((Test-IsArray $existing) -and (Test-IsArray $incoming)) {
    $list = [System.Collections.ArrayList]::new()
    $seen = @{}
    foreach ($item in (@($existing) + @($incoming))) {
      $k = ConvertTo-Json -InputObject $item -Compress -Depth 20
      if (-not $seen.ContainsKey($k)) { $seen[$k] = $true; [void]$list.Add($item) }
    }
    return , $list.ToArray()
  }
  if (Test-IsArray $incoming) { return , $incoming }
  return $incoming
}

# hooks: { Event: [ { matcher, hooks: [ {type, command, ...} ] } ] }. A repo hook is matched to a machine hook by
# its command: same command -> the repo's fields win in place, otherwise it is added (to the group with the same
# matcher, or as a new group). Machine hooks the repo doesn't know stay.
function Merge-HookEvents($existing, $incoming) {
  foreach ($ev in $incoming.PSObject.Properties) {
    $cur = $existing.PSObject.Properties[$ev.Name]
    if (-not $cur -or -not (Test-IsArray $cur.Value)) {
      $existing | Add-Member -NotePropertyName $ev.Name -NotePropertyValue $ev.Value -Force
      continue
    }
    $groups = [System.Collections.ArrayList]::new()
    foreach ($g in $cur.Value) { [void]$groups.Add($g) }
    foreach ($tg in @($ev.Value)) {
      $sameMatcher = $null
      foreach ($g in $groups) { if ([string]$g.matcher -eq [string]$tg.matcher) { $sameMatcher = $g; break } }
      if (-not $sameMatcher) { [void]$groups.Add($tg); continue }
      $hooks = [System.Collections.ArrayList]::new()
      foreach ($h in @($sameMatcher.hooks)) { if ($h) { [void]$hooks.Add($h) } }
      foreach ($th in @($tg.hooks)) {
        $found = $null
        foreach ($g in $groups) {
          foreach ($h in @($g.hooks)) { if ($h -and $th.command -and $h.command -eq $th.command) { $found = $h; break } }
          if ($found) { break }
        }
        if ($found) {
          foreach ($p in $th.PSObject.Properties) { $found | Add-Member -NotePropertyName $p.Name -NotePropertyValue $p.Value -Force }
        } else { [void]$hooks.Add($th) }
      }
      $sameMatcher | Add-Member -NotePropertyName hooks -NotePropertyValue $hooks.ToArray() -Force
    }
    $existing | Add-Member -NotePropertyName $ev.Name -NotePropertyValue $groups.ToArray() -Force
  }
  return $existing
}

# Merges the repo's settings.json (template) into the machine's (current). Keys:
#   enabledPlugins  per plugin (repo wins)          env          per variable (repo wins)
#   permissions     arrays unioned, scalars repo     hooks        per event, per command (see Merge-HookEvents)
#   everything else replaced wholesale by the repo's value
# "<repo>" in a template string value stands for this clone's path (forward slashes).
function Merge-ClaudeSettings($current, $template, [string]$repoDir) {
  $repoFwd = $repoDir -replace '\\', '/'
  foreach ($prop in $template.PSObject.Properties) {
    $existing = $current.PSObject.Properties[$prop.Name]
    $hasObj = $existing -and (Test-IsObject $existing.Value)
    if ($prop.Name -eq 'enabledPlugins' -and $hasObj) {
      foreach ($plugin in $prop.Value.PSObject.Properties) {
        $existing.Value | Add-Member -NotePropertyName $plugin.Name -NotePropertyValue $plugin.Value -Force
      }
    } elseif ($prop.Name -eq 'env') {
      $ours = [pscustomobject]@{}   # a copy, so the template object is not changed
      foreach ($v in $prop.Value.PSObject.Properties) {
        $val = $v.Value
        if ($val -is [string]) { $val = $val.Replace('<repo>', $repoFwd) }
        $ours | Add-Member -NotePropertyName $v.Name -NotePropertyValue $val
      }
      if (-not $hasObj) {
        $current | Add-Member -NotePropertyName 'env' -NotePropertyValue $ours -Force
      } else {
        foreach ($v in $ours.PSObject.Properties) {
          $existing.Value | Add-Member -NotePropertyName $v.Name -NotePropertyValue $v.Value -Force
        }
      }
    } elseif ($prop.Name -eq 'permissions' -and $hasObj) {
      $merged = Merge-Json $existing.Value $prop.Value
      $current | Add-Member -NotePropertyName 'permissions' -NotePropertyValue $merged -Force
    } elseif ($prop.Name -eq 'hooks' -and $hasObj) {
      $merged = Merge-HookEvents $existing.Value $prop.Value
      $current | Add-Member -NotePropertyName 'hooks' -NotePropertyValue $merged -Force
    } else {
      $current | Add-Member -NotePropertyName $prop.Name -NotePropertyValue $prop.Value -Force
    }
  }
  return $current
}

# ---- Nerd Font (kept for a later visual rebuild) ----
$nerdFontId = 'DEVCOM.JetBrainsMonoNerdFont'
$nerdFontFace = 'JetBrainsMono Nerd Font'
function Get-NerdFontFiles {
  foreach ($d in "$env:LOCALAPPDATA\Microsoft\Windows\Fonts", "$env:WINDIR\Fonts") {
    Get-ChildItem $d -Filter '*Nerd*Font*' -ErrorAction SilentlyContinue
  }
}

# Windows Terminal settings.json is JSON with comments, so edit it as text. Insert a font face into profiles.defaults
# only when the file names no font at all; an existing choice (even a non-Nerd one) is left for the user.
# Returns 'set', 'kept' (a font is already configured) or 'none' (no settings file / no defaults block).
function Set-TerminalFont([string]$path, [string]$face) {
  $text = [IO.File]::ReadAllText($path)
  if ($text -match '"font"\s*:' -or $text -match '"face"\s*:') { return 'kept' }
  $m = [regex]::Match($text, '"defaults"\s*:\s*\{')
  if (-not $m.Success) { return 'none' }
  $edited = $text.Insert($m.Index + $m.Length, ' "font": { "face": "' + $face + '" },')
  Write-Utf8NoBom $path $edited
  return 'set'
}

# Windows Terminal opens in System32 unless the defaults profile names a folder, and sessions started there load
# the wrong project context. Add one only when profiles.defaults has no startingDirectory of its own.
function Set-TerminalStartDir([string]$path, [string]$dir) {
  $text = [IO.File]::ReadAllText($path)
  $m = [regex]::Match($text, '"defaults"\s*:\s*\{')
  if (-not $m.Success) { return 'none' }
  $depth = 1; $i = $m.Index + $m.Length
  while ($i -lt $text.Length -and $depth -gt 0) {
    $c = $text[$i]
    if ($c -eq '{') { $depth++ } elseif ($c -eq '}') { $depth-- }
    $i++
  }
  if ($text.Substring($m.Index, $i - $m.Index) -match '"startingDirectory"\s*:') { return 'kept' }
  Write-Utf8NoBom $path ($text.Insert($m.Index + $m.Length, ' "startingDirectory": "' + $dir.Replace('\', '\\') + '",'))
  return 'set'
}

# Retired: the Readable colour scheme this repo used to add. Edits Windows Terminal settings as text (JSON with
# comments, so no round-trip through ConvertFrom-Json): the scheme object named $name is dropped from "schemes", and
# every "colorScheme": "<name>" key (that value only; other schemes stay) from the defaults and the profiles, with
# the commas around them. Writes only when something changed. Returns what was removed.
function Remove-TerminalScheme([string]$path, [string]$name) {
  $text = [IO.File]::ReadAllText($path)
  $old = $text
  $schemeRemoved = $false
  $s = [regex]::Match($text, '"schemes"\s*:\s*\[')
  if ($s.Success) {
    # The array ends at its matching ']', found skipping strings and comments.
    $start = $s.Index + $s.Length; $i = $start; $depth = 1
    while ($i -lt $text.Length) {
      $c = $text[$i]
      if ($c -eq '"') {
        $i++
        while ($i -lt $text.Length -and $text[$i] -ne '"') { if ($text[$i] -eq '\') { $i++ }; $i++ }
      } elseif ($c -eq '/' -and $i + 1 -lt $text.Length -and $text[$i + 1] -eq '/') {
        while ($i -lt $text.Length -and $text[$i] -ne "`n") { $i++ }
      } elseif ($c -eq '/' -and $i + 1 -lt $text.Length -and $text[$i + 1] -eq '*') {
        $e = $text.IndexOf('*/', $i + 2); $i = if ($e -lt 0) { $text.Length } else { $e + 1 }
      } elseif ($c -eq '[') { $depth++ }
      elseif ($c -eq ']') { $depth--; if ($depth -eq 0) { break } }
      $i++
    }
    $region = $text.Substring($start, $i - $start)
    $obj = '\{[^{}]*"name"\s*:\s*"' + [regex]::Escape($name) + '"[^{}]*\}'
    while (($m = [regex]::Match($region, $obj)).Success) {
      $before = $region.Substring(0, $m.Index)
      $after = $region.Substring($m.Index + $m.Length)
      if ($after.Trim(" `t`r`n,") -eq '') {
        # last element: its separator is the comma before it
        $before = [regex]::Replace($before, ',\s*$', '')
        $after = [regex]::Replace($after, '^\s*,', '')
      } else {
        $after = [regex]::Replace($after, '^\s*,\s*', '')
      }
      $region = $before + $after
      $schemeRemoved = $true
    }
    $text = $text.Substring(0, $start) + $region + $text.Substring($i)
  }
  $key = '"colorScheme"\s*:\s*"' + [regex]::Escape($name) + '"'
  $keys = [regex]::Matches($text, $key).Count
  if ($keys -gt 0) {
    $text = [regex]::Replace($text, "$key\s*,\s*", '')
    $text = [regex]::Replace($text, ",\s*$key", '')
    $text = [regex]::Replace($text, $key, '')
  }
  if ($text -ne $old) { Write-Utf8NoBom $path $text }
  [pscustomobject]@{ Scheme = $schemeRemoved; Keys = $keys }
}

# Windows Terminal keeps settings.json per install (Store, Preview, unpackaged). Each is backed up once per run under
# a name taken from its path below LOCALAPPDATA, so two installs never share a backup file.
$wtSettings = @(
  "$env:LOCALAPPDATA\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json",
  "$env:LOCALAPPDATA\Packages\Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe\LocalState\settings.json",
  "$env:LOCALAPPDATA\Microsoft\Windows Terminal\settings.json"
) | Where-Object { Test-Path $_ }
function Backup-TerminalSettings([string]$path) {
  $name = 'wt' + ($path.Substring($env:LOCALAPPDATA.Length) -replace '[\\/: ]', '_')
  $copy = Join-Path $backup $name
  if (-not (Test-Path $copy)) { Copy-Item $path $copy }
}

# PowerShell 7 started from Start or the taskbar opens in System32 (Windows Terminal's startingDirectory never
# applies there), and Claude Code started there loads the wrong project. The profile gets one block between these
# markers; a re-run replaces it, and the rest of the profile is left alone.
$profileStart = '# >>> claude-setup'
$profileEnd = '# <<< claude-setup'
function Set-ProfileBlock([string]$text, [string]$body) {
  $block = "$profileStart`r`n$body`r`n$profileEnd"
  $pattern = [regex]::Escape($profileStart) + '[\s\S]*?' + [regex]::Escape($profileEnd)
  if ($text -match $pattern) { return [regex]::Replace($text, $pattern, { param($m) $block }) }
  if ($text -and -not $text.EndsWith("`n")) { $text += "`r`n" }
  return $text + $block + "`r`n"
}

# Hooks this repo used to install. The merge keeps machine hooks it doesn't know, so a retired one would live on
# forever; drop every hook whose command mentions a retired script, and any group or event left empty.
$retiredHooks = @('block-dangerous-git.sh', 'bigquery-headers.py', '.bigquery-token.json', 'history_sync')
function Remove-RetiredHooks($current, [string[]]$retired) {
  if (-not $current.PSObject.Properties['hooks'] -or $null -eq $current.hooks) { return $current }
  $events = [ordered]@{}
  foreach ($ev in $current.hooks.PSObject.Properties) {
    $groups = @()
    foreach ($g in @($ev.Value)) {
      $kept = @(@($g.hooks) | Where-Object { $h = $_; $h -and -not ($retired | Where-Object { ([string]$h.command).Contains($_) }) })
      if ($kept.Count -gt 0) { $g | Add-Member -NotePropertyName hooks -NotePropertyValue $kept -Force; $groups += $g }
    }
    if ($groups.Count -gt 0) { $events[$ev.Name] = $groups }
  }
  if ($events.Count -gt 0) { $current | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]$events) -Force }
  else { $current.PSObject.Properties.Remove('hooks') }
  return $current
}

# Retired visual setup, as it sits on a machine that installed it. Each function changes the object it is given and
# returns the lines to print (none when there was nothing to remove).
# settings.json: theme only when it is ours, statusLine only when it launches statusline, and the readable-session
# mod's folder from CLAUDE_CODE_PLUGIN_DIRS (';'-separated; compared ignoring slash style, trailing slash and case).
# Other entries stay, and the variable goes when nothing is left.
function Remove-VisualSettings($current) {
  $done = @()
  $t = $current.PSObject.Properties['theme']
  if ($t -and $t.Value -eq 'custom:readable') { $current.PSObject.Properties.Remove('theme'); $done += 'theme custom:readable' }
  $sl = $current.PSObject.Properties['statusLine']
  if ($sl -and ([string]$sl.Value.command) -like '*statusline*') { $current.PSObject.Properties.Remove('statusLine'); $done += 'statusLine' }
  $envProp = $current.PSObject.Properties['env']
  $pd = if ($envProp -and (Test-IsObject $envProp.Value)) { $envProp.Value.PSObject.Properties['CLAUDE_CODE_PLUGIN_DIRS'] } else { $null }
  if ($pd) {
    $keep = @(); $dropped = 0
    foreach ($d in ([string]$pd.Value).Split(';')) {
      if (-not $d.Trim()) { continue }
      if ((($d.Trim() -replace '\\', '/').TrimEnd('/').ToLowerInvariant()).EndsWith('/mods/readable-session')) { $dropped++ } else { $keep += $d.Trim() }
    }
    if ($dropped -gt 0) {
      if ($keep.Count -gt 0) { $envProp.Value | Add-Member -NotePropertyName CLAUDE_CODE_PLUGIN_DIRS -NotePropertyValue ($keep -join ';') -Force }
      else { $envProp.Value.PSObject.Properties.Remove('CLAUDE_CODE_PLUGIN_DIRS') }
      $done += 'readable-session in CLAUDE_CODE_PLUGIN_DIRS'
    }
  }
  return $done
}

# keybindings.json: the Chat context's "ctrl+x ctrl+a": null (it unbound the panel's collapse shortcut). The context
# block goes when that leaves it empty; other bindings stay.
function Remove-VisualKeybinding($kb) {
  $done = @()
  if (-not $kb.PSObject.Properties['bindings']) { return $done }
  $blocks = @()
  foreach ($b in @($kb.bindings)) {
    $p = if ($b -and $b.context -eq 'Chat' -and $b.PSObject.Properties['bindings'] -and $b.bindings) { $b.bindings.PSObject.Properties['ctrl+x ctrl+a'] } else { $null }
    if ($p -and $null -eq $p.Value) {
      $b.bindings.PSObject.Properties.Remove('ctrl+x ctrl+a')
      $done += 'ctrl+x ctrl+a'
      if (@($b.bindings.PSObject.Properties).Count -eq 0) { continue }
    }
    $blocks += $b
  }
  if ($done.Count -gt 0) { $kb | Add-Member -NotePropertyName bindings -NotePropertyValue $blocks -Force }
  return $done
}

# Git Bash, the shell Claude Code runs status lines in: CLAUDE_CODE_GIT_BASH_PATH when set, else bin\bash.exe next to the
# git on PATH. A plain `bash` on PATH is often the WSL launcher in WindowsApps, which has no Windows python.
function Get-GitBash {
  if ($env:CLAUDE_CODE_GIT_BASH_PATH -and (Test-Path $env:CLAUDE_CODE_GIT_BASH_PATH)) { return $env:CLAUDE_CODE_GIT_BASH_PATH }
  $git = (Get-Command git -ErrorAction SilentlyContinue | Select-Object -First 1).Source
  if ($git) {
    $dir = Split-Path $git
    foreach ($root in $dir, (Split-Path $dir), (Split-Path (Split-Path $dir))) {
      if ($root -and (Test-Path (Join-Path $root 'bin\bash.exe'))) { return (Join-Path $root 'bin\bash.exe') }
    }
  }
  return 'bash'
}

# Runs $command (statusLine.command from the installed settings) the way Claude Code does on Windows: Git Bash
# `-c` (a non-login shell: Claude Code spawns hooks with execa's shell option, which never reads the bash profile,
# so python must be on the Windows PATH itself), the session JSON on stdin, COLUMNS=160. CLAUDE_CODE_AUTO_COMPACT_WINDOW is pinned to 300000
# (the environment outranks every settings file) so the context meter reads the same on every machine. The
# environment and the console encoding (the bar prints UTF-8) are put back afterwards.
function Test-StatusBar([string]$command, [string]$sample) {
  $savedEnv = @{}
  foreach ($n in 'COLUMNS', 'CLAUDE_CODE_AUTO_COMPACT_WINDOW') { $savedEnv[$n] = [Environment]::GetEnvironmentVariable($n) }
  $savedEnc = [Console]::OutputEncoding
  try {
    $env:COLUMNS = '160'  # wide enough for every piece of the sample, cost included
    $env:CLAUDE_CODE_AUTO_COMPACT_WINDOW = '300000'
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $out = $sample | & (Get-GitBash) -c $command 2>&1
    $ok = ($LASTEXITCODE -eq 0)
  } finally {
    foreach ($n in $savedEnv.Keys) { [Environment]::SetEnvironmentVariable($n, $savedEnv[$n]) }
    [Console]::OutputEncoding = $savedEnc
  }
  [pscustomobject]@{ Ok = $ok; Output = (@($out | ForEach-Object { "$_" }) -join "`n") }
}

foreach ($tool in 'claude', 'git', 'python') {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    throw "'$tool' not found on PATH. See README.md for the desktop bootstrap list."
  }
}
# 1. Backup
Write-Step "Backing up current config to $backup"
New-Item -ItemType Directory -Force $backup | Out-Null
foreach ($f in 'CLAUDE.md', 'settings.json', 'statusbar.py', 'statusline.py', 'keybindings.json') {
  $p = Join-Path $claudeDir $f
  if (Test-Path $p) { Copy-Item $p $backup }
}

# 2. Copy files
Write-Step 'Copying CLAUDE.md, statusbar.py, skills/, agents/'
Copy-Item (Join-Path $repo 'CLAUDE.md') $claudeDir -Force
Copy-Item (Join-Path $repo 'statusbar.py') $claudeDir -Force
# Skills: each folder under skills/ becomes ~/.claude/skills/<name>. Copy keeps a skill's local .venv.
foreach ($skill in Get-ChildItem (Join-Path $repo 'skills') -Directory -ErrorAction SilentlyContinue) {
  $dest = Join-Path $claudeDir "skills\$($skill.Name)"
  New-Item -ItemType Directory -Force $dest | Out-Null
  Copy-Item (Join-Path $skill.FullName '*') $dest -Recurse -Force
}
# Agents: each file under agents/ becomes ~/.claude/agents/<name>.md (a file named like a built-in agent replaces it).
if (Test-Path (Join-Path $repo 'agents')) {
  New-Item -ItemType Directory -Force (Join-Path $claudeDir 'agents') | Out-Null
  Copy-Item (Join-Path $repo 'agents\*.md') (Join-Path $claudeDir 'agents') -Force
}
# 3. Merge settings.json
Write-Step 'Merging settings.json'
$template = Get-Content (Join-Path $repo 'settings.json') -Raw | ConvertFrom-Json
$current = if (Test-Path $settingsPath) { Get-Content $settingsPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }

# Per-key rules (enabledPlugins, env, permissions, hooks merge; the rest is replaced) live in Merge-ClaudeSettings.
$current = Merge-ClaudeSettings $current $template $repo
$current = Remove-RetiredHooks $current $retiredHooks
foreach ($r in $retiredHooks) { Remove-Item (Join-Path $claudeDir "hooks\$r") -Force -ErrorAction SilentlyContinue }
# The status bar draws Nerd Font icons; on a machine without a Nerd Font the installed command gets --labels
# (short words instead of glyphs), so the bar reads in whatever font the terminal uses.
$slProp = $current.PSObject.Properties['statusLine']
if ($slProp -and $slProp.Value -and $slProp.Value.PSObject.Properties['command'] -and @(Get-NerdFontFiles).Count -eq 0) {
  $cmd = [string]$slProp.Value.command
  if ($cmd -notmatch '--labels') { $slProp.Value | Add-Member -NotePropertyName command -NotePropertyValue "$cmd --labels" -Force }
}
Write-Utf8NoBom $settingsPath (($current | ConvertTo-Json -Depth 20) + "`n")

# 4. Plugins
# Windows PowerShell 5.1 turns a native command's stderr into a terminating error under
# $ErrorActionPreference = 'Stop' ("plugin is already enabled" would abort the script), so the
# plugin calls run with 'Continue' and their stderr is captured, not thrown.
$savedEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
if (-not $SkipPlugins) {
  # Plugins from outside the official marketplace (good-css) need their marketplace known first.
  foreach ($mp in $template.extraKnownMarketplaces.PSObject.Properties) {
    $out = & claude plugin marketplace add $mp.Value.source.repo 2>&1
    if ($LASTEXITCODE -ne 0 -and ($out -join ' ') -notmatch 'already') { $failures += "marketplace $($mp.Name): $out" }
  }
  & claude plugin marketplace update 2>&1 | Out-Null
  Write-Step 'Installing and enabling plugins'
  foreach ($plugin in $template.enabledPlugins.PSObject.Properties) {
    if ($plugin.Value -ne $true) { continue }
    $name = $plugin.Name
    $out = & claude plugin install $name 2>&1
    if ($LASTEXITCODE -ne 0 -and ($out -join ' ') -notmatch 'already') { $failures += "install $name : $out" }
    & claude plugin enable $name 2>&1 | Out-Null
    $upd = & claude plugin update $name 2>&1
    $ver = ($upd | Out-String).Trim() -replace '\s+', ' '
    Write-Host "    $name  $ver"
  }
  # Enabling a plugin by name also flips on a same-named copy from another marketplace, so pin the false ones off afterwards.
  foreach ($plugin in $template.enabledPlugins.PSObject.Properties) {
    if ($plugin.Value -ne $false) { continue }
    & claude plugin disable $plugin.Name 2>&1 | Out-Null
  }
}
$ErrorActionPreference = $savedEap

# 4b. BigQuery MCP server is retired: drop the user-scope registration (a missing one is not an error).
Write-Step 'Removing BigQuery MCP server'
$ErrorActionPreference = 'Continue'
& claude mcp remove bigquery -s user 2>&1 | Out-Null
$ErrorActionPreference = $savedEap

# 4b2. The visual setup (theme, status line, readable-session mod, Windows Terminal Readable scheme) is retired. The
# settings merge keeps machine keys the repo no longer has, so an earlier install is undone here, after the merge.
# Step 1 backed up settings.json, statusline.py and keybindings.json; Windows Terminal settings are backed up below.
Write-Step 'Removing the retired visual setup'
$removed = 0
$cur = Get-Content $settingsPath -Raw | ConvertFrom-Json
$done = Remove-VisualSettings $cur
if ($done.Count -gt 0) {
  Write-Utf8NoBom $settingsPath (($cur | ConvertTo-Json -Depth 20) + "`n")
  Write-Host "    removed from settings.json: $($done -join ', ')"; $removed++
}
$gone = @()
foreach ($f in 'statusline.py', 'themes\readable.json') {
  $p = Join-Path $claudeDir $f
  if (Test-Path $p) { Remove-Item $p -Force; $gone += "~/.claude/$($f -replace '\\', '/')" }
}
foreach ($f in Get-ChildItem (Join-Path $claudeDir '__pycache__') -Filter 'statusline*.pyc' -ErrorAction SilentlyContinue) {
  Remove-Item $f.FullName -Force; $gone += "~/.claude/__pycache__/$($f.Name)"
}
if ($gone.Count -gt 0) { Write-Host "    deleted: $($gone -join ', ')"; $removed++ }
$kbPath = Join-Path $claudeDir 'keybindings.json'
if (Test-Path $kbPath) {
  $kb = Get-Content $kbPath -Raw | ConvertFrom-Json
  $done = Remove-VisualKeybinding $kb
  if ($done.Count -gt 0) {
    Write-Utf8NoBom $kbPath (($kb | ConvertTo-Json -Depth 10) + "`n")
    Write-Host "    removed from keybindings.json: $($done -join ', ')"; $removed++
  }
}
foreach ($wt in $wtSettings) {
  Backup-TerminalSettings $wt
  $r = Remove-TerminalScheme $wt 'Readable'
  if ($r.Scheme -or $r.Keys -gt 0) {
    $what = @(); if ($r.Scheme) { $what += 'the Readable scheme' }; if ($r.Keys -gt 0) { $what += "$($r.Keys) colorScheme setting(s)" }
    Write-Host "    removed $($what -join ' and ') from $wt"; $removed++
  }
}
if ($removed -eq 0) { Write-Color '    nothing to remove' 244 }

# 4c. Adobe connector off by default: 5k tokens a turn that only design work needs. Back up ~/.claude.json first.
Write-Step 'Adobe connector off in each known project (/mcp turns it back on)'
$claudeJson = Join-Path $HOME '.claude.json'
if (Test-Path $claudeJson) { Copy-Item $claudeJson (Join-Path $backup 'claude.json') }
& python -S (Join-Path $repo 'mcp_off.py') $claudeJson (Join-Path $claudeDir 'claude-setup-state.json') 'claude.ai Adobe'
if ($LASTEXITCODE -ne 0) { $failures += 'mcp_off.py failed' }

# 4d. Nerd Font. Best effort: a failure here warns and never fails the install.
if (-not $SkipFont) {
  Write-Step 'Nerd Font'
  $weInstalled = $false
  if (@(Get-NerdFontFiles).Count -gt 0) {
    Write-Color '    a Nerd Font is already installed' 244
  } elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    $savedEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & winget install --id $nerdFontId -e --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    $ErrorActionPreference = $savedEap
    $weInstalled = @(Get-NerdFontFiles).Count -gt 0
    if ($weInstalled) { Write-Host "    installed $nerdFontFace" } else { Write-Color "    winget could not install $nerdFontId; install a Nerd Font by hand (https://www.nerdfonts.com)" 228 }
  } else {
    Write-Color '    winget not found; install a Nerd Font by hand (https://www.nerdfonts.com)' 228
  }
  # Point Windows Terminal at the font only when this run installed it, or the machine has JetBrainsMono.
  $haveFace = $weInstalled -or (@(Get-NerdFontFiles | Where-Object { $_.Name -like 'JetBrainsMono*' }).Count -gt 0)
  if ($haveFace) {
    foreach ($wt in $wtSettings) {
      Backup-TerminalSettings $wt
      $r = Set-TerminalFont $wt $nerdFontFace
      $msg = switch ($r) { 'set' { "font set to $nerdFontFace in $wt" } 'kept' { "a font is already set in $wt; left as is" } default { "no defaults block in $wt; set the font by hand" } }
      Write-Host "    $msg"
    }
    if (@($wtSettings).Count -eq 0) { Write-Color '    Windows Terminal not found; set the terminal font to a Nerd Font by hand' 228 }
  }
}

# 4e. Start folder (independent of the font): Windows Terminal's default, and the PowerShell 7 profile block.
Write-Step 'Terminal start folder'
foreach ($wt in $wtSettings) {
  Backup-TerminalSettings $wt
  $r = Set-TerminalStartDir $wt 'C:\dev'
  $msg = switch ($r) { 'set' { "start folder set to C:\dev in $wt" } 'kept' { "a start folder is already set in $wt; left as is" } default { "no defaults block in $wt; set the start folder by hand" } }
  Write-Host "    $msg"
}
$ps7Profile = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\Microsoft.PowerShell_profile.ps1'
$old = if (Test-Path $ps7Profile) { [IO.File]::ReadAllText($ps7Profile) } else { '' }
if ($old) { Copy-Item $ps7Profile (Join-Path $backup 'Microsoft.PowerShell_profile.ps1') }
$new = Set-ProfileBlock $old 'if ((Get-Location).Path -eq "$env:SystemRoot\System32") { Set-Location C:\dev }'
if ($new -ne $old) {
  New-Item -ItemType Directory -Force (Split-Path $ps7Profile) | Out-Null
  Write-Utf8NoBom $ps7Profile $new
}
Write-Host "    PowerShell 7 profile: $ps7Profile"

# 5. Verify
$ErrorActionPreference = 'Continue'
# The status bar fails silently inside Claude Code (an empty bar), so prove it here: take the command from the
# installed settings.json (what this machine will run), feed it the sample from statusbar.py --demo-json, and
# require one row with the sample's model, branch, context percentage and cost, plus the meter glyph (so the
# UTF-8 round trip through Git Bash is proven, not assumed). The bar uses no icon font: its only non-ASCII
# characters are ones every monospace font has.
Write-Step 'Status bar check'
$py = & python -c "import sys;print(sys.version_info[:2]>=(3,10))" 2>&1
if (("$py").Trim() -ne 'True') {
  $failures += "status bar: python is not Python 3.10+ (the Windows Store alias?): $py"
} else {
  $installed = Get-Content $settingsPath -Raw | ConvertFrom-Json
  $slProp = $installed.PSObject.Properties['statusLine']
  $barCommand = if ($slProp -and $slProp.Value) { [string]$slProp.Value.command } else { '' }
  if (-not $barCommand) {
    $failures += 'status bar: ~/.claude/settings.json has no statusLine.command'
  } else {
    $sample = (& python -I -S (Join-Path $repo 'statusbar.py') --demo-json) -join "`n"
    $bar = Test-StatusBar $barCommand $sample
    $rows = @($bar.Output -split "\r?\n" | Where-Object { $_ -ne '' })
    $missing = @('Opus', 'main', '42%', '$1.23', [string][char]0x2588 | Where-Object { -not $bar.Output.Contains($_) })
    if ($bar.Ok -and $rows.Count -eq 1 -and $missing.Count -eq 0) {
      foreach ($row in $rows) { Write-Host "    $row" }
    } else {
      $failures += "status bar: '$barCommand' gave $($rows.Count) row(s) (exit ok: $($bar.Ok), missing: $($missing -join ' ')): $($rows -join ' / ')"
    }
  }
}
Write-Step 'MCP health'
& claude mcp list 2>&1 | Where-Object { $_ -match 'Needs authentication|Failed|error' } | ForEach-Object { Write-Color "    $_" 228 }

Write-Host ''
if ($failures.Count -eq 0) {
  Write-Color 'DONE: all checks passed. Restart Claude Code to load the new config.' 223
} else {
  Write-Color 'DONE WITH FAILURES:' 203
  $failures | ForEach-Object { Write-Color "  - $_" 203 }
  exit 1
}
