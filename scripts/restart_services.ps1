<#
.SYNOPSIS
Kills every Pratidhvani runtime (backend, Celery, frontend) and
starts them again. Verifies Redis (which runs as a Windows service).

.DESCRIPTION
One-stop restart for the four services that make up the app:
  1. Redis                 -- Windows service, just checked + started if stopped
  2. Backend (uvicorn)     -- killed by PID on port 8000, relaunched detached
  3. Celery worker         -- killed by matching "celery" in its command line
  4. Frontend (vite dev)   -- killed by PID on port 5173, relaunched detached

This is also the script invoked by POST /api/v1/admin/restart. Because
the backend process calls this script and will be killed by it, we run
the whole thing detached (fire-and-forget) with a brief initial pause so
the HTTP handler has time to return its 202 before we kill the parent.

.PARAMETER SkipFrontend
Skip restarting the frontend dev server. Useful when you only changed
backend code and don't want to blow away your browser session.

.PARAMETER KillOnly
Kill the four services but don't start them again. Handy when debugging.

.PARAMETER Delay
Seconds to sleep before the kill phase begins. Defaults to 0 for CLI use;
the backend endpoint passes 2 so its HTTP response can fly first.

.EXAMPLE
# Full restart:
.\scripts\restart_services.ps1

.EXAMPLE
# Backend + Celery only, leave frontend alone:
.\scripts\restart_services.ps1 -SkipFrontend
#>

param(
    [switch]$SkipFrontend = $false,
    [switch]$KillOnly = $false,
    [int]$Delay = 0
)

$ErrorActionPreference = 'Continue'

$repoRoot = Split-Path $PSScriptRoot -Parent
$backendDir = Join-Path $repoRoot 'backend'
$frontendDir = Join-Path $repoRoot 'frontend'
$venvPython = Join-Path $backendDir 'venv\Scripts\python.exe'
$venvCelery = Join-Path $backendDir 'venv\Scripts\celery.exe'

# When spawned detached by the backend (no console attached), Write-Host
# output goes nowhere. Mirror every step to a rotating log so we can debug
# self-restart issues after the fact.
$logFile = Join-Path $repoRoot 'restart_services.log'

function Write-Step {
    param([string]$msg)
    $ts = (Get-Date).ToString('HH:mm:ss.fff')
    $line = "[restart $ts] $msg"
    Write-Host $line
    try {
        Add-Content -Path $logFile -Value $line -ErrorAction SilentlyContinue
    } catch { }
}

Write-Step "script invoked; args: SkipFrontend=$SkipFrontend KillOnly=$KillOnly Delay=$Delay"

if ($Delay -gt 0) {
    Write-Step "Sleeping $Delay seconds before kill phase..."
    Start-Sleep -Seconds $Delay
}

# ---- 1. Kill backend (port 8000) ----
Write-Step "Stopping backend on :8000..."
try {
    $conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop
    foreach ($c in $conn) {
        if ($c.OwningProcess -gt 0) {
            Write-Step "  killing PID $($c.OwningProcess)"
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
} catch {
    Write-Step "  nothing listening on :8000"
}

# ---- 2. Kill Celery workers (python.exe with "celery" in cmdline) ----
Write-Step "Stopping Celery workers..."
$celeryProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -like '*celery*' }
foreach ($p in $celeryProcs) {
    Write-Step "  killing Celery PID $($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
# Also catch helper subprocesses left over from --pool=solo
$celeryExe = Get-CimInstance Win32_Process -Filter "Name='celery.exe'" -ErrorAction SilentlyContinue
foreach ($p in $celeryExe) {
    Write-Step "  killing celery.exe PID $($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

# ---- 3. Kill frontend dev server (port 5173) ----
if (-not $SkipFrontend) {
    Write-Step "Stopping frontend on :5173..."
    try {
        $conn = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction Stop
        foreach ($c in $conn) {
            if ($c.OwningProcess -gt 0) {
                Write-Step "  killing PID $($c.OwningProcess)"
                # node (vite) often spawns helper children; kill the whole tree.
                Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {
        Write-Step "  nothing listening on :5173"
    }
}

if ($KillOnly) {
    Write-Step "KillOnly flag set - stopping here."
    return
}

# ---- 4. Ensure Redis is running (installed as a Windows service) ----
Write-Step "Checking Redis service..."
$redis = Get-Service -Name Redis -ErrorAction SilentlyContinue
if (-not $redis) {
    Write-Step "  WARNING: Redis service not installed. Run: winget install Redis.Redis"
} elseif ($redis.Status -ne 'Running') {
    Write-Step "  Redis is $($redis.Status); starting..."
    Start-Service -Name Redis -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
} else {
    Write-Step "  Redis already running"
}

# Detached processes have no attached console, so their stdout/stderr would
# otherwise vanish. Redirect each service to its own log file in the repo
# root so post-mortem debugging is possible. Hidden dotfiles keep them out
# of directory listings and git (see .gitignore).
#
# NOTE: Start-Process refuses -RedirectStandardOutput and -RedirectStandardError
# pointing at the same file (even though cmd/bash are perfectly happy with
# `>file 2>&1`). So every service gets separate .out.log and .err.log files.
$backendOut  = Join-Path $repoRoot '.uvicorn.out.log'
$backendErr  = Join-Path $repoRoot '.uvicorn.err.log'
$celeryOut   = Join-Path $repoRoot '.celery.out.log'
$celeryErr   = Join-Path $repoRoot '.celery.err.log'
$frontendOut = Join-Path $repoRoot '.frontend.out.log'
$frontendErr = Join-Path $repoRoot '.frontend.err.log'

# backend/.env is authoritative for this app's secrets. pydantic-settings
# gives real OS environment variables precedence over .env, so a
# machine-level key set for some other tool silently shadows the project's
# key (bit us twice: GOOGLE_API_KEY and OPENAI_API_KEY — D-054 amendment).
# Clear any inherited var that .env defines so children resolve from the file.
$dotenvPath = Join-Path $repoRoot 'backend\.env'
if (Test-Path $dotenvPath) {
    Select-String -Path $dotenvPath -Pattern '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=' |
        ForEach-Object { $_.Matches[0].Groups[1].Value } |
        ForEach-Object {
            if (Test-Path "Env:$_") {
                Write-Step "  clearing inherited env var $_ (shadowed by backend/.env)"
                Remove-Item "Env:$_"
            }
        }
}

# ---- 5. Start backend detached ----
Write-Step "Starting backend (uvicorn :8000) -> $backendOut / $backendErr"
if (-not (Test-Path $venvPython)) {
    Write-Step "  ERROR: venv python not found at $venvPython"
} else {
    Start-Process -FilePath $venvPython `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendOut `
        -RedirectStandardError $backendErr
}

# ---- 6. Start Celery worker detached ----
# T-5.6.5: per-tier task queues. The dispatcher routes user-initiated
# work to tier_free / tier_pro / tier_studio; only system-initiated
# tasks land on `default`. Self-host workers consume all four queues
# or jobs stay queued forever (see PR #185 for the same fix in
# scripts/start.ps1; if the queue list drifts in one, drift it in both).
Write-Step "Starting Celery worker (-Q all-tier-queues) -> $celeryOut / $celeryErr"
if (-not (Test-Path $venvCelery)) {
    Write-Step "  ERROR: celery not found at $venvCelery"
} else {
    Start-Process -FilePath $venvCelery `
        -ArgumentList @('-A', 'app.tasks.celery_app', 'worker', '--loglevel=info', '--pool=solo', '-Q', 'default,tier_free,tier_pro,tier_studio') `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $celeryOut `
        -RedirectStandardError $celeryErr
}

# ---- 7. Start frontend dev server detached ----
if (-not $SkipFrontend) {
    Write-Step "Starting frontend (vite :5173) -> $frontendOut / $frontendErr"
    # Use cmd /c so npm's .cmd shim resolves correctly regardless of the
    # PowerShell execution policy.
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList @('/c', 'npm', 'run', 'dev') `
        -WorkingDirectory $frontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendOut `
        -RedirectStandardError $frontendErr
}

Write-Step "Done. Backend should be healthy within ~10s."
