<#
.SYNOPSIS
Foreground launcher: starts Redis (if needed), backend (uvicorn),
Celery worker, frontend (vite), opens the browser, then blocks until
Ctrl+C — at which point it tears everything down.

.DESCRIPTION
One-command dev loop:

  1. Verify Redis Windows service is running (start it if stopped).
  2. Start uvicorn on 127.0.0.1:8000 (detached, logs to .uvicorn.out.log
     + .uvicorn.err.log at repo root).
  3. Start Celery worker (--pool=solo per Windows convention).
  4. Poll /api/v1/health until the backend is responsive.
  5. Start `npm run dev` (Vite) on 5173.
  6. Poll port 5173 until the dev server accepts connections.
  7. Open the default browser to http://localhost:5173.
  8. Block until Ctrl+C. On exit (including Ctrl+C), kill the whole
     subprocess tree of each service so nothing leaks.

Logs land at the repo root as hidden dotfiles (matches the
restart_services.ps1 convention; already covered by .gitignore via the
generic `*.log` rule). Tail them in another terminal if you want
streaming output:

    Get-Content .\.uvicorn.out.log -Tail 20 -Wait

.PARAMETER NoBrowser
Skip the browser auto-open. Useful for headless dev sessions or when
you already have the page open.

.PARAMETER NoFrontend
Skip starting Vite. Useful when you only want backend + Celery (e.g.
testing the API directly).

.PARAMETER HealthTimeoutSec
How long to wait for /api/v1/health before giving up. Default 120.
Cold boots (first start after a reboot / AV cache flush) take 45-90 s
just to import torch + transformers; warm boots pass in ~10-15 s. The
wait loop returns the moment health responds, so the generous default
costs nothing on warm starts.

.EXAMPLE
.\scripts\start.ps1
# Starts everything, opens browser, blocks until Ctrl+C.

.EXAMPLE
.\scripts\start.ps1 -NoBrowser
# Same, but don't auto-open the browser.

.EXAMPLE
.\scripts\start.ps1 -NoFrontend
# Backend + Celery only.
#>

param(
    [switch]$NoBrowser = $false,
    [switch]$NoFrontend = $false,
    [int]$HealthTimeoutSec = 120
)

$ErrorActionPreference = 'Stop'

$repoRoot    = Split-Path $PSScriptRoot -Parent
$backendDir  = Join-Path $repoRoot 'backend'
$frontendDir = Join-Path $repoRoot 'frontend'
$venvPython  = Join-Path $backendDir 'venv\Scripts\python.exe'
$venvCelery  = Join-Path $backendDir 'venv\Scripts\celery.exe'

$backendOut  = Join-Path $repoRoot '.uvicorn.out.log'
$backendErr  = Join-Path $repoRoot '.uvicorn.err.log'
$celeryOut   = Join-Path $repoRoot '.celery.out.log'
$celeryErr   = Join-Path $repoRoot '.celery.err.log'
$frontendOut = Join-Path $repoRoot '.frontend.out.log'
$frontendErr = Join-Path $repoRoot '.frontend.err.log'

# Track every Process object we spawn so the finally block can kill them.
$script:children = New-Object System.Collections.Generic.List[object]

function Write-Step {
    param([string]$msg, [string]$color = 'Cyan')
    $ts = (Get-Date).ToString('HH:mm:ss')
    Write-Host "[$ts] $msg" -ForegroundColor $color
}

function Stop-Tree {
    param([System.Diagnostics.Process]$proc, [string]$label)
    if (-not $proc) { return }
    if ($proc.HasExited) {
        Write-Step "  $label (PID $($proc.Id)) already exited" 'DarkGray'
        return
    }
    Write-Step "  killing $label tree (PID $($proc.Id))" 'Yellow'
    # taskkill /T walks the child-process tree; /F forces. uvicorn / npm /
    # celery all spawn helper children that Stop-Process alone misses.
    & taskkill.exe /F /T /PID $proc.Id 2>$null | Out-Null
}

function Wait-Http200 {
    param([string]$url, [int]$timeoutSec)
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { return $true }
        } catch {
            # Service not up yet — fall through to the sleep.
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Wait-PortOpen {
    param([int]$port, [int]$timeoutSec)
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($conn) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

try {
    Write-Step "Pratidhvani launcher starting..." 'Green'

    # ---- 0. Sanity checks ----
    if (-not (Test-Path $venvPython)) {
        throw "Backend venv python not found at $venvPython. Run 'python -m venv venv' in backend/ and 'pip install -r requirements.txt'."
    }
    if (-not (Test-Path $venvCelery)) {
        throw "Celery not found at $venvCelery. Run 'pip install -r requirements.txt' in the venv."
    }
    if (-not $NoFrontend -and -not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
        Write-Step "frontend/node_modules missing -- running 'npm install' first" 'Yellow'
        Push-Location $frontendDir
        try {
            & cmd.exe /c 'npm install' 2>&1 | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit $LASTEXITCODE)" }
        } finally {
            Pop-Location
        }
    }

    # ---- 1. Redis ----
    Write-Step "Checking Redis service..."
    $redis = Get-Service -Name Redis -ErrorAction SilentlyContinue
    if (-not $redis) {
        throw "Redis service not installed. Run: winget install Redis.Redis"
    } elseif ($redis.Status -ne 'Running') {
        Write-Step "  Redis is $($redis.Status); starting..."
        Start-Service -Name Redis
        Start-Sleep -Milliseconds 500
    } else {
        Write-Step "  Redis already running" 'DarkGray'
    }

    # Free :8000 if a previous run left uvicorn behind (otherwise the new
    # one silently fails to bind and the health check hangs).
    $stale = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($stale) {
        Write-Step "Port 8000 already in use; killing the holder..." 'Yellow'
        foreach ($c in $stale) {
            if ($c.OwningProcess -gt 0) {
                Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
        Start-Sleep -Milliseconds 500
    }

    # backend/.env is authoritative for this app's secrets. pydantic-settings
    # gives real OS environment variables precedence over .env, so a
    # machine-level key set for some other tool silently shadows the
    # project's key (bit us twice: GOOGLE_API_KEY and OPENAI_API_KEY —
    # D-054 amendment). Clear any inherited var that .env defines so the
    # children resolve from the file.
    $dotenvPath = Join-Path $backendDir '.env'
    if (Test-Path $dotenvPath) {
        Select-String -Path $dotenvPath -Pattern '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=' |
            ForEach-Object { $_.Matches[0].Groups[1].Value } |
            ForEach-Object {
                if (Test-Path "Env:$_") {
                    Write-Step "  clearing inherited env var $_ (shadowed by backend/.env)" 'Yellow'
                    Remove-Item "Env:$_"
                }
            }
    }

    # ---- 2. Backend (uvicorn) ----
    Write-Step "Starting backend (uvicorn :8000)..."
    $backend = Start-Process -FilePath $venvPython `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendOut `
        -RedirectStandardError $backendErr `
        -PassThru
    $script:children.Add($backend)

    # ---- 3. Celery worker ----
    # T-5.6.5: per-tier task queues. The dispatcher routes user-initiated
    # work to tier_free / tier_pro / tier_studio based on the user's tier;
    # only system-initiated tasks land on `default`. The self-host worker
    # must consume all four queues or jobs stay queued forever (this is the
    # default failure mode — celery_task_id is set, status stays `pending`,
    # progress sits at 0%).
    Write-Step "Starting Celery worker (--pool=solo, -Q all-tier-queues)..."
    $celery = Start-Process -FilePath $venvCelery `
        -ArgumentList @('-A', 'app.tasks.celery_app', 'worker', '--loglevel=info', '--pool=solo', '-Q', 'default,tier_free,tier_pro,tier_studio') `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $celeryOut `
        -RedirectStandardError $celeryErr `
        -PassThru
    $script:children.Add($celery)

    # ---- 4. Wait for backend health ----
    Write-Step "Waiting for backend /api/v1/health (up to $HealthTimeoutSec s)..."
    if (-not (Wait-Http200 -url 'http://127.0.0.1:8000/api/v1/health' -timeoutSec $HealthTimeoutSec)) {
        throw "Backend did not become healthy within $HealthTimeoutSec s. See $backendErr for details."
    }
    Write-Step "  backend is up" 'Green'

    # ---- 5. Frontend ----
    if (-not $NoFrontend) {
        # Free :5173 if needed.
        $stale = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
        if ($stale) {
            Write-Step "Port 5173 already in use; killing the holder..." 'Yellow'
            foreach ($c in $stale) {
                if ($c.OwningProcess -gt 0) {
                    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
                }
            }
            Start-Sleep -Milliseconds 500
        }

        Write-Step "Starting frontend (vite :5173)..."
        # cmd /c so npm's .cmd shim resolves regardless of execution policy.
        $frontend = Start-Process -FilePath 'cmd.exe' `
            -ArgumentList @('/c', 'npm', 'run', 'dev') `
            -WorkingDirectory $frontendDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $frontendOut `
            -RedirectStandardError $frontendErr `
            -PassThru
        $script:children.Add($frontend)

        Write-Step "Waiting for Vite to bind :5173..."
        if (-not (Wait-PortOpen -port 5173 -timeoutSec 30)) {
            throw "Vite did not bind :5173 within 30 s. See $frontendErr for details."
        }
        Write-Step "  frontend is up" 'Green'
    }

    # ---- 6. Open browser ----
    if (-not $NoBrowser -and -not $NoFrontend) {
        Write-Step "Opening browser to http://localhost:5173..."
        Start-Process 'http://localhost:5173' | Out-Null
    }

    # ---- 7. Block until Ctrl+C ----
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "  Pratidhvani is running:" -ForegroundColor Green
    Write-Host "    backend  http://127.0.0.1:8000  (logs: .uvicorn.*.log)" -ForegroundColor Gray
    Write-Host "    celery   --pool=solo            (logs: .celery.*.log)"  -ForegroundColor Gray
    if (-not $NoFrontend) {
        Write-Host "    frontend http://localhost:5173  (logs: .frontend.*.log)" -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "  Press Ctrl+C to shut everything down." -ForegroundColor Yellow
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host ""

    # Sleep-loop pattern: Ctrl+C interrupts Start-Sleep, exception bubbles
    # into the finally block, which kills every child tree. Also detects
    # if any child dies on its own and bails out early.
    while ($true) {
        Start-Sleep -Seconds 2
        foreach ($p in $script:children) {
            if ($p.HasExited) {
                $label = switch ($p.Id) {
                    $backend.Id  { 'backend'  }
                    $celery.Id   { 'celery'   }
                    default      { if (-not $NoFrontend -and $p.Id -eq $frontend.Id) { 'frontend' } else { 'service' } }
                }
                Write-Step "$label exited unexpectedly (exit $($p.ExitCode)). See the matching .err.log for details." 'Red'
                Write-Step "Shutting everything down..." 'Yellow'
                return
            }
        }
    }
}
finally {
    Write-Host ""
    Write-Step "Cleanup: stopping all child processes..." 'Yellow'
    # Reverse order so frontend dies before backend before celery — minor
    # nicety so users don't see a Vite proxy error during shutdown.
    $reversed = New-Object System.Collections.Generic.List[object]
    for ($i = $script:children.Count - 1; $i -ge 0; $i--) {
        $reversed.Add($script:children[$i])
    }
    foreach ($p in $reversed) {
        $label = switch ($p.Id) {
            { $backend  -and $_ -eq $backend.Id  } { 'backend'  }
            { $celery   -and $_ -eq $celery.Id   } { 'celery'   }
            { $frontend -and $_ -eq $frontend.Id } { 'frontend' }
            default                                { 'service'  }
        }
        Stop-Tree -proc $p -label $label
    }
    Write-Step "Done. Logs preserved at .uvicorn.*, .celery.*, .frontend.* in $repoRoot." 'Green'
}
