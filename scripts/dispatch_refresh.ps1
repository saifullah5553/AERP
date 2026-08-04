<#
Trigger the "Refresh Demo Data" workflow from this PC, so the site actually updates on a
30-minute cadence.

WHY THIS EXISTS
  The workflow already carries a 30-minute cron. GitHub does not honour it. Measured over
  8 days: the schedule asked for 48 runs a day and GitHub STARTED 3-7. The runs were not
  failing - 44 of the 48 that started succeeded - they were simply never launched, because
  scheduled Actions are best-effort and get dropped when the shared runner pool is busy.

  A workflow_dispatch is not best-effort. It is an explicit API call and it always runs.
  So this PC - which is already on around the clock for the scrapers - asks for the run,
  and the cron stays as a backstop for when the PC is off.

SETUP (once)
  1. Make a fine-grained token: https://github.com/settings/personal-access-tokens/new
     Repository access -> Only select repositories -> saifullah5553/AERP
     Permissions -> Repository permissions -> Actions -> Read and write
     Nothing else. That token can start workflows in this one repo and do nothing else.
  2. Store it for your user account only (NOT in the repo - it is a credential):
       setx AERP_GH_TOKEN "github_pat_xxxxxxxx"
     Then open a NEW terminal so the variable exists.
  3. Register the schedule (see register_refresh_task.ps1).

Run it by hand any time to force an immediate refresh:
    powershell -File scripts\dispatch_refresh.ps1
#>

$ErrorActionPreference = "Stop"

$token = $env:AERP_GH_TOKEN
if (-not $token) {
    Write-Error "AERP_GH_TOKEN is not set. See the setup notes at the top of this file."
    exit 1
}

$uri = "https://api.github.com/repos/saifullah5553/AERP/actions/workflows/refresh-data.yml/dispatches"
$headers = @{
    Authorization          = "Bearer $token"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "AERP-refresh-dispatcher"
}

# TLS 1.2 is not the default in Windows PowerShell 5.1 and github.com refuses anything less.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

try {
    Invoke-RestMethod -Uri $uri -Method Post -Headers $headers `
        -Body '{"ref":"main"}' -ContentType "application/json" | Out-Null
    Write-Output "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  refresh dispatched"
} catch {
    # Never throw: a failed dispatch (laptop asleep, wifi down, token rotated) must not stop
    # the next attempt 30 minutes later. Just leave a line in the log saying what happened.
    Write-Output "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  dispatch FAILED: $($_.Exception.Message)"
    exit 1
}
