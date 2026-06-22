# Generic parallel deep-eval wrapper — d22 / traps(d28) / d32 via parallel_runner.py.
# Replaces run_enrich_d22_parallel.ps1. NON-WORKING-DAY use (weekday CPU stays free).
#
#   run_parallel.ps1 -Job traps           # d28 trap-pair verify (3x2 threads)
#   run_parallel.ps1 -Job d32             # d32 順包 cross-check
#   run_parallel.ps1 -Job d22             # full-public d22 backlog blitz
#   run_parallel.ps1 -Job traps -Threads 4 -NumShards 2   # less thread-count drift
#
# Each worker writes its own shard in output/_shards; the orchestrator merges once
# then runs the job's post (render/migrate/push). Runs to completion (no --max-hours).

param(
  [Parameter(Mandatory = $true)][ValidateSet('d22', 'traps', 'd32')][string]$Job,
  [int]$NumShards = 3,
  [int]$Threads = 2
)

Set-Location 'd:\Elton\TestArea\chess-book-ai'
$env:PYTHONIOENCODING = 'utf-8'

powercfg /change standby-timeout-ac 0   2>&1 | Out-Null
powercfg /change monitor-timeout-ac 0   2>&1 | Out-Null
powercfg /change hibernate-timeout-ac 0 2>&1 | Out-Null

$ts = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$log = "output/parallel_${Job}_$ts.log"
"=== parallel $Job start $ts ($NumShards shards x $Threads threads) ===" | Out-File -FilePath $log -Encoding utf8

try {
  .\.venv\Scripts\python.exe site_builder\parallel_runner.py `
    --job $Job --num-shards $NumShards --threads $Threads --shard-dir output/_shards `
    *>&1 | Out-File -FilePath $log -Encoding utf8 -Append
} finally {
  powercfg /change standby-timeout-ac 30   2>&1 | Out-Null
  powercfg /change monitor-timeout-ac 15   2>&1 | Out-Null
  powercfg /change hibernate-timeout-ac 60 2>&1 | Out-Null
  "=== finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8 -Append
}
