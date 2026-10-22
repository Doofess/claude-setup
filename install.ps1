#Requires -Version 5.1
<#
.SYNOPSIS
  Applies this repo's Claude Code config to the current machine. Safe to re-run.

.DESCRIPTION
  1. Backs up ~/.claude/{CLAUDE.md,settings.json,statusline.py,keybindings.json} to ~/.claude/backups/claude-setup-<stamp>/
  2. Copies CLAUDE.md, statusline.py, skills/ and agents/ into ~/.claude
  3. Merges settings.json keys into the existing file (machine-local keys survive), and keybindings.json
     bindings into ~/.claude/keybindings.json per context and key (null unbinds a default; other keys survive)
  4. Adds the marketplaces in extraKnownMarketplaces, installs + enables every plugin marked true in enabledPlugins,
     updates them, then disables every plugin marked false
  5. Turns the claude.ai Adobe connector off in each known project once (see mcp_off.py; /mcp turns it back on)
  6. Installs a Nerd Font through winget when the machine has none, and sets it as the Windows Terminal default
     font when no font is configured there (the status line's icons need one)
  7. Sets the Windows Terminal start folder, and adds a PowerShell 7 profile block that leaves System32 for C:\dev.
     Adds the Readable colour scheme (terminal/readable-scheme.json) and makes it the default when no scheme is set:
     the readable theme's dark-ansi base draws syntax, diff markers and inline code in the terminal's 16 colours
  8. Smoke-tests the status line and lists MCP health

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

# Output colours come from the repo's two palettes, orange and grey (xterm-256 indices, as in statusline.py):
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

function Format-DirKey([string]$d) { ($d.Trim() -replace '\\', '/').TrimEnd('/').ToLowerInvariant() }

# CLAUDE_CODE_PLUGIN_DIRS is split on the OS path delimiter (';' on Windows). Keep the machine's other dirs
# and add ours once (compared ignoring slash style, trailing slash and case).
function Merge-PluginDirs([string]$existing, [string]$ours) {
  $sep = [string][IO.Path]::PathSeparator
  $dirs = [System.Collections.ArrayList]::new()
  if ($existing) { foreach ($d in $existing.Split($sep)) { if ($d.Trim()) { [void]$dirs.Add($d.Trim()) } } }
  $has = $false
  foreach ($d in $dirs) { if ((Format-DirKey $d) -eq (Format-DirKey $ours)) { $has = $true } }
  if (-not $has) { [void]$dirs.Add($ours) }
  return ($dirs.ToArray() -join $sep)
}

# Merges the repo's settings.json (template) into the machine's (current). Keys:
#   enabledPlugins  per plugin (repo wins)          env          per variable (repo wins; PLUGIN_DIRS is unioned)
#   permissions     arrays unioned, scalars repo     hooks        per event, per command (see Merge-HookEvents)
#   everything else replaced wholesale by the repo's value
# "<repo>" in a template string value stands for this clone's path (forward slashes).
function Merge-ClaudeSettings($current, $template, [string]$repoDir) {
  $repoFwd = $repoDir -replace '\\', '/'
  if ($repoFwd.Contains(';')) { throw "Repo path '$repoDir' contains ';', which CLAUDE_CODE_PLUGIN_DIRS cannot hold." }
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
          $val = $v.Value
          $old = $existing.Value.PSObject.Properties[$v.Name]
          if ($v.Name -eq 'CLAUDE_CODE_PLUGIN_DIRS' -and $old) { $val = Merge-PluginDirs ([string]$old.Value) ([string]$v.Value) }
          $existing.Value | Add-Member -NotePropertyName $v.Name -NotePropertyValue $val -Force
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

# ---- Nerd Font (the status line's --icons nerd glyphs need one) ----
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

# Windows Terminal colour scheme, as text like the two above. The scheme named $name is replaced (it is ours) or added
# to "schemes"; profiles.defaults gets "colorScheme" only when it names none. Returns 'set', 'kept' (another scheme is
# the default; ours is still there to pick) or 'none' (no defaults block).
function Set-TerminalScheme([string]$path, [string]$schemeJson, [string]$name) {
  $text = [IO.File]::ReadAllText($path)
  $old = $text
  $obj = $schemeJson | ConvertFrom-Json | ConvertTo-Json -Compress
  $m = [regex]::Match($text, '\{[^{}]*"name"\s*:\s*"' + [regex]::Escape($name) + '"[^{}]*\}')
  if ($m.Success) {
    $text = $text.Remove($m.Index, $m.Length).Insert($m.Index, $obj)
  } else {
    $s = [regex]::Match($text, '"schemes"\s*:\s*\[')
    if ($s.Success) {
      $sep = if ($text.Substring($s.Index + $s.Length).TrimStart().StartsWith(']')) { '' } else { ',' }
      $text = $text.Insert($s.Index + $s.Length, " $obj$sep")
    } else {
      $top = [regex]::Match($text, '(?m)^\{')
      if (-not $top.Success) { return 'none' }
      $text = $text.Insert($top.Index + 1, ' "schemes": [' + $obj + '],')
    }
  }
  $r = 'none'
  $d = [regex]::Match($text, '"defaults"\s*:\s*\{')
  if ($d.Success) {
    $depth = 1; $i = $d.Index + $d.Length
    while ($i -lt $text.Length -and $depth -gt 0) {
      $c = $text[$i]
      if ($c -eq '{') { $depth++ } elseif ($c -eq '}') { $depth-- }
      $i++
    }
    $block = $text.Substring($d.Index, $i - $d.Index)
    $set = [regex]::Match($block, '"colorScheme"\s*:\s*"([^"]*)"')
    if (-not $set.Success) {
      $text = $text.Insert($d.Index + $d.Length, ' "colorScheme": "' + $name + '",'); $r = 'set'
    } elseif ($set.Groups[1].Value -eq $name) { $r = 'set' } else { $r = 'kept' }
  }
  if ($text -ne $old) { Write-Utf8NoBom $path $text }
  return $r
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

# keybindings: { bindings: [ { context, bindings: { "chord": "action" | null } } ] }. Per context, per key: the repo's
# value wins, including null (null unbinds a default, so it must be written, not skipped). The machine's other
# contexts, keys and top-level properties stay.
function Merge-Keybindings($current, $template) {
  $blocks = [System.Collections.ArrayList]::new()
  foreach ($b in @($current.bindings)) { if ($b) { [void]$blocks.Add($b) } }
  foreach ($tb in @($template.bindings)) {
    $cb = $blocks | Where-Object { $_.context -eq $tb.context } | Select-Object -First 1
    if (-not $cb) { [void]$blocks.Add($tb); continue }
    if (-not $cb.PSObject.Properties['bindings'] -or $null -eq $cb.bindings) {
      $cb | Add-Member -NotePropertyName 'bindings' -NotePropertyValue ([pscustomobject]@{}) -Force
    }
    foreach ($kb in $tb.bindings.PSObject.Properties) {
      $cb.bindings | Add-Member -NotePropertyName $kb.Name -NotePropertyValue $kb.Value -Force
    }
  }
  $merged = [ordered]@{ '$schema' = $template.'$schema'; '$docs' = $template.'$docs'; bindings = $blocks.ToArray() }
  foreach ($prop in $current.PSObject.Properties) {
    if (-not $merged.Contains($prop.Name)) { $merged[$prop.Name] = $prop.Value }
  }
  return [pscustomobject]$merged
}

# The status line's launch form from settings.json: import the module with its directory on sys.path, so
# Python reuses __pycache__/statusline.*.pyc instead of recompiling the script on every one-second
# render (the first run writes that cache). Ok is $false when Python failed or printed nothing.
function Test-StatusLine([string]$dir, [string]$sample) {
  $ErrorActionPreference = 'Continue'   # Windows PowerShell 5.1 would turn Python's stderr into a terminating error
  $code = "import os,sys;sys.path.insert(0,'" + ($dir -replace '\\', '/') + "');import statusline;statusline.main()"
  # Windows PowerShell 5.1 pipes to a native command in [Console]::InputEncoding, and on a UTF-8 console (code page
  # 65001) that encoding carries a BOM; json.loads rejects it and the script prints its fallback. Pipe BOM-free.
  $prevIn = [Console]::InputEncoding
  try {
    try { [Console]::InputEncoding = New-Object System.Text.UTF8Encoding $false } catch {}
    $out = @($sample | & python -S -c $code 2>&1 | ForEach-Object { "$_" })
    $exit = $LASTEXITCODE
  } finally { try { [Console]::InputEncoding = $prevIn } catch {} }
  $text = $out -join "`n"
  # "Claude | --" is what main() prints when rendering raised, so it counts as a failure too.
  [pscustomobject]@{ Ok = ($exit -eq 0 -and $out.Count -gt 0 -and $text -notmatch 'Claude \| --'); Output = $text }
}

foreach ($tool in 'claude', 'git', 'python') {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    throw "'$tool' not found on PATH. See README.md for the desktop bootstrap list."
  }
}
# 1. Backup
Write-Step "Backing up current config to $backup"
New-Item -ItemType Directory -Force $backup | Out-Null
foreach ($f in 'CLAUDE.md', 'settings.json', 'statusline.py', 'keybindings.json') {
  $p = Join-Path $claudeDir $f
  if (Test-Path $p) { Copy-Item $p $backup }
}

# 2. Copy files
Write-Step 'Copying CLAUDE.md, statusline.py, skills/, agents/, themes/'
Copy-Item (Join-Path $repo 'CLAUDE.md') $claudeDir -Force
Copy-Item (Join-Path $repo 'statusline.py') $claudeDir -Force
# Python trusts __pycache__/statusline.*.pyc while the source's size and mtime match what the cache recorded, and
# Copy-Item keeps the source's mtime, so a same-size edit could leave a stale cache. Drop it; the smoke test rebuilds it.
Get-ChildItem (Join-Path $claudeDir '__pycache__') -Filter 'statusline*.pyc' -ErrorAction SilentlyContinue | Remove-Item -Force
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
# Themes: each file under themes/ becomes ~/.claude/themes/<name>.json, picked by "theme": "custom:<name>".
if (Test-Path (Join-Path $repo 'themes')) {
  New-Item -ItemType Directory -Force (Join-Path $claudeDir 'themes') | Out-Null
  Copy-Item (Join-Path $repo 'themes\*.json') (Join-Path $claudeDir 'themes') -Force
}

# 3. Merge settings.json
Write-Step 'Merging settings.json'
$template = Get-Content (Join-Path $repo 'settings.json') -Raw | ConvertFrom-Json
$current = if (Test-Path $settingsPath) { Get-Content $settingsPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }

# Per-key rules (enabledPlugins, env, permissions, hooks merge; the rest is replaced) live in Merge-ClaudeSettings.
$current = Merge-ClaudeSettings $current $template $repo
$current = Remove-RetiredHooks $current $retiredHooks
foreach ($r in $retiredHooks) { Remove-Item (Join-Path $claudeDir "hooks\$r") -Force -ErrorAction SilentlyContinue }
Write-Utf8NoBom $settingsPath (($current | ConvertTo-Json -Depth 20) + "`n")

# 3b. Merge keybindings.json (the backup above already holds the previous file).
# Ctrl+X Ctrl+A is unbound so the readable-session band above the prompt cannot be collapsed.
Write-Step 'Merging keybindings.json'
$kbPath = Join-Path $claudeDir 'keybindings.json'
$kbTemplate = Get-Content (Join-Path $repo 'keybindings.json') -Raw | ConvertFrom-Json
$kbCurrent = if (Test-Path $kbPath) { Get-Content $kbPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
Write-Utf8NoBom $kbPath ((Merge-Keybindings $kbCurrent $kbTemplate | ConvertTo-Json -Depth 10) + "`n")

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
Write-Step 'Terminal colours'
$schemeJson = [IO.File]::ReadAllText((Join-Path $repo 'terminal/readable-scheme.json'))
foreach ($wt in $wtSettings) {
  Backup-TerminalSettings $wt
  $r = Set-TerminalScheme $wt $schemeJson 'Readable'
  $msg = switch ($r) { 'set' { "Readable colour scheme is the default in $wt" } 'kept' { "another colour scheme is the default in $wt; left as is (Readable is there to pick)" } default { "no defaults block in $wt; pick the Readable scheme by hand" } }
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
Write-Step 'Status line smoke test'
$sample = '{"model":{"display_name":"Test"},"workspace":{"current_dir":"' + ($HOME -replace '\\', '/') + '"},"cwd":"' + ($HOME -replace '\\', '/') + '","context_window":{"used_percentage":1}}'
$sl = Test-StatusLine $claudeDir $sample
if (-not $sl.Ok) { $failures += "statusline.py failed: $($sl.Output)" }

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
