param([switch]$FunctionsOnly)

function Get-WorkspaceProcess([object]$ProcessId, [string]$Started, [string]$Role, [object]$Port) {
    if (-not $Started -or "$ProcessId" -notmatch '^[1-9][0-9]*$' -or "$Port" -notmatch '^[1-9][0-9]*$') { return $null }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    $running = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process -or -not $running -or $running.StartTime.ToUniversalTime().Ticks.ToString() -ne $Started) { return $null }
    if (-not $process.CreationDate -or [Math]::Abs(($process.CreationDate.ToUniversalTime() - $running.StartTime.ToUniversalTime()).TotalMilliseconds) -gt 1) { return $null }
    $command = $process.CommandLine
    $portPattern = '(?:^|\s)--port\s+"?' + [regex]::Escape("$Port") + '"?(?=\s|$)'
    if ($command -notmatch $portPattern) { return $null }
    if ($Role -eq 'backend') {
        if ($command -notmatch '(?:^|\s)-m\s+uvicorn\s+backend\.app\.main:app(?=\s|$)' -or $process.Name -notmatch '^python(?:w)?\.exe$') { return $null }
    } elseif ($Role -eq 'frontend') {
        if ($command -notmatch 'vite[/\\]bin[/\\]vite\.js(?:"|\s|$)' -or $process.Name -ne 'node.exe') { return $null }
    } else { return $null }
    return $process
}

function Get-WorkspaceBackendChildren($Parent, [object]$Port) {
    # 仅接受仍存活且身份已确认的 launcher 的直接子进程，不按端口或进程名批量终止。
    foreach ($child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($Parent.ProcessId)" -ErrorAction SilentlyContinue)) {
        if (-not $child -or -not $child.CreationDate -or $child.CreationDate -lt $Parent.CreationDate) { continue }
        $running = Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
        if (-not $running) { continue }
        $started = $running.StartTime.ToUniversalTime().Ticks.ToString()
        $verified = Get-WorkspaceProcess $child.ProcessId $started 'backend' $Port
        if (-not $verified -or $verified.ParentProcessId -ne $Parent.ProcessId) { continue }
        $parentArgs = [regex]::Match($Parent.CommandLine, '(?s)(?:^|\s)(-m\s+uvicorn\s+backend\.app\.main:app(?:\s.*)?)$').Groups[1].Value
        $childArgs = [regex]::Match($verified.CommandLine, '(?s)(?:^|\s)(-m\s+uvicorn\s+backend\.app\.main:app(?:\s.*)?)$').Groups[1].Value
        if (-not $parentArgs -or $parentArgs -cne $childArgs) { continue }
        [pscustomobject]@{ ProcessId=$verified.ProcessId; Started=$started; CommandLine=$verified.CommandLine; CreationDate=$verified.CreationDate }
    }
}

function Test-WorkspacePort([int]$Port) {
    if (-not $Port) { return $false }
    $client = [System.Net.Sockets.TcpClient]::new()
    try { [void]$client.ConnectAsync('127.0.0.1', $Port).Wait(300); return $client.Connected }
    catch { return $false }
    finally { $client.Dispose() }
}

if ($FunctionsOnly) { return }
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $projectRoot '.local-runtime/processes.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'No workspace process record.'; return }
$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
if ($state.root -ne $projectRoot) { throw 'The process record belongs to a different project.' }
$foreign = @()
foreach ($role in @('backend', 'frontend')) {
    $processId = $state."${role}Pid"
    $expectedStarted = $state."${role}Started"
    $port = $state."${role}Port"
    if ("$processId" -notmatch '^[1-9][0-9]*$') { throw '进程记录 PID 无效，记录已保留。' }
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if (-not $existing) { continue }
    $process = Get-WorkspaceProcess $processId $expectedStarted $role $port
    if (-not $process) { $foreign += $processId; continue }
    $children = if ($role -eq 'backend') { @(Get-WorkspaceBackendChildren $process $port) } else { @() }
    foreach ($child in $children) {
        # 终止前重新核对父子双方，防止 PID 回收或扫描期间身份变化。
        $parentNow = Get-WorkspaceProcess $processId $expectedStarted $role $port
        $childNow = Get-WorkspaceProcess $child.ProcessId $child.Started 'backend' $port
        if (-not $parentNow -or -not $childNow -or $childNow.ParentProcessId -ne $processId -or
            $childNow.CommandLine -cne $child.CommandLine -or $childNow.CreationDate -ne $child.CreationDate -or
            $parentNow.CommandLine -cne $process.CommandLine -or $childNow.CreationDate -lt $parentNow.CreationDate) {
            throw '子进程身份或父子关系发生变化，拒绝停止，进程记录已保留。'
        }
        Stop-Process -Id $child.ProcessId
        Wait-Process -Id $child.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    }
    $current = Get-WorkspaceProcess $processId $expectedStarted $role $port
    if ($current) {
        Stop-Process -Id $processId
        Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
    } elseif (Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue) {
        $foreign += $processId
    }
}
$backendPort = if ($state.backendPort) { [int]$state.backendPort } else { 8000 }
$frontendPort = if ($state.frontendPort) { [int]$state.frontendPort } else { 5173 }
$released = $false
for ($attempt=0; $attempt -lt 30; $attempt++) {
    if (-not (Test-WorkspacePort $backendPort) -and -not (Test-WorkspacePort $frontendPort)) { $released=$true; break }
    Start-Sleep -Milliseconds 100
}
if ($foreign.Count -gt 0) { throw "进程身份无法确认，未停止这些 PID：$($foreign -join ', ')。记录已保留，请人工检查；不会按端口终止进程。" }
if (-not $released) { throw '工作区端口仍被占用，进程记录已保留；不会终止身份未确认的进程。' }
Remove-Item -LiteralPath $statePath
Write-Host 'Workspace services stopped. Local files and database are preserved.'
