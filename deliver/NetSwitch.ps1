#requires -Version 5.1
<#
.SYNOPSIS
  有线 / WiFi 出网切换工具（核心脚本，可独立使用）

.DESCRIPTION
  Windows 选路比较的是「默认路由 RouteMetric + 接口 InterfaceMetric」之和，不是只看接口跃点。
  本脚本把目标网卡接口跃点固定为 5，其它物理网卡设为一个足够大的动态值
  （自动覆盖默认路由自带偏置，公司有线网常见 256），并关闭「自动跃点」；
  切换后还会用 Find-NetRoute 实测确认，不再盲报成功。
  加 -Hard 会额外禁用另一张网卡（彻底断开，但会短暂断网）。
  修改网络配置需要管理员权限，脚本会自动请求 UAC 提权。
  默认用 223.5.5.5 探测实际出网；特殊网络可用 -ProbeIP 换一个公网地址。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File NetSwitch.ps1 -List
  powershell -ExecutionPolicy Bypass -File NetSwitch.ps1 -Use 17
  powershell -ExecutionPolicy Bypass -File NetSwitch.ps1 -Toggle
  powershell -ExecutionPolicy Bypass -File NetSwitch.ps1 -Toggle -Hard
  powershell -ExecutionPolicy Bypass -File NetSwitch.ps1 -Reset
#>
[CmdletBinding()]
param(
    [switch]$List,
    [switch]$Status,
    [switch]$Toggle,
    [string]$Use,
    [switch]$Reset,
    [switch]$Hard,
    [switch]$JsonB64,
    [string]$Disable,
    [string]$Enable,
    [switch]$NoElevate,
    [int]$PreferredMetric = 5,
    [int]$BackupMetric = 200,
    [string]$ProbeIP = '223.5.5.5'
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding          = [System.Text.Encoding]::UTF8
$ErrorActionPreference   = 'Stop'

# ---------------- 权限 ----------------
function Test-Admin {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

function Get-ParamString {
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($k in $PSBoundParameters.Keys) {
        $v = $PSBoundParameters[$k]
        if ($v -is [System.Management.Automation.SwitchParameter]) {
            if ($v.IsPresent) { $parts.Add("-$k") }
        } else {
            $parts.Add("-$k")
            $s = ([string]$v).Replace('"', '\"')
            $parts.Add('"' + $s + '"')
        }
    }
    return ($parts -join ' ')
}

$needsWrite = $Toggle.IsPresent -or $Reset.IsPresent -or $Use -or $Disable -or $Enable
if ($needsWrite -and -not (Test-Admin)) {
    if ($NoElevate) {
        Write-Host "[错误] 需要管理员权限才能修改网络配置，请以管理员身份运行。" -ForegroundColor Red
        exit 1
    }
    $p       = Get-ParamString
    $psExe   = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $argLine = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" ' + $p + ' -NoElevate'
    try {
        Start-Process -FilePath $psExe -ArgumentList $argLine -Verb RunAs | Out-Null
        Write-Host "已申请管理员权限，请在 UAC 窗口确认，结果在新窗口显示。"
        exit 0
    } catch {
        Write-Host "[错误] 提权失败：$($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# ---------------- 网卡信息 ----------------
function Get-AdapterList {
    $all = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
        $_.HardwareInterface -eq $true -and $_.Status -ne 'Not Present'
    })
    $result = @()
    foreach ($a in $all) {
        $idx  = [int]$a.ifIndex
        $kind = '其它'
        if ($a.MediaType -match '802\.11|Wireless|Wi-?Fi') { $kind = 'WiFi' }
        elseif ($a.MediaType -match '802\.3')               { $kind = '有线' }

        $ip = ''
        try {
            $o = Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                 Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' } |
                 Select-Object -First 1
            if ($o) { $ip = [string]$o.IPAddress }
        } catch {}

        $gw = ''
        try {
            $r = Get-NetRoute -InterfaceIndex $idx -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                 Select-Object -First 1
            if ($r) { $gw = [string]$r.NextHop }
        } catch {}

        $metric = 0
        $auto   = ''
        try {
            $i = Get-NetIPInterface -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                 Select-Object -First 1
            if ($i) { $metric = [int]$i.InterfaceMetric; $auto = [string]$i.AutomaticMetric }
        } catch {}

        $result += [pscustomobject]@{
            Name       = [string]$a.Name
            IfIndex    = $idx
            Kind       = $kind
            Status     = [string]$a.Status
            LinkSpeed  = [string]$a.LinkSpeed
            IP         = $ip
            Gateway    = $gw
            MetricV4   = $metric
            AutoMetric = $auto
            IsUp       = ($a.Status -eq 'Up')
        }
    }
    return $result
}

function Get-ActiveIndex {
    # Find-NetRoute 直接问系统「去这个地址会走哪块网卡」，最权威
    try {
        $r = Find-NetRoute -RemoteIPAddress $ProbeIP -ErrorAction Stop | Select-Object -First 1
        if ($r -and $r.InterfaceIndex) { return [int]$r.InterfaceIndex }
    } catch {}
    # 后备：默认路由的 RouteMetric + InterfaceMetric 最小者
    try {
        $best = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -ErrorAction Stop |
            ForEach-Object {
                $m = 0
                try {
                    $i = Get-NetIPInterface -InterfaceIndex $_.ifIndex -AddressFamily IPv4 -ErrorAction Stop | Select-Object -First 1
                    if ($i) { $m = [int]$i.InterfaceMetric }
                } catch {}
                [pscustomobject]@{ Idx = [int]$_.ifIndex; Total = ([int]$_.RouteMetric + $m) }
            } | Sort-Object Total | Select-Object -First 1
        if ($best) { return [int]$best.Idx }
    } catch {}
    return 0
}

function Get-MaxDefaultRouteMetric {
    # Windows 选路比较的是 (默认路由 RouteMetric + 接口 InterfaceMetric) 之和。
    # 公司有线网常给 0.0.0.0/0 自带 256 的 RouteMetric（WiFi 一般为 0），
    # 只把接口跃点设成 5/200 时差距不够，有线依然会输。这里取最大值作为偏置。
    $max = 0
    try {
        $routes = @()
        $routes += @(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -ErrorAction SilentlyContinue)
        $routes += @(Get-NetRoute -DestinationPrefix '::/0'      -AddressFamily IPv6 -ErrorAction SilentlyContinue)
        foreach ($r in $routes) {
            $m = 0
            try { $m = [int]$r.RouteMetric } catch {}
            if ($m -gt $max) { $max = $m }
        }
    } catch {}
    return $max
}

function Resolve-Adapter([string]$key) {
    $adapterList = @(Get-AdapterList)
    $n    = 0
    $hit  = $null
    if ([int]::TryParse($key, [ref]$n)) {
        $hit = $adapterList | Where-Object { $_.IfIndex -eq $n } | Select-Object -First 1
    } else {
        $hit = $adapterList | Where-Object { $_.Name -eq $key -or $_.Kind -eq $key } | Select-Object -First 1
    }
    if (-not $hit) { throw "找不到网卡：$key（用 -List 查看可用网卡）" }
    return $hit
}

# ---------------- 写操作 ----------------
function Set-FixedMetric([int]$idx, [int]$metric) {
    foreach ($af in @('IPv4', 'IPv6')) {
        $done = $false
        try {
            Set-NetIPInterface -InterfaceIndex $idx -AddressFamily $af `
                -InterfaceMetric $metric -AutomaticMetric Disabled -ErrorAction Stop | Out-Null
            $done = $true
        } catch {}
        if (-not $done) {
            # netsh 对 Disconnected 状态的接口也能设，作为后备
            $proto = if ($af -eq 'IPv4') { 'ipv4' } else { 'ipv6' }
            $null = & netsh interface $proto set interface "$idx" "metric=$metric" 2>&1
        }
    }
}

function Reset-AutoMetric([int]$idx) {
    foreach ($af in @('IPv4', 'IPv6')) {
        try {
            Set-NetIPInterface -InterfaceIndex $idx -AddressFamily $af -AutomaticMetric Enabled -ErrorAction Stop | Out-Null
        } catch {}
    }
    $null = & netsh interface ipv4 set interface "$idx" metric=automatic 2>&1
    $null = & netsh interface ipv6 set interface "$idx" metric=automatic 2>&1
}

function Set-AdapterPower([string]$name, [bool]$on) {
    try {
        if ($on) { Enable-NetAdapter  -Name $name -Confirm:$false -ErrorAction Stop | Out-Null }
        else     { Disable-NetAdapter -Name $name -Confirm:$false -ErrorAction Stop | Out-Null }
        return $true
    } catch {
        $state = if ($on) { 'enabled' } else { 'disabled' }
        $null = & netsh interface set interface "name=$name" "admin=$state" 2>&1
        return ($LASTEXITCODE -eq 0)
    }
}

function Clear-DnsCacheSafe {
    try { Clear-DnsClientCache -ErrorAction SilentlyContinue } catch {}
}

# ---------------- 主流程 ----------------
$failed  = $false
$message = ''

try {
    if ($Disable) {
        $a = Resolve-Adapter $Disable
        if (Set-AdapterPower $a.Name $false) { $message = "已禁用网卡：$($a.Name)" }
        else { throw "禁用失败：$($a.Name)（可能被组策略或驱动限制）" }

    } elseif ($Enable) {
        $a = Resolve-Adapter $Enable
        if (Set-AdapterPower $a.Name $true) { $message = "已启用网卡：$($a.Name)" }
        else { throw "启用失败：$($a.Name)" }

    } elseif ($Reset) {
        $adapterList = @(Get-AdapterList)
        foreach ($a in $adapterList) {
            Reset-AutoMetric $a.IfIndex
            if ($a.Status -eq 'Disabled') { Set-AdapterPower $a.Name $true | Out-Null }
        }
        Clear-DnsCacheSafe
        $message = "已恢复 $($adapterList.Count) 张物理网卡的「自动跃点」，并重新启用被禁用的网卡。系统重新按链路速度自动选路。"

    } elseif ($Use -or $Toggle) {
        if ($Use) {
            $target = Resolve-Adapter $Use
        } else {
            $adapterList   = @(Get-AdapterList)
            $active = Get-ActiveIndex
            $cands  = @($adapterList | Where-Object { $_.Kind -in @('有线', 'WiFi') })
            if ($cands.Count -lt 2) {
                throw "需要至少一张有线 + 一张 WiFi 网卡才能来回切换（当前识别到 $($cands.Count) 张）"
            }
            $upOthers = @($cands | Where-Object { $_.IfIndex -ne $active -and $_.IsUp })
            if ($upOthers.Count -eq 0) {
                throw "另一张网卡当前未连接，没有可切换的目标。请先连上 WiFi 或插好网线。"
            }
            $target = $upOthers[0]
        }

        $useHard = $Hard.IsPresent
        if ($useHard) {
            # 先全部启用，否则上次被禁用的那张没法参与切换
            foreach ($a in @(Get-AdapterList)) {
                if ($a.Status -eq 'Disabled') { Set-AdapterPower $a.Name $true | Out-Null }
            }
            Start-Sleep -Seconds 2
        }
        $adapterList   = @(Get-AdapterList)
        $target = $adapterList | Where-Object { $_.IfIndex -eq $target.IfIndex } | Select-Object -First 1

        if (-not $target -or -not $target.IsUp) {
            $st = if ($target) { $target.Status } else { '不存在' }
            throw "目标网卡「$($target.Name)」当前状态为 $st，未连接，切换会断网，已中止。"
        }

        $others = @($adapterList | Where-Object { $_.IfIndex -ne $target.IfIndex })

        # 备份跃点必须盖过默认路由自带的 RouteMetric，否则 5/200 翻不过 256 的偏置。
        # 留 50 点余量，并限制在接口跃点合法上限内。
        $routeBias       = Get-MaxDefaultRouteMetric
        $effectiveBackup = [Math]::Min(9999,
                             [Math]::Max($BackupMetric, ($routeBias + $PreferredMetric + 50)))
        Set-FixedMetric $target.IfIndex $PreferredMetric
        foreach ($o in $others) { Set-FixedMetric $o.IfIndex $effectiveBackup }

        if ($useHard -and $others.Count -ge 1) {
            foreach ($o in $others) {
                if ($o.Kind -in @('有线', 'WiFi')) { Set-AdapterPower $o.Name $false | Out-Null }
            }
        }
        Clear-DnsCacheSafe

        # 实测校验：不再盲报「已切换」。VPN / 策略路由 / 组策略都可能夺走默认路由。
        $verified = $false
        for ($n = 0; $n -lt 3 -and -not $verified; $n++) {
            Start-Sleep -Milliseconds 400
            $verified = ((Get-ActiveIndex) -eq $target.IfIndex)
        }
        if (-not $verified) {
            $act     = Get-ActiveIndex
            $actObj  = @(Get-AdapterList) | Where-Object { $_.IfIndex -eq $act } | Select-Object -First 1
            $actName = if ($actObj) { $actObj.Name } else { "ifIndex=$act" }
            throw "跃点已写入（目标 $PreferredMetric / 其它 $effectiveBackup），但系统实际出网仍是「$actName」。请执行 route print -4 检查活跃路由跃点数，通常是 VPN / 虚拟网卡或组策略注入了更优路由。"
        }

        $how = ''
        if ($useHard) { $how = '，并已禁用其它网卡' }
        $message = "已切换出网到「$($target.Name)」（$($target.Kind)，ifIndex=$($target.IfIndex)）：跃点固定为 $PreferredMetric，其它网卡设为 $effectiveBackup（已抵消默认路由偏置 $routeBias）$how。实测确认当前出网已走该网卡，已有 TCP 连接不会自动迁移，新连接立即生效。"

    } elseif ($Status) {
        $act = Get-ActiveIndex
        $a   = @(Get-AdapterList) | Where-Object { $_.IfIndex -eq $act } | Select-Object -First 1
        if ($a) { $message = "当前出网：$($a.Name)（$($a.Kind)，$($a.IP)）" }
        else    { $message = "未检测到活动默认路由" }
    } else {
        $List = $true
    }
} catch {
    $failed  = $true
    $message = $_.Exception.Message
    try {
        $message = $message +
            ' | LINE: '  + [string]$_.InvocationInfo.Line +
            ' | POS: '   + [string]$_.InvocationInfo.PositionMessage +
            ' | STACK: ' + [string]$_.ScriptStackTrace
    } catch {}
}

# ---------------- 输出 ----------------
if ($JsonB64) {
    $payload = [ordered]@{
        ok          = (-not $failed)
        message     = $message
        activeIndex = (Get-ActiveIndex)
        adapters    = @(Get-AdapterList)
    }
    $json = $payload | ConvertTo-Json -Compress -Depth 6
    $b64  = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($json))
    Write-Output ('<<<NS:' + $b64 + ':NS>>>')
} else {
    if (-not $Status) {
        $act  = Get-ActiveIndex
        $rows = @()
        foreach ($x in @(Get-AdapterList)) {
            $star = ''
            if ($x.IfIndex -eq $act) { $star = '★' }
            $rows += [pscustomobject]@{
                Idx = $x.IfIndex
                名称 = $x.Name
                类型 = $x.Kind
                状态 = $x.Status
                IP  = $x.IP
                网关 = $x.Gateway
                跃点 = $x.MetricV4
                自动 = $x.AutoMetric
                出网 = $star
            }
        }
        Write-Host ""
        Write-Host "=== 物理网卡（★ = 当前出网） ===" -ForegroundColor Cyan
        Write-Host ""
        $rows | Format-Table -AutoSize | Out-String -Width 220 | Write-Host
        Write-Host ""
        $cur = $rows | Where-Object { $_.出网 -eq '★' } | Select-Object -First 1
        if ($cur) { Write-Host "当前出网：$($cur.名称)（$($cur.类型)）" -ForegroundColor Green }
    }
    if ($message) {
        if ($failed) { Write-Host "[失败] $message" -ForegroundColor Red }
        else         { Write-Host $message -ForegroundColor Green }
    }
    if ($NoElevate) {
        Write-Host ""
        Read-Host "按回车关闭窗口" | Out-Null
    }
}

if ($failed) { exit 1 }
