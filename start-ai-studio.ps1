param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

# Some Windows environments expose a proxy as `host:port`, while Wrangler's
# Node runtime requires a URL. Clear that malformed value for this local
# process so the build and local server can start without a proxy parse error.
foreach ($proxyName in @("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")) {
  $proxyValue = [Environment]::GetEnvironmentVariable($proxyName)
  if ($proxyValue -and $proxyValue -notmatch "://") {
    Set-Item -Path ("Env:{0}" -f $proxyName) -Value ""
  }
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $projectRoot ".runtime"
$backendPython = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
$bundledNode = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
$bundledPnpm = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd"
$backendPidFile = Join-Path $runtimeDir "backend.pid.json"
$frontendPidFile = Join-Path $runtimeDir "frontend.pid.json"
$backendOut = Join-Path $runtimeDir "backend.out.log"
$backendErr = Join-Path $runtimeDir "backend.err.log"
$frontendOut = Join-Path $runtimeDir "frontend.out.log"
$frontendErr = Join-Path $runtimeDir "frontend.err.log"

function Test-Http([string]$Url) {
  try { return (Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3).StatusCode -eq 200 }
  catch { return $false }
}

function Test-Port([int]$Port) {
  $client = [System.Net.Sockets.TcpClient]::new()
  try { return $client.ConnectAsync("127.0.0.1", $Port).Wait(400) -and $client.Connected }
  catch { return $false }
  finally { $client.Dispose() }
}

function Save-ProcessRecord([System.Diagnostics.Process]$Process, [string]$Path) {
  @{ pid = $Process.Id; startedUtcTicks = $Process.StartTime.ToUniversalTime().Ticks } |
    ConvertTo-Json | Set-Content -LiteralPath $Path -Encoding utf8
}

function Get-RecordedProcess([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  try {
    $record = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    $process = Get-Process -Id ([int]$record.pid) -ErrorAction Stop
    if ($process.StartTime.ToUniversalTime().Ticks -ne [long]$record.startedUtcTicks) { return $null }
    return $process
  } catch { return $null }
}

function Stop-RecordedProcess([string]$Path) {
  $process = Get-RecordedProcess $Path
  if ($null -ne $process) { & taskkill.exe /PID $process.Id /T /F | Out-Null }
  Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
}

function Wait-ForHttp([string]$Url, [int]$Seconds) {
  $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
  while ([DateTime]::UtcNow -lt $deadline) {
    if (Test-Http $Url) { return $true }
    Start-Sleep -Milliseconds 400
  }
  return $false
}

try {
  New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
  if (-not (Test-Path -LiteralPath $backendPython)) { throw "Backend Python environment is missing: backend\.venv" }
  if (Test-Path -LiteralPath $bundledNode) { $env:Path = "$bundledNode;$env:Path" }
  $pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
  $pnpm = if ($pnpmCommand) { $pnpmCommand.Source } elseif (Test-Path -LiteralPath $bundledPnpm) { $bundledPnpm } else { $null }
  if (-not $pnpm) { throw "pnpm was not found; the frontend cannot start." }

  if (-not (Test-Http "http://127.0.0.1:8000/api/health/live")) {
    if ($null -ne (Get-RecordedProcess $backendPidFile)) { Stop-RecordedProcess $backendPidFile; Start-Sleep -Milliseconds 500 }
    if (Test-Port 8000) { throw "Port 8000 is occupied by another program." }
    Set-Content -LiteralPath $backendOut -Value "" -Encoding utf8
    Set-Content -LiteralPath $backendErr -Value "" -Encoding utf8
    $backend = Start-Process -FilePath $backendPython -ArgumentList @("-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -PassThru
    Save-ProcessRecord $backend $backendPidFile
    if (-not (Wait-ForHttp "http://127.0.0.1:8000/api/health/live" 20)) {
      Stop-RecordedProcess $backendPidFile
      throw "Backend startup failed. See .runtime\backend.err.log."
    }
  }

  Write-Host "Checking AI connectivity without creating a generation task..." -ForegroundColor Cyan
  $aiReady = $false
  try {
    $connectivity = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/replicate/connectivity?refresh=true" -TimeoutSec 30
    $aiReady = [bool]$connectivity.connected
    if (-not $aiReady) {
      Write-Warning "AI is offline ($($connectivity.error_code)): $($connectivity.message) The backend will retry automatically."
    }
  } catch {
    Write-Warning "AI connectivity check could not complete. The backend will retry automatically: $($_.Exception.Message)"
  }
  $backendReady = Test-Http "http://127.0.0.1:8000/api/health/ready"
  if (-not $backendReady) {
    Write-Warning "One or more AI image clients are not ready yet. The website will start and the backend will keep checking."
  }
  $aiReady = $aiReady -and $backendReady
  try {
    $aiConnections = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/ai/connections" -TimeoutSec 5
    if (-not $aiConnections.template_plan.connected) {
      Write-Warning "Visual planning AI is not ready: $($aiConnections.template_plan.message)"
      $aiReady = $false
    }
  } catch {
    Write-Warning "Visual planning AI status is unavailable; the backend will keep checking."
    $aiReady = $false
  }

  if (-not (Test-Http "http://127.0.0.1:3000/")) {
    if ($null -ne (Get-RecordedProcess $frontendPidFile)) { Stop-RecordedProcess $frontendPidFile; Start-Sleep -Milliseconds 500 }
    if (Test-Port 3000) { throw "Port 3000 is occupied by another program." }
    Write-Host "Building frontend..." -ForegroundColor Cyan
    # This launcher is only for local development; keep the demo hint off in normal server builds.
    if (-not $env:NEXT_PUBLIC_DEMO_LOGIN_ENABLED) { $env:NEXT_PUBLIC_DEMO_LOGIN_ENABLED = "1" }
    & $pnpm build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    Set-Content -LiteralPath $frontendOut -Value "" -Encoding utf8
    Set-Content -LiteralPath $frontendErr -Value "" -Encoding utf8
    $env:PORT = "3000"
    $frontend = Start-Process -FilePath $pnpm -ArgumentList @("start") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -PassThru
    Save-ProcessRecord $frontend $frontendPidFile
    if (-not (Wait-ForHttp "http://127.0.0.1:3000/" 30)) {
      Stop-RecordedProcess $frontendPidFile
      throw "Frontend startup failed. See .runtime\frontend.err.log."
    }
  }

  if ($aiReady) {
    Write-Host "Local website and AI service are ready." -ForegroundColor Green
  } else {
    Write-Host "Local website is ready. AI connectivity will be retried by the backend." -ForegroundColor Yellow
  }
  if (-not $NoBrowser) { Start-Process "http://127.0.0.1:3000" }
} catch {
  Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
  Read-Host "Press Enter to close"
  exit 1
}
