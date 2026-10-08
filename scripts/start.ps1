param(
    [switch]$InstallDependencies,
    [switch]$NoBrowser,
    [string]$PythonPath = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.local-runtime'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
. (Join-Path $PSScriptRoot 'port-selection.ps1')

# Read configuration as data, never as PowerShell. Explicit environment variables win.
$envPath = Join-Path $projectRoot '.env'
if (Test-Path -LiteralPath $envPath) {
    foreach ($line in [System.IO.File]::ReadAllLines($envPath)) {
        if ($line -match '^\s*(PAPER_READER_[A-Z0-9_]+|OPENAI_API_KEY)\s*=\s*(.*?)\s*$') {
            $configName = $matches[1]
            $configValue = $matches[2]
            if ($configValue.Length -ge 2 -and (($configValue.StartsWith('"') -and $configValue.EndsWith('"')) -or ($configValue.StartsWith("'") -and $configValue.EndsWith("'")))) {
                $configValue = $configValue.Substring(1, $configValue.Length - 2)
            }
            if (-not [System.Environment]::GetEnvironmentVariable($configName, 'Process')) {
                [System.Environment]::SetEnvironmentVariable($configName, $configValue, 'Process')
            }
        }
    }
}

$backendPort = Get-AvailablePort -PreferredPort 8000
$frontendPort = Get-AvailablePort -PreferredPort 5173
Push-Location $projectRoot
try {
    if (-not $PythonPath) {
        $PythonPath = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $PythonPath)) {
            & python -m venv (Join-Path $projectRoot 'backend/.venv')
            if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required to create the environment.' }
            $InstallDependencies = $true
        }
    }
    $PythonPath = (Get-Command $PythonPath).Source
    & $PythonPath -c 'import fastapi, sqlalchemy, pymupdf, alembic, uvicorn, httpx'
    if ($InstallDependencies -or $LASTEXITCODE -ne 0) {
        & $PythonPath -m pip install -r backend/requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    }
    if ($InstallDependencies -or -not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend/node_modules/vite'))) {
        $npmPath = (Get-Command npm.cmd -CommandType Application).Source
        & $npmPath --prefix frontend ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    }
    $nodePath = (Get-Command node).Source
    $env:RIW_BACKEND_URL = "http://127.0.0.1:$backendPort"
    $backend = Start-Process -FilePath $PythonPath -ArgumentList @('-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port',"$backendPort") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'backend.log') -RedirectStandardError (Join-Path $runtimeDir 'backend.err.log') -PassThru
    $frontend = Start-Process -FilePath $nodePath -ArgumentList @('node_modules/vite/bin/vite.js','--config','vite.config.ts','--host','127.0.0.1','--port',"$frontendPort",'--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'frontend.log') -RedirectStandardError (Join-Path $runtimeDir 'frontend.err.log') -PassThru
    @{ backendPid=$backend.Id; frontendPid=$frontend.Id; backendPort=$backendPort; frontendPort=$frontendPort; url="http://127.0.0.1:$frontendPort"; backendStarted=$backend.StartTime.ToUniversalTime().Ticks.ToString(); frontendStarted=$frontend.StartTime.ToUniversalTime().Ticks.ToString(); root=$projectRoot } | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $runtimeDir 'processes.json')
    $ready = $false
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        $backend.Refresh(); $frontend.Refresh()
        if ($backend.HasExited -or $frontend.HasExited) { throw 'A service exited. See .local-runtime/*.err.log.' }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/health" -TimeoutSec 1
            $web = Invoke-WebRequest -Uri "http://127.0.0.1:$frontendPort" -TimeoutSec 1 -UseBasicParsing
            if ($health.status -eq 'ok' -and $web.StatusCode -eq 200) { $ready=$true; break }
        } catch { Start-Sleep -Milliseconds 300 }
    }
    if (-not $ready) { throw 'Startup timed out. See .local-runtime/*.log.' }
    Write-Host "Research workspace is ready: http://127.0.0.1:$frontendPort"
    Write-Host 'Data: backend/paper_reader.db and backend/storage/; logs: .local-runtime/'
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$frontendPort" }
} catch {
    if ($frontend -and -not $frontend.HasExited) { Stop-Process -Id $frontend.Id -ErrorAction SilentlyContinue }
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue }
    throw
} finally { Pop-Location }
