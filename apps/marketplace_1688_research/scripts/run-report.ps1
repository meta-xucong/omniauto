param(
    [Parameter(Mandatory = $true)]
    [string]$Keyword,

    [int]$Pages = 3,

    [int]$DetailSampleSize = 27,

    [string]$TaskSlug = "",

    [string]$ProfileDir = "runtime/apps/marketplace_1688_research/chrome_profile_1688_safe",

    [int]$CdpPort = 9232,

    [switch]$SkipCloseout,

    [switch]$Preview
)

$ErrorActionPreference = "Stop"

function Resolve-RepoPath {
    param([string]$PathValue)
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRoot $PathValue))
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$builder = Join-Path $repoRoot "apps\marketplace_1688_research\workflows\build_1688_workflow.py"
$closeoutHelper = Join-Path $repoRoot "apps\marketplace_1688_research\scripts\closeout_marketplace_run.py"

if (-not (Test-Path $python)) {
    throw "Python runtime not found: $python"
}
if (-not (Test-Path $builder)) {
    throw "Workflow builder not found: $builder"
}
if (-not (Test-Path $closeoutHelper)) {
    throw "Closeout helper not found: $closeoutHelper"
}

if (-not $TaskSlug) {
    $TaskSlug = "adhoc_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}

$builderArgs = @(
    $builder,
    "--repo-root", $repoRoot,
    "--keyword", $Keyword,
    "--pages", "$Pages",
    "--detail-sample-size", "$DetailSampleSize",
    "--task-slug", $TaskSlug
)

$builderOutput = & $python @builderArgs
$builderExitCode = $LASTEXITCODE
if ($builderExitCode -ne 0) {
    throw "Workflow generation failed with exit code $builderExitCode"
}

$generated = $builderOutput | ConvertFrom-Json
$workflowPath = $generated.workflow_path
$outputDir = $generated.output_dir
$profileDirResolved = Resolve-RepoPath $ProfileDir

if ($Preview.IsPresent) {
    Write-Output ("workflow: " + $workflowPath)
    Write-Output ("output_dir: " + $outputDir)
    Write-Output ("command: " + $python + " " + $workflowPath)
    if (-not $SkipCloseout.IsPresent) {
        $previewCloseout = @(
            $closeoutHelper,
            "--repo-root", $repoRoot,
            "--workflow", $workflowPath,
            "--output-dir", $outputDir,
            "--keyword", $Keyword,
            "--pages", "$Pages",
            "--detail-sample-size", "$DetailSampleSize",
            "--exit-code", "<workflow-exit-code>"
        )
        Write-Output ("closeout: " + $python + " " + ($previewCloseout -join " "))
    } else {
        Write-Output "closeout: skipped"
    }
    return
}

$env:PYTHONPATH = Join-Path $repoRoot "platform\src"
$env:OMNIAUTO_1688_PROFILE_DIR = $profileDirResolved
$env:OMNIAUTO_1688_BROWSER_MODE = "cdp_attach"
$env:OMNIAUTO_1688_CDP_PORT = "$CdpPort"
$env:OMNIAUTO_1688_REUSE_EXISTING_CDP = "1"

$runStartedAtEpoch = [DateTimeOffset]::Now.ToUnixTimeSeconds()
& $python $workflowPath
$workflowExitCode = $LASTEXITCODE

if (-not $SkipCloseout.IsPresent) {
    $closeoutArgs = @(
        $closeoutHelper,
        "--repo-root", $repoRoot,
        "--workflow", $workflowPath,
        "--output-dir", $outputDir,
        "--keyword", $Keyword,
        "--pages", "$Pages",
        "--detail-sample-size", "$DetailSampleSize",
        "--exit-code", "$workflowExitCode",
        "--run-start-epoch", "$runStartedAtEpoch"
    )
    & $python @closeoutArgs
    $closeoutExitCode = $LASTEXITCODE
    if ($closeoutExitCode -ne 0) {
        Write-Warning "Knowledge closeout failed with exit code $closeoutExitCode"
    }
}

exit $workflowExitCode

