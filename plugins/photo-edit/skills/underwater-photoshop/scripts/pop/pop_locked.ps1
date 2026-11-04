# Runs pop.jsx on one params file, queued on the machine-wide Photoshop mutex.
param([Parameter(Mandatory=$true)][string]$Params)
$jsx = Join-Path $PSScriptRoot "pop.jsx"
$m = New-Object System.Threading.Mutex($false, "Global\ClaudePhotoshop")
try { [void]$m.WaitOne() } catch [System.Threading.AbandonedMutexException] { }
try {
  $ps = New-Object -ComObject Photoshop.Application
  $ps.DoJavaScriptFile($jsx, @($Params)) | Out-Null
} finally { $m.ReleaseMutex(); $m.Dispose() }
Get-Content "$Params.log"
