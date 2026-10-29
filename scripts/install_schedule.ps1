<#
.SYNOPSIS
    Configures Windows Task Scheduler to run the daily job pipeline on every startup/logon.

.DESCRIPTION
    Creates or updates the scheduled task "JobPipelineDaily".
    Trigger: AtLogon (fires every time this user logs in / laptop boots).
    The pipeline itself enforces a once-per-day guard via data/last_successful_run.txt,
    so the task fires on every startup but only does real work once per calendar day.
    If the pipeline was interrupted (laptop closed mid-run), it will resume on next boot.
#>

param(
    [switch]$DryRun
)

$TaskName = "JobPipelineDaily"
$RepoDir = "d:\Code\Job"
$PythonExe = Join-Path $RepoDir ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $RepoDir "scripts\run_scheduled.py"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Virtual environment python executable not found at: $PythonExe"
    exit 1
}

if (-not (Test-Path $ScriptPath)) {
    Write-Error "Scheduled runner script not found at: $ScriptPath"
    exit 1
}

# Action: run the scheduled wrapper with Ollama triage enabled
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "scripts\run_scheduled.py" `
    -WorkingDirectory $RepoDir

# Trigger: fire at every logon of the current user
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

# Settings:
#   - StartWhenAvailable: if the laptop was off when the task was due, run it on next boot
#   - ExecutionTimeLimit: cap at 2 hours (pipeline is usually ~5-10 min)
#   - AllowStartIfOnBatteries / DontStopIfGoingOnBatteries: works on laptops
#   - MultipleInstances: IgnoreNew (file lock in script also protects, but belt-and-suspenders)
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

Write-Host "================================================================="
Write-Host "  WINDOWS TASK SCHEDULER SETUP: $TaskName"
Write-Host "================================================================="
Write-Host "  Action:    $PythonExe scripts\run_scheduled.py"
Write-Host "  Working:   $RepoDir"
Write-Host "  Trigger:   AtLogon (every startup/login, once per day guard in script)"
Write-Host "  Catch-up:  StartWhenAvailable (runs on next boot if missed)"
Write-Host "  Stamp:     data\last_successful_run.txt tracks today's run"
Write-Host "================================================================="

if ($DryRun) {
    Write-Host "[DRY RUN] Would register task '$TaskName' with AtLogon trigger."
    exit 0
}

# Register task
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "Daily job search pipeline. Fires at logon, runs once per day (guard in script). Ollama triage enabled." `
        -Force
    Write-Host "SUCCESS: Scheduled task '$TaskName' registered." -ForegroundColor Green
    Write-Host "To verify:  Get-ScheduledTask -TaskName '$TaskName'"
    Write-Host "To run now: Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host "To remove:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
} catch {
    Write-Error "Failed to register scheduled task: $_"
    exit 1
}
