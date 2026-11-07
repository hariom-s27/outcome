# Fresh-clone check (PR-63, PR-73, P4-04). Run by Hariom from the repo root; never by the agent.
#   powershell -ExecutionPolicy Bypass -File scripts\fresh_clone_check.ps1
# Clones the pushed origin into _freshclone (git-ignored), builds it under its own compose
# project name (freshcheck, so the main stack's containers and DB volume are never touched),
# waits for /health, then removes the project (down -v) and the folder.
# Exit 0 only when /health answered HTTP 200 on the cloned commit == local HEAD.
# Windows PowerShell 5.1 compatible.

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Clone = Join-Path $Root '_freshclone'
$Project = 'freshcheck'
$HealthUrl = 'http://localhost:8080/health'
$TimeoutS = 60

function Test-PortBusy([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        $done = $async.AsyncWaitHandle.WaitOne(500)
        return ($done -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Remove-Clone {
    if (Test-Path $Clone) {
        # git marks pack files read-only; -Force removes them
        Remove-Item -Recurse -Force $Clone
    }
}

Set-Location $Root

# 1. the main stack must be down: both stacks publish :8080
if (Test-PortBusy 8080) {
    Write-Host 'port 8080 is busy'
    Write-Host 'stop the main stack first: docker compose -f compose.yaml -f compose.dev.yaml down'
    exit 1
}

# 2. the local tree must be clean, so the clone and HEAD mean the same code
$dirty = (git status --porcelain) | Where-Object { $_.Trim() -ne '' }
if ($dirty) {
    Write-Host ("local tree is dirty ({0} paths): commit or stash first" -f @($dirty).Count)
    exit 1
}
$localHead = (git rev-parse HEAD).Trim()
$origin = (git remote get-url origin).Trim()
if (-not $origin) {
    Write-Host 'no origin remote'
    exit 1
}

# 3. fresh clone of what is pushed
Remove-Clone
git clone --quiet $origin $Clone
if ($LASTEXITCODE -ne 0) {
    Write-Host 'git clone failed'
    Remove-Clone
    exit 1
}
$cloneHead = (git -C $Clone rev-parse HEAD).Trim()
Write-Host "cloned commit: $cloneHead"
Write-Host "local HEAD:    $localHead"
if ($cloneHead -ne $localHead) {
    Write-Host 'FAIL: the cloned commit is not the local HEAD (push first, or wrong branch)'
    Remove-Clone
    exit 1
}

# 4. build and start under its own project name; always clean up
$code = 1
$status = 'no answer'
$waited = 0.0
Push-Location $Clone
try {
    docker compose -p $Project up -d --build
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'docker compose up failed'
    } else {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        while ($sw.Elapsed.TotalSeconds -lt $TimeoutS) {
            try {
                $resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
                $status = [int]$resp.StatusCode
                if ($status -eq 200) { break }
            } catch {
                $status = 'no answer'
            }
            Start-Sleep -Seconds 2
        }
        $waited = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        Write-Host "health: $status after $waited s"
        if ($status -eq 200) { $code = 0 }
    }
} finally {
    docker compose -p $Project down -v
    Pop-Location
    Remove-Clone
}

if ($code -eq 0) {
    Write-Host "PASS: fresh clone $cloneHead healthy in $waited s"
} else {
    Write-Host "FAIL: fresh clone did not answer HTTP 200 within $TimeoutS s"
}
exit $code
