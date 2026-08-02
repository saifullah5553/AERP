# Gentle, resumable fundamentals backfill - one modest batch per run.
#
# yfinance hard-throttles long hammering runs (a single big pass stalls in backoff), so instead
# of one marathon we take a small batch each time and let a Scheduled Task repeat it. Coverage
# converges over days without tripping the rate limiter. Fully resumable: names already scored
# (or marked fund_na) are skipped, and every raw fetch is cached.
#
# Manual run:  powershell -ExecutionPolicy Bypass -File scripts\fundamentals_batch_local.ps1
# Optional:    -BatchSize 400

param([int]$BatchSize = 250)

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo "backend\.venv\Scripts\python.exe"
$log = Join-Path $repo "data\fundamentals_batch.log"

function Log($msg) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
  Write-Output $line
  Add-Content -Path $log -Value $line -Encoding utf8
}

# Don't stack runs, and don't race any OTHER snapshot writer either. Everything below writes
# screener.json, so two of them at once means last-writer-wins and a half-updated snapshot.
# Skipping a slot is free - the next one is only four hours away.
$writers = @(
  "*refresh-fundamentals-web*", "*refresh-technicals*", "*model-portfolio*",
  "*refresh-prices*", "*refresh-sectors*", "*expand-universe*", "*backfill_quality*"
)
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $cl = $_.CommandLine; $writers | Where-Object { $cl -like $_ } }
if ($running) { Log "another snapshot writer is running - skipping this slot"; exit 0 }

Log "=== batch start (size $BatchSize) ==="

Push-Location (Join-Path $repo "backend")
& $py -m app.cli refresh-fundamentals-web --region all --limit $BatchSize 2>&1 |
  Select-String -Pattern "refresh-fundamentals-web:" | ForEach-Object { Log $_.Line }

# Keep market breadth + securities count in step with the new scores.
& $py "..\scripts\consolidate_snapshot.py" 2>&1 | ForEach-Object { Log $_ }
Pop-Location

# Commit + push only on a real change (push triggers the Pages deploy).
Push-Location $repo
git add frontend/public/data 2>&1 | Out-Null
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
  git commit -q -m "data: fundamentals backfill batch" 2>&1 | Out-Null
  git pull --no-rebase -X ours --no-edit origin main 2>&1 | Out-Null
  git push origin main 2>&1 | Out-Null
  Log "committed + pushed"
} else {
  Log "no data changes (likely rate-limited - will retry next slot)"
}
Pop-Location

Log "=== batch done ==="
