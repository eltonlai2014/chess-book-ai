# Wrapper invoked by the Windows scheduled task "ChessBookVerifyDepth28".
# Logs everything to output/verify_traps_run.log so master can tail it.
Set-Location 'd:\Elton\TestArea\chess-book-ai'
$env:PYTHONIOENCODING = 'utf-8'
$ts = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$log = "output/verify_traps_run_$ts.log"
"=== scheduled start $ts ===" | Out-File -FilePath $log -Encoding utf8
py site_builder\verify_traps.py *>&1 | Out-File -FilePath $log -Encoding utf8 -Append
"=== finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8 -Append
