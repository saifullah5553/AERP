# Local fundamentals refresh: who has reported, scrape them, merge, publish the store.
#
# Registered as a Scheduled Task ("AERP Earnings Fundamentals"), twice a week. A residential IP
# gets far fewer 429s than CI, so this works through what CI's daily budget has not reached.
# Run manually with:  powershell -ExecutionPolicy Bypass -File scripts\earnings_refresh_local.ps1
#
# It publishes ONLY data/fundamentals_ttm, through scripts/tip_files.py. It must never commit the
# snapshot: this checkout sits behind main, and the version this replaced did `git add
# frontend/public/data` and merged with -X ours, which would have put a stale snapshot over CI's.
# fundamentals-refresh.yml pushes the store into the company files and rescores on its next run.

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo "backend\.venv\Scripts\python.exe"
$log = Join-Path $repo "data\earnings_refresh.log"
$regions = @("us", "india", "australia", "gcc", "dfm")
$scrapeMinutes = 240
$maxSymbols = 2000

function Log($msg) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
  Write-Output $line
  Add-Content -Path $log -Value $line -Encoding utf8
}

# One scrape at a time: two from one IP is what brings on the 429s.
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*scrape_fundamentals*" }
if ($running) { Log "a scrape is already running - skipping this slot"; exit 0 }

Log "=== earnings refresh start ==="
Push-Location $repo

# 1. The tip's store and universe. Merging into a stale store would drop what CI has added.
$store = $regions | ForEach-Object { "data/fundamentals_ttm/$_.json.gz" }
& $py "scripts\tip_files.py" pull @store `
  "frontend/public/data/screener.json=data/tip_snapshot/screener.json" `
  "frontend/public/data/catalysts.json=data/tip_snapshot/catalysts.json" 2>&1 |
  ForEach-Object { Log $_ }
if ($LASTEXITCODE -ne 0) { Log "could not read the tip - stopping"; Pop-Location; exit 1 }

# 2. Who has results we do not hold, largest first.
Push-Location "backend"
foreach ($region in $regions) {
  & $py -m app.cli pending-results --region $region --data-dir "..\data\tip_snapshot" 2>&1 |
    Select-String -Pattern "pending-results:" | ForEach-Object { Log $_.Line }
}
Pop-Location
$symbols = @()
foreach ($region in $regions) {
  $file = "data\pending\$region.txt"
  if (Test-Path $file) {
    $symbols += Get-Content $file | Where-Object { $_ -and -not $_.StartsWith("#") }
  }
}
$symbols = $symbols | Select-Object -Unique
if (-not $symbols) { Log "nothing pending"; Pop-Location; exit 0 }
Log "pending: $($symbols.Count)"
# More than a run can fetch anyway, and a full list would pass Windows' 32k command-line limit.
$symbols = $symbols | Select-Object -First $maxSymbols

# 3. Scrape, within a budget.
& $py "scripts\scrape_fundamentals.py" --regions ($regions -join ",") `
  --symbols ($symbols -join ",") --workers 3 --page-pause 0.5 --work 900 --rest 0 `
  --max-minutes $scrapeMinutes 2>&1 | Select-String -Pattern "COMPLETE|time budget" |
  ForEach-Object { Log $_.Line }

# 4. Merge into the store, and publish only the store.
Push-Location "backend"
& $py -m app.cli consolidate-fundamentals --regions ($regions -join ",") --no-apply 2>&1 |
  Select-String -Pattern "fundamentals_store:" | ForEach-Object { Log $_.Line }
Pop-Location
$message = Join-Path $repo "data\earnings_refresh_commit.txt"
Set-Content -Path $message -Encoding ascii -Value "data: fundamentals scraped locally for companies that reported"
& $py "scripts\tip_files.py" push $message @store 2>&1 | ForEach-Object { Log $_ }

Pop-Location
Log "=== earnings refresh done ==="
