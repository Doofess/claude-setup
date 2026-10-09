#Requires -Version 5.1
<#
.SYNOPSIS
  Applies this repo's Claude Code config to the current machine. Safe to re-run.

.DESCRIPTION
  1. Backs up ~/.claude/{CLAUDE.md,settings.json,statusline.py} to ~/.claude/backups/claude-setup-<stamp>/
  2. Copies CLAUDE.md, statusline.py, hooks/ and skills/ into ~/.claude
  3. Merges settings.json keys into the existing file (machine-local keys survive)
  4. Adds the marketplaces in extraKnownMarketplaces, installs + enables every plugin marked true in enabledPlugins,
     updates them, then disables every plugin marked false
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
