param(
    [ValidateSet("single", "retry", "until_success")]
    [string]$Mode = "single",

    [int]$MaxAttempts = 0,

    [switch]$StopOnLoss,

    [double]$MaxRepeatFailureSeconds = -1,

    [int]$SingleAttemptSteps = 0,

    [switch]$SkipCloseout,

    [switch]$Preview
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..\\..\\..")).Path
$python = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
$solver = Join-Path $repoRoot "workflows\\temporary\\desktop\\minesweeper_solver.py"
$closeoutHelper = Join-Path $PSScriptRoot "closeout_solver_run.py"
$artifactsDir = Join-Path $repoRoot "runtime\\test_artifacts\\verification\\minesweeper"

if (-not (Test-Path $python)) {
    throw "Python runtime not found: $python"
}
if (-not (Test-Path $solver)) {
    throw "Solver not found: $solver"
}
if (-not (Test-Path $closeoutHelper)) {
    throw "Closeout helper not found: $closeoutHelper"
}

$arguments = @($solver, "--mode", $Mode)

if ($MaxAttempts -gt 0) {
    $arguments += @("--max-attempts", "$MaxAttempts")
}

if ($StopOnLoss.IsPresent) {
    $arguments += @("--stop-on-loss", "true")
}

if ($MaxRepeatFailureSeconds -gt 0) {
    $arguments += @("--max-repeat-failure-seconds", "$MaxRepeatFailureSeconds")
} elseif ($MaxRepeatFailureSeconds -eq 0) {
    $arguments += @("--max-repeat-failure-seconds", "0")
}

if ($SingleAttemptSteps -gt 0) {
    $arguments += @("--single-attempt-steps", "$SingleAttemptSteps")
}

if ($Preview.IsPresent) {
    Write-Output ("solver: " + $python + " " + ($arguments -join " "))
    if (-not $SkipCloseout.IsPresent) {
        $previewCloseout = @(
            $closeoutHelper,
            "--repo-root", $repoRoot,
            "--solver", $solver,
            "--artifacts-dir", $artifactsDir,
            "--mode", $Mode,
            "--exit-code", "<solver-exit-code>"
        )
        Write-Output ("closeout: " + $python + " " + ($previewCloseout -join " "))
    } else {
        Write-Output "closeout: skipped"
    }
    return
}

$runStartedAtEpoch = [DateTimeOffset]::Now.ToUnixTimeSeconds()
& $python @arguments
$solverExitCode = $LASTEXITCODE

if (-not $SkipCloseout.IsPresent) {
    $closeoutArguments = @(
        $closeoutHelper,
        "--repo-root", $repoRoot,
        "--solver", $solver,
        "--artifacts-dir", $artifactsDir,
        "--mode", $Mode,
        "--exit-code", "$solverExitCode",
        "--run-start-epoch", "$runStartedAtEpoch"
    )
    & $python @closeoutArguments
    $closeoutExitCode = $LASTEXITCODE
    if ($closeoutExitCode -ne 0) {
        Write-Warning "Knowledge closeout failed with exit code $closeoutExitCode"
    }
}

exit $solverExitCode
