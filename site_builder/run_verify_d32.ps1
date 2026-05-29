# Wrapper invoked by the Windows scheduled task "ChessBookVerifyD32".
# 21:00 daily start, --max-hours 8 self-deadline (resumable across runs).
# Same powercfg keepalive + tee-to-log pattern as run_verify_traps.ps1.
#
# Why --max-hours 8: schtask is "Interactive only" + machine has aggressive
# Modern Standby, so the wrapper sometimes gets killed before its run finishes.
# The deadline forces extra checkpoints + clean post-render before something
# external kills us.

Set-Location 'd:\Elton\TestArea\chess-book-ai'
$env:PYTHONIOENCODING = 'utf-8'

powercfg /change standby-timeout-ac 0   2>&1 | Out-Null
powercfg /change monitor-timeout-ac 0   2>&1 | Out-Null
powercfg /change hibernate-timeout-ac 0 2>&1 | Out-Null

$ts = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$log = "output/verify_d32_run_$ts.log"
"=== scheduled start $ts ===" | Out-File -FilePath $log -Encoding utf8

try {
  .\.venv\Scripts\python.exe site_builder\verify_d32.py --max-hours 8 --checkpoint-every 5 `
    *>&1 | Out-File -FilePath $log -Encoding utf8 -Append
} finally {
  powercfg /change standby-timeout-ac 30   2>&1 | Out-Null
  powercfg /change monitor-timeout-ac 15   2>&1 | Out-Null
  powercfg /change hibernate-timeout-ac 60 2>&1 | Out-Null
  "=== finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8 -Append
}
