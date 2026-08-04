<#
Register the 30-minute refresh dispatcher as a Windows scheduled task.

Run ONCE, from this repo's root, after AERP_GH_TOKEN is set (see dispatch_refresh.ps1):

    powershell -File scripts\register_refresh_task.ps1

It runs as the logged-in user (no admin needed), every 30 minutes, indefinitely, and does
not wake or hold the machine. If the PC is off the workflow's own cron still covers it,
just less often.

To check it:      Get-ScheduledTask AERP-Refresh | Get-ScheduledTaskInfo
To run it now:    Start-ScheduledTask AERP-Refresh
To remove it:     Unregister-ScheduledTask AERP-Refresh -Confirm:$false
Log:              %LOCALAPPDATA%\AERP\refresh-dispatch.log
#>

$ErrorActionPreference = "Stop"

$name   = "AERP-Refresh"
$script = Join-Path $PSScriptRoot "dispatch_refresh.ps1"
if (-not (Test-Path $script)) { Write-Error "Not found: $script"; exit 1 }

$logDir = Join-Path $env:LOCALAPPDATA "AERP"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "refresh-dispatch.log"

# -WindowStyle Hidden so a console does not flash on screen every half hour.
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
    "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass " +
    "-File `"$script`" *>> `"$log`"")

# RepetitionDuration of [TimeSpan]::MaxValue means "forever" - a fixed duration would
# silently stop repeating after it elapsed, which is the classic way these tasks die quietly.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Description "Ask GitHub to refresh the AERP data snapshot." `
    -Force | Out-Null

Write-Output "Registered '$name' - every 30 minutes. Log: $log"
Write-Output "Testing it now..."
Start-ScheduledTask -TaskName $name
