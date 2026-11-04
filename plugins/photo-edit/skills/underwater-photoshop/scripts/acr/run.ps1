# Renders a jobs file through Camera Raw. Usage: run.ps1 -Jobs C:\path\jobs.txt [-Psd]
#   jobs.txt lines: srcRaw|outJpg|maxEdge(0 = full)|quality      (-Psd: srcRaw|outPsd, Camera Raw Smart Object PSD)
# The <name>.xmp sidecar next to each ARW (make_xmp.py) is what Camera Raw applies. Log: <jobs>.log
param([Parameter(Mandatory=$true)][string]$Jobs, [switch]$Psd)
$jsx = Join-Path $PSScriptRoot ($(if ($Psd) { 'render_psd.jsx' } else { 'render.jsx' }))
$m = New-Object System.Threading.Mutex($false, "Global\ClaudePhotoshop")
try { [void]$m.WaitOne() } catch [System.Threading.AbandonedMutexException] { }
try {
  $ps = New-Object -ComObject Photoshop.Application
  $ps.DoJavaScriptFile($jsx, @((Resolve-Path $Jobs).Path)) | Out-Null
} finally { $m.ReleaseMutex(); $m.Dispose() }
Get-Content "$Jobs.log"
