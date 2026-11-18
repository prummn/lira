param(
    [switch]$InstallDependencies,
    [switch]$NoBrowser,
    [switch]$Restart,
    [string]$PythonPath = '',
    [string]$NodePath = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.local-runtime'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
. (Join-Path $PSScriptRoot 'frontend-build.ps1')

function Get-SourceFingerprint([string]$Root) {
    # 白名单只包含源码和启动配置；不读取 .env、凭据或运行数据。
    $files = @(Get-ChildItem -LiteralPath (Join-Path $Root 'backend/app') -Recurse -File -Filter '*.py' |
        ForEach-Object { $_.FullName.Substring($Root.Length + 1).Replace('\', '/') })
    $files += @('backend/__init__.py', 'backend/requirements.txt', 'backend/alembic.ini',
        'frontend/package.json', 'frontend/package-lock.json', 'frontend/vite.config.ts',
        'frontend/index.html', 'frontend/tsconfig.json', 'frontend/tsconfig.app.json',
        'scripts/start.ps1', 'scripts/stop.ps1', 'scripts/port-selection.ps1', 'scripts/frontend-build.ps1')
    foreach ($directory in @('frontend/src', 'frontend/public')) {
        $files += @(Get-ChildItem -LiteralPath (Join-Path $Root $directory) -Recurse -File |
            ForEach-Object { $_.FullName.Substring($Root.Length + 1).Replace('\', '/') })
    }
    # Ordinal ordering is identical in Windows PowerShell (.NET Framework) and
    # PowerShell 7 (.NET). Culture sorting disagrees about dots/underscores.
    $sortedFiles = [string[]]@($files | Select-Object -Unique)
    [Array]::Sort($sortedFiles, [StringComparer]::Ordinal)
    $manifest = foreach ($relative in $sortedFiles) {
        $path = Join-Path $Root $relative
        $hash = if (Test-Path -LiteralPath $path -PathType Leaf) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash } else { 'missing' }
        "$relative=$hash"
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($manifest -join "`n"))))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

. (Join-Path $PSScriptRoot 'stop.ps1') -FunctionsOnly

function Stop-UnrecordedWorkspaceProcess($Launched, [string]$Role, [int]$Port) {
    if (-not $Launched) { return }
    $started = $Launched.StartTime.ToUniversalTime().Ticks.ToString()
    $verified = Get-WorkspaceProcess $Launched.Id $started $Role $Port
    if (-not $verified) { return }
    $children = if ($Role -eq 'backend') { @(Get-WorkspaceBackendChildren $verified $Port) } else { @() }
    foreach ($child in $children) {
        $parentNow = Get-WorkspaceProcess $Launched.Id $started $Role $Port
        $childNow = Get-WorkspaceProcess $child.ProcessId $child.Started 'backend' $Port
        if (-not $parentNow -or -not $childNow -or $childNow.ParentProcessId -ne $Launched.Id -or
            $childNow.CommandLine -cne $child.CommandLine -or $childNow.CreationDate -ne $child.CreationDate -or
            $parentNow.CommandLine -cne $verified.CommandLine -or $childNow.CreationDate -lt $parentNow.CreationDate) {
            throw '启动清理时父子进程身份发生变化，拒绝停止。'
        }
        Stop-Process -Id $child.ProcessId
        Wait-Process -Id $child.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    }
    if (Get-WorkspaceProcess $Launched.Id $started $Role $Port) {
        Stop-Process -Id $Launched.Id
        Wait-Process -Id $Launched.Id -Timeout 10 -ErrorAction SilentlyContinue
    }
}

$sourceFingerprint = Get-SourceFingerprint $projectRoot
$statePath = Join-Path $runtimeDir 'processes.json'
if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if ($state.root -ne $projectRoot) { throw '进程记录属于其他项目，拒绝复用或覆盖。' }
    $canReuse = $false
    if (-not $Restart -and $state.sourceFingerprint -and $state.sourceFingerprint -eq $sourceFingerprint) {
        $backend = Get-WorkspaceProcess $state.backendPid $state.backendStarted 'backend' $state.backendPort
        $frontend = Get-WorkspaceProcess $state.frontendPid $state.frontendStarted 'frontend' $state.frontendPort
        if ($backend -and $frontend) {
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:$($state.backendPort)/api/health" -TimeoutSec 5
                $frontendReady = Test-FrontendReady "http://127.0.0.1:$($state.frontendPort)"
                $canReuse = $health.status -eq 'ok' -and $frontendReady
            } catch { $canReuse = $false }
        }
    }
    if ($canReuse) {
        Write-Host "源码版本一致，复用运行中的实例：$($state.url)"
        if (-not $NoBrowser) { Start-Process $state.url }
        return
    }
    Write-Host '正在恢复工作区：清理已退出的实例，或重新启动已更新的服务。'
    & (Join-Path $PSScriptRoot 'stop.ps1')
    if (Test-Path -LiteralPath $statePath) { throw '停止未完成，拒绝启动新实例。请检查进程记录。' }
}
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
    # Desktop launchers do not inherit WorkBuddy's private Node.js PATH.
    # Resolve a complete runtime (node + npm CLI) before starting services.
    $nodeCandidates = @()
    if ($NodePath) {
        $nodeCommand = Get-Command $NodePath -CommandType Application -ErrorAction SilentlyContinue
        if (-not $nodeCommand) { throw "Node.js executable not found: $NodePath" }
        $nodeCandidates = @($nodeCommand.Source)
    } else {
        $nodeCommand = Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue
        if ($nodeCommand) { $nodeCandidates += $nodeCommand.Source }
        foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
            if ($base) {
                $nodeCandidates += Join-Path $base 'nodejs/node.exe'
                $nodeCandidates += Join-Path $base 'Programs/nodejs/node.exe'
            }
        }
        if ($env:USERPROFILE) {
            $versionsDir = Join-Path $env:USERPROFILE '.workbuddy/binaries/node/versions'
            if (Test-Path -LiteralPath $versionsDir) {
                $nodeCandidates += @(Get-ChildItem -LiteralPath $versionsDir -Directory |
                    Sort-Object LastWriteTime -Descending |
                    ForEach-Object { Join-Path $_.FullName 'node.exe' })
            }
        }
    }
    $needsNpm = $InstallDependencies -or -not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend/node_modules/vite'))
    $nodePath = $null
    $npmCli = $null
    foreach ($candidate in $nodeCandidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $candidateNpm = Join-Path (Split-Path -Parent $candidate) 'node_modules/npm/bin/npm-cli.js'
        if ($needsNpm -and -not (Test-Path -LiteralPath $candidateNpm -PathType Leaf)) { continue }
        $nodePath = $candidate
        $npmCli = $candidateNpm
        break
    }
    if (-not $nodePath) {
        throw 'Node.js with npm was not found. Install Node.js 22 LTS, reopen the launcher, or pass -NodePath with the full path to node.exe.'
    }
    # npm lifecycle scripts must also be able to resolve this same node.exe.
    $env:PATH = (Split-Path -Parent $nodePath) + [System.IO.Path]::PathSeparator + $env:PATH
    & $nodePath --version
    if ($LASTEXITCODE -ne 0) { throw 'Node.js runtime validation failed.' }
    if ($needsNpm) {
        & $nodePath $npmCli --prefix frontend ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    }
    $frontendFingerprint = Get-FrontendFingerprint $projectRoot
    if (-not (Test-FrontendBuild $projectRoot $frontendFingerprint)) {
        Write-Host '正在准备界面（首次运行或源码更新时构建，完成后再打开浏览器）…'
        Push-Location (Join-Path $projectRoot 'frontend')
        try {
            & $nodePath 'node_modules/typescript/bin/tsc' -b
            if ($LASTEXITCODE -ne 0) { throw '前端类型检查失败；未启动旧版页面。' }
            & $nodePath 'node_modules/vite/bin/vite.js' build --config vite.config.ts
            if ($LASTEXITCODE -ne 0) { throw '前端构建失败；请查看上方错误。' }
        } finally { Pop-Location }
        Save-FrontendBuild $projectRoot $frontendFingerprint
    }
    $env:RIW_BACKEND_URL = "http://127.0.0.1:$backendPort"
    $backend = Start-Process -FilePath $PythonPath -ArgumentList @('-m','uvicorn','backend.app.main:app','--host','127.0.0.1','--port',"$backendPort") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'backend.log') -RedirectStandardError (Join-Path $runtimeDir 'backend.err.log') -PassThru
    $frontend = Start-Process -FilePath $nodePath -ArgumentList @('node_modules/vite/bin/vite.js','preview','--config','vite.config.ts','--host','127.0.0.1','--port',"$frontendPort",'--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'frontend.log') -RedirectStandardError (Join-Path $runtimeDir 'frontend.err.log') -PassThru
    @{ sourceFingerprint=$sourceFingerprint; backendPid=$backend.Id; frontendPid=$frontend.Id; backendPort=$backendPort; frontendPort=$frontendPort; url="http://127.0.0.1:$frontendPort"; backendStarted=$backend.StartTime.ToUniversalTime().Ticks.ToString(); frontendStarted=$frontend.StartTime.ToUniversalTime().Ticks.ToString(); root=$projectRoot } | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath ($statePath + '.pending')
    Move-Item -LiteralPath ($statePath + '.pending') -Destination $statePath -Force
    $ready = $false
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        $backend.Refresh(); $frontend.Refresh()
        if ($backend.HasExited -or $frontend.HasExited) { throw 'A service exited. See .local-runtime/*.err.log.' }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$backendPort/api/health" -TimeoutSec 5
            if ($health.status -eq 'ok' -and (Test-FrontendReady "http://127.0.0.1:$frontendPort")) { $ready=$true; break }
        } catch { Start-Sleep -Milliseconds 300 }
    }
    if (-not $ready) { throw 'Startup timed out. See .local-runtime/*.log.' }
    Write-Host "Research workspace is ready: http://127.0.0.1:$frontendPort"
    Write-Host 'Data: backend/paper_reader.db and backend/storage/; logs: .local-runtime/'
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$frontendPort" }
} catch {
    $startupError = $_
    if (Test-Path -LiteralPath $statePath) {
        try { & (Join-Path $PSScriptRoot 'stop.ps1') }
        catch { Write-Warning "启动清理未完成，保留进程记录：$_" }
    }
    # A failed state write can leave an unreadable record; always verify this
    # invocation's launch objects as well. Already stopped processes are skipped.
    foreach ($entry in @(@{Process=$backend;Role='backend';Port=$backendPort},
                         @{Process=$frontend;Role='frontend';Port=$frontendPort})) {
        try { Stop-UnrecordedWorkspaceProcess $entry.Process $entry.Role $entry.Port }
        catch { Write-Warning "启动清理未完成，请检查日志：$_" }
    }
    throw $startupError
} finally { Pop-Location }
