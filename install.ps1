#Requires -Version 5.1
<#
.SYNOPSIS
  Applies this repo's Claude Code config to the current machine. Safe to re-run.

.DESCRIPTION
  1. Backs up ~/.claude/{CLAUDE.md,settings.json,statusline.py,keybindings.json} to ~/.claude/backups/claude-setup-<stamp>/
  2. Copies CLAUDE.md, statusline.py, hooks/ and skills/ into ~/.claude
  3. Merges settings.json keys into the existing file (machine-local keys survive), and keybindings.json
     bindings into ~/.claude/keybindings.json per context (other contexts and keys survive)
  4. Adds the marketplaces in extraKnownMarketplaces, installs + enables every plugin marked true in enabledPlugins,
     updates them, then disables every plugin marked false
  5. Self-tests the git guardrail hook and lists MCP health

.PARAMETER SkipPlugins
  Skip the plugin install/update step (faster when only config changed).

.PARAMETER WindowsTerminal
  Optional, off by default. Adds the Ctrl+Alt+S -> ESC s (Alt+S) mapping the status line hint relies on to the
  Windows Terminal settings.json (Stable, Preview and unpackaged paths, whichever exist). The file is backed up
  first, edited by minimal text insertion so comments and layout survive, and validated before it is written.

.PARAMETER WindowsTerminalPath
  Use this settings.json instead of the default Windows Terminal locations (for testing against a copy).
  Only takes effect together with -WindowsTerminal.
#>
[CmdletBinding()]
param([switch]$SkipPlugins, [switch]$WindowsTerminal, [string]$WindowsTerminalPath)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$claudeDir = Join-Path $HOME '.claude'
$settingsPath = Join-Path $claudeDir 'settings.json'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $claudeDir "backups\claude-setup-$stamp"
$failures = @()

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
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

# ---- Windows Terminal settings.json (JSONC): minimal text insertion, never a re-serialise ----
# One pass over the text that understands strings and // and /* */ comments. Returns the text with comments
# blanked (same length, so offsets match), the top-level keys, and for each top-level array and the root object
# where it opens/closes and the offset of the last real character before the close.
function Read-JsoncMap([string]$text) {
  $n = $text.Length
  $clean = $text.ToCharArray()
  $stack = [System.Collections.Stack]::new()
  $arrays = @{}
  $keys = [System.Collections.ArrayList]::new()
  $root = $null; $curKey = $null; $lastSig = -1; $i = 0
  while ($i -lt $n) {
    $c = $text[$i]
    if ($c -eq [char]'"') {
      $start = $i; $i++
      while ($i -lt $n -and $text[$i] -ne [char]'"') { if ($text[$i] -eq [char]'\') { $i++ }; $i++ }
      if ($i -ge $n) { throw 'unterminated string' }
      if ($stack.Count -eq 1 -and $stack.Peek().Ch -eq [char]'{' -and $lastSig -ge 0 -and ($text[$lastSig] -eq [char]'{' -or $text[$lastSig] -eq [char]',')) {
        $curKey = $text.Substring($start + 1, $i - $start - 1)
        [void]$keys.Add($curKey)
      }
      $lastSig = $i; $i++; continue
    }
    if ($c -eq [char]'/' -and $i + 1 -lt $n -and $text[$i + 1] -eq [char]'/') {
      while ($i -lt $n -and $text[$i] -ne [char]"`n") { $clean[$i] = ' '; $i++ }
      continue
    }
    if ($c -eq [char]'/' -and $i + 1 -lt $n -and $text[$i + 1] -eq [char]'*') {
      $end = $text.IndexOf('*/', $i + 2)
      if ($end -lt 0) { throw 'unterminated comment' }
      for ($j = $i; $j -lt $end + 2; $j++) { if ($text[$j] -ne [char]"`n" -and $text[$j] -ne [char]"`r") { $clean[$j] = ' ' } }
      $i = $end + 2; continue
    }
    if ($c -eq [char]'{' -or $c -eq [char]'[') {
      $k = $null; if ($stack.Count -eq 1) { $k = $curKey }
      $stack.Push(@{ Ch = $c; Key = $k; Open = $i }); $lastSig = $i; $i++; continue
    }
    if ($c -eq [char]'}' -or $c -eq [char]']') {
      if ($stack.Count -eq 0) { throw 'unbalanced brackets' }
      $top = $stack.Pop()
      $info = @{ Open = $top.Open; Close = $i; LastSig = $lastSig }
      if ($stack.Count -eq 1 -and $c -eq [char]']' -and $top.Key) { $arrays[$top.Key] = $info }
      if ($stack.Count -eq 0) { $root = $info }
      $lastSig = $i; $i++; continue
    }
    if (-not [char]::IsWhiteSpace($c)) { $lastSig = $i }
    $i++
  }
  if ($stack.Count -ne 0 -or -not $root) { throw 'unbalanced brackets' }
  [pscustomobject]@{ Clean = (-join $clean); Keys = $keys.ToArray(); Arrays = $arrays; Root = $root }
}

# Parses blanked JSONC (trailing commas tolerated, as Windows Terminal does) into objects, for reading only.
function ConvertFrom-JsoncClean([string]$clean) {
  ($clean -replace ',(\s*[\]}])', '$1') | ConvertFrom-Json
}

# Inserts one pre-formatted item (multi-line text, no indentation) as the last element of top-level array $key,
# creating the array when the key is absent. Returns the new text.
function Add-JsoncArrayItem([string]$text, $map, [string]$key, [string]$item, [string]$nl) {
  $indentOf = {
    param($pos)
    $ls = $text.LastIndexOf("`n", [Math]::Max($pos - 1, 0)) + 1
    $pre = $text.Substring($ls, $pos - $ls)
    if ($pre.Trim() -eq '') { $pre } else { $null }
  }
  if ($map.Arrays.ContainsKey($key)) {
    $a = $map.Arrays[$key]
    $base = & $indentOf $a.Close; if ($null -eq $base) { $base = '    ' }
    $pad = $base + '    '
    $body = ($item -split "`r?`n" | ForEach-Object { $pad + $_ }) -join $nl
    if ($a.LastSig -eq $a.Open) {
      return $text.Insert($a.Open + 1, $nl + $body + $nl + $base)
    }
    $comma = if ($text[$a.LastSig] -eq [char]',') { '' } else { ',' }
    return $text.Insert($a.LastSig + 1, $comma + $nl + $body)
  }
  $r = $map.Root
  $pad = '    '
  $body = ($item -split "`r?`n" | ForEach-Object { $pad + '    ' + $_ }) -join $nl
  $block = $pad + '"' + $key + '": [' + $nl + $body + $nl + $pad + ']'
  $last = $text[$r.LastSig]
  $comma = if ($last -eq [char]',' -or $last -eq [char]'{') { '' } else { ',' }
  $tail = if ($last -eq [char]'{') { $nl } else { '' }
  return $text.Insert($r.LastSig + 1, $comma + $nl + $block + $tail)
}

# Adds the User.StatuslineToggle action and Ctrl+Alt+S binding to one Windows Terminal settings.json.
# Returns a status string. Throws (writing nothing) when the file cannot be edited safely.
function Add-StatuslineToggleToWt([string]$path, [string]$stamp) {
  $id = 'User.StatuslineToggle'
  $bytes = [IO.File]::ReadAllBytes($path)
  $bom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
  $skip = if ($bom) { 3 } else { 0 }
  $text = [Text.UTF8Encoding]::new($false).GetString($bytes, $skip, $bytes.Length - $skip)
  $nl = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }

  try {
    $map = Read-JsoncMap $text
    $doc = ConvertFrom-JsoncClean $map.Clean
  } catch { throw "cannot parse $path ($($_.Exception.Message)); edit it by hand, nothing was changed" }
  foreach ($k in 'actions', 'keybindings') {
    if ($map.Keys -contains $k -and -not $map.Arrays.ContainsKey($k)) { throw "'$k' in $path is not a plain array; nothing was changed" }
  }

  $actions = @($doc.actions | Where-Object { $_ })
  $binds = @($doc.keybindings | Where-Object { $_ })
  $haveAction = [bool]($actions | Where-Object { $_ -and $_.id -eq $id })
  # Older files key bindings by "command", newer ones by "id"; mirror whichever the file already uses.
  $refProp = if ($binds | Where-Object { $_ -and $_.PSObject.Properties['id'] }) { 'id' }
             elseif ($binds | Where-Object { $_ -and $_.PSObject.Properties['command'] }) { 'command' }
             else { 'id' }
  $haveBind = [bool]($binds | Where-Object { $_ -and ($_.id -eq $id -or $_.command -eq $id) }) -or
              [bool]($actions | Where-Object { $_ -and $_.id -eq $id -and $_.keys })
  $keyTaken = @(@($binds) + @($actions) | Where-Object { $_ -and $_.keys -and ([string]$_.keys).ToLowerInvariant() -eq 'ctrl+alt+s' -and $_.id -ne $id -and $_.command -ne $id })
  $notes = @()

  if ($haveAction -and $haveBind) { return 'already present, nothing to do' }

  $newText = $text
  if (-not $haveAction) {
    $item = '{' + "`n" + '    "command": { "action": "sendInput", "input": "\u001bs" },' + "`n" + '    "id": "' + $id + '"' + "`n" + '}'
    $newText = Add-JsoncArrayItem $newText $map 'actions' $item $nl
    $map = Read-JsoncMap $newText
  }
  $addBind = -not $haveBind
  if ($addBind -and $keyTaken.Count -gt 0) {
    $addBind = $false
    $notes += 'Ctrl+Alt+S is already bound to something else, so no keybinding was added (the action was)'
  }
  if ($addBind) {
    $item = '{' + "`n" + '    "' + $refProp + '": "' + $id + '",' + "`n" + '    "keys": "ctrl+alt+s"' + "`n" + '}'
    $newText = Add-JsoncArrayItem $newText $map 'keybindings' $item $nl
  }
  if ($newText -eq $text) { return ('nothing added; ' + ($notes -join '; ')) }

  # Validate the result before touching the file: it must parse, keep every old top-level key and entry, and
  # contain exactly one of our action / binding.
  try {
    $map2 = Read-JsoncMap $newText
    $doc2 = ConvertFrom-JsoncClean $map2.Clean
  } catch { throw "edit would produce invalid JSON ($($_.Exception.Message)); nothing was changed" }
  foreach ($k in $map.Keys) { if ($map2.Keys -notcontains $k) { throw "edit would lose key '$k'; nothing was changed" } }
  $n1 = @($doc2.actions | Where-Object { $_ -and $_.id -eq $id }).Count
  $n2 = @(@($doc2.keybindings) + @($doc2.actions) | Where-Object { $_ -and ($_.id -eq $id -or $_.command -eq $id) -and $_.keys }).Count
  if ($n1 -ne 1 -or $n2 -gt 1) { throw "edit would leave $n1 action(s) and $n2 binding(s) for $id; nothing was changed" }
  if (@($doc2.actions | Where-Object { $_ }).Count -lt $actions.Count -or @($doc2.keybindings | Where-Object { $_ }).Count -lt $binds.Count) { throw 'edit would drop entries; nothing was changed' }

  Copy-Item $path "$path.bak-claude-setup-$stamp"
  $out = [Text.UTF8Encoding]::new($false).GetBytes($newText)
  if ($bom) { $out = [byte[]](0xEF, 0xBB, 0xBF) + $out }
  [IO.File]::WriteAllBytes($path, $out)
  $msg = 'updated (backup: ' + (Split-Path "$path.bak-claude-setup-$stamp" -Leaf) + ')'
  if ($notes) { $msg += '; ' + ($notes -join '; ') }
  return $msg
}

foreach ($tool in 'claude', 'git', 'python') {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    throw "'$tool' not found on PATH. See README.md for the desktop bootstrap list."
  }
}
# 'bash' on PATH is often the WSL stub; Claude Code runs hooks through Git Bash, so test with that one.
$gitBash = Join-Path (Split-Path (Split-Path (Get-Command git).Source)) 'bin\bash.exe'
if (-not (Test-Path $gitBash)) { throw "Git Bash not found at $gitBash. Install Git for Windows." }

# 1. Backup
Write-Step "Backing up current config to $backup"
New-Item -ItemType Directory -Force $backup | Out-Null
foreach ($f in 'CLAUDE.md', 'settings.json', 'statusline.py', 'keybindings.json') {
  $p = Join-Path $claudeDir $f
  if (Test-Path $p) { Copy-Item $p $backup }
}

# 2. Copy files
Write-Step 'Copying CLAUDE.md, statusline.py, hooks/, skills/'
New-Item -ItemType Directory -Force (Join-Path $claudeDir 'hooks') | Out-Null
Copy-Item (Join-Path $repo 'CLAUDE.md') $claudeDir -Force
Copy-Item (Join-Path $repo 'statusline.py') $claudeDir -Force
Copy-Item (Join-Path $repo 'hooks\*') (Join-Path $claudeDir 'hooks') -Force
# Skills: each folder under skills/ becomes ~/.claude/skills/<name>. Copy keeps a skill's local .venv.
foreach ($skill in Get-ChildItem (Join-Path $repo 'skills') -Directory -ErrorAction SilentlyContinue) {
  $dest = Join-Path $claudeDir "skills\$($skill.Name)"
  New-Item -ItemType Directory -Force $dest | Out-Null
  Copy-Item (Join-Path $skill.FullName '*') $dest -Recurse -Force
}

# 3. Merge settings.json
Write-Step 'Merging settings.json'
$template = Get-Content (Join-Path $repo 'settings.json') -Raw | ConvertFrom-Json
$current = if (Test-Path $settingsPath) { Get-Content $settingsPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }

# Per-key rules (enabledPlugins, env, permissions, hooks merge; the rest is replaced) live in Merge-ClaudeSettings.
$current = Merge-ClaudeSettings $current $template $repo
Write-Utf8NoBom $settingsPath (($current | ConvertTo-Json -Depth 20) + "`n")

# 3b. Merge keybindings.json: each repo context block's keys win; the machine's other blocks and keys stay.
# Alt+S is the status line toggle (the readable-session mod's hidden Button on app:toggleDiffPreSession);
# Windows Terminal maps Ctrl+Alt+S to it (sendInput ESC s), since Claude Code can't bind a raw Ctrl+Alt chord.
Write-Step 'Merging keybindings.json'
$kbPath = Join-Path $claudeDir 'keybindings.json'
$kbTemplate = Get-Content (Join-Path $repo 'keybindings.json') -Raw | ConvertFrom-Json
$kbCurrent = if (Test-Path $kbPath) { Get-Content $kbPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
$blocks = [System.Collections.ArrayList]::new()
foreach ($b in @($kbCurrent.bindings)) { if ($b) { [void]$blocks.Add($b) } }
foreach ($tb in $kbTemplate.bindings) {
  $cb = $blocks | Where-Object { $_.context -eq $tb.context } | Select-Object -First 1
  if (-not $cb) { [void]$blocks.Add($tb); continue }
  foreach ($kb in $tb.bindings.PSObject.Properties) {
    $cb.bindings | Add-Member -NotePropertyName $kb.Name -NotePropertyValue $kb.Value -Force
  }
}
$kbMerged = [ordered]@{ '$schema' = $kbTemplate.'$schema'; '$docs' = $kbTemplate.'$docs'; bindings = $blocks.ToArray() }
foreach ($prop in $kbCurrent.PSObject.Properties) {
  if (-not $kbMerged.Contains($prop.Name)) { $kbMerged[$prop.Name] = $prop.Value }
}
Write-Utf8NoBom $kbPath (([pscustomobject]$kbMerged | ConvertTo-Json -Depth 10) + "`n")

# 3c. Optional: Windows Terminal mapping for Ctrl+Alt+S (the hint the status line shows). Off unless -WindowsTerminal.
if ($WindowsTerminal) {
  Write-Step 'Windows Terminal: Ctrl+Alt+S -> Alt+S'
  $wtPaths = if ($WindowsTerminalPath) { @($WindowsTerminalPath) } else {
    @((Join-Path $env:LOCALAPPDATA 'Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json'),
      (Join-Path $env:LOCALAPPDATA 'Packages\Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe\LocalState\settings.json'),
      (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows Terminal\settings.json'))
  }
  $wtFound = @($wtPaths | Where-Object { Test-Path -LiteralPath $_ })
  if ($wtFound.Count -eq 0) { Write-Host '    no Windows Terminal settings.json found, skipped' -ForegroundColor Yellow }
  foreach ($wt in $wtFound) {
    try { Write-Host "    $wt : $(Add-StatuslineToggleToWt $wt $stamp)" }
    catch { $failures += "windows terminal ($wt): $($_.Exception.Message)" }
  }
}

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
  Write-Step 'Installing and enabling plugins'
  foreach ($plugin in $template.enabledPlugins.PSObject.Properties) {
    if ($plugin.Value -ne $true) { continue }
    $name = $plugin.Name
    $out = & claude plugin install $name 2>&1
    if ($LASTEXITCODE -ne 0 -and ($out -join ' ') -notmatch 'already') { $failures += "install $name : $out" }
    & claude plugin enable $name 2>&1 | Out-Null
    & claude plugin update $name 2>&1 | Out-Null
    Write-Host "    $name"
  }
  # Enabling a plugin by name also flips on a same-named copy from another marketplace, so pin the false ones off afterwards.
  foreach ($plugin in $template.enabledPlugins.PSObject.Properties) {
    if ($plugin.Value -ne $false) { continue }
    & claude plugin disable $plugin.Name 2>&1 | Out-Null
  }
}
$ErrorActionPreference = $savedEap

# 4b. BigQuery MCP server (user scope lives in ~/.claude.json, which this repo doesn't copy).
# Auth comes from the Google Cloud CLI sign-in through hooks/bigquery-headers.py, so no OAuth client or secret.
Write-Step 'BigQuery MCP server'
$gcloud = Get-Command gcloud -ErrorAction SilentlyContinue
if (-not $gcloud) {
  foreach ($base in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    $candidate = Join-Path $base 'Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
    if ($base -and (Test-Path $candidate)) { $gcloud = $candidate; break }
  }
}
if ($gcloud) {
  $helper = (Join-Path $claudeDir 'hooks\bigquery-headers.py') -replace '\\', '/'
  # headersHelper gets no ~ expansion, so the path must be absolute, and quoted: a user folder with a
  # space ("Home Office") otherwise splits it. Python does the registration because Windows PowerShell 5.1
  # strips the quotes out of a JSON argument before a native command sees it (PowerShell 7 does not).
  $register = @'
import json, subprocess, sys
helper, claude = sys.argv[1], sys.argv[2]
cfg = {"type": "http", "url": "https://bigquery.googleapis.com/mcp", "headersHelper": 'python "%s"' % helper}
subprocess.run([claude, "mcp", "remove", "bigquery", "-s", "user"], capture_output=True, text=True)
r = subprocess.run([claude, "mcp", "add-json", "--scope", "user", "bigquery", json.dumps(cfg)], capture_output=True, text=True)
sys.stdout.write((r.stdout + r.stderr).strip())
sys.exit(r.returncode)
'@
  $ErrorActionPreference = 'Continue'
  $out = $register | & python - $helper (Get-Command claude).Source 2>&1
  $ErrorActionPreference = $savedEap
  if ($LASTEXITCODE -ne 0) { $failures += "bigquery registration: $out" } else { Write-Host '    registered' }
  if (-not (Test-Path (Join-Path $env:APPDATA 'gcloud\application_default_credentials.json'))) {
    Write-Host '    not signed in yet: run  gcloud config set project bookandry; gcloud auth login --update-adc' -ForegroundColor Yellow
  }
} else {
  Write-Host '    skipped: Google Cloud CLI not installed (winget install Google.CloudSDK), see README' -ForegroundColor Yellow
}

# 5. Verify
Write-Step 'Self-testing git guardrail hook'
$ErrorActionPreference = 'Continue'   # the hook writes BLOCKED to stderr on purpose
$hook = (Join-Path $claudeDir 'hooks\block-dangerous-git.sh') -replace '\\', '/'
# Built by concatenation so the live hook doesn't block this script when Claude runs it.
$dangerous = 'git pu' + 'sh origin main'
$blocked = ('{"tool_input":{"command":"' + $dangerous + '"}}') | & $gitBash $hook 2>&1
if ($LASTEXITCODE -ne 2) { $failures += "guardrail did not block '$dangerous' (exit $LASTEXITCODE)" }
$allowed = '{"tool_input":{"command":"git status"}}' | & $gitBash $hook 2>&1
if ($LASTEXITCODE -ne 0) { $failures += "guardrail blocked 'git status' (exit $LASTEXITCODE)" }

Write-Step 'Status line smoke test'
$sample = '{"model":{"display_name":"Test"},"workspace":{"current_dir":"' + ($HOME -replace '\\', '/') + '"},"cwd":"' + ($HOME -replace '\\', '/') + '","context_window":{"used_percentage":1}}'
$line = $sample | & python -S (Join-Path $claudeDir 'statusline.py') 2>&1
if ($LASTEXITCODE -ne 0 -or -not $line) { $failures += "statusline.py failed: $line" }

Write-Step 'MCP health'
& claude mcp list 2>&1 | Where-Object { $_ -match 'Needs authentication|Failed|error' } | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }

Write-Host ''
if ($failures.Count -eq 0) {
  Write-Host 'DONE: all checks passed. Restart Claude Code to load the new config.' -ForegroundColor Green
} else {
  Write-Host 'DONE WITH FAILURES:' -ForegroundColor Red
  $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
  exit 1
}
