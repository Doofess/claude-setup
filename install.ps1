#Requires -Version 5.1
<#
.SYNOPSIS
  Applies this repo's Claude Code config to the current machine. Safe to re-run.

.DESCRIPTION
  1. Backs up ~/.claude/{CLAUDE.md,settings.json,statusbar.py,statusline.py,keybindings.json} to ~/.claude/backups/claude-setup-<stamp>/
  2. Copies global/CLAUDE.md, statusbar.py, themes/, skills/ and agents/ into ~/.claude
  3. Merges settings.json keys into the existing file (machine-local keys survive)
  4. Adds the marketplaces in extraKnownMarketplaces, installs + enables every plugin marked true in enabledPlugins,
     updates them, then disables every plugin marked false
  5. Turns the claude.ai Adobe connector off in each known project once (see mcp_off.py; /mcp turns it back on)
  6. Removes the retired visual setup (custom theme, status line, readable-session mod, keybinding, Windows Terminal
     Readable scheme) from the machine
  7. Installs a Nerd Font through winget when the machine has none, and sets terminal/profile.json's font (face and
     cellHeight) as the Windows Terminal default font whenever it differs, and drops a font face or cellHeight set
     on any profile, so every profile looks the same
  8. Sets the Windows Terminal default colour scheme to terminal/profile.json's (Campbell) and drops a colorScheme
     set on any profile, so the default applies
  9. Sets the Windows Terminal start folder, adds a profile block that leaves System32 for C:\dev to both the PowerShell 7
     and the Windows PowerShell 5.1 profile, and sets the 5.1 execution policy to RemoteSigned for this user when it is
     stricter and no group policy pins it
 10. Installs PowerShell 7 through winget when `pwsh` is missing, makes it the Windows Terminal default profile (when
     its profile is there or PowerShell 7 is installed) and adds a Git Bash profile unless one, or Git for Windows'
     own Windows Terminal fragment, already exists
 11. Sets VS Code's integrated terminal (and VS Code Insiders' when installed) from terminal/vscode.json in the user
     settings.json: the Nerd Font, Campbell's colours and a minimum contrast ratio of 1; every other key stays
 12. Runs the status bar command from the installed settings.json on sample data and fails when its line is wrong
 13. Checks the session-cards mod is in CLAUDE_CODE_PLUGIN_DIRS and passes `claude plugin validate`
 14. Prints the `Same experience` table (font, colour scheme, Claude Code theme, status line, mod folder, tool
     versions) and fails when a row is FAIL
 15. Lists MCP health

.PARAMETER SkipPlugins
  Skip the plugin install/update step (faster when only config changed).

.PARAMETER SkipFont
  Do not install a Nerd Font or touch the Windows Terminal font (the font rows of the check read `kept`).

.PARAMETER KeepFont
  Keep the machine's own Windows Terminal and VS Code terminal font instead of terminal/profile.json's (its check rows read `kept`).

.PARAMETER KeepScheme
  Keep the machine's own Windows Terminal colour scheme and VS Code terminal colours instead of Campbell (its check row reads `kept`).

.PARAMETER Check
  Run only the checks (status bar, session cards mod, `Same experience`, MCP health): nothing is backed up, copied,
  merged or installed, and no file changes. Exits 1 when a check fails.

.PARAMETER Json
  With -Check, print one JSON document {rows: [{name, expected, actual, status}], failures: [...]} to stdout and
  nothing else.

#>
[CmdletBinding()]
param([switch]$SkipPlugins, [switch]$SkipFont, [switch]$KeepFont, [switch]$KeepScheme, [switch]$Check, [switch]$Json)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$claudeDir = Join-Path $HOME '.claude'
$settingsPath = Join-Path $claudeDir 'settings.json'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $claudeDir "backups\claude-setup-$stamp"
$failures = @()
$quiet = [bool]$Json   # -Json: stdout carries the JSON document only, so nothing else is written to the host

# Output colours come from the repo's two palettes, orange and grey (xterm-256 indices):
# 208 orange for steps, 223 peach for success, 228 yellow for warnings, 203 red for failures, 244 grey.
# The 16 Write-Host console colours have no orange, so these are ANSI escapes ([char]27: `e needs PS 6+).
function Write-Color($msg, [int]$color) { if ($quiet) { return }; Write-Host "$([char]27)[38;5;${color}m$msg$([char]27)[0m" }
function Write-Step($msg) { Write-Color "==> $msg" 208 }
# Windows PowerShell 5.1's Get-Content reads a BOM-less file in the ANSI code page (1252 on most PCs), which garbles
# any non-ASCII value in the JSON this script writes back, so every read names UTF-8.
function Read-Utf8($path) { [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) }
function Write-Utf8NoBom($path, $text) {
  [IO.File]::WriteAllText($path, $text, [Text.UTF8Encoding]::new($false))
}

function Set-StateRepo([string]$statePath, [string]$repoDir) {
  # Records the clone in the state file (the /setup-check skill reads it). Keeps every other key; writes only on change.
  $state = $null
  if (Test-Path $statePath) { $state = Read-Utf8 $statePath | ConvertFrom-Json }
  if ($null -eq $state) { $state = [pscustomobject]@{} }
  if ($state.PSObject.Properties['repo'] -and $state.repo -ceq $repoDir) { return }
  $state | Add-Member -NotePropertyName repo -NotePropertyValue $repoDir -Force
  Write-Utf8NoBom $statePath (($state | ConvertTo-Json -Depth 20) + "`n")
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
$terminalLook = Read-Utf8 (Join-Path $repo 'terminal\profile.json') | ConvertFrom-Json   # this PC's measured look
$nerdFontFace = $terminalLook.font.face
$template = Read-Utf8 (Join-Path $repo 'settings.json') | ConvertFrom-Json
function Get-NerdFontFiles {
  foreach ($d in "$env:LOCALAPPDATA\Microsoft\Windows\Fonts", "$env:WINDIR\Fonts") {
    Get-ChildItem $d -Filter '*Nerd*Font*' -ErrorAction SilentlyContinue
  }
}
# The font face may be a comma list (the later faces are Windows Terminal's glyph fallbacks); only the first is a font
# to look for or install. Windows Terminal's setting is compared with and written from the whole string.
function Get-PrimaryFace([string]$face) { ($face -split ',')[0].Trim() }
function Get-FaceFiles([string]$face) {
  $stem = (Get-PrimaryFace $face) -replace '\s*Nerd Font.*$', '' -replace '\s+', ''
  Get-NerdFontFiles | Where-Object { $_.Name -like "$stem*" }
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
  $empty = Test-JsoncEmpty $t $obj   # comments aside, so a comment-only object takes no comma
  return $t.Insert($obj + 1, ' "' + $key + '": ' + $raw + $(if ($empty) { ' ' } else { ',' }))
}
function Set-JsoncString([string]$t, [int]$obj, [string]$key, [string]$value) {
  $kv = Find-JsoncKey $t $obj $key
  $lit = '"' + $value + '"'
  if ($kv) { return $t.Substring(0, $kv.ValueStart) + $lit + $t.Substring($kv.ValueEnd) }
  return Add-JsoncRaw $t $obj $key $lit
}
function Set-JsoncRaw([string]$t, [int]$obj, [string]$key, [string]$raw) {   # $raw is JSON text: a number, true, an object ...
  $kv = Find-JsoncKey $t $obj $key
  if ($kv) { return $t.Substring(0, $kv.ValueStart) + $raw + $t.Substring($kv.ValueEnd) }
  return Add-JsoncRaw $t $obj $key $raw
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
  # Last key: the comma before it goes with it, however many comments sit between the two (the comments stay).
  # Found by scanning forward, since a line comment cannot be told from the text before it by looking back.
  $comma = -1; $i = $obj + 1
  while ($i -lt $a) {
    $c = $t[$i]
    if ($c -eq '"') { $i = Skip-JsoncString $t $i; $comma = -1; continue }
    if ($c -eq '/') { $n = Skip-JsoncComment $t $i; if ($n -ne $i) { $i = $n; continue } }
    if ($c -eq '{' -or $c -eq '[') { $i = (Get-JsoncEnd $t $i) + 1; $comma = -1; continue }
    if ($c -eq ',') { $comma = $i } elseif (-not [char]::IsWhiteSpace($c)) { $comma = -1 }
    $i++
  }
  if ($comma -ge 0) { return $t.Substring(0, $comma) + $t.Substring($comma + 1, $a - $comma - 1) + $t.Substring($b) }
  return $t.Substring(0, $a) + $t.Substring($b)
}

# Where profiles.defaults, the profiles.list array, the default profile (the one whose guid is defaultProfile) and every
# object in profiles.list start; -1 (Profiles: empty) when absent.
function Get-WtLayout([string]$t) {
  $l = [pscustomobject]@{ Defaults = -1; Profile = -1; List = -1; Profiles = @() }
  $root = Get-JsoncRoot $t
  if ($root -lt 0) { return $l }
  $profiles = Find-JsoncKey $t $root 'profiles'
  if (-not $profiles -or $t[$profiles.ValueStart] -ne '{') { return $l }
  $d = Find-JsoncKey $t $profiles.ValueStart 'defaults'
  if ($d -and $t[$d.ValueStart] -eq '{') { $l.Defaults = $d.ValueStart }
  $dp = Find-JsoncKey $t $root 'defaultProfile'
  $list = Find-JsoncKey $t $profiles.ValueStart 'list'
  if ($list -and $t[$list.ValueStart] -eq '[') {
    $l.List = $list.ValueStart
    $l.Profiles = @(Get-JsoncObjects $t $list.ValueStart)
    if ($dp) {
      $guid = Get-JsoncString $t $dp
      foreach ($o in $l.Profiles) {
        $g = Find-JsoncKey $t $o 'guid'
        if ($g -and (Get-JsoncString $t $g) -eq $guid) { $l.Profile = $o; break }
      }
    }
  }
  return $l
}

# A profile's name for messages: its name, else its guid, else its place in the list.
function Get-WtProfileName([string]$t, [int]$obj, [int]$n) {
  foreach ($k in 'name', 'guid') { $kv = Find-JsoncKey $t $obj $k; if ($kv) { return (Get-JsoncString $t $kv) } }
  return "profile $($n + 1)"
}

# What the file says today (DefaultGuid / DefaultName: the defaultProfile guid and the name of the list profile that has it, $null when none does): profiles.defaults font face, cellHeight and colorScheme, the font face, cellHeight and
# colorScheme set on the default profile itself (each $null when not set), and Overrides: one "<profile name>: <key>
# <value>" for every profile in the list (the default one included) that sets a face, cellHeight or colorScheme.
function Read-TerminalLook([string]$path) {
  $t = [IO.File]::ReadAllText($path)
  $l = Get-WtLayout $t
  $r = [pscustomobject]@{ HasDefaults = ($l.Defaults -ge 0); Face = $null; CellHeight = $null; Scheme = $null; ProfileFace = $null; ProfileCellHeight = $null; ProfileScheme = $null; Overrides = [string[]]@(); DefaultGuid = $null; DefaultName = $null }
  $over = @()
  for ($n = 0; $n -lt $l.Profiles.Count; $n++) {
    $o = $l.Profiles[$n]
    $name = Get-WtProfileName $t $o $n
    $f = Find-JsoncKey $t $o 'font'
    if ($f -and $t[$f.ValueStart] -eq '{') {
      foreach ($k in 'face', 'cellHeight') { $x = Find-JsoncKey $t $f.ValueStart $k; if ($x) { $over += "${name}: $k $(Get-JsoncString $t $x)" } }
    }
    $x = Find-JsoncKey $t $o 'colorScheme'; if ($x) { $over += "${name}: colorScheme $(Get-JsoncString $t $x)" }
  }
  $r.Overrides = [string[]]@($over)
  $dpRoot = Get-JsoncRoot $t
  $dpKey = if ($dpRoot -ge 0) { Find-JsoncKey $t $dpRoot 'defaultProfile' } else { $null }
  if ($dpKey) { $r.DefaultGuid = Get-JsoncString $t $dpKey }
  if ($l.Profile -ge 0) { $r.DefaultName = Get-WtProfileName $t $l.Profile 0 }
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
# cellHeight from the font of every profile in the list (each would outrank the default, so that profile would look
# different; the whole font goes when nothing else is left in it). Returns the result ('set', 'already set' or 'none':
# no defaults block) and what changed.
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
  $count = (Get-WtLayout $t).Profiles.Count
  for ($n = 0; $n -lt $count; $n++) {
    $l = Get-WtLayout $t   # every edit moved what follows it, so the positions are read again; the count stays
    $o = $l.Profiles[$n]
    $pf = Find-JsoncKey $t $o 'font'
    if (-not $pf -or $t[$pf.ValueStart] -ne '{') { continue }
    $label = (Get-WtProfileName $t $o $n) + $(if ($o -eq $l.Profile) { ' (default profile)' } else { '' })
    $removed = $false
    foreach ($k in 'face', 'cellHeight') {
      $kv = Find-JsoncKey $t $pf.ValueStart $k
      if ($kv) {
        $changed += "removed font $k $(Get-JsoncString $t $kv) from $label"
        $t = Remove-JsoncKey $t $pf.ValueStart $k   # only text after the font's opening brace moves
        $removed = $true
      }
    }
    if ($removed -and (Test-JsoncEmpty $t $pf.ValueStart)) { $t = Remove-JsoncKey $t $o 'font' }
  }
  if ($changed.Count -gt 0) { Write-Utf8NoBom $path $t }
  return [pscustomobject]@{ Result = $(if ($changed.Count -gt 0) { 'set' } else { 'already set' }); Changed = $changed }
}

# Sets profiles.defaults.colorScheme and drops a colorScheme set on any profile in the list (it would outrank the
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
  }
  $count = (Get-WtLayout $t).Profiles.Count
  for ($n = 0; $n -lt $count; $n++) {
    $l = Get-WtLayout $t   # every edit moved what follows it, so the positions are read again; the count stays
    $o = $l.Profiles[$n]
    $x = Find-JsoncKey $t $o 'colorScheme'
    if ($x) {
      $label = (Get-WtProfileName $t $o $n) + $(if ($o -eq $l.Profile) { ' (default profile)' } else { '' })
      $changed += "removed colorScheme $(Get-JsoncString $t $x) from $label"
      $t = Remove-JsoncKey $t $o 'colorScheme'
    }
  }
  if ($changed.Count -gt 0) { Write-Utf8NoBom $path $t }
  return [pscustomobject]@{ Result = $(if ($changed.Count -gt 0) { 'set' } else { 'already set' }); Changed = $changed }
}

# Windows Terminal's guid for PowerShell 7 (its generated profile always has this one) and Git for Windows' own fragment
# guid for Git Bash (installer.iss, InstallWindowsTerminalFragment), so a later Git fragment does not duplicate the profile.
$ps7Guid = '{574e775e-4f2a-5b96-ac1e-a2962a402336}'
$gitBashGuid = '{2ece5bfe-50ed-5f3a-ab87-5cd4baafed2b}'

# Makes $guid the profile Windows Terminal opens (defaultProfile at the top of the file). Returns 'set', 'already set' or
# 'missing': no profile in the list has that guid and PowerShell 7 is not installed (Windows Terminal generates its profile
# with $ps7Guid only once it is there), so nothing is written. With -DryRun the same word comes back and nothing is
# written; 'set' then means "would change".
function Set-TerminalDefaultProfile([string]$path, [string]$guid, [bool]$ps7Installed = $false, [switch]$DryRun) {
  $t = [IO.File]::ReadAllText($path)
  $root = Get-JsoncRoot $t
  if ($root -lt 0) { return 'missing' }
  $dp = Find-JsoncKey $t $root 'defaultProfile'
  if ($dp -and (Get-JsoncString $t $dp) -eq $guid) { return 'already set' }
  $known = $false
  foreach ($o in (Get-WtLayout $t).Profiles) {
    $g = Find-JsoncKey $t $o 'guid'
    if ($g -and (Get-JsoncString $t $g) -eq $guid) { $known = $true; break }
  }
  if (-not $known -and -not $ps7Installed) { return 'missing' }
  if (-not $DryRun) { Write-Utf8NoBom $path (Set-JsoncString $t $root 'defaultProfile' $guid) }
  return 'set'
}

function ConvertTo-JsonText([string]$s) { '"' + $s.Replace('\', '\\').Replace('"', '\"') + '"' }   # a JSON string literal

# The leading whitespace of the line that holds position $pos.
function Get-LineIndent([string]$t, [int]$pos) {
  $s = if ($pos -le 0) { 0 } else { $t.LastIndexOf([char]10, $pos - 1) + 1 }
  $e = $s
  while ($e -lt $t.Length -and ($t[$e] -eq ' ' -or $t[$e] -eq "`t")) { $e++ }
  return $t.Substring($s, $e - $s)
}

# Adds a Git Bash profile to profiles.list. Returns 'added', 'present' or 'none' (no profiles.list). It is present when a
# profile in the list has Git for Windows' fragment guid or is named Git Bash, or when a Git folder exists under one of
# $fragmentDirs (Git for Windows' own Windows Terminal fragment, which Windows Terminal turns into that profile). With
# -DryRun the same word comes back and nothing is written; 'added' then means "would add".
function Add-GitBashProfile([string]$path, [string]$bashExe, [string]$gitRoot,
    [string[]]$fragmentDirs = @("$env:ProgramData\Microsoft\Windows Terminal\Fragments", "$env:LOCALAPPDATA\Microsoft\Windows Terminal\Fragments"),
    [switch]$DryRun) {
  $t = [IO.File]::ReadAllText($path)
  $l = Get-WtLayout $t
  if ($l.List -lt 0) { return 'none' }
  foreach ($o in $l.Profiles) {
    $g = Find-JsoncKey $t $o 'guid'; $nm = Find-JsoncKey $t $o 'name'
    if (($g -and (Get-JsoncString $t $g) -eq $gitBashGuid) -or ($nm -and (Get-JsoncString $t $nm) -eq 'Git Bash')) { return 'present' }
  }
  foreach ($d in $fragmentDirs) { if ($d -and (Test-Path (Join-Path $d 'Git'))) { return 'present' } }
  if (-not $DryRun) {
    $raw = '{ "guid": "' + $gitBashGuid + '", "name": "Git Bash", "commandline": ' + (ConvertTo-JsonText ('"' + $bashExe + '" -i -l')) +
      ', "icon": ' + (ConvertTo-JsonText (Join-Path $gitRoot 'mingw64\share\git\git-for-windows.ico')) + ', "hidden": false }'
    $nl = if ($t.Contains("`r`n")) { "`r`n" } else { "`n" }
    $close = Get-JsoncEnd $t $l.List
    if ($l.Profiles.Count -eq 0) {
      $at = $l.List + 1
      $ins = $nl + (Get-LineIndent $t $l.List) + '    ' + $raw
      # the ] stays on its own line when it already is, else follows the object
      $t = $t.Insert($at, $ins + $(if ($t.Substring($at, $close - $at) -match '\n') { '' } else { $nl + (Get-LineIndent $t $l.List) }))
    } else {
      $last = $l.Profiles[$l.Profiles.Count - 1]
      $at = (Get-JsoncEnd $t $last) + 1
      $indent = Get-LineIndent $t $last
      # a comma already after the last element (a trailing one, comments aside) is reused: the new object goes after it
      $i = $at; $comma = -1
      while ($i -lt $close) {
        if ($t[$i] -eq ',') { $comma = $i; break }
        if ($t[$i] -eq '/') { $n = Skip-JsoncComment $t $i; if ($n -ne $i) { $i = $n; continue } }
        if (-not [char]::IsWhiteSpace($t[$i])) { break }
        $i++
      }
      if ($comma -ge 0) { $t = $t.Insert($comma + 1, $nl + $indent + $raw) }
      else { $t = $t.Insert($at, ',' + $nl + $indent + $raw) }
    }
    Write-Utf8NoBom $path $t
  }
  return 'added'
}

# $v as JSON text: strings quoted, numbers in invariant culture (1, not "1"; 1.25 with a point on every PC).
function ConvertTo-JsonValue($v) {
  if ($v -is [bool]) { return $(if ($v) { 'true' } else { 'false' }) }
  if ($v -is [string]) { return (ConvertTo-JsonText $v) }
  return ([IFormattable]$v).ToString($null, [Globalization.CultureInfo]::InvariantCulture)
}

# True when the value at $kv in $t means the same as $want: a string equal (a hex colour in any case), a number equal
# whatever its spelling (1 and 1.0), or a boolean.
function Test-JsoncValueIs([string]$t, $kv, $want) {
  $raw = $t.Substring($kv.ValueStart, $kv.ValueEnd - $kv.ValueStart).Trim()
  if ($want -is [string]) {
    if ($raw.Length -lt 2 -or $raw[0] -ne '"') { return $false }
    $have = [regex]::Unescape($raw.Substring(1, $raw.Length - 2))
    if ($want -match '^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$') { return $have -ieq $want }
    return $have -ceq $want
  }
  if ($want -is [bool]) { return $raw -ceq $(if ($want) { 'true' } else { 'false' }) }
  $d = 0.0
  if ([double]::TryParse($raw, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$d)) { return $d -eq [double]$want }
  return $false
}

# Sets the keys of terminal/vscode.json ($want, parsed) in VS Code's user settings.json, which is JSON with comments, so
# it is edited as text: the font family, the contrast ratio and, inside workbench.colorCustomizations, only the listed
# colours (the user's other colours and every other key stay). A value already there counts as set when it means the
# same. $keepFont skips the font family and $keepScheme the colours. A missing file is created as {} (folder included)
# when VS Code is $installed, else nothing is written ('no VS Code'). Returns the result ('set', 'already set' or
# 'no VS Code') and what changed. With -DryRun the same result comes back and nothing is written; 'set' then means
# "would change".
function Set-VsCodeTerminal([string]$path, $want, [bool]$installed, [bool]$keepFont, [bool]$keepScheme, [switch]$DryRun) {
  if (Test-Path -LiteralPath $path) {
    $t = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8)
    if (-not $t.Trim()) { $t = '{}' }
  } elseif ($installed) {
    $t = '{}'
  } else {
    return [pscustomobject]@{ Result = 'no VS Code'; Changed = [string[]]@() }
  }
  $root = Get-JsoncRoot $t
  if ($root -lt 0) { throw "$path is not a JSON object" }
  $changed = @()
  foreach ($prop in $want.PSObject.Properties) {
    $key = $prop.Name
    if ($key -eq 'workbench.colorCustomizations') { continue }
    if ($keepFont -and $key -eq 'terminal.integrated.fontFamily') { continue }
    $kv = Find-JsoncKey $t $root $key
    if ($kv -and (Test-JsoncValueIs $t $kv $prop.Value)) { continue }
    $t = Set-JsoncRaw $t $root $key (ConvertTo-JsonValue $prop.Value)
    $changed += $key
  }
  $colours = $want.PSObject.Properties['workbench.colorCustomizations']
  if ($colours -and -not $keepScheme) {
    $ck = 'workbench.colorCustomizations'
    $cc = Find-JsoncKey $t $root $ck
    if ($cc -and $t[$cc.ValueStart] -ne '{') {   # not an object (rare): replaced by one holding the wanted colours
      $t = $t.Substring(0, $cc.ValueStart) + '{}' + $t.Substring($cc.ValueEnd)
      $changed += "$ck replaced (it was not an object)"
    } elseif (-not $cc) {
      $t = Add-JsoncRaw $t $root $ck '{}'
    }
    $cc = Find-JsoncKey $t $root $ck   # the object's opening brace stays put while its keys change
    $n = 0
    foreach ($c in $colours.Value.PSObject.Properties) {
      $kv = Find-JsoncKey $t $cc.ValueStart $c.Name
      if ($kv -and (Test-JsoncValueIs $t $kv $c.Value)) { continue }
      $t = Set-JsoncRaw $t $cc.ValueStart $c.Name (ConvertTo-JsonValue $c.Value)
      $n++
    }
    if ($n -gt 0) { $changed += "$ck ($n colours)" }
  }
  if ($changed.Count -eq 0) { return [pscustomobject]@{ Result = 'already set'; Changed = [string[]]@() } }
  if (-not $DryRun) {
    New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
    Write-Utf8NoBom $path $t
  }
  return [pscustomobject]@{ Result = 'set'; Changed = [string[]]$changed }
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

# PowerShell 7 and Windows PowerShell 5.1 started from Start or the taskbar open in System32 (Windows Terminal's
# startingDirectory never applies there), and Claude Code started there loads the wrong project. Each of the two
# profiles gets one block between these markers; a re-run replaces it, and the rest of the profile is left alone.
$profileStart = '# >>> claude-setup'
$profileEnd = '# <<< claude-setup'
function Set-ProfileBlock([string]$text, [string]$body) {
  $block = "$profileStart`r`n$body`r`n$profileEnd"
  $pattern = [regex]::Escape($profileStart) + '[\s\S]*?' + [regex]::Escape($profileEnd)
  if ($text -match $pattern) { return [regex]::Replace($text, $pattern, { param($m) $block }) }
  if ($text -and -not $text.EndsWith("`n")) { $text += "`r`n" }
  return $text + $block + "`r`n"
}

# The two profile files that run in a terminal, both under the (possibly OneDrive-redirected) Documents folder:
# PowerShell 7 reads PowerShell\, Windows PowerShell 5.1 reads WindowsPowerShell\.
function Get-PowerShellProfiles {
  $docs = [Environment]::GetFolderPath('MyDocuments')
  [string[]]@(
    (Join-Path $docs 'PowerShell\Microsoft.PowerShell_profile.ps1'),
    (Join-Path $docs 'WindowsPowerShell\Microsoft.PowerShell_profile.ps1')
  )
}

# Windows PowerShell 5.1 ships with Restricted, which refuses the profile block and this script itself. Set-ExecutionPolicy
# from pwsh changes pwsh's own config, so the 5.1 per-user value is written in the registry. A group policy that pins a
# stricter value wins over it and is only reported ('pinned by MachinePolicy' / 'pinned by UserPolicy', nothing written);
# RemoteSigned, Unrestricted and Bypass are left alone. -DryRun returns the same word and writes nothing.
function Set-WindowsPowerShellPolicy(
  [string]$regPath = 'HKCU:\Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell',
  [string[]]$policyPaths = @('HKLM:\Software\Policies\Microsoft\Windows\PowerShell', 'HKCU:\Software\Policies\Microsoft\Windows\PowerShell'),
  [switch]$DryRun
) {
  function Get-PolicyValue([string]$path) {
    try {
      $item = Get-ItemProperty -Path $path -Name ExecutionPolicy -ErrorAction SilentlyContinue
      if ($item -and $item.ExecutionPolicy) { return [string]$item.ExecutionPolicy }
    } catch { }
    return ''
  }
  $loose = @('RemoteSigned', 'Unrestricted', 'Bypass')
  $scopes = @('MachinePolicy', 'UserPolicy')
  for ($i = 0; $i -lt $policyPaths.Count; $i++) {
    $pinned = Get-PolicyValue $policyPaths[$i]
    if (-not $pinned) { continue }
    if ($loose -contains $pinned) { return 'already set' }
    if (@('Restricted', 'AllSigned') -contains $pinned) { return "pinned by $($scopes[[Math]::Min($i, 1)])" }
  }
  if ($loose -contains (Get-PolicyValue $regPath)) { return 'already set' }
  if (-not $DryRun) {
    if (-not (Test-Path $regPath)) { New-Item -Path $regPath -Force | Out-Null }
    Set-ItemProperty -Path $regPath -Name ExecutionPolicy -Value 'RemoteSigned' -Type String
  }
  return 'set'
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

# The advisor is switched per project (skills/advisor-switch writes the project's .claude/settings.local.json). A
# user-level advisorModel, which /advisor writes, would turn it on in every session of every project, so it goes.
# Returns what it removed (nothing when the key was not there).
function Remove-UserAdvisor($current) {
  $p = $current.PSObject.Properties['advisorModel']
  if (-not $p) { return @() }
  $current.PSObject.Properties.Remove('advisorModel')
  return @("advisorModel $($p.Value)")
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
# The Git for Windows folder a bash.exe belongs to: bash.exe sits in <root>\bin (Get-GitBash's choice) or <root>\usr\bin.
function Get-GitRoot([string]$bashExe) {
  $dir = Split-Path $bashExe
  if ((Split-Path $dir -Leaf) -eq 'bin') {
    $dir = Split-Path $dir
    if ((Split-Path $dir -Leaf) -eq 'usr') { $dir = Split-Path $dir }
  }
  return $dir
}
# PowerShell 7 is installed when pwsh is on PATH or in its default folder (PATH changes made by a winget install in this
# very run are not in this process's PATH yet).
function Test-Pwsh {
  return [bool]((Get-Command pwsh -ErrorAction SilentlyContinue) -or (Test-Path "$env:ProgramFiles\PowerShell\7\pwsh.exe"))
}

# A VS Code edition is installed when its exe sits in the per-user folder (the user installer's default) or its command
# (`code`, `code-insiders`) is on PATH.
function Test-VsCode([string]$folder, [string]$exe, [string]$command) {
  return [bool]((Test-Path (Join-Path $env:LOCALAPPDATA "Programs\$folder\$exe")) -or (Get-Command $command -ErrorAction SilentlyContinue))
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
if (-not $Check) {
  # 1. Backup
  Write-Step "Backing up current config to $backup"
  New-Item -ItemType Directory -Force $backup | Out-Null
  foreach ($f in 'CLAUDE.md', 'settings.json', 'statusbar.py', 'statusline.py', 'keybindings.json') {
    $p = Join-Path $claudeDir $f
    if (Test-Path $p) { Copy-Item $p $backup }
  }

  # 2. Copy files
  Write-Step 'Copying CLAUDE.md, statusbar.py, themes/, skills/, agents/'
  Copy-Item (Join-Path $repo 'global\CLAUDE.md') $claudeDir -Force
  Copy-Item (Join-Path $repo 'statusbar.py') $claudeDir -Force
  # Themes: settings.json selects custom:clear, which Claude Code reads from ~/.claude/themes/clear.json.
  $themesDir = Join-Path $claudeDir 'themes'
  New-Item -ItemType Directory -Force $themesDir | Out-Null
  Copy-Item (Join-Path $repo 'themes\*.json') $themesDir -Force
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
  $current = if (Test-Path $settingsPath) { Read-Utf8 $settingsPath | ConvertFrom-Json } else { [pscustomobject]@{} }

  # Per-key rules (enabledPlugins, env, permissions, hooks merge; the rest is replaced) live in Merge-ClaudeSettings.
  $current = Merge-ClaudeSettings $current $template $repo
  $current = Remove-RetiredHooks $current $retiredHooks
  foreach ($d in @(Remove-UserAdvisor $current)) { Write-Host "    removed from settings.json: $d (the advisor is per project: advisor-switch skill)" }
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
      $out = & claude plugin install $name --scope user 2>&1
      if ($LASTEXITCODE -ne 0 -and ($out -join ' ') -notmatch 'already') { $failures += "install $name : $out" }
      & claude plugin enable $name --scope user 2>&1 | Out-Null
      $upd = & claude plugin update $name --scope user 2>&1
      $ver = ($upd | Out-String).Trim() -replace '\s+', ' '
      Write-Host "    $name  $ver"
    }
    # --scope user: auto-detect would write into a project's .claude/settings.json when run inside a repo that has one.
    # Enabling a plugin by name also flips on a same-named copy from another marketplace, so pin the false ones off afterwards.
    foreach ($plugin in $template.enabledPlugins.PSObject.Properties) {
      if ($plugin.Value -ne $false) { continue }
      & claude plugin disable $plugin.Name --scope user 2>&1 | Out-Null
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
  $cur = Read-Utf8 $settingsPath | ConvertFrom-Json
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
    $kb = Read-Utf8 $kbPath | ConvertFrom-Json
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
  Set-StateRepo (Join-Path $claudeDir 'claude-setup-state.json') $repo

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
      if ($weInstalled) { Write-Host "    installed $(Get-PrimaryFace $nerdFontFace)" } else { Write-Color "    winget could not install $nerdFontId; install a Nerd Font by hand (https://www.nerdfonts.com)" 228 }
    } else {
      Write-Color '    winget not found; install a Nerd Font by hand (https://www.nerdfonts.com)' 228
    }
    # Point Windows Terminal's default font at terminal/profile.json's (face and cellHeight) whenever it differs, but only
    # when this run installed the face or the machine has JetBrainsMono; -KeepFont keeps the machine's own.
    $haveFace = $weInstalled -or (@(Get-FaceFiles $nerdFontFace).Count -gt 0)
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

  # 4e. Start folder (independent of the font): Windows Terminal's default, the profile block in both the PowerShell 7
  # and the Windows PowerShell 5.1 profile, and RemoteSigned for 5.1 so that profile can load.
  Write-Step 'Terminal start folder'
  foreach ($wt in $wtSettings) {
    Backup-TerminalSettings $wt
    $r = Set-TerminalStartDir $wt 'C:\dev'
    $msg = switch ($r) { 'set' { "start folder set to C:\dev in $wt" } 'kept' { "a start folder is already set in $wt; left as is" } default { "no defaults block in $wt; set the start folder by hand" } }
    Write-Host "    $msg"
  }
  foreach ($profilePath in Get-PowerShellProfiles) {
    $exists = Test-Path $profilePath
    $old = if ($exists) { Read-Utf8 $profilePath } else { '' }
    # Read-Utf8 drops the BOM; keep it when the file had one. Windows PowerShell 5.1 reads a BOM-less .ps1 in the ANSI
    # code page, so its profile is always written with a BOM.
    $hadBom = $false
    if ($exists) { $head = [IO.File]::ReadAllBytes($profilePath); $hadBom = ($head.Length -ge 3 -and $head[0] -eq 0xEF -and $head[1] -eq 0xBB -and $head[2] -eq 0xBF) }
    if ($exists) { Copy-Item $profilePath (Join-Path $backup ((Split-Path (Split-Path $profilePath) -Leaf) + '.' + (Split-Path $profilePath -Leaf))) -Force }
    $new = Set-ProfileBlock $old 'if ((Get-Location).Path -eq "$env:SystemRoot\System32") { Set-Location C:\dev }'
    if ($new -ne $old) {
      New-Item -ItemType Directory -Force (Split-Path $profilePath) | Out-Null
      if ($hadBom -or (Split-Path (Split-Path $profilePath) -Leaf) -eq 'WindowsPowerShell') { [IO.File]::WriteAllText($profilePath, $new, [Text.UTF8Encoding]::new($true)) }
      else { Write-Utf8NoBom $profilePath $new }
    }
    $label = if ((Split-Path (Split-Path $profilePath) -Leaf) -eq 'WindowsPowerShell') { 'Windows PowerShell profile' } else { 'PowerShell 7 profile' }
    Write-Host "    ${label}: $profilePath"
  }
  $policyReg = 'HKCU:\Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell'
  $oldPolicy = [string](Get-ItemProperty -Path $policyReg -Name ExecutionPolicy -ErrorAction SilentlyContinue).ExecutionPolicy
  $r = Set-WindowsPowerShellPolicy
  if ($r -like 'pinned by *') { Write-Color "    Windows PowerShell execution policy is $r; scripts stay blocked until that policy changes" 228 }
  elseif ($r -eq 'set') { Write-Host "    Windows PowerShell execution policy set to RemoteSigned for this user (was: $(if ($oldPolicy) { $oldPolicy } else { 'not set' }))" }
  else { Write-Host '    Windows PowerShell execution policy is already RemoteSigned or looser' }

  # 4f. PowerShell 7 (winget; best effort, like the Nerd Font: a failure here warns and never fails the install), then
  # Windows Terminal opens it by default, and a Git Bash profile is added next to the others.
  Write-Step 'PowerShell 7'
  $ps7Installed = Test-Pwsh
  if ($ps7Installed) {
    Write-Color '    PowerShell 7 is already installed' 244
  } elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    $savedEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & winget install --id Microsoft.PowerShell -e --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    $ErrorActionPreference = $savedEap
    # winget put it on the PATH in the registry; this process still has the old one
    $env:Path = "$env:Path;" + [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $ps7Installed = Test-Pwsh
    if ($ps7Installed) { Write-Host '    installed PowerShell 7' } else { Write-Color '    winget could not install Microsoft.PowerShell; install PowerShell 7 by hand (https://aka.ms/powershell)' 228 }
  } else {
    Write-Color '    winget not found; install PowerShell 7 by hand (https://aka.ms/powershell)' 228
  }

  Write-Step 'Terminal profiles'
  $wtBash = Get-GitBash
  $haveGitBash = ($wtBash -ne 'bash') -and (Test-Path $wtBash)
  foreach ($wt in $wtSettings) {
    Backup-TerminalSettings $wt
    $r = Set-TerminalDefaultProfile $wt $ps7Guid $ps7Installed
    $msg = switch ($r) {
      'set' { "PowerShell 7 is now the default profile in $wt" }
      'already set' { "PowerShell 7 is already the default profile in $wt" }
      default { "PowerShell 7 is not installed and not in $wt; the default profile stays as it is" }
    }
    Write-Host "    $msg"
    if ($haveGitBash) {
      $r = Add-GitBashProfile $wt $wtBash (Get-GitRoot $wtBash)
      $msg = switch ($r) {
        'added' { "Git Bash profile added to $wt" }
        'present' { "a Git Bash profile is already in $wt" }
        default { "no profiles list in $wt; add Git Bash by hand" }
      }
      Write-Host "    $msg"
    }
  }
  if (@($wtSettings).Count -eq 0) { Write-Color '    Windows Terminal not found; set PowerShell 7 as the default profile and add Git Bash by hand' 228 }
  elseif (-not $haveGitBash) { Write-Color '    Git Bash not found; no Git Bash profile added' 228 }

  # 4g. VS Code's integrated terminal (stable, and Insiders when it is installed): the Nerd Font, Campbell's colours and a
  # contrast ratio of 1 from terminal/vscode.json, so it looks like Windows Terminal. -KeepFont / -SkipFont keep the font
  # and -KeepScheme the colours.
  Write-Step 'VS Code terminal'
  $vsWant = Read-Utf8 (Join-Path $repo 'terminal\vscode.json') | ConvertFrom-Json
  foreach ($vs in @(@('Code', 'Microsoft VS Code', 'Code.exe', 'code'), @('Code - Insiders', 'Microsoft VS Code Insiders', 'Code - Insiders.exe', 'code-insiders'))) {
    $vsInstalled = Test-VsCode $vs[1] $vs[2] $vs[3]
    if ($vs[0] -ne 'Code' -and -not $vsInstalled) { continue }
    $vsPath = Join-Path $env:APPDATA "$($vs[0])\User\settings.json"
    try {
      if (Test-Path $vsPath) { Copy-Item $vsPath (Join-Path $backup ('vscode-' + ($vs[0] -replace ' ', '') + '-settings.json')) -Force }
      $r = Set-VsCodeTerminal $vsPath $vsWant $vsInstalled ([bool]($KeepFont -or $SkipFont)) ([bool]$KeepScheme)
      $msg = switch ($r.Result) {
        'set' { "terminal settings changed in $vsPath ($($r.Changed -join ', '))" }
        'already set' { "terminal settings already set in $vsPath" }
        default { "$($vs[0]) is not installed and has no $vsPath; nothing written" }
      }
      Write-Host "    $msg"
    } catch {
      Write-Color "    could not update ${vsPath}: $($_.Exception.Message)" 228
    }
  }
}

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
  $installed = Read-Utf8 $settingsPath | ConvertFrom-Json
  $slProp = $installed.PSObject.Properties['statusLine']
  $barCommand = if ($slProp -and $slProp.Value) { [string]$slProp.Value.command } else { '' }
  if (-not $barCommand) {
    $failures += 'status bar: ~/.claude/settings.json has no statusLine.command'
  } else {
    $sample = (& python -I -S (Join-Path $repo 'statusbar.py') --demo-json) -join "`n"
    $bar = Test-StatusBar $barCommand $sample
    $rows = @($bar.Output -split "\r?\n" | Where-Object { $_ -ne '' })
    $missing = @('Opus', 'main', '42%', '$ ', '1.23', [string][char]0x2588 | Where-Object { -not $bar.Output.Contains($_) })
    if ($bar.Ok -and $rows.Count -eq 1 -and $missing.Count -eq 0) {
      if (-not $quiet) { foreach ($row in $rows) { Write-Host "    $row" } }
    } else {
      $failures += "status bar: '$barCommand' gave $($rows.Count) row(s) (exit ok: $($bar.Ok), missing: $($missing -join ' ')): $($rows -join ' / ')"
    }
  }
}
# The session-cards mod loads through CLAUDE_CODE_PLUGIN_DIRS in the installed settings.json (the settings merge put
# <repo>/mods/session-cards there). Prove the variable names this clone's folder and that Claude Code accepts the folder.
Write-Step 'Session cards mod'
$modDir = ($repo -replace '\\', '/') + '/mods/session-cards'
$installed = Read-Utf8 $settingsPath | ConvertFrom-Json
$pdEnv = if ($installed.PSObject.Properties['env'] -and $installed.env) { $installed.env.PSObject.Properties['CLAUDE_CODE_PLUGIN_DIRS'] } else { $null }
$modListed = $pdEnv -and (@(([string]$pdEnv.Value).Split(';') | ForEach-Object { Format-DirKey $_ }) -contains (Format-DirKey $modDir))
$claudeVersionText = (& claude --version 2>&1 | Out-String).Trim()
if (-not $modListed) {
  $failures += "session cards mod: ~/.claude/settings.json env.CLAUDE_CODE_PLUGIN_DIRS does not contain $modDir"
} else {
  $out = & claude plugin validate $modDir 2>&1
  if ($LASTEXITCODE -ne 0) { $failures += "session cards mod: claude plugin validate $modDir failed: $(($out | Out-String).Trim())" }
  elseif (-not $quiet) { Write-Host "    $claudeVersionText loads $modDir" }
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
$nerdFile = @(Get-FaceFiles $nerdFontFace | Select-Object -First 1)
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
# A custom theme (custom:<slug>) also needs its file, or Claude Code falls back to its default theme.
$themeFileOk = -not $wantTheme.StartsWith('custom:') -or (Test-Path (Join-Path $claudeDir "themes\$($wantTheme.Substring(7)).json"))
Add-SameRow 'Claude Code theme' $wantTheme $(if ($themeProp) { [string]$themeProp.Value } else { 'unset' }) ([bool]($themeProp -and $themeProp.Value -eq $wantTheme -and $themeFileOk))
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
$wtOverrides = if ($wtLook) { @($wtLook.Overrides) } else { @() }
Add-SameRow 'Terminal profile overrides' 'none' $(if (-not $wtLook) { 'no Windows Terminal settings' } elseif ($wtOverrides.Count) { $wtOverrides -join '; ' } else { 'none' }) ([bool]($wtLook -and $wtOverrides.Count -eq 0)) ([bool]($fontKept -and $KeepScheme))
$defActual = if (-not $wtLook) { 'no Windows Terminal settings' } elseif ($wtLook.DefaultName) { $wtLook.DefaultName } elseif ($wtLook.DefaultGuid) { $wtLook.DefaultGuid } else { 'not set' }
Add-SameRow 'Terminal default profile' 'PowerShell 7' $defActual ([bool]($wtLook -and $wtLook.DefaultGuid -eq $ps7Guid))
$gbActual = 'no Windows Terminal settings'
if ($wtLook) {
  $gbResult = Add-GitBashProfile @($wtSettings)[0] $gitBash $(if (Test-Path $gitBash) { Get-GitRoot $gitBash } else { '' }) -DryRun
  $gbActual = if ($gbResult -eq 'present') { 'present' } elseif ($gbResult -eq 'added') { 'missing' } else { 'no profiles list' }
}
Add-SameRow 'Git Bash profile' 'present' $gbActual ($gbActual -eq 'present')
$pwshCmd = Get-Command pwsh -ErrorAction SilentlyContinue | Select-Object -First 1
$pwshPath = if ($pwshCmd) { [string]$pwshCmd.Source } elseif (Test-Path "$env:ProgramFiles\PowerShell\7\pwsh.exe") { "$env:ProgramFiles\PowerShell\7\pwsh.exe" } else { '' }
Add-SameRow 'PowerShell 7' 'pwsh found' $(if ($pwshPath) { $pwshPath } else { 'not found' }) (Test-Pwsh)
$polReg = 'HKCU:\Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell'
$polNow = [string](Get-ItemProperty -Path $polReg -Name ExecutionPolicy -ErrorAction SilentlyContinue).ExecutionPolicy
$polResult = Set-WindowsPowerShellPolicy -DryRun
$polActual = if ($polResult -like 'pinned by *') { $polResult } elseif ($polResult -eq 'set') { $(if ($polNow) { $polNow } else { 'not set' }) } elseif ($polNow) { $polNow } else { 'pinned loose by policy' }
Add-SameRow 'Windows PowerShell policy' 'RemoteSigned or looser' $polActual ($polResult -eq 'already set')
$profMissing = @()
foreach ($pp in (Get-PowerShellProfiles)) {
  $hasBlock = $false
  if (Test-Path $pp) { $pt = Read-Utf8 $pp; $hasBlock = $pt.Contains($profileStart) -and $pt.Contains($profileEnd) }
  if (-not $hasBlock) { $profMissing += $pp }
}
Add-SameRow 'PowerShell profiles' 'block in both' $(if ($profMissing.Count) { 'missing in ' + ($profMissing -join '; ') } else { 'block in both' }) ($profMissing.Count -eq 0)
$vsRowWant = Read-Utf8 (Join-Path $repo 'terminal\vscode.json') | ConvertFrom-Json
$vsRowInstalled = Test-VsCode 'Microsoft VS Code' 'Code.exe' 'code'
$vsRowPath = Join-Path $env:APPDATA 'Code\User\settings.json'
$vsStatusKept = $false; $vsOk = $false
try {
  $vsRow = Set-VsCodeTerminal $vsRowPath $vsRowWant $vsRowInstalled $fontKept ([bool]$KeepScheme) -DryRun
  if ($vsRow.Result -eq 'no VS Code') { $vsActual = 'no VS Code'; $vsStatusKept = $true }
  elseif ($vsRow.Result -eq 'already set') { $vsActual = 'set'; $vsOk = $true }
  else { $vsActual = @($vsRow.Changed) -join '; ' }
} catch { $vsActual = $_.Exception.Message }
Add-SameRow 'VS Code terminal' 'set' $vsActual $vsOk $vsStatusKept
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

if ($Json) {
  $docRows = @($sameRows | ForEach-Object { [pscustomobject]@{ name = $_.Name; expected = $_.Expected; actual = $_.Actual; status = $_.Status } })
  $doc = [pscustomobject]@{ rows = $docRows; failures = @($failures) } | ConvertTo-Json -Depth 5 -Compress
  [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
  [Console]::Out.WriteLine($doc)
  if ($failures.Count -gt 0) { exit 1 }
  exit 0
}
Write-Host ''
if ($failures.Count -eq 0) {
  Write-Color 'DONE: all checks passed. Restart Claude Code to load the new config.' 223
} else {
  Write-Color 'DONE WITH FAILURES:' 203
  $failures | ForEach-Object { Write-Color "  - $_" 203 }
  exit 1
}
