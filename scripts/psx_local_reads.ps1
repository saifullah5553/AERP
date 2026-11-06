# Registered as the Scheduled Task "AERP PSX Local Reads", weekdays after the PSX close.
# See psx_local_reads.py for why this has to run on this machine.
# Run manually with:  powershell -ExecutionPolicy Bypass -File scripts\psx_local_reads.ps1

$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo "backend\.venv\Scripts\python.exe"
$log = Join-Path $repo "data\psx_local_reads.log"

Add-Content -Path $log -Value "=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" -Encoding utf8
& $py (Join-Path $PSScriptRoot "psx_local_reads.py") 2>&1 | ForEach-Object {
  Add-Content -Path $log -Value "$_" -Encoding utf8
}
exit $LASTEXITCODE
