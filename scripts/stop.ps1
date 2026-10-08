$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $projectRoot '.local-runtime/processes.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'No workspace process record.'; exit 0 }
$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
if ($state.root -ne $projectRoot) { throw 'The process record belongs to a different project.' }
$owned = @()
$foreign = @()
foreach ($processId in @($state.frontendPid, $state.backendPid)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    if ($process.CommandLine -notmatch 'vite[/\\]bin[/\\]vite.js|uvicorn backend.app.main:app') { $foreign += $processId; continue }
    $expectedStarted = if ($processId -eq $state.frontendPid) { $state.frontendStarted } else { $state.backendStarted }
    $running = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $expectedStarted -or ($running -and $running.StartTime.ToUniversalTime().Ticks.ToString() -ne $expectedStarted)) {
        $foreign += $processId
        continue
    }
    $owned += $processId
    Stop-Process -Id $processId
    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
        Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
    }
}
function Test-WorkspacePort([int]$Port) {
    if (-not $Port) { return $false }
    $client = [System.Net.Sockets.TcpClient]::new()
    try { [void]$client.ConnectAsync('127.0.0.1', $Port).Wait(300); return $client.Connected }
    catch { return $false }
    finally { $client.Dispose() }
}
# A Windows virtual-environment launcher can exit before its interpreter releases sockets.
$backendPort = if ($state.backendPort) { [int]$state.backendPort } else { 8000 }
$frontendPort = if ($state.frontendPort) { [int]$state.frontendPort } else { 5173 }
$released = $false
for ($attempt=0; $attempt -lt 30; $attempt++) {
    if (-not (Test-WorkspacePort $backendPort) -and -not (Test-WorkspacePort $frontendPort)) { $released=$true; break }
    Start-Sleep -Milliseconds 100
}
if ($owned.Count -gt 0 -and -not $released) { throw 'Services were stopped, but a workspace port is still occupied. The process record is preserved for inspection.' }
Remove-Item -LiteralPath $statePath
if ($foreign.Count -gt 0) { Write-Host "Workspace services stopped. Left unrelated process(es) running: $($foreign -join ', ')." }
else { Write-Host 'Workspace services stopped. Local files and database are preserved.' }
