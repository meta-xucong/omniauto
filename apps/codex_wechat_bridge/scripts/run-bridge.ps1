param(
    [string]$Config = "apps\codex_wechat_bridge\configs\default.example.json",
    [string]$Prompt = "",
    [switch]$Once,
    [switch]$Loop,
    [switch]$Bootstrap,
    [switch]$Send,
    [switch]$Monitor,
    [double]$IntervalSeconds = 5,
    [int]$MonitorPort = 0,
    [switch]$ResetState,
    [string]$ThreadId = "",
    [string]$Title = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

if ($Monitor) {
    $EntryPoint = Join-Path $RepoRoot "apps\codex_wechat_bridge\workflows\monitor_server.py"
} else {
    $EntryPoint = Join-Path $RepoRoot "apps\codex_wechat_bridge\workflows\bridge_loop.py"
}

$ArgsList = @($EntryPoint, "--config", $Config)
if ($Monitor) {
    if ($MonitorPort -gt 0) {
        $ArgsList += @("--port", [string]$MonitorPort)
    }
} else {
    if ($Prompt) {
        $ArgsList += @("--prompt", $Prompt)
    }
    if ($Once) {
        $ArgsList += "--once"
    }
    if ($Loop) {
        $ArgsList += @("--loop", "--interval-seconds", [string]$IntervalSeconds)
    }
    if ($Bootstrap) {
        $ArgsList += "--bootstrap"
    }
    if ($Send) {
        $ArgsList += "--send"
    }
    if ($ResetState) {
        $ArgsList += "--reset-state"
    }
    if ($ThreadId) {
        $ArgsList += @("--thread-id", $ThreadId)
    }
    if ($Title) {
        $ArgsList += @("--title", $Title)
    }
}
& $Python @ArgsList
