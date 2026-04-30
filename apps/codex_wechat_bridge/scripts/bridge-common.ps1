$ErrorActionPreference = "Stop"

function Get-CodexBridgeRepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
}

function Get-CodexBridgePython {
    param([string]$RepoRoot)

    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return "python"
}

function Resolve-CodexBridgeConfig {
    param(
        [string]$RepoRoot,
        [string]$Config
    )

    if ([System.IO.Path]::IsPathRooted($Config)) {
        return $Config
    }
    return (Join-Path $RepoRoot $Config)
}

function Get-CodexBridgeProcesses {
    $items = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and $_.CommandLine -match "codex_wechat_bridge"
    }
    return @($items)
}

function Get-CodexBridgeProcessRole {
    param([string]$CommandLine)

    if ($CommandLine -match "bridge_loop\.py") {
        return "loop"
    }
    if ($CommandLine -match "monitor_server\.py") {
        return "monitor"
    }
    if ($CommandLine -match "wxauto4_sidecar\.py") {
        return "wechat_sidecar"
    }
    return "bridge_python"
}

function Convert-CodexBridgeProcessRecord {
    param([object]$Process)

    $commandLine = [string]$Process.CommandLine
    return [ordered]@{
        process_id = $Process.ProcessId
        parent_process_id = $Process.ParentProcessId
        role = Get-CodexBridgeProcessRole -CommandLine $commandLine
        command_line = $commandLine
    }
}

function Get-CodexBridgeStatusName {
    param([object[]]$Processes)

    $roles = @($Processes | ForEach-Object { Get-CodexBridgeProcessRole -CommandLine ([string]$_.CommandLine) })
    $loopCount = @($roles | Where-Object { $_ -eq "loop" }).Count
    $monitorCount = @($roles | Where-Object { $_ -eq "monitor" }).Count
    if ($loopCount -gt 0) {
        if ($monitorCount -gt 0) {
            return "running"
        }
        return "loop_only"
    }
    if ($monitorCount -gt 0) {
        return "monitor_only"
    }
    return "stopped"
}

function Wait-CodexBridgeProcessesGone {
    param([int]$TimeoutSeconds = 20)

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    do {
        $remaining = @(Get-CodexBridgeProcesses)
        if ($remaining.Count -eq 0) {
            return @()
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    return @(Get-CodexBridgeProcesses)
}

function Stop-CodexBridgeProcesses {
    param([object[]]$Processes)

    foreach ($process in @($Processes)) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Get-CodexBridgeRuntimeRoot {
    param([string]$RepoRoot)
    return (Join-Path $RepoRoot "runtime\apps\codex_wechat_bridge")
}

function New-CodexBridgeRuntimeDirs {
    param([string]$RepoRoot)

    $runtimeRoot = Get-CodexBridgeRuntimeRoot -RepoRoot $RepoRoot
    foreach ($path in @(
        $runtimeRoot,
        (Join-Path $runtimeRoot "live_logs"),
        (Join-Path $runtimeRoot "live_logs\archive"),
        (Join-Path $runtimeRoot "state"),
        (Join-Path $runtimeRoot "test_artifacts")
    )) {
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }
    return $runtimeRoot
}

function Move-CodexBridgeLogsToArchive {
    param(
        [string]$RepoRoot,
        [int]$KeepArchives = 20
    )

    $runtimeRoot = New-CodexBridgeRuntimeDirs -RepoRoot $RepoRoot
    $logDir = Join-Path $runtimeRoot "live_logs"
    $archiveRoot = Join-Path $logDir "archive"
    $logs = @(Get-ChildItem -Path $logDir -File -Filter "*.log" -ErrorAction SilentlyContinue)
    if ($logs.Count -gt 0) {
        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $archiveDir = Join-Path $archiveRoot $stamp
        New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null
        foreach ($log in $logs) {
            Move-Item -LiteralPath $log.FullName -Destination (Join-Path $archiveDir $log.Name) -Force
        }
    }

    $oldArchives = @(Get-ChildItem -Path $archiveRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip ([Math]::Max(0, $KeepArchives)))
    foreach ($archive in $oldArchives) {
        Remove-Item -LiteralPath $archive.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Write-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Text
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $encoding)
}

function Write-CodexBridgeJson {
    param(
        [string]$Path,
        [object]$Payload
    )

    $json = $Payload | ConvertTo-Json -Depth 12
    Write-Utf8NoBom -Path $Path -Text ($json + [Environment]::NewLine)
}

function Write-CodexBridgeConsoleJson {
    param([object]$Payload)

    $json = $Payload | ConvertTo-Json -Depth 12
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    [Console]::Out.WriteLine($json)
    [Console]::Out.Flush()
}

function Invoke-CodexBridgeToast {
    param(
        [string]$Title,
        [string]$Message,
        [switch]$Disabled
    )

    if ($Disabled) {
        return $false
    }

    try {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        Add-Type -AssemblyName System.Drawing | Out-Null
        $notify = New-Object System.Windows.Forms.NotifyIcon
        $notify.Icon = [System.Drawing.SystemIcons]::Information
        $notify.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
        $notify.BalloonTipTitle = $Title
        $notify.BalloonTipText = $Message
        $notify.Text = "Codex WeChat Bridge"
        $notify.Visible = $true
        $notify.ShowBalloonTip(5000)
        Start-Sleep -Milliseconds 1200
        $notify.Dispose()
        return $true
    } catch {
        return $false
    }
}

function Get-CodexBridgeMonitorUrl {
    param([string]$ConfigPath)

    try {
        $config = Get-Content -Raw -Encoding UTF8 $ConfigPath | ConvertFrom-Json
        $hostValue = "127.0.0.1"
        $portValue = 17911
        if ($config.monitor.host) {
            $hostValue = [string]$config.monitor.host
        }
        if ($config.monitor.port) {
            $portValue = [int]$config.monitor.port
        }
        return "http://$hostValue`:$portValue"
    } catch {
        return "http://127.0.0.1:17911"
    }
}

function Get-CodexBridgeMonitorSnapshot {
    param([string]$MonitorUrl)

    try {
        return Invoke-RestMethod -Uri ($MonitorUrl.TrimEnd("/") + "/api/status") -TimeoutSec 5
    } catch {
        return $null
    }
}

function Wait-CodexBridgeFreshMonitorSnapshot {
    param(
        [string]$MonitorUrl,
        [datetime]$StartedAfter,
        [int]$TimeoutSeconds = 20
    )

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    $latest = $null
    do {
        $snapshot = Get-CodexBridgeMonitorSnapshot -MonitorUrl $MonitorUrl
        if ($snapshot) {
            $latest = $snapshot
            if ($snapshot.ok -and $snapshot.last_poll -and $snapshot.last_poll.at) {
                try {
                    $pollAt = [datetime]::Parse([string]$snapshot.last_poll.at)
                    if ($pollAt -ge $StartedAfter.AddSeconds(-1)) {
                        return $snapshot
                    }
                } catch {
                    return $snapshot
                }
            }
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    return $latest
}
