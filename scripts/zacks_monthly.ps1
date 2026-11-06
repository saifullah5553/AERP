# Registered as the Scheduled Task "AERP Zacks Monthly", last day of each month.
# See zacks_monthly.py. Run by hand with:
#   powershell -ExecutionPolicy Bypass -File scripts\zacks_monthly.ps1

$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo "backend\.venv\Scripts\python.exe"
$log = Join-Path $repo "data\zacks_monthly.log"

Add-Content -Path $log -Value "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" -Encoding utf8
& $py (Join-Path $PSScriptRoot "zacks_monthly.py") 2>&1 | ForEach-Object {
  Add-Content -Path $log -Value "$_" -Encoding utf8
}
exit $LASTEXITCODE
