function Test-Listening([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        [void]$client.ConnectAsync('127.0.0.1', $Port).Wait(800)
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Get-AvailablePort([int]$PreferredPort, [int]$Attempts = 20) {
    for ($offset = 0; $offset -lt $Attempts; $offset++) {
        $candidate = $PreferredPort + $offset
        if (-not (Test-Listening $candidate)) { return $candidate }
    }
    throw "No available port found from $PreferredPort through $($PreferredPort + $Attempts - 1)."
}
