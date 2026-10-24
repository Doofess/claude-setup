param([string]$Pattern = '', [switch]$Types)
# Resolves the running claude version, binary and claude-code.d.ts; -Pattern searches the binary (80 chars of context, 20 matches).
$ErrorActionPreference = 'Stop'
$claude = (Get-Command claude -ErrorAction Stop).Source
$version = (& $claude --version) -join ' '
$ver = if ($version -match '\d+\.\d+\.\d+') { $Matches[0] } else { '' }
"version: $version"
"binary:  $claude"
$bundle = Join-Path ([IO.Path]::GetTempPath()) 'claude\bundled-skills'
$d = $null
if (Test-Path $bundle) {
  $all = @(Get-ChildItem $bundle -Recurse -Filter 'claude-code.d.ts' -ErrorAction SilentlyContinue)
  $d = $all | Where-Object { $_.FullName -like "*\$ver\*" } | Select-Object -First 1
  if (-not $d) { $d = $all | Sort-Object LastWriteTime -Descending | Select-Object -First 1 }
}
if ($d) { "types:   $($d.FullName)" } else { 'types:   claude-code.d.ts not found' }
if ($Types -and $d) { Get-Content $d.FullName }
if ($Pattern) {
  $rg = Get-Command rg -ErrorAction SilentlyContinue
  if ($rg) {
    & $rg.Source -a -o ".{0,80}$Pattern.{0,80}" $claude | Select-Object -First 20
  } else {
    # No ripgrep: scan the binary as Latin-1 text with .NET regex.
    $text = [Text.Encoding]::GetEncoding(28591).GetString([IO.File]::ReadAllBytes($claude))
    $n = 0
    foreach ($m in [regex]::Matches($text, $Pattern)) {
      $from = [Math]::Max(0, $m.Index - 80); $len = [Math]::Min($text.Length - $from, $m.Length + 160)
      ($text.Substring($from, $len) -replace '[^ -~]', '.')
      if (++$n -ge 20) { break }
    }
  }
}
