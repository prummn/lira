param([switch]$StaticOnly)
$ErrorActionPreference = 'Stop'
$helper = Join-Path $PSScriptRoot '..\port-selection.ps1'
. $helper

if (-not $StaticOnly) {
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
}

# 只解析脚本并执行抽取的函数或模拟命令，不运行启动/停止入口。
$scriptsDir = Split-Path -Parent $PSScriptRoot
$asts = @{}
foreach ($name in @('start.ps1', 'stop.ps1', 'port-selection.ps1')) {
    $tokens = $null
    $parseErrors = $null
    $asts[$name] = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $scriptsDir $name), [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw "${name} 解析失败：$parseErrors" }
}
function Assert-True($Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
foreach ($name in @('start.ps1', 'stop.ps1')) {
    foreach ($definition in $asts[$name].FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
        Invoke-Expression $definition.Extent.Text
    }
}
$root = Split-Path -Parent $scriptsDir
$first = Get-SourceFingerprint $root
Assert-True ($first -match '^[0-9a-f]{64}$' -and $first -eq (Get-SourceFingerprint $root)) '指纹必须稳定且为 SHA256。'

& {
    # 模拟文件列表和哈希，不写文件、不读取秘密配置。
    $script:revision = 'A'
    $script:extra = $false
    $script:paths = @()
    function Get-ChildItem { param($LiteralPath, [switch]$Recurse, [switch]$File, $Filter)
        [pscustomobject]@{ FullName=(Join-Path $root 'backend/app/main.py') }
        if ($script:extra) { [pscustomobject]@{ FullName=(Join-Path $root 'backend/app/new.py') } }
    }
    function Test-Path { param($LiteralPath, $PathType) return $true }
    function Get-FileHash { param($LiteralPath, $Algorithm)
        $script:paths += $LiteralPath
        [pscustomobject]@{ Hash= $(if ($LiteralPath -like '*main.py') { $script:revision } else { 'B' }) }
    }
    $a = Get-SourceFingerprint $root
    $script:revision = 'C'
    Assert-True ($a -ne (Get-SourceFingerprint $root)) '源码内容变化必须改变指纹。'
    $script:revision = 'A'
    $script:extra = $true
    Assert-True ($a -ne (Get-SourceFingerprint $root)) '新增 Python 文件必须改变指纹。'
    Assert-True (-not ($script:paths | Where-Object { $_ -match '\.env|secret|credential' })) '指纹不能包含秘密配置。'
}

& {
    $script:table = @{}
    $created = [datetime]::UtcNow.AddMinutes(-10)
    $argsText = '-m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000'
    $script:table[101] = [pscustomobject]@{ ProcessId=101; ParentProcessId=1; Name='python.exe'; CommandLine="venv/python.exe $argsText"; CreationDate=$created }
    $script:table[102] = [pscustomobject]@{ ProcessId=102; ParentProcessId=101; Name='python.exe'; CommandLine="base/python.exe $argsText"; CreationDate=$created.AddSeconds(1) }
    function Get-CimInstance { param($ClassName, $Filter, $ErrorAction)
        if ($Filter -match '^ProcessId = (\d+)$') { return $script:table[[int]$matches[1]] }
        if ($Filter -match '^ParentProcessId = (\d+)$') {
            $parentId = [int]$matches[1]
            return @($script:table.Values | Where-Object { $_.ParentProcessId -eq $parentId })
        }
        throw '不应查询全部真实进程。'
    }
    function Get-Process { param($Id, $ErrorAction)
        $item = $script:table[[int]$Id]
        if ($item) { [pscustomobject]@{ StartTime=$item.CreationDate } }
    }
    $ticks = $created.Ticks.ToString()
    $parent = Get-WorkspaceProcess 101 $ticks 'backend' 8000
    Assert-True ($null -ne $parent) '有效 launcher 应通过校验。'
    Assert-True (@(Get-WorkspaceBackendChildren $parent 8000).Count -eq 1) '应识别同一 uvicorn 子进程。'
    Assert-True ($null -eq (Get-WorkspaceProcess 101 '1' 'backend' 8000)) 'PID 回收/创建时间不符必须拒绝。'
    Assert-True ($null -eq (Get-WorkspaceProcess 101 $ticks 'backend' 8001)) '端口不符必须拒绝。'
    $script:table[102].CreationDate = $created.AddSeconds(-1)
    Assert-True (@(Get-WorkspaceBackendChildren $parent 8000).Count -eq 0) '早于父进程创建的子进程必须拒绝。'
    $script:table[102].CreationDate = $created.AddSeconds(1)
    $script:table[102].CommandLine = "base/python.exe $argsText --reload"
    Assert-True (@(Get-WorkspaceBackendChildren $parent 8000).Count -eq 0) '参数不同的 uvicorn 必须拒绝。'
    $script:table[102].CommandLine = 'python.exe unrelated.py --port 8000'
    Assert-True (@(Get-WorkspaceBackendChildren $parent 8000).Count -eq 0) '无关子进程必须拒绝。'
    $script:table[102].CommandLine = "base/python.exe $argsText"
    $script:table[102].ParentProcessId = 999
    Assert-True (@(Get-WorkspaceBackendChildren $parent 8000).Count -eq 0) '父子关系不同必须拒绝。'

    $script:table[102].ParentProcessId = 101
    $script:table[103] = [pscustomobject]@{ ProcessId=103; ParentProcessId=1; Name='node.exe'; CommandLine='node.exe node_modules/vite/bin/vite.js --port 5173'; CreationDate=$created }
    $script:stopped = @()
    $script:removed = $false
    $script:record = @{ root=$root; backendPid=101; backendStarted=$ticks; backendPort=8000; frontendPid=103; frontendStarted=$ticks; frontendPort=5173 }
    function Test-Path { param($LiteralPath) return $true }
    function Get-Content { param([switch]$Raw, $LiteralPath) return ($script:record | ConvertTo-Json) }
    function Stop-Process { param($Id)
        $script:stopped += [int]$Id
        $script:table.Remove([int]$Id)
    }
    function Wait-Process { param($Id, $Timeout, $ErrorAction) }
    function Test-WorkspacePort { param($Port) return $false }
    function Remove-Item { param($LiteralPath) $script:removed = $true }
    function Start-Sleep { param($Milliseconds) throw '模拟测试不应等待真实端口。' }
    $stopBody = ($asts['stop.ps1'].EndBlock.Statements | Where-Object {
        $_.Extent.StartLineNumber -ge ($asts['stop.ps1'].EndBlock.Statements | Where-Object { $_.Extent.Text -eq '$ErrorActionPreference = ''Stop''' }).Extent.StartLineNumber
    } | ForEach-Object { $_.Extent.Text }) -join "`n"
    $stopBody = $stopBody.Replace('$projectRoot = Split-Path -Parent $PSScriptRoot', '$projectRoot = $root')
    Invoke-Expression $stopBody
    Assert-True (($script:stopped -join ',') -eq '102,101,103') '停止应先子进程后 launcher，再停止前端。'
    Assert-True $script:removed '安全停止且端口释放后才应删除记录。'

    $script:table[101] = [pscustomobject]@{ ProcessId=101; ParentProcessId=1; Name='python.exe'; CommandLine="venv/python.exe $argsText"; CreationDate=$created.AddSeconds(2) }
    $script:stopped = @()
    $script:removed = $false
    $rejected = $false
    try { Invoke-Expression $stopBody } catch { $rejected = $true }
    Assert-True ($rejected -and $script:stopped.Count -eq 0 -and -not $script:removed) 'PID 已回收时不得停止进程或删除记录。'
}

# 只执行已记录实例分支；任何真实启动/停止/网络操作均由失败桩拦截。
& {
    $startAst = $asts['start.ps1']
    $recordBranch = $startAst.EndBlock.Statements | Where-Object { $_ -is [System.Management.Automation.Language.IfStatementAst] -and $_.Extent.Text.StartsWith('if (Test-Path -LiteralPath $statePath)') } | Select-Object -First 1
    Assert-True ($null -ne $recordBranch) '未找到复用入口。'
    $projectRoot = $root
    $statePath = 'mock-processes.json'
    $sourceFingerprint = 'current'
    $Restart = $false
    $NoBrowser = $true
    $script:record = @{ root=$root; backendPid=101; frontendPid=102; backendPort=8000; frontendPort=5173 }
    function Test-Path { param($LiteralPath) return $true }
    function Get-Content { param([switch]$Raw, $LiteralPath) return ($script:record | ConvertTo-Json) }
    function Get-WorkspaceProcess { throw '版本检查前不得检查进程。' }
    function Invoke-RestMethod { throw '测试禁止网络调用。' }
    function Invoke-WebRequest { throw '测试禁止网络调用。' }
    function Start-Process { throw '测试禁止启动进程。' }
    foreach ($fingerprint in @($null, 'old')) {
        $script:record.sourceFingerprint = $fingerprint
        $message = ''
        try { Invoke-Expression $recordBranch.Extent.Text } catch { $message = $_.Exception.Message }
        Assert-True ($message -like '*-Restart*' -and $message -like '*指纹*') '旧记录或源码更新必须明确拒绝复用。'
    }
    $script:record.sourceFingerprint = 'current'
    $script:record.url = 'mock-url'
    function Get-WorkspaceProcess { return [pscustomobject]@{ ProcessId=101 } }
    function Invoke-RestMethod { return [pscustomobject]@{ status='ok' } }
    function Invoke-WebRequest { return [pscustomobject]@{ StatusCode=200 } }
    Invoke-Expression $recordBranch.Extent.Text
}
Write-Host '脚本解析、指纹变化、旧版本拒绝复用及父子进程身份模拟验证通过；未启动或停止服务。'
