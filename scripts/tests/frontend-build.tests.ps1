$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../frontend-build.ps1')
function Assert-True($Value, [string]$Message) { if (-not $Value) { throw $Message } }
$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('lira-build-test-' + [guid]::NewGuid())
try {
    foreach ($directory in @('frontend/src', 'frontend/public', 'frontend/dist/assets', '.local-runtime')) {
        New-Item -ItemType Directory -Force -Path (Join-Path $fixtureRoot $directory) | Out-Null
    }
    Set-Content -LiteralPath (Join-Path $fixtureRoot 'frontend/src/main.tsx') -Value 'source-a'
    Set-Content -LiteralPath (Join-Path $fixtureRoot 'frontend/index.html') -Value 'entry-a'
    Set-Content -LiteralPath (Join-Path $fixtureRoot 'frontend/dist/index.html') -Value 'built-entry'
    Set-Content -LiteralPath (Join-Path $fixtureRoot 'frontend/dist/assets/app.js') -Value 'built-source'
    $fingerprint = Get-FrontendFingerprint $fixtureRoot
    Assert-True (-not (Test-FrontendBuild $fixtureRoot $fingerprint)) 'A build without a matching record must be rebuilt.'
    Save-FrontendBuild $fixtureRoot $fingerprint
    Assert-True (Test-FrontendBuild $fixtureRoot $fingerprint) 'An unchanged complete build should be reused.'
    Set-Content -LiteralPath (Join-Path $fixtureRoot 'frontend/src/main.tsx') -Value 'source-b'
    Assert-True (-not (Test-FrontendBuild $fixtureRoot (Get-FrontendFingerprint $fixtureRoot))) 'Changed source must invalidate the build.'
    Set-Content -LiteralPath (Join-Path $fixtureRoot 'frontend/src/main.tsx') -Value 'source-a'
    Set-Content -LiteralPath (Join-Path $fixtureRoot 'frontend/dist/assets/app.js') -Value 'damaged'
    Assert-True (-not (Test-FrontendBuild $fixtureRoot $fingerprint)) 'Changed output must invalidate the build.'
    Set-Content -LiteralPath (Join-Path $fixtureRoot 'frontend/dist/assets/app.js') -Value 'built-source'
    Remove-Item -LiteralPath (Join-Path $fixtureRoot 'frontend/dist/assets/app.js')
    Assert-True (-not (Test-FrontendBuild $fixtureRoot $fingerprint)) 'Missing output must invalidate the build.'
    Set-Content -LiteralPath (Join-Path $fixtureRoot 'frontend/dist/assets/app.js') -Value 'built-source'
    Set-Content -LiteralPath (Join-Path $fixtureRoot '.local-runtime/frontend-build.json') -Value 'invalid-json'
    Assert-True (-not (Test-FrontendBuild $fixtureRoot $fingerprint)) 'A corrupt record must request a rebuild.'
    Write-Host 'Frontend build reuse and invalidation passed.'
} finally {
    # The fixture is a directly created GUID directory, never the user's checkout.
    if (-not ([IO.Path]::GetFullPath($fixtureRoot).StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()), [StringComparison]::OrdinalIgnoreCase)) -or
        (Split-Path -Leaf $fixtureRoot) -notlike 'lira-build-test-*') { throw 'Unsafe fixture cleanup path.' }
    Remove-Item -LiteralPath $fixtureRoot -Recurse -Force
}

& {
    $script:responseMode = 'valid'
    $script:assetCalls = 0
    function Invoke-WebRequest {
        param($Uri, $TimeoutSec, [switch]$UseBasicParsing)
        if ($Uri -eq 'http://fixture') {
            $html = if ($script:responseMode -eq 'empty') { '<html></html>' }
                else { '<script src="/assets/app.js"></script><link href="/assets/vendor.js"><link href="/assets/app.css">' }
            return [pscustomobject]@{ StatusCode=200; Content=$html }
        }
        $script:assetCalls++
        if ($script:responseMode -eq 'missing') { throw 'asset unavailable' }
        $type = if ($script:responseMode -eq 'fallback') { 'text/html' }
            elseif ($Uri.EndsWith('.css')) { 'text/css' } else { 'application/javascript' }
        return [pscustomobject]@{ StatusCode=200; Headers=@{'Content-Type'=$type} }
    }
    Assert-True (Test-FrontendReady 'http://fixture') 'A complete built entry should be ready.'
    Assert-True ($script:assetCalls -eq 3) 'Readiness must fetch entry, preload and CSS.'
    foreach ($mode in @('empty', 'missing', 'fallback')) {
        $script:responseMode = $mode
        Assert-True (-not (Test-FrontendReady 'http://fixture')) 'Missing assets and SPA fallback HTML must not pass readiness.'
    }
    Write-Host 'Frontend asset readiness passed.'
}
