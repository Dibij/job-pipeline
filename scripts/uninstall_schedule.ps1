<#
.SYNOPSIS
    Uninstalls the daily job pipeline scheduled task from Windows Task Scheduler.
#>

$TaskName = "JobPipelineDaily"

Write-Host "Unregistering scheduled task '$TaskName'..."
try {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "SUCCESS: Task '$TaskName' has been removed." -ForegroundColor Green
    } else {
        Write-Host "Task '$TaskName' does not exist. Nothing to remove." -ForegroundColor Yellow
    }
} catch {
    Write-Error "Failed to unregister scheduled task: $_"
    exit 1
}
