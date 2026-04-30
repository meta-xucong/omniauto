param(
    [string]$Config = "apps\codex_wechat_bridge\configs\default.example.json",
    [double]$IntervalSeconds = 3,
    [switch]$NoBootstrap,
    [switch]$NoMonitor,
    [switch]$NoToast,
    [int]$KeepLogArchives = 20,
    [int]$StartupWaitSeconds = 20
)

. "$PSScriptRoot\bridge-common.ps1"

$repoRoot = Get-CodexBridgeRepoRoot
$python = Get-CodexBridgePython -RepoRoot $repoRoot
$configPath = Resolve-CodexBridgeConfig -RepoRoot $repoRoot -Config $Config
$runtimeRoot = New-CodexBridgeRuntimeDirs -RepoRoot $repoRoot
$logDir = Join-Path $runtimeRoot "live_logs"
$stateDir = Join-Path $runtimeRoot "state"
$artifactDir = Join-Path $runtimeRoot "test_artifacts"
$monitorUrl = Get-CodexBridgeMonitorUrl -ConfigPath $configPath

$existing = @(Get-CodexBridgeProcesses)
if ($existing.Count -gt 0) {
    Stop-CodexBridgeProcesses -Processes $existing
    Wait-CodexBridgeProcessesGone -TimeoutSeconds 10 | Out-Null
}

Move-CodexBridgeLogsToArchive -RepoRoot $repoRoot -KeepArchives $KeepLogArchives

$clearStopScript = @'
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

repo = Path(sys.argv[1])
config_path = Path(sys.argv[2])
app_root = repo / "apps" / "codex_wechat_bridge"
for item in (app_root, app_root / "workflows"):
    sys.path.insert(0, str(item))
from bridge_loop import load_config, state_path

config = load_config(config_path)
path = state_path(config)
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        state = {"version": 1}
else:
    state = {"version": 1}
state["stop_requested"] = False
state["shutdown_requested_at"] = 0
state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(str(path))
'@

$statePath = $clearStopScript | & $python - $repoRoot $configPath

$bootstrapPath = Join-Path $artifactDir "startup_bootstrap.latest.json"
if (-not $NoBootstrap) {
    & $python (Join-Path $repoRoot "apps\codex_wechat_bridge\workflows\bridge_loop.py") --config $configPath --bootstrap |
        Out-File -Encoding utf8 $bootstrapPath
    if ($LASTEXITCODE -ne 0) {
        throw "Bootstrap failed; see $bootstrapPath"
    }
}

$monitorProcess = $null
$monitorOut = Join-Path $logDir "monitor.out.log"
$monitorErr = Join-Path $logDir "monitor.err.log"
if (-not $NoMonitor) {
    $monitorProcess = Start-Process -FilePath $python `
        -ArgumentList @((Join-Path $repoRoot "apps\codex_wechat_bridge\workflows\monitor_server.py"), "--config", $configPath) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $monitorOut `
        -RedirectStandardError $monitorErr `
        -PassThru
    Start-Sleep -Seconds 1
}

$loopOut = Join-Path $logDir "loop.out.log"
$loopErr = Join-Path $logDir "loop.err.log"
$startedAtDate = Get-Date
$loopProcess = Start-Process -FilePath $python `
    -ArgumentList @((Join-Path $repoRoot "apps\codex_wechat_bridge\workflows\bridge_loop.py"), "--config", $configPath, "--loop", "--send", "--interval-seconds", [string]$IntervalSeconds) `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $loopOut `
    -RedirectStandardError $loopErr `
    -PassThru

Start-Sleep -Seconds 2
$processes = @(Get-CodexBridgeProcesses)
$snapshot = if ($NoMonitor) { $null } else { Wait-CodexBridgeFreshMonitorSnapshot -MonitorUrl $monitorUrl -StartedAfter $startedAtDate -TimeoutSeconds $StartupWaitSeconds }
$startedAt = $startedAtDate.ToString("yyyy-MM-ddTHH:mm:ss")
$statusName = Get-CodexBridgeStatusName -Processes $processes

$payload = [ordered]@{
    status = $statusName
    started_at = $startedAt
    config = $configPath
    state_path = $statePath
    monitor_url = if ($NoMonitor) { $null } else { $monitorUrl }
    interval_seconds = $IntervalSeconds
    pids = @($processes | ForEach-Object { Convert-CodexBridgeProcessRecord -Process $_ })
    logs = [ordered]@{
        loop_out = $loopOut
        loop_err = $loopErr
        monitor_out = if ($NoMonitor) { $null } else { $monitorOut }
        monitor_err = if ($NoMonitor) { $null } else { $monitorErr }
    }
    bootstrap = if (Test-Path $bootstrapPath) { $bootstrapPath } else { $null }
    last_poll = if ($snapshot) { $snapshot.last_poll } else { $null }
    latest_run = if ($snapshot) { $snapshot.latest_run } else { $null }
}

$processPath = Join-Path $stateDir "processes.json"
Write-CodexBridgeJson -Path $processPath -Payload $payload

Invoke-CodexBridgeToast -Title "Codex WeChat Bridge running" -Message "Polling File Transfer Assistant. Monitor: $monitorUrl" -Disabled:$NoToast | Out-Null

Write-CodexBridgeConsoleJson -Payload $payload
