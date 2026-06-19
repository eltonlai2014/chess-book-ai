# All-day full-speed d22 sweep for NON-WORKING days (machine idle 24h).
# Unlike run_enrich_d22.ps1 (nightly 22:30, 8h cap, 4 threads), this:
#   - uses 6 threads (all physical cores on the i7-8700; no headroom needed)
#   - has NO --max-hours cap: runs until the d22 sweep clears, then auto-chains
#     into recompute_d12_full.py via --auto-d12-recompute, then exits.
# Use during the 2026-06-19..06-21 window. DO NOT run concurrently with the
# nightly ChessBookEnrichD22 task — both write positions_deep.js. Pause the
# nightly task for the duration.

Set-Location 'd:\Elton\TestArea\chess-book-ai'
$env:PYTHONIOENCODING = 'utf-8'

powercfg /change standby-timeout-ac 0   2>&1 | Out-Null
powercfg /change monitor-timeout-ac 0   2>&1 | Out-Null
powercfg /change hibernate-timeout-ac 0 2>&1 | Out-Null

$ts = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$log = "output/enrich_d22_allday_$ts.log"
"=== allday start $ts (threads=6, no max-hours) ===" | Out-File -FilePath $log -Encoding utf8

try {
  .\.venv\Scripts\python.exe site_builder\enrich_decisive.py --depth 22 --full-public --threads 6 --auto-d12-recompute `
    *>&1 | Out-File -FilePath $log -Encoding utf8 -Append
} finally {
  powercfg /change standby-timeout-ac 30   2>&1 | Out-Null
  powercfg /change monitor-timeout-ac 15   2>&1 | Out-Null
  powercfg /change hibernate-timeout-ac 60 2>&1 | Out-Null
  "=== finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8 -Append
}
