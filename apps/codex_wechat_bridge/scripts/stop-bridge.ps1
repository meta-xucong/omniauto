param(
    [string]$Config = "apps\codex_wechat_bridge\configs\default.example.json",
    [int]$TimeoutSeconds = 20,
    [switch]$GracefulOnly,
    [switch]$NoToast
)

. "$PSScriptRoot\bridge-common.ps1"

$repoRoot = Get-CodexBridgeRepoRoot
$python = Get-CodexBridgePython -RepoRoot $repoRoot
$configPath = Resolve-CodexBridgeConfig -RepoRoot $repoRoot -Config $Config
$runtimeRoot = New-CodexBridgeRuntimeDirs -RepoRoot $repoRoot
$stateDir = Join-Path $runtimeRoot "state"
$processPath = Join-Path $stateDir "processes.json"

$markerScript = @'
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
state["stop_requested"] = True
state["shutdown_requested_at"] = time.time()
state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(str(path))
'@

$statePath = $markerScript | & $python - $repoRoot $configPath

$before = @(Get-CodexBridgeProcesses)
$remaining = @(Wait-CodexBridgeProcessesGone -TimeoutSeconds $TimeoutSeconds)
$forced = $false
if ($remaining.Count -gt 0 -and -not $GracefulOnly) {
    Stop-CodexBridgeProcesses -Processes $remaining
    Start-Sleep -Seconds 1
    $forced = $true
}
$after = @(Get-CodexBridgeProcesses)
$stoppedAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
$statusName = Get-CodexBridgeStatusName -Processes $after

$payload = [ordered]@{
    status = if ($after.Count -eq 0) { "stopped" } else { $statusName }
    stopped_at = $stoppedAt
    config = $configPath
    state_path = $statePath
    requested_process_count = $before.Count
    forced = $forced
    remaining = @($after | ForEach-Object { Convert-CodexBridgeProcessRecord -Process $_ })
}

Write-CodexBridgeJson -Path $processPath -Payload $payload

$toastMessage = if ($after.Count -eq 0) { "Loop and monitor are stopped." } else { "Some bridge processes are still running." }
Invoke-CodexBridgeToast -Title "Codex WeChat Bridge stopped" -Message $toastMessage -Disabled:$NoToast | Out-Null

Write-CodexBridgeConsoleJson -Payload $payload
