param(
    [string]$Config = "apps\codex_wechat_bridge\configs\default.example.json"
)

. "$PSScriptRoot\bridge-common.ps1"

$repoRoot = Get-CodexBridgeRepoRoot
$configPath = Resolve-CodexBridgeConfig -RepoRoot $repoRoot -Config $Config
$runtimeRoot = New-CodexBridgeRuntimeDirs -RepoRoot $repoRoot
$stateDir = Join-Path $runtimeRoot "state"
$processPath = Join-Path $stateDir "processes.json"
$monitorUrl = Get-CodexBridgeMonitorUrl -ConfigPath $configPath
$processes = @(Get-CodexBridgeProcesses)
$snapshot = Get-CodexBridgeMonitorSnapshot -MonitorUrl $monitorUrl
$statusName = Get-CodexBridgeStatusName -Processes $processes

$payload = [ordered]@{
    status = $statusName
    checked_at = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    config = $configPath
    monitor_url = $monitorUrl
    process_count = $processes.Count
    processes = @($processes | ForEach-Object { Convert-CodexBridgeProcessRecord -Process $_ })
    monitor = if ($snapshot) {
        [ordered]@{
            ok = $snapshot.ok
            generated_at = $snapshot.generated_at
            active_thread_id = $snapshot.active_thread_id
            last_poll = $snapshot.last_poll
            latest_run = $snapshot.latest_run
        }
    } else {
        $null
    }
    process_file = if (Test-Path $processPath) { $processPath } else { $null }
}

Write-CodexBridgeConsoleJson -Payload $payload
