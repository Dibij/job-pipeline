<#
.SYNOPSIS
    Configures Windows Task Scheduler to run the daily job pipeline at 06:00 local time.

.DESCRIPTION
    Creates or updates the scheduled task "JobPipelineDaily".
    Executes scripts/run_scheduled.py using the repository's virtual environment Python.
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

# Construct action, trigger, and settings
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "scripts\run_scheduled.py" -WorkingDirectory $RepoDir
$Trigger = New-ScheduledTaskTrigger -Daily -At 06:00
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Write-Host "================================================================="
Write-Host "  WINDOWS TASK SCHEDULER SETUP: $TaskName"
Write-Host "================================================================="
Write-Host "  Action:    $PythonExe scripts\run_scheduled.py"
Write-Host "  Working:   $RepoDir"
Write-Host "  Trigger:   Daily at 06:00 AM (local time)"
Write-Host "  Catch-up:  StartWhenAvailable (runs on wake if laptop was off)"
Write-Host "================================================================="

if ($DryRun) {
    Write-Host "[DRY RUN] Registration command:"
    Write-Host "Register-ScheduledTask -TaskName '$TaskName' -Action `$Action -Trigger `$Trigger -Settings `$Settings -Description 'Daily automated job search pipeline runner' -Force"
    exit 0
}

# Register task
try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Daily automated job search pipeline runner" -Force
    Write-Host "SUCCESS: Scheduled task '$TaskName' registered successfully." -ForegroundColor Green
    Write-Host "To verify: Get-ScheduledTask -TaskName '$TaskName'"
} catch {
    Write-Error "Failed to register scheduled task: $_"
    exit 1
}
