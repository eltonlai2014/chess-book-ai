# Wrapper invoked by the Windows scheduled task "ChessBookVerifyDepth28".
# 1. Prevents the machine from sleeping while the engine runs (powercfg).
#    Note: doesn't override WU auto-reboot — Active Hours / pause-updates
#    is master's responsibility.
# 2. Self-bounds the verify_traps run to 13 hours via --max-hours, so a
#    21:00 start exits cleanly by 10:00 next morning if not finished.
# 3. Tees Python output to a timestamped log under output/ for tailing.

Set-Location 'd:\Elton\TestArea\chess-book-ai'
$env:PYTHONIOENCODING = 'utf-8'

# Keep the machine awake. powercfg is harmless if not admin (it just no-ops).
$prevStandby = (powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE | Select-String -Pattern 'Current AC Power Setting Index:').Line
powercfg /change standby-timeout-ac 0   2>&1 | Out-Null
powercfg /change monitor-timeout-ac 0   2>&1 | Out-Null
powercfg /change hibernate-timeout-ac 0 2>&1 | Out-Null

$ts = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$log = "output/verify_traps_run_$ts.log"
"=== scheduled start $ts ===" | Out-File -FilePath $log -Encoding utf8

try {
  .\.venv\Scripts\python.exe site_builder\verify_traps.py --max-hours 13 --checkpoint-every 5 `
    *>&1 | Out-File -FilePath $log -Encoding utf8 -Append
} finally {
  # Restore reasonable defaults so the machine sleeps normally afterwards.
  powercfg /change standby-timeout-ac 30   2>&1 | Out-Null
  powercfg /change monitor-timeout-ac 15   2>&1 | Out-Null
  powercfg /change hibernate-timeout-ac 60 2>&1 | Out-Null
  "=== finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8 -Append
}
