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
  7. Installs a Nerd Font through winget when the machine has none, and sets terminal/profile.json's font (face and
     cellHeight) as the Windows Terminal default font whenever it differs, and drops a font face or cellHeight set
     on the default profile itself
  8. Sets the Windows Terminal default colour scheme to terminal/profile.json's (Campbell) and drops a colorScheme
     set on the default profile itself, so the default applies
  9. Sets the Windows Terminal start folder, and adds a PowerShell 7 profile block that leaves System32 for C:\dev
 10. Runs the status bar command from the installed settings.json on sample data and fails when its line is wrong
 11. Checks the session-cards mod is in CLAUDE_CODE_PLUGIN_DIRS and passes `claude plugin validate`
 12. Prints the `Same experience` table (font, colour scheme, Claude Code theme, status line, mod folder, tool
     versions) and fails when a row is FAIL
 13. Lists MCP health

.PARAMETER SkipPlugins
  Skip the plugin install/update step (faster when only config changed).

.PARAMETER SkipFont
  Do not install a Nerd Font or touch the Windows Terminal font (the font rows of the check read `kept`).

.PARAMETER KeepFont
  Keep the machine's own Windows Terminal font instead of terminal/profile.json's (its check rows read `kept`).

.PARAMETER KeepScheme
  Keep the machine's own Windows Terminal colour scheme instead of Campbell (its check row reads `kept`).

#>
[CmdletBinding()]
param([switch]$SkipPlugins, [switch]$SkipFont, [switch]$KeepFont, [switch]$KeepScheme)

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

# CLAUDE_CODE_PLUGIN_DIRS is ';'-separated. Entries compare ignoring slash style, trailing slash and case. The result is
# the machine's other entries, then ours (once): an existing entry ending in /mods/session-cards (an older clone or
# worktree path) is replaced by ours, every other entry stays.
function Format-DirKey([string]$d) { ($d.Trim() -replace '\\', '/').TrimEnd('/').ToLowerInvariant() }
function Merge-PluginDirs([string]$current, [string]$ours) {
  $mine = @($ours.Split(';') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  $mineKeys = @($mine | ForEach-Object { Format-DirKey $_ })
  $keep = @()
  foreach ($d in $current.Split(';')) {
    $d = $d.Trim()
    if (-not $d) { continue }
    $k = Format-DirKey $d
    if ($k.EndsWith('/mods/session-cards') -or $mineKeys -contains $k) { continue }
    $keep += $d
  }
  return (($keep + $mine) -join ';')
}

# Merges the repo's settings.json (template) into the machine's (current). Keys:
#   enabledPlugins  per plugin (repo wins)          env          per variable (repo wins)
#   permissions     arrays unioned, scalars repo     hooks        per event, per command (see Merge-HookEvents)
#   everything else replaced wholesale by the repo's value
# CLAUDE_CODE_PLUGIN_DIRS inside env is a union (see Merge-PluginDirs), so a machine's own mod folders survive.
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
          $val = $v.Value
          $cur = $existing.Value.PSObject.Properties[$v.Name]
          if ($v.Name -eq 'CLAUDE_CODE_PLUGIN_DIRS' -and $cur) { $val = Merge-PluginDirs ([string]$cur.Value) ([string]$val) }
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

# ---- Nerd Font (kept for a later visual rebuild) ----
$nerdFontId = 'DEVCOM.JetBrainsMonoNerdFont'
$terminalLook = Get-Content (Join-Path $repo 'terminal\profile.json') -Raw | ConvertFrom-Json   # this PC's measured look
$nerdFontFace = $terminalLook.font.face
function Get-NerdFontFiles {
  foreach ($d in "$env:LOCALAPPDATA\Microsoft\Windows\Fonts", "$env:WINDIR\Fonts") {
    Get-ChildItem $d -Filter '*Nerd*Font*' -ErrorAction SilentlyContinue
  }
}

# ---- Windows Terminal settings.json ----
# It is JSON with comments, so it is read and edited as text: these helpers scan past strings and comments, find a
# key at the top level of an object, and replace, insert or remove just that key, so comments and layout survive.
# Positions are indexes into the text; a key is { KeyStart; ValueStart; ValueEnd } (ValueEnd is exclusive).
function Skip-JsoncComment([string]$t, [int]$i) {
  if ($t[$i] -ne '/' -or $i + 1 -ge $t.Length) { return $i }
  if ($t[$i + 1] -eq '/') { while ($i -lt $t.Length -and $t[$i] -ne "`n") { $i++ }; return $i }
  if ($t[$i + 1] -eq '*') { $e = $t.IndexOf('*/', $i + 2); if ($e -lt 0) { return $t.Length }; return $e + 2 }
  return $i
}
function Skip-JsoncString([string]$t, [int]$i) {   # $i is at the opening quote; returns the index after the closing one
  $i++
  while ($i -lt $t.Length -and $t[$i] -ne '"') { if ($t[$i] -eq '\') { $i++ }; $i++ }
  return $i + 1
}
function Get-JsoncEnd([string]$t, [int]$open) {   # the bracket that closes the one at $open, or -1
  $depth = 0; $i = $open
  while ($i -lt $t.Length) {
    $c = $t[$i]
    if ($c -eq '"') { $i = Skip-JsoncString $t $i; continue }
    if ($c -eq '/') { $n = Skip-JsoncComment $t $i; if ($n -ne $i) { $i = $n; continue } }
    if ($c -eq '{' -or $c -eq '[') { $depth++ }
    elseif ($c -eq '}' -or $c -eq ']') { $depth--; if ($depth -eq 0) { return $i } }
    $i++
  }
  return -1
}
function Get-JsoncRoot([string]$t) {
  $i = 0
  while ($i -lt $t.Length) {
    if ($t[$i] -eq '{') { return $i }
    if ($t[$i] -eq '/') { $n = Skip-JsoncComment $t $i; if ($n -ne $i) { $i = $n; continue } }
    $i++
  }
  return -1
}
function Find-JsoncKey([string]$t, [int]$open, [string]$key) {   # $key at the top level of the object at $open
  $end = Get-JsoncEnd $t $open
  $i = $open + 1
  while ($i -lt $end) {
    $c = $t[$i]
    if ($c -eq '"') {
      $s = $i
      $i = Skip-JsoncString $t $i
      $name = $t.Substring($s + 1, $i - $s - 2)
      $j = $i
      while ($j -lt $end -and [char]::IsWhiteSpace($t[$j])) { $j++ }
      if ($j -lt $end -and $t[$j] -eq ':') {
        $v = $j + 1
        while ($v -lt $end -and [char]::IsWhiteSpace($t[$v])) { $v++ }
        if ($name -eq $key) {
          if ($t[$v] -eq '"') { $e = Skip-JsoncString $t $v }
          elseif ($t[$v] -eq '{' -or $t[$v] -eq '[') { $e = (Get-JsoncEnd $t $v) + 1 }
          else { $e = $v; while ($e -lt $end -and ',}]/'.IndexOf($t[$e]) -lt 0 -and -not [char]::IsWhiteSpace($t[$e])) { $e++ } }
          return [pscustomobject]@{ KeyStart = $s; ValueStart = $v; ValueEnd = $e }
        }
        $i = $v
      }
      continue
    }
    if ($c -eq '/') { $n = Skip-JsoncComment $t $i; if ($n -ne $i) { $i = $n; continue } }
    if ($c -eq '{' -or $c -eq '[') { $i = (Get-JsoncEnd $t $i) + 1; continue }
    $i++
  }
  return $null
}
function Get-JsoncString([string]$t, $kv) { $t.Substring($kv.ValueStart, $kv.ValueEnd - $kv.ValueStart).Trim('"') }
function Get-JsoncObjects([string]$t, [int]$arrOpen) {   # the start index of each object element of the array at $arrOpen
  $end = Get-JsoncEnd $t $arrOpen
  $i = $arrOpen + 1; $out = @()
  while ($i -lt $end) {
    if ($t[$i] -eq '{') { $out += $i; $i = (Get-JsoncEnd $t $i) + 1; continue }
    if ($t[$i] -eq '/') { $n = Skip-JsoncComment $t $i; if ($n -ne $i) { $i = $n; continue } }
    $i++
  }
  return $out
}
function Add-JsoncRaw([string]$t, [int]$obj, [string]$key, [string]$raw) {   # new first key of the object at $obj
  $end = Get-JsoncEnd $t $obj
  $empty = $t.Substring($obj + 1, $end - $obj - 1).Trim() -eq ''
  return $t.Insert($obj + 1, ' "' + $key + '": ' + $raw + $(if ($empty) { ' ' } else { ',' }))
}
function Set-JsoncString([string]$t, [int]$obj, [string]$key, [string]$value) {
  $kv = Find-JsoncKey $t $obj $key
  $lit = '"' + $value + '"'
  if ($kv) { return $t.Substring(0, $kv.ValueStart) + $lit + $t.Substring($kv.ValueEnd) }
  return Add-JsoncRaw $t $obj $key $lit
}
function Test-JsoncEmpty([string]$t, [int]$obj) {   # true when the object at $obj has no key left (comments aside)
  $end = Get-JsoncEnd $t $obj
  $i = $obj + 1
  while ($i -lt $end) {
    if ($t[$i] -eq '"') { return $false }
    if ($t[$i] -eq '/') { $n = Skip-JsoncComment $t $i; if ($n -ne $i) { $i = $n; continue } }
    $i++
  }
  return $true
}
function Remove-JsoncKey([string]$t, [int]$obj, [string]$key) {
  $kv = Find-JsoncKey $t $obj $key
  if (-not $kv) { return $t }
  $a = $kv.KeyStart; $b = $kv.ValueEnd
  $j = $b
  while ($j -lt $t.Length -and [char]::IsWhiteSpace($t[$j])) { $j++ }
  if ($j -lt $t.Length -and $t[$j] -eq ',') {
    $j++
    while ($j -lt $t.Length -and [char]::IsWhiteSpace($t[$j])) { $j++ }
    return $t.Substring(0, $a) + $t.Substring($j)
  }
  $k = $a
  while ($k -gt 0 -and [char]::IsWhiteSpace($t[$k - 1])) { $k-- }
  if ($k -gt 0 -and $t[$k - 1] -eq ',') { $a = $k - 1 }   # last key: the comma before it goes with it
  return $t.Substring(0, $a) + $t.Substring($b)
}

# Where profiles.defaults and the default profile (the one whose guid is defaultProfile) start; -1 when absent.
function Get-WtLayout([string]$t) {
  $l = [pscustomobject]@{ Defaults = -1; Profile = -1 }
  $root = Get-JsoncRoot $t
  if ($root -lt 0) { return $l }
  $profiles = Find-JsoncKey $t $root 'profiles'
  if (-not $profiles -or $t[$profiles.ValueStart] -ne '{') { return $l }
  $d = Find-JsoncKey $t $profiles.ValueStart 'defaults'
  if ($d -and $t[$d.ValueStart] -eq '{') { $l.Defaults = $d.ValueStart }
  $dp = Find-JsoncKey $t $root 'defaultProfile'
  $list = Find-JsoncKey $t $profiles.ValueStart 'list'
  if ($dp -and $list -and $t[$list.ValueStart] -eq '[') {
    $guid = Get-JsoncString $t $dp
    foreach ($o in (Get-JsoncObjects $t $list.ValueStart)) {
      $g = Find-JsoncKey $t $o 'guid'
      if ($g -and (Get-JsoncString $t $g) -eq $guid) { $l.Profile = $o; break }
    }
  }
  return $l
}

# What the file says today: profiles.defaults font face, cellHeight and colorScheme, and the font face, cellHeight and
# colorScheme set on the default profile itself (each $null when not set).
function Read-TerminalLook([string]$path) {
  $t = [IO.File]::ReadAllText($path)
  $l = Get-WtLayout $t
  $r = [pscustomobject]@{ HasDefaults = ($l.Defaults -ge 0); Face = $null; CellHeight = $null; Scheme = $null; ProfileFace = $null; ProfileCellHeight = $null; ProfileScheme = $null }
  if ($l.Defaults -ge 0) {
    $f = Find-JsoncKey $t $l.Defaults 'font'
    if ($f -and $t[$f.ValueStart] -eq '{') {
      $x = Find-JsoncKey $t $f.ValueStart 'face'; if ($x) { $r.Face = Get-JsoncString $t $x }
      $x = Find-JsoncKey $t $f.ValueStart 'cellHeight'; if ($x) { $r.CellHeight = Get-JsoncString $t $x }
    }
    $x = Find-JsoncKey $t $l.Defaults 'colorScheme'; if ($x) { $r.Scheme = Get-JsoncString $t $x }
  }
  if ($l.Profile -ge 0) {
    $f = Find-JsoncKey $t $l.Profile 'font'
    if ($f -and $t[$f.ValueStart] -eq '{') {
      $x = Find-JsoncKey $t $f.ValueStart 'face'; if ($x) { $r.ProfileFace = Get-JsoncString $t $x }
      $x = Find-JsoncKey $t $f.ValueStart 'cellHeight'; if ($x) { $r.ProfileCellHeight = Get-JsoncString $t $x }
    }
    $x = Find-JsoncKey $t $l.Profile 'colorScheme'; if ($x) { $r.ProfileScheme = Get-JsoncString $t $x }
  }
  return $r
}

# Sets profiles.defaults.font to the repo's face and cellHeight (other font keys, such as size, stay) and drops face and
# cellHeight from the default profile's own font (it would outrank the default; the whole font goes when nothing else is
# left in it). Returns the result ('set', 'already set' or 'none': no defaults block) and what changed.
function Set-TerminalFont([string]$path, [string]$face, [string]$cellHeight) {
  $t = [IO.File]::ReadAllText($path)
  $l = Get-WtLayout $t
  if ($l.Defaults -lt 0) { return [pscustomobject]@{ Result = 'none'; Changed = @() } }
  $changed = @()
  $f = Find-JsoncKey $t $l.Defaults 'font'
  if (-not $f -or $t[$f.ValueStart] -ne '{') {
    $raw = '{ "face": "' + $face + '", "cellHeight": "' + $cellHeight + '" }'
    if ($f) { $t = $t.Substring(0, $f.ValueStart) + $raw + $t.Substring($f.ValueEnd) } else { $t = Add-JsoncRaw $t $l.Defaults 'font' $raw }
    $changed = @("face -> $face", "cellHeight -> $cellHeight")
  } else {
    foreach ($pair in @(@('face', $face), @('cellHeight', $cellHeight))) {
      $kv = Find-JsoncKey $t $f.ValueStart $pair[0]
      $old = if ($kv) { Get-JsoncString $t $kv } else { 'unset' }
      if ($old -ne $pair[1]) {
        $t = Set-JsoncString $t $f.ValueStart $pair[0] $pair[1]
        $changed += "$($pair[0]) $old -> $($pair[1])"
      }
    }
  }
  $l = Get-WtLayout $t   # an insert moved everything after it
  if ($l.Profile -ge 0) {
    $pf = Find-JsoncKey $t $l.Profile 'font'
    if ($pf -and $t[$pf.ValueStart] -eq '{') {
      foreach ($k in 'face', 'cellHeight') {
        $kv = Find-JsoncKey $t $pf.ValueStart $k
        if ($kv) {
          $changed += "removed font $k $(Get-JsoncString $t $kv) from the default profile"
          $t = Remove-JsoncKey $t $pf.ValueStart $k
          $pf = Find-JsoncKey $t (Get-WtLayout $t).Profile 'font'
        }
      }
      if ($pf -and (Test-JsoncEmpty $t $pf.ValueStart)) { $t = Remove-JsoncKey $t (Get-WtLayout $t).Profile 'font' }
    }
  }
  if ($changed.Count -gt 0) { Write-Utf8NoBom $path $t }
  return [pscustomobject]@{ Result = $(if ($changed.Count -gt 0) { 'set' } else { 'already set' }); Changed = $changed }
}

# Sets profiles.defaults.colorScheme and drops a colorScheme set on the default profile itself (it would outrank the
# default). Returns the result ('set', 'already set' or 'none') and what changed.
function Set-TerminalScheme([string]$path, [string]$scheme) {
  $t = [IO.File]::ReadAllText($path)
  $l = Get-WtLayout $t
  if ($l.Defaults -lt 0) { return [pscustomobject]@{ Result = 'none'; Changed = @() } }
  $changed = @()
  $x = Find-JsoncKey $t $l.Defaults 'colorScheme'
  $old = if ($x) { Get-JsoncString $t $x } else { 'unset' }
  if ($old -ne $scheme) {
    $t = Set-JsoncString $t $l.Defaults 'colorScheme' $scheme
    $changed += "colorScheme $old -> $scheme"
    $l = Get-WtLayout $t   # an insert moved everything after it
  }
  if ($l.Profile -ge 0) {
    $x = Find-JsoncKey $t $l.Profile 'colorScheme'
    if ($x) {
      $changed += "removed colorScheme $(Get-JsoncString $t $x) from the default profile"
      $t = Remove-JsoncKey $t $l.Profile 'colorScheme'
    }
  }
  if ($changed.Count -gt 0) { Write-Utf8NoBom $path $t }
  return [pscustomobject]@{ Result = $(if ($changed.Count -gt 0) { 'set' } else { 'already set' }); Changed = $changed }
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
  # Point Windows Terminal's default font at terminal/profile.json's (face and cellHeight) whenever it differs, but only
  # when this run installed the face or the machine has JetBrainsMono; -KeepFont keeps the machine's own.
  $haveFace = $weInstalled -or (@(Get-NerdFontFiles | Where-Object { $_.Name -like 'JetBrainsMono*' }).Count -gt 0)
  if ($KeepFont) {
    Write-Color '    -KeepFont: the Windows Terminal font stays as it is' 244
  } elseif ($haveFace) {
    foreach ($wt in $wtSettings) {
      Backup-TerminalSettings $wt
      $r = Set-TerminalFont $wt $nerdFontFace ([string]$terminalLook.font.cellHeight)
      $msg = switch ($r.Result) { 'set' { "font set in $wt ($($r.Changed -join ', '))" } 'already set' { "font already set in $wt" } default { "no defaults block in $wt; set the font by hand" } }
      Write-Host "    $msg"
    }
    if (@($wtSettings).Count -eq 0) { Write-Color '    Windows Terminal not found; set the terminal font to a Nerd Font by hand' 228 }
  }
}

# 4d2. Colour scheme. The status bar's and the session-cards mod's colours are the terminal's own 16, so every machine
# runs the scheme in terminal/profile.json (Campbell). A colorScheme set on the default profile itself would outrank
# the default, so it is removed. -KeepScheme keeps the machine's own.
Write-Step 'Terminal scheme'
if ($KeepScheme) {
  Write-Color '    -KeepScheme: the Windows Terminal colour scheme stays as it is' 244
} else {
  foreach ($wt in $wtSettings) {
    Backup-TerminalSettings $wt
    $r = Set-TerminalScheme $wt ([string]$terminalLook.colorScheme)
    $msg = switch ($r.Result) { 'set' { "scheme changed in $wt ($($r.Changed -join ', '))" } 'already set' { "scheme already set in $wt" } default { "no defaults block in $wt; set the scheme by hand" } }
    Write-Host "    $msg"
  }
  if (@($wtSettings).Count -eq 0) { Write-Color '    Windows Terminal not found; set the colour scheme to Campbell by hand' 228 }
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
# The session-cards mod loads through CLAUDE_CODE_PLUGIN_DIRS in the installed settings.json (the settings merge put
# <repo>/mods/session-cards there). Prove the variable names this clone's folder and that Claude Code accepts the folder.
Write-Step 'Session cards mod'
$modDir = ($repo -replace '\\', '/') + '/mods/session-cards'
$installed = Get-Content $settingsPath -Raw | ConvertFrom-Json
$pdEnv = if ($installed.PSObject.Properties['env'] -and $installed.env) { $installed.env.PSObject.Properties['CLAUDE_CODE_PLUGIN_DIRS'] } else { $null }
$modListed = $pdEnv -and (@(([string]$pdEnv.Value).Split(';') | ForEach-Object { Format-DirKey $_ }) -contains (Format-DirKey $modDir))
$claudeVersionText = (& claude --version 2>&1 | Out-String).Trim()
if (-not $modListed) {
  $failures += "session cards mod: ~/.claude/settings.json env.CLAUDE_CODE_PLUGIN_DIRS does not contain $modDir"
} else {
  $out = & claude plugin validate $modDir 2>&1
  if ($LASTEXITCODE -ne 0) { $failures += "session cards mod: claude plugin validate $modDir failed: $(($out | Out-String).Trim())" }
  else { Write-Host "    $claudeVersionText loads $modDir" }
}

# What shapes the screen, checked against what the repo asks for (terminal/profile.json, settings.json) and the
# minimum tool versions. A FAIL fails the install with the row named; -KeepFont / -KeepScheme (and -SkipFont for the
# font rows) turn the rows they cover into `kept`.
Write-Step 'Same experience'
$sameRows = @()
function Add-SameRow([string]$name, [string]$expected, [string]$actual, [bool]$ok, [bool]$kept = $false) {
  $status = if ($kept) { 'kept' } elseif ($ok) { 'ok' } else { 'FAIL' }
  $script:sameRows += [pscustomobject]@{ Name = $name; Expected = $expected; Actual = $actual; Status = $status }
}
$fontKept = [bool]($KeepFont -or $SkipFont)
$nerdFile = @(Get-NerdFontFiles | Where-Object { $_.Name -like 'JetBrainsMono*' } | Select-Object -First 1)
Add-SameRow 'Nerd Font file' 'JetBrainsMono*Nerd*Font*' $(if ($nerdFile.Count) { $nerdFile[0].Name } else { 'none' }) ($nerdFile.Count -gt 0) ([bool]$SkipFont)
$wtLook = if (@($wtSettings).Count -gt 0) { Read-TerminalLook @($wtSettings)[0] } else { $null }
$wantHeight = [string]$terminalLook.font.cellHeight
$wantScheme = [string]$terminalLook.colorScheme
$faceActual = if (-not $wtLook) { 'no Windows Terminal settings' } elseif ($wtLook.ProfileFace) { "$($wtLook.Face); default profile sets $($wtLook.ProfileFace)" } else { "$($wtLook.Face)" }
$heightActual = if (-not $wtLook) { 'no Windows Terminal settings' } elseif ($wtLook.ProfileCellHeight) { "$($wtLook.CellHeight); default profile sets $($wtLook.ProfileCellHeight)" } else { "$($wtLook.CellHeight)" }
Add-SameRow 'Terminal font face' "$nerdFontFace, none on the default profile" $faceActual ([bool]($wtLook -and $wtLook.Face -eq $nerdFontFace -and -not $wtLook.ProfileFace)) $fontKept
Add-SameRow 'Terminal cellHeight' "$wantHeight, none on the default profile" $heightActual ([bool]($wtLook -and $wtLook.CellHeight -eq $wantHeight -and -not $wtLook.ProfileCellHeight)) $fontKept
$schemeActual = if (-not $wtLook) { 'no Windows Terminal settings' } elseif ($wtLook.ProfileScheme) { "$($wtLook.Scheme); default profile sets $($wtLook.ProfileScheme)" } else { "$($wtLook.Scheme)" }
Add-SameRow 'Terminal colour scheme' "$wantScheme, none on the default profile" $schemeActual ([bool]($wtLook -and $wtLook.Scheme -eq $wantScheme -and -not $wtLook.ProfileScheme)) ([bool]$KeepScheme)
$themeProp = $installed.PSObject.Properties['theme']
$wantTheme = [string]$template.theme
Add-SameRow 'Claude Code theme' $wantTheme $(if ($themeProp) { [string]$themeProp.Value } else { 'unset' }) ([bool]($themeProp -and $themeProp.Value -eq $wantTheme))
$slInst = $installed.PSObject.Properties['statusLine']
$slCmd = if ($slInst -and $slInst.Value) { [string]$slInst.Value.command } else { '' }
Add-SameRow 'Status line command' 'ends with statusbar.py [--labels]' $(if ($slCmd) { $slCmd } else { 'unset' }) ($slCmd -match 'statusbar\.py( --labels)?$')
Add-SameRow 'Session cards mod' $modDir $(if ($modListed) { 'in CLAUDE_CODE_PLUGIN_DIRS' } else { 'not in CLAUDE_CODE_PLUGIN_DIRS' }) ([bool]$modListed)
$minClaude = [version]'2.1.308'
$haveClaude = [regex]::Match($claudeVersionText, '\d+\.\d+\.\d+').Value
Add-SameRow 'Claude Code version' ">= $minClaude" $(if ($haveClaude) { $haveClaude } else { 'unknown' }) ([bool]($haveClaude -and [version]$haveClaude -ge $minClaude))
$havePy = [regex]::Match((& python --version 2>&1 | Out-String), '\d+\.\d+(\.\d+)?').Value
Add-SameRow 'Python version' '>= 3.10' $(if ($havePy) { $havePy } else { 'unknown' }) ([bool]($havePy -and [version]$havePy -ge [version]'3.10'))
$gitBash = Get-GitBash
Add-SameRow 'Git Bash' 'bash.exe found' $(if (Test-Path $gitBash) { $gitBash } else { 'not found' }) (Test-Path $gitBash)
$wName = ($sameRows | ForEach-Object { $_.Name.Length } | Measure-Object -Maximum).Maximum
$wExp = ($sameRows | ForEach-Object { $_.Expected.Length } | Measure-Object -Maximum).Maximum
$wAct = ($sameRows | ForEach-Object { $_.Actual.Length } | Measure-Object -Maximum).Maximum
Write-Color ("    {0}  {1}  {2}  {3}" -f 'name'.PadRight($wName), 'expected'.PadRight($wExp), 'actual'.PadRight($wAct), 'ok') 244
foreach ($row in $sameRows) {
  $color = switch ($row.Status) { 'ok' { 223 } 'kept' { 228 } default { 203 } }
  Write-Color ("    {0}  {1}  {2}  {3}" -f $row.Name.PadRight($wName), $row.Expected.PadRight($wExp), $row.Actual.PadRight($wAct), $row.Status) $color
  if ($row.Status -eq 'FAIL') { $failures += "same experience: $($row.Name): expected $($row.Expected), got $($row.Actual)" }
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
