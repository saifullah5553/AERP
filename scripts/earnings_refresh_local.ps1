# Local (residential-IP) earnings-driven fundamentals refresh - the reliable counterpart to
# .github/workflows/earnings-fundamentals.yml, which no-ops because yfinance rate-limits CI.
#
# Refreshes fundamentals ONLY for US/India/Australia companies whose earnings date just passed,
# regenerates market breadth, and commits + pushes (which triggers the Pages deploy).
#
# Registered as a Scheduled Task ("AERP Earnings Fundamentals") to run twice a week.
# Run manually with:  powershell -ExecutionPolicy Bypass -File scripts\earnings_refresh_local.ps1

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo "backend\.venv\Scripts\python.exe"
$log = Join-Path $repo "data\earnings_refresh.log"

function Log($msg) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
  Write-Output $line
  Add-Content -Path $log -Value $line -Encoding utf8
}

Log "=== earnings refresh start ==="

# 1. Who just reported? (blank = nothing to do)
Push-Location $repo
$syms = & $py "scripts\earnings_refresh_symbols.py" 5 120
Pop-Location
if ([string]::IsNullOrWhiteSpace($syms)) { Log "no companies reported recently - nothing to do"; exit 0 }
$count = ($syms -split ",").Count
Log "refreshing $count symbol(s)"

# 2. Re-fetch their fundamentals (force = bypass the statement cache; their numbers changed).
Push-Location (Join-Path $repo "backend")
& $py -m app.cli refresh-fundamentals-web --region all --symbols $syms --force 2>&1 |
  Select-String -Pattern "refresh-fundamentals-web:" | ForEach-Object { Log $_.Line }

# 3. Regenerate market breadth + securities count so the dashboard stays consistent.
& $py "..\scripts\consolidate_snapshot.py" 2>&1 | ForEach-Object { Log $_ }
Pop-Location

# 4. Commit + push only when something actually changed (push triggers the Pages deploy).
Push-Location $repo
git add frontend/public/data 2>&1 | Out-Null
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
  git commit -q -m "chore: refresh fundamentals for companies that just reported" 2>&1 | Out-Null
  git pull --no-rebase -X ours --no-edit origin main 2>&1 | Out-Null
  git push origin main 2>&1 | Out-Null
  Log "committed + pushed"
} else {
  Log "no data changes"
}
Pop-Location

Log "=== earnings refresh done ==="
