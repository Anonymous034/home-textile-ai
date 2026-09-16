$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $projectRoot ".runtime"

function Stop-RecordedProcess([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return }
  try {
    $record = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $process = Get-Process -Id ([int]$record.pid) -ErrorAction Stop
    if ($process.StartTime.ToUniversalTime().Ticks -eq [long]$record.startedUtcTicks) {
      & taskkill.exe /PID $process.Id /T /F | Out-Null
    }
  } catch { Write-Host "The recorded process is already stopped." -ForegroundColor DarkGray }
  Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
}

Stop-RecordedProcess (Join-Path $runtimeDir "frontend.pid.json")
Stop-RecordedProcess (Join-Path $runtimeDir "backend.pid.json")
Write-Host "Local website stopped." -ForegroundColor Green
