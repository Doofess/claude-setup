param([Parameter(Mandatory)][string]$Out, [int]$Columns = 120, [int]$Rows = 30, [string]$Prompt = '',
      [string]$Worktree = '', [string]$Mode = 'bypassPermissions', [int]$Wait = 20, [switch]$Keep)
# Starts a demo claude.exe in its own Windows Terminal window, captures it with PrintWindow, kills only that claude.exe.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class LiveW {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public static IntPtr Find(string t) { IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => { var s = new StringBuilder(256); GetWindowText(h, s, 256); if (s.ToString() == t) { found = h; return false; } return true; }, IntPtr.Zero);
    return found; }
}
"@
# Strip the tool shell's session env, or the demo is colourless and warns about transcripts.
foreach ($v in 'NO_COLOR', 'CLAUDECODE', 'CLAUDE_PID') { Remove-Item "env:$v" -ErrorAction SilentlyContinue }
Get-ChildItem env: | Where-Object { $_.Name -like 'CLAUDE_CODE_*' } | ForEach-Object { Remove-Item "env:$($_.Name)" -ErrorAction SilentlyContinue }

$token = [guid]::NewGuid().ToString('N')
$title = "LIVECHK$($token.Substring(0, 8))"
$settings = Join-Path ([IO.Path]::GetTempPath()) "livecheck-$token.json"   # the token also marks the demo's command line
if ($Worktree) {
  $wt = (Resolve-Path $Worktree).Path.Replace([string][char]92, '/')
  $cfg = [ordered]@{
    statusLine = [ordered]@{ type = 'command'; command = "python -I -S $wt/statusbar.py"; refreshInterval = 60 }
    env        = [ordered]@{ CLAUDE_CODE_PLUGIN_DIRS = "$wt/mods/session-cards" }
  }
  $dir = (Resolve-Path $Worktree).Path
} else { $cfg = [ordered]@{}; $dir = (Get-Location).Path }
[IO.File]::WriteAllText($settings, ($cfg | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))

$wtArgs = @('-w', 'new', '--size', "$Columns,$Rows", '--title', $title, '--suppressApplicationTitle', '-d', $dir,
            'claude.exe', '--permission-mode', $Mode, '--settings', $settings)
if ($Prompt) { $wtArgs += $Prompt }
# One verbatim command line: Start-Process would join an array without quoting, and wt treats ';' as its own separator.
function ConvertTo-WtArg([string]$a) {
  $bs = [string][char]92; $q = [string][char]34
  $a = $a.Replace(';', $bs + ';')
  if ($a -ne '' -and $a -notmatch '[\s"]') { return $a }
  $a = [regex]::Replace($a, '(\\*)"', { param($m) ($bs * (2 * $m.Groups[1].Length)) + $bs + $q })
  $a = [regex]::Replace($a, '(\\+)$', { param($m) $bs * (2 * $m.Groups[1].Length) })
  return $q + $a + $q
}
Start-Process wt -ArgumentList (($wtArgs | ForEach-Object { ConvertTo-WtArg $_ }) -join ' ')
$h = [IntPtr]::Zero
for ($i = 0; $i -lt $Wait -and $h -eq [IntPtr]::Zero; $i++) { Start-Sleep -Seconds 1; $h = [LiveW]::Find($title) }
# Let the TUI draw, and outlive the fullscreen boot canary: a launch killed within 10 s of its first frame is a
# strike, and two strikes turn fullscreen off on this machine until /tui fullscreen or an update (2.1.310).
Start-Sleep -Seconds ([Math]::Max(15, [Math]::Min($Wait, 60)))

function Stop-Demo {
  # Only claude.exe processes whose command line carries this run's settings file name.
  Get-CimInstance Win32_Process -Filter "Name='claude.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains("livecheck-$token") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
try {
  if ($h -eq [IntPtr]::Zero) { Write-Output 'window not found'; exit 1 }
  [void][LiveW]::ShowWindow($h, 4)   # SW_SHOWNOACTIVATE
  $r = New-Object LiveW+RECT; [void][LiveW]::GetWindowRect($h, [ref]$r)
  $bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
  $g = [System.Drawing.Graphics]::FromImage($bmp); $dc = $g.GetHdc()
  [void][LiveW]::PrintWindow($h, $dc, 2); $g.ReleaseHdc($dc); $g.Dispose()
  $bmp.Save($Out); $bmp.Dispose()
  Write-Output "saved $Out $($r.R - $r.L)x$($r.B - $r.T)"
} finally {
  if (-not $Keep) {
    Stop-Demo
    Start-Sleep -Milliseconds 500
    if ($h -ne [IntPtr]::Zero) { [void][LiveW]::SendMessage($h, 0x10, [IntPtr]::Zero, [IntPtr]::Zero) }   # WM_CLOSE to the demo window only
    Remove-Item $settings -ErrorAction SilentlyContinue
  }
}
