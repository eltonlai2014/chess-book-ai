# Wrapper for ChessBookEnrichD22 scheduled task.
# Daily 22:30 → 06:30 d22 sweep over public-game positions (42 books).
# Resumable; tee-to-log; powercfg keepalive matches run_verify_d28_shunbao.ps1.

Set-Location 'd:\Elton\TestArea\chess-book-ai'
$env:PYTHONIOENCODING = 'utf-8'

powercfg /change standby-timeout-ac 0   2>&1 | Out-Null
powercfg /change monitor-timeout-ac 0   2>&1 | Out-Null
powercfg /change hibernate-timeout-ac 0 2>&1 | Out-Null

$ts = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$log = "output/enrich_d22_$ts.log"
"=== scheduled start $ts ===" | Out-File -FilePath $log -Encoding utf8

try {
  # --auto-d12-recompute: when d22 sweep clears (no deadline-hit + 0 remaining),
  # automatically chain into site_builder/recompute_d12_full.py to re-eval d12
  # with the new DFS+TT evaluator (D12_TT_SWEEP.md). One-shot, marker-blocked.
  # --full-public: cover EVERY public-book position at d22 (no opening-skip /
  # decisive cutoff) so new games are 100% covered the night they arrive.
  # 中貴棋譜 still excluded (d12 baseline only).
  .\.venv\Scripts\python.exe site_builder\enrich_decisive.py --depth 22 --full-public --max-hours 8 --auto-d12-recompute `
    *>&1 | Out-File -FilePath $log -Encoding utf8 -Append
} finally {
  powercfg /change standby-timeout-ac 30   2>&1 | Out-Null
  powercfg /change monitor-timeout-ac 15   2>&1 | Out-Null
  powercfg /change hibernate-timeout-ac 60 2>&1 | Out-Null
  "=== finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8 -Append
}
