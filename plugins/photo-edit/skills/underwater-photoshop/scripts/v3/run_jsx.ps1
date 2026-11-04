# Runs one JSX with one params file, queued on a machine-wide Photoshop mutex (one script at a time); prints the params log.
param([Parameter(Mandatory=$true)][string]$Jsx, [Parameter(Mandatory=$true)][string]$Params)
$m = New-Object System.Threading.Mutex($false, "Global\ClaudePhotoshop")
try { [void]$m.WaitOne() } catch [System.Threading.AbandonedMutexException] { }
try {
  $ps = New-Object -ComObject Photoshop.Application
  $ps.DoJavaScriptFile($Jsx, @($Params)) | Out-Null
} finally { $m.ReleaseMutex(); $m.Dispose() }
Get-Content "$Params.log"
