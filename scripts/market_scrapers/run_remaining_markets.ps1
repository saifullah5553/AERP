<#
Scrape the markets that have not been done yet, one at a time, unattended.

WHY THIS IS A SCHEDULED TASK AND NOT A DETACHED PROCESS. The previous version of this was
launched with Start-Process from a terminal. It wrote its first log line and was gone before the
US scrape it was waiting on had finished, so India never started and nobody knew until morning.
A detached process is still a child of whatever launched it and dies with the session, the job
object, or the sleep it did not survive. Register it with the task scheduler instead:

    scripts\market_scrapers\register_remaining_markets.ps1

The scheduler owns the process, restarts it if it dies, and starts it again at logon. That is
the difference between "it should keep running" and "it does".

ONE AT A TIME, DELIBERATELY. Two scrapers against stockanalysis.com from one IP is what tripped
the Cloudflare bot check during the US run. Each market here waits for every other scraper to
exit first, so this never adds a second concurrent session no matter when it fires.

Nothing is lost by running it early or twice: each scraper skips what is already on disk, and
the mutex means a second copy of this script exits rather than doubling up.

Log: %LOCALAPPDATA%\AERP\remaining-markets.log
#>

$ErrorActionPreference = "Continue"

$logDir = Join-Path $env:LOCALAPPDATA "AERP"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "remaining-markets.log"

function Write-Log([string]$msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
}

# Markets still to do, in order. Each is (script name, output folder).
$queue = @(
    @{ Script = "Stock Analysis CSV Data Tadawul.py"; Dir = "tadawul_data" },
    @{ Script = "Stock Analysis CSV Data DFM.py";     Dir = "dfm_data" }
)

$home_ = $env:USERPROFILE
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

# Single instance. Two copies would put two scrapers on the same folder, which corrupts both.
$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, "Global\AERP-Remaining-Markets", [ref]$createdNew)
if (-not $createdNew) {
    Write-Log "another copy already holds the lock - exiting"
    exit 0
}

function Get-RunningScrapers {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*Stock Analysis CSV Data*" }
}

function Wait-ForClearField([string]$forWhat) {
    # Heartbeat every 15 min. Silence for hours was the other half of the last failure: there
    # was no way to tell "waiting patiently" from "dead" without listing processes by hand.
    $waited = 0
    while ($true) {
        $running = Get-RunningScrapers
        if (-not $running) { return }
        Start-Sleep -Seconds 30
        $waited += 30
        if ($waited % 900 -eq 0) {
            $names = ($running | ForEach-Object {
                ($_.CommandLine -split 'Stock Analysis CSV Data ')[-1] -replace '\.py.*', ''
            } | Sort-Object -Unique) -join ', '
            Write-Log "waiting to start $forWhat - still running: $names ($($waited/60) min)"
        }
    }
}

Write-Log "=== started; queue: $(($queue | ForEach-Object { $_.Dir }) -join ', ')"

foreach ($market in $queue) {
    $script = Join-Path $home_ $market.Script
    if (-not (Test-Path $script)) {
        Write-Log "SKIP $($market.Dir): $script not found"
        continue
    }

    Wait-ForClearField $market.Dir

    Write-Log "starting $($market.Dir): $($market.Script)"
    & $python $script *>> $log
    $code = $LASTEXITCODE

    $n = (Get-ChildItem (Join-Path $home_ $market.Dir) -Filter *.csv -File -ErrorAction SilentlyContinue).Count
    Write-Log "$($market.Dir) exited with code $code - $n csv files on disk"
}

Write-Log "=== queue finished"
$mutex.ReleaseMutex()
