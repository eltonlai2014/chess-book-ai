# Wrapper invoked by the Windows scheduled task "ChessBookVerifyD32".
# 19:00 start, no self-deadline — runs until the 56-FEN todo list is empty.
# Worst-case bound: 56 × ~18min ≈ 17h, so it will finish during the day.
# Same powercfg keepalive + tee-to-log pattern as run_verify_traps.ps1.

Set-Location 'd:\Elton\TestArea\chess-book-ai'
$env:PYTHONIOENCODING = 'utf-8'

powercfg /change standby-timeout-ac 0   2>&1 | Out-Null
powercfg /change monitor-timeout-ac 0   2>&1 | Out-Null
powercfg /change hibernate-timeout-ac 0 2>&1 | Out-Null

$ts = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$log = "output/verify_d32_run_$ts.log"
"=== scheduled start $ts ===" | Out-File -FilePath $log -Encoding utf8

try {
  py site_builder\verify_d32.py --checkpoint-every 5 `
    *>&1 | Out-File -FilePath $log -Encoding utf8 -Append
} finally {
  powercfg /change standby-timeout-ac 30   2>&1 | Out-Null
  powercfg /change monitor-timeout-ac 15   2>&1 | Out-Null
  powercfg /change hibernate-timeout-ac 60 2>&1 | Out-Null
  "=== finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8 -Append
}
