#Requires -Version 5.1
<#
.SYNOPSIS
  Applies this repo's Claude Code config to the current machine. Safe to re-run.

.DESCRIPTION
  1. Backs up ~/.claude/{CLAUDE.md,settings.json,statusline.py} to ~/.claude/backups/claude-setup-<stamp>/
  2. Copies CLAUDE.md, statusline.py and hooks/ into ~/.claude
  3. Merges settings.json keys into the existing file (machine-local keys survive)
  4. Installs + enables every plugin marked true in enabledPlugins, then updates them
  5. Self-tests the git guardrail hook and lists MCP health

.PARAMETER SkipPlugins
  Skip the plugin install/update step (faster when only config changed).
#>
[CmdletBinding()]
param([switch]$SkipPlugins)

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
foreach ($f in 'CLAUDE.md', 'settings.json', 'statusline.py') {
  $p = Join-Path $claudeDir $f
  if (Test-Path $p) { Copy-Item $p $backup }
}

# 2. Copy files
Write-Step 'Copying CLAUDE.md, statusline.py, hooks/'
New-Item -ItemType Directory -Force (Join-Path $claudeDir 'hooks') | Out-Null
Copy-Item (Join-Path $repo 'CLAUDE.md') $claudeDir -Force
Copy-Item (Join-Path $repo 'statusline.py') $claudeDir -Force
Copy-Item (Join-Path $repo 'hooks\*') (Join-Path $claudeDir 'hooks') -Force

# 3. Merge settings.json
Write-Step 'Merging settings.json'
$template = Get-Content (Join-Path $repo 'settings.json') -Raw | ConvertFrom-Json
$current = if (Test-Path $settingsPath) { Get-Content $settingsPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }

foreach ($prop in $template.PSObject.Properties) {
  $existing = $current.PSObject.Properties[$prop.Name]
  # enabledPlugins is merged per plugin so machine-local plugins stay; every other key is replaced wholesale.
  if ($prop.Name -eq 'enabledPlugins' -and $existing -and $existing.Value) {
    foreach ($plugin in $prop.Value.PSObject.Properties) {
      $existing.Value | Add-Member -NotePropertyName $plugin.Name -NotePropertyValue $plugin.Value -Force
    }
  } else {
    $current | Add-Member -NotePropertyName $prop.Name -NotePropertyValue $prop.Value -Force
  }
}
Write-Utf8NoBom $settingsPath (($current | ConvertTo-Json -Depth 20) + "`n")

# 4. Plugins
if (-not $SkipPlugins) {
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
}

# 5. Verify
Write-Step 'Self-testing git guardrail hook'
$hook = (Join-Path $claudeDir 'hooks\block-dangerous-git.sh') -replace '\\', '/'
# Built by concatenation so the live hook doesn't block this script when Claude runs it.
$dangerous = 'git pu' + 'sh origin main'
$blocked = ('{"tool_input":{"command":"' + $dangerous + '"}}') | & $gitBash $hook 2>&1
if ($LASTEXITCODE -ne 2) { $failures += "guardrail did not block '$dangerous' (exit $LASTEXITCODE)" }
$allowed = '{"tool_input":{"command":"git status"}}' | & $gitBash $hook 2>&1
if ($LASTEXITCODE -ne 0) { $failures += "guardrail blocked 'git status' (exit $LASTEXITCODE)" }

Write-Step 'Status line smoke test'
$sample = '{"model":{"display_name":"Test"},"workspace":{"current_dir":"' + ($HOME -replace '\\', '/') + '"},"cwd":"' + ($HOME -replace '\\', '/') + '","context_window":{"used_percentage":1}}'
$line = $sample | & python (Join-Path $claudeDir 'statusline.py') 2>&1
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
