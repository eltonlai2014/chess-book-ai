# Wrapper for the "ChessBookSourceSync" scheduled task (daily 20:00).
#
# Purpose: detect SOURCE XQF changes (new games / edited annotes) and fold them
# into the pipeline. The nightly d28/d22/d32 tasks all read the already-built
# games.json and never re-scan the source library, so without this nothing picks
# up edits to D:\Elton\TestArea\chess-book\ (e.g. weekend game additions).
#
# Pipeline:
#   1. build_data.py -d 12   - re-scan ALL XQF, regenerate games.json (fresh
#      annotes), eval ONLY new FENs (incremental/resumable), migrate sqlite.
#      NOTE: incremental d12 build, NOT recompute_d12_full (does not delete
#      positions.js). No --auto-d12-recompute anywhere here.
#   2. enrich_decisive.py --depth 22 --no-post - deep-eval any new decisive
#      variations; --no-post so it doesn't render/commit (done once below).
#   3. ONLY IF data actually changed (hash of games.json / positions.js /
#      positions_deep.js differs) -> render + migrate + commit + push.
#      Avoids a no-op commit every night just to bump the dashboard stamp.
#
# Runs windowless via the task's S4U principal. ASCII-only on purpose: PS 5.1
# misreads non-ASCII in BOM-less .ps1 files, which would garble the commit msg.

Set-Location 'd:\Elton\TestArea\chess-book-ai'
$env:PYTHONIOENCODING = 'utf-8'
$py = '.\.venv\Scripts\python.exe'

$ts  = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$log = "output/source_sync_$ts.log"
"=== source sync start $ts ===" | Out-File -FilePath $log -Encoding utf8

function FileHash($p) { if (Test-Path $p) { (Get-FileHash $p -Algorithm MD5).Hash } else { '' } }
$watch = @('output/site/data/games.json', 'output/site/positions.js', 'output/site/positions_deep.js')
$before = $watch | ForEach-Object { FileHash $_ }

# 1. ingest source XQF (regenerate games.json, eval only new FENs, migrate sqlite)
& $py site_builder\build_data.py -d 12 *>&1 | Out-File -FilePath $log -Encoding utf8 -Append
# 2. deep-eval new public-book d22 candidates. --full-public = every public
#    position (no opening-skip / decisive cutoff) so new games land 100% d22.
#    中貴棋譜 still excluded (d12 baseline only). --no-post: render once below.
#    --max-hours 0.75: BOUNDED so a large backlog (e.g. a freshly-merged book
#    adding ~20k FENs) does a ~45min chunk here and finishes before the 21:00
#    d28 task instead of monopolising the engine for 30h. The dedicated 22:30
#    enrich_d22 task (--max-hours 8) owns the heavy lifting; both are resumable.
& $py site_builder\enrich_decisive.py --depth 22 --threads 4 --full-public --max-hours 0.75 --no-post *>&1 | Out-File -FilePath $log -Encoding utf8 -Append

$after = $watch | ForEach-Object { FileHash $_ }
$changed = $false
for ($i = 0; $i -lt $watch.Count; $i++) { if ($before[$i] -ne $after[$i]) { $changed = $true } }

if (-not $changed) {
  "[sync] no source changes - skipping render/publish" | Out-File -FilePath $log -Encoding utf8 -Append
} else {
  "[sync] source changed - render + migrate + publish" | Out-File -FilePath $log -Encoding utf8 -Append
  & $py site_builder\render_site.py        *>&1 | Out-File -FilePath $log -Encoding utf8 -Append
  & $py site_builder\migrate_to_sqlite.py  *>&1 | Out-File -FilePath $log -Encoding utf8 -Append
  git add docs/ output/site/ DEEP_STATUS.md 2>&1 | Out-File -FilePath $log -Encoding utf8 -Append
  git diff --cached --quiet
  if ($LASTEXITCODE -ne 0) {
    git commit -m "Source sync: ingest XQF changes (auto build_data + enrich + render)" 2>&1 | Out-File -FilePath $log -Encoding utf8 -Append
    git push 2>&1 | Out-File -FilePath $log -Encoding utf8 -Append
  } else {
    "[sync] staged tree clean after add - nothing to commit" | Out-File -FilePath $log -Encoding utf8 -Append
  }
}

"=== source sync done $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8 -Append
