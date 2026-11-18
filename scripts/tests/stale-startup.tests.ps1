param()
$ErrorActionPreference = 'Stop'
$scriptsDir = Split-Path -Parent $PSScriptRoot
. (Join-Path $scriptsDir 'stop.ps1') -FunctionsOnly
function Assert-True($Value, [string]$Message) { if (-not $Value) { throw $Message } }
$root = Split-Path -Parent $scriptsDir
$created = [datetime]::UtcNow.AddDays(-2)
$ticks = $created.Ticks.ToString()

& {
    function Get-CimInstance { param($ClassName, $Filter, $ErrorAction)
        [pscustomobject]@{ ProcessId=101; Name='vmnetdhcp.exe'; CreationDate=$created.AddDays(1) }
    }
    function Get-Process { param($Id, $ErrorAction) [pscustomobject]@{ StartTime=$null } }
    Assert-True ($null -eq (Get-WorkspaceProcess 101 $ticks 'frontend' 5173)) 'Inaccessible recycled PID must return no match without throwing.'
}

$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $scriptsDir 'stop.ps1'),[ref]$tokens,[ref]$errors)
$stopBody=($ast.EndBlock.Statements | Where-Object {
    $_.Extent.StartLineNumber -ge ($ast.EndBlock.Statements | Where-Object { $_.Extent.Text -eq '$ErrorActionPreference = ''Stop''' }).Extent.StartLineNumber
} | ForEach-Object { $_.Extent.Text }) -join "`n"
$stopBody=$stopBody.Replace('$projectRoot = Split-Path -Parent $PSScriptRoot','$projectRoot = $root')
& {
    $script:removed=$false
    $script:unknown=$false
    $script:record=@{root=$root;backendPid=100;backendStarted=$ticks;backendPort=8000;frontendPid=101;frontendStarted=$ticks;frontendPort=5173}
    function Test-Path { param($LiteralPath) $true }
    function Get-Content { param([switch]$Raw,$LiteralPath) $script:record | ConvertTo-Json }
    function Get-CimInstance { param($ClassName,$Filter,$ErrorAction)
        if ($Filter -eq 'ProcessId = 101') {
            [pscustomobject]@{ProcessId=101;Name='vmnetdhcp.exe';CreationDate=$(if($script:unknown){$null}else{$created.AddDays(1)})}
        }
    }
    function Get-Process { param($Id,$ErrorAction) [pscustomobject]@{StartTime=$null} }
    function Stop-Process { throw 'Must never stop the unrelated process.' }
    function Test-WorkspacePort { $false }
    function Remove-Item { param($LiteralPath) $script:removed=$true }
    Invoke-Expression $stopBody
    Assert-True $script:removed 'A confirmed recycled PID must not prevent clearing stale runtime records.'
    $script:removed=$false; $script:unknown=$true; $rejected=$false
    try { Invoke-Expression $stopBody } catch { $rejected=$true }
    Assert-True ($rejected -and -not $script:removed) 'Unknown process identity must preserve the record and stop no processes.'
}
Write-Host 'Stale startup identity tests passed.'
