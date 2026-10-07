$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $projectRoot '.local-runtime/processes.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'No workspace process record.'; exit 0 }
$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
if ($state.root -ne $projectRoot) { throw 'The process record belongs to a different project.' }
foreach ($processId in @($state.frontendPid, $state.backendPid)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    if ($process.CommandLine -notmatch 'vite[/\\]bin[/\\]vite.js|uvicorn backend.app.main:app') {
        throw "Process $processId no longer belongs to this workspace; leaving it running."
    }
    $expectedStarted = if ($processId -eq $state.frontendPid) { $state.frontendStarted } else { $state.backendStarted }
    $running = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $expectedStarted -or ($running -and $running.StartTime.ToUniversalTime().Ticks.ToString() -ne $expectedStarted)) {
        throw "Process $processId has a different start time; leaving it running."
    }
    Stop-Process -Id $processId
    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
        Wait-Process -Id $processId -Timeout 10 -ErrorAction SilentlyContinue
    }
}
function Test-WorkspacePort([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try { [void]$client.ConnectAsync('127.0.0.1', $Port).Wait(300); return $client.Connected }
    catch { return $false }
    finally { $client.Dispose() }
}
# A Windows virtual-environment launcher can exit before its interpreter releases sockets.
$released = $false
for ($attempt=0; $attempt -lt 30; $attempt++) {
    if (-not (Test-WorkspacePort 8000) -and -not (Test-WorkspacePort 5173)) { $released=$true; break }
    Start-Sleep -Milliseconds 100
}
if (-not $released) { throw 'Services were stopped, but a port is still occupied. The process record is preserved for inspection.' }
Remove-Item -LiteralPath $statePath
Write-Host 'Workspace services stopped. Local files and database are preserved.'
