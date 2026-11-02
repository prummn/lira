param([string]$Version = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$releasePython = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $releasePython)) {
    throw 'Missing backend/.venv. Set up the development environment before building a release.'
}
$releaseArgs = @((Join-Path $PSScriptRoot 'release.py'))
if ($Version) { $releaseArgs += @('--version', $Version) }
Push-Location $projectRoot
try {
    & $releasePython -X utf8 @releaseArgs
    if ($LASTEXITCODE -ne 0) { throw 'Release verification failed. See the diagnostic path above.' }
} finally {
    Pop-Location
}
