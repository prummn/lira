$ErrorActionPreference = 'Stop'
$helper = Join-Path $PSScriptRoot '..\port-selection.ps1'
. $helper

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$listener.Start()
$occupiedPort = $listener.LocalEndpoint.Port
try {
    $fallback = Get-AvailablePort -PreferredPort $occupiedPort -Attempts 5
    if ($fallback -eq $occupiedPort) { throw 'Expected an occupied preferred port to be skipped.' }
    if ($fallback -ne ($occupiedPort + 1)) { throw "Expected port $($occupiedPort + 1), got $fallback." }
} finally {
    $listener.Stop()
}

Write-Host "Port selection fallback passed: $fallback"
