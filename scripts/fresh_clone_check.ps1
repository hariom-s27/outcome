# Fresh-clone check (PR-63, PR-73, P4-04; -Cold: P8a A-10, A-13). Run by Hariom from the repo
# root; never by the agent.
#   powershell -ExecutionPolicy Bypass -File scripts\fresh_clone_check.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\fresh_clone_check.ps1 -Cold
# Clones the pushed origin into _freshclone (git-ignored), builds it under its own compose
# project name (freshcheck, so the main stack's containers and DB volume are never touched),
# waits for /health, then removes the project (down -v) and the folder.
# Exit 0 only when /health answered HTTP 200 on the cloned commit == local HEAD.
#
# -Cold adds, in order:
#   1. `docker compose -p freshcheck build --no-cache` (build seconds recorded)
#   2. `up -d` without --build, timed from `up` to /health 200 (must be <= 60 s)
#   3. image size of docextract:local
#   4. no-key run: down -v, then up with an env file whose LLM_BASE_URL / LLM_API_KEY are empty
#      (and both removed from this process's environment): /health must be 200, and one POST of
#      an invented CSV + invented field list must end terminal with a contract-valid answer
#      (SUCCESS/PARTIAL: result passes tools/validate.py; FAILED: error present, no result).
#   Then down -v and the clone is deleted. Prints COLD lines that go into logs/P8a_report.md.
# Note: the build tags docextract:local, the main stack's image tag. Rebuild the main stack
# afterwards (`docker compose up -d --build`).
# Windows PowerShell 5.1 compatible. ASCII only.

param([switch]$Cold)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Clone = Join-Path $Root '_freshclone'
$Project = 'freshcheck'
$BaseUrl = 'http://localhost:8080'
$HealthUrl = "$BaseUrl/health"
$TimeoutS = 60
$JobTimeoutS = 300
$Image = 'docextract:local'
$Work = Join-Path $env:TEMP 'freshcheck_nokey'

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

# Polls /health until 200 or $TimeoutS; returns @(status, seconds) from the given stopwatch.
function Wait-Health($sw) {
    $status = 'no answer'
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
    return @($status, [math]::Round($sw.Elapsed.TotalSeconds, 1))
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding $false))
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
$buildS = $null
$imageSize = $null
$nokeyHealth = 'not run'
$nokeyStatus = 'not run'
$nokeyValid = $false
$resultFile = $null
$schemaFile = $null
Push-Location $Clone
try {
    if ($Cold) {
        $swb = [System.Diagnostics.Stopwatch]::StartNew()
        docker compose -p $Project build --no-cache
        $buildOk = ($LASTEXITCODE -eq 0)
        $buildS = [math]::Round($swb.Elapsed.TotalSeconds, 1)
        Write-Host "COLD build_no_cache_s: $buildS (exit ok: $buildOk)"
        if (-not $buildOk) { throw 'docker compose build --no-cache failed' }
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        docker compose -p $Project up -d
    } else {
        docker compose -p $Project up -d --build
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'docker compose up failed'
    } else {
        $r = Wait-Health $sw
        $status = $r[0]
        $waited = $r[1]
        if ($Cold) {
            Write-Host "COLD up_to_health_s: $waited (status $status; limit $TimeoutS s)"
        } else {
            Write-Host "health: $status after $waited s"
        }
        if ($status -eq 200) { $code = 0 }
    }

    if ($Cold -and $code -eq 0) {
        $imageSize = (docker image ls $Image --format '{{.Size}}' | Select-Object -First 1)
        Write-Host "COLD image_size: $imageSize ($Image)"

        # no-key run (A-13): empty LLM variables from an env file, none from this process
        docker compose -p $Project down -v
        Remove-Item Env:LLM_API_KEY -ErrorAction SilentlyContinue
        Remove-Item Env:LLM_BASE_URL -ErrorAction SilentlyContinue
        if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
        New-Item -ItemType Directory -Force $Work | Out-Null
        $keyFile = Join-Path $Work 'nokey-vars.txt'
        Write-Utf8NoBom $keyFile "LLM_BASE_URL=`nLLM_API_KEY=`n"
        # invented fixture (no sample data)
        $docFile = Join-Path $Work 'widgets.csv'
        Write-Utf8NoBom $docFile "widget,count`nsprocket,7`ngear,3`n"
        $schemaFile = Join-Path $Work 'widget_schema.json'
        Write-Utf8NoBom $schemaFile ('{"name": "widget_check", "description": "invented cold-check list", ' +
            '"fields": {"widget_name": {"name": "Widget name", "description": "Name of the first widget"}, ' +
            '"widget_count": {"name": "Widget count", "description": "Count of the first widget"}}}')

        $code = 1
        $sw2 = [System.Diagnostics.Stopwatch]::StartNew()
        docker compose -p $Project --env-file $keyFile up -d
        if ($LASTEXITCODE -ne 0) { throw 'no-key docker compose up failed' }
        $r = Wait-Health $sw2
        $nokeyHealth = $r[0]
        Write-Host ("COLD nokey_health: {0} after {1} s" -f $r[0], $r[1])
        if ($nokeyHealth -eq 200) {
            $post = (& curl.exe -s -F "file=@$docFile" -F "schema=<$schemaFile" "$BaseUrl/jobs") -join "`n"
            $jobId = ($post | ConvertFrom-Json).job_id
            Write-Host "COLD nokey_job: $jobId"
            $swj = [System.Diagnostics.Stopwatch]::StartNew()
            $job = $null
            while ($swj.Elapsed.TotalSeconds -lt $JobTimeoutS) {
                $body = (& curl.exe -s "$BaseUrl/jobs/$jobId") -join "`n"
                $job = $body | ConvertFrom-Json
                if (@('SUCCESS', 'PARTIAL', 'FAILED') -contains $job.status) { break }
                Start-Sleep -Seconds 2
            }
            $nokeyStatus = $job.status
            Write-Host ("COLD nokey_status: {0} after {1} s" -f $nokeyStatus, [math]::Round($swj.Elapsed.TotalSeconds, 1))
            if ($nokeyStatus -eq 'FAILED') {
                $nokeyValid = ($null -ne $job.error) -and ($null -eq $job.result)
            } elseif (@('SUCCESS', 'PARTIAL') -contains $nokeyStatus -and $null -ne $job.result) {
                $resultFile = Join-Path $Work 'nokey_result.json'
                Write-Utf8NoBom $resultFile ($job.result | ConvertTo-Json -Depth 50)
            }
        }
    }
} finally {
    docker compose -p $Project down -v
    Pop-Location
    Remove-Clone
}

if ($Cold -and $code -eq 1 -and $status -eq 200) {
    # result check with the frozen validator, run from the repo (not the deleted clone)
    if ($resultFile) {
        uv run python tools/validate.py $resultFile --schema $schemaFile
        $nokeyValid = ($LASTEXITCODE -eq 0)
    }
    Write-Host "COLD nokey_valid: $nokeyValid"
    if ($nokeyValid -and $waited -le $TimeoutS) { $code = 0 }
}
if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }

if ($code -eq 0) {
    if ($Cold) {
        Write-Host "PASS: cold check on $cloneHead (build $buildS s, up->health $waited s, image $imageSize, no-key $nokeyStatus valid)"
    } else {
        Write-Host "PASS: fresh clone $cloneHead healthy in $waited s"
    }
} else {
    Write-Host "FAIL: see the lines above (health $status after $waited s; no-key health $nokeyHealth, status $nokeyStatus, valid $nokeyValid)"
}
exit $code
