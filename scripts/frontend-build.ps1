# Hash only application sources or public build files; never inspect user data.
function Get-FrontendFingerprint([string]$Root, [switch]$Built) {
    $frontendRoot = Join-Path $Root 'frontend'
    $files = @()
    if ($Built) {
        $directories = @('dist')
    } else {
        $directories = @('src', 'public')
        $files += @('index.html', 'package.json', 'package-lock.json', 'vite.config.ts', 'tsconfig.json', 'tsconfig.app.json') |
            ForEach-Object { Join-Path $frontendRoot $_ }
    }
    foreach ($directory in $directories) {
        $path = Join-Path $frontendRoot $directory
        if (Test-Path -LiteralPath $path -PathType Container) {
            $files += @(Get-ChildItem -LiteralPath $path -Recurse -File | ForEach-Object { $_.FullName })
        }
    }
    $sortedFiles = [string[]]@($files | Select-Object -Unique)
    [Array]::Sort($sortedFiles, [StringComparer]::Ordinal)
    $manifest = foreach ($path in $sortedFiles) {
        $relative = $path.Substring($frontendRoot.Length + 1).Replace('\', '/')
        $hash = if (Test-Path -LiteralPath $path -PathType Leaf) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash } else { 'missing' }
        "$relative=$hash"
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($manifest -join "`n"))))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Test-FrontendBuild([string]$Root, [string]$Fingerprint) {
    $recordPath = Join-Path $Root '.local-runtime/frontend-build.json'
    if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $Root 'frontend/dist/index.html') -PathType Leaf)) { return $false }
    try {
        $record = Get-Content -Raw -LiteralPath $recordPath | ConvertFrom-Json
        return $record.source -eq $Fingerprint -and $record.output -eq (Get-FrontendFingerprint $Root -Built)
    } catch { return $false }
}

function Save-FrontendBuild([string]$Root, [string]$Fingerprint) {
    $recordPath = Join-Path $Root '.local-runtime/frontend-build.json'
    @{ source=$Fingerprint; output=(Get-FrontendFingerprint $Root -Built) } |
        ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath ($recordPath + '.pending')
    Move-Item -LiteralPath ($recordPath + '.pending') -Destination $recordPath -Force
}

function Test-FrontendReady([string]$Address) {
    # HTML alone is not readiness: verify the built entry and its module preload.
    try {
        $web = Invoke-WebRequest -Uri $Address -TimeoutSec 3 -UseBasicParsing
        if ($web.StatusCode -ne 200) { return $false }
        $assets = @([regex]::Matches($web.Content, '(?:src|href)="(/assets/[^"?]+\.(?:js|css))"') |
            ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
        if (-not $assets.Count) { return $false }
        foreach ($asset in $assets) {
            $response = Invoke-WebRequest -Uri ($Address.TrimEnd('/') + $asset) -TimeoutSec 3 -UseBasicParsing
            $contentType = if ($asset.EndsWith('.css')) { 'text/css' } else { 'javascript' }
            if ($response.StatusCode -ne 200 -or $response.Headers['Content-Type'] -notmatch $contentType) { return $false }
        }
        return $true
    } catch { return $false }
}
