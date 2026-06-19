# Parallel d22 sweep wrapper (replaces the 1x6-thread all-day approach).
# Orchestrates 3 Pikafish instances x 2 threads each (= 6 cores) via
# enrich_parallel.py — measured ~2.1x the old 1x6-thread sweep, ~-3cp signed
# divergence (negligible). Each worker writes its own shard; the orchestrator
# atomically merges into positions_deep.js, then render/migrate/push, then
# (if the sweep cleared) auto d12 DFS recompute.
#
# Non-working-day window 2026-06-19..21. Tear down + restore nightly on 6-22.
# Runs continuously (no --max-hours) until the d22 backlog is cleared.

Set-Location 'd:\Elton\TestArea\chess-book-ai'
$env:PYTHONIOENCODING = 'utf-8'

powercfg /change standby-timeout-ac 0   2>&1 | Out-Null
powercfg /change monitor-timeout-ac 0   2>&1 | Out-Null
powercfg /change hibernate-timeout-ac 0 2>&1 | Out-Null

$ts = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$log = "output/enrich_d22_parallel_$ts.log"
"=== parallel start $ts (3 shards x 2 threads) ===" | Out-File -FilePath $log -Encoding utf8

try {
  .\.venv\Scripts\python.exe site_builder\enrich_parallel.py `
    --num-shards 3 --threads 2 --depth 22 --full-public --auto-d12-recompute `
    --shard-dir output/_shards `
    *>&1 | Out-File -FilePath $log -Encoding utf8 -Append
} finally {
  powercfg /change standby-timeout-ac 30   2>&1 | Out-Null
  powercfg /change monitor-timeout-ac 15   2>&1 | Out-Null
  powercfg /change hibernate-timeout-ac 60 2>&1 | Out-Null
  "=== finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8 -Append
}
