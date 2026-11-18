$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot '../frontend-build.ps1')
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $projectRoot 'scripts/start.ps1'), [ref]$null, [ref]$null)
$definition = $ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-SourceFingerprint'
}, $true)[0].Extent.Text
Invoke-Expression $definition

# Real inventory deliberately contains punctuation-sensitive names such as
# knowledge.py and knowledge_maintenance.py. Both launch shells must agree.
$source = Get-SourceFingerprint $projectRoot
$frontend = Get-FrontendFingerprint $projectRoot
$built = Get-FrontendFingerprint $projectRoot -Built
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $probe = Join-Path ([IO.Path]::GetTempPath()) ('lira-fingerprint-' + [guid]::NewGuid() + '.ps1')
    try {
        @'
param([string]$Root)
$ErrorActionPreference = 'Stop'
. (Join-Path $Root 'scripts/frontend-build.ps1')
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $Root 'scripts/start.ps1'), [ref]$null, [ref]$null)
$definition = $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-SourceFingerprint'}, $true)[0].Extent.Text
Invoke-Expression $definition
[pscustomobject]@{source=(Get-SourceFingerprint $Root); frontend=(Get-FrontendFingerprint $Root); built=(Get-FrontendFingerprint $Root -Built)} | ConvertTo-Json -Compress
'@ | Set-Content -LiteralPath $probe
        $other = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $probe -Root $projectRoot) | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $other.source -ne $source -or $other.frontend -ne $frontend -or $other.built -ne $built) {
            throw 'Windows PowerShell and PowerShell 7 computed different source/build fingerprints.'
        }
    } finally { Remove-Item -LiteralPath $probe -Force }
    Write-Host 'Windows PowerShell / PowerShell 7 fingerprints match.'
} else {
    Write-Host 'Fingerprints computed; run this test in PowerShell 7 for cross-shell comparison.'
}
