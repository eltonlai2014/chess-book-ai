# Full 41-file build pipeline. Designed to run unattended overnight.
# Logs everything to output/nightly_<timestamp>.log so progress survives reboots.

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"

$REPO = "D:\Elton\TestArea\chess-book-ai"
Set-Location $REPO

$ts = Get-Date -Format "yyyyMMdd_HHmm"
$log = "$REPO\output\nightly_$ts.log"
New-Item -ItemType Directory -Force -Path "$REPO\output" | Out-Null

function Log { param($msg) "$(Get-Date -Format 'HH:mm:ss') $msg" | Tee-Object -FilePath $log -Append }

Log "=== nightly build starting ==="
Log "host: $env:COMPUTERNAME  user: $env:USERNAME"

# Stage 1: shallow eval of all unique FENs across all 41 XQF files (depth 12).
# Resumable — if existing positions.js has cached entries, only new FENs are
# evaluated. Threads stays at default (1) since this stage is engine-bound and
# resumable, leaving the machine usable if user wakes up early.
Log "[1/3] build_data.py depth=12 (full corpus)"
.\.venv\Scripts\python.exe site_builder\build_data.py -d 12 2>&1 | Tee-Object -FilePath $log -Append

# Stage 2: deep eval (depth 22) for plies in decisive variations. Threads=4
# to finish faster overnight. SKIP_OPENING_PLIES=15 already wired in.
Log "[2/3] enrich_decisive.py depth=22 threads=4"
.\.venv\Scripts\python.exe site_builder\enrich_decisive.py --depth 22 --threads 4 --threshold 300 2>&1 | Tee-Object -FilePath $log -Append

# Stage 3: render HTML site + mirror to docs/.
Log "[3/3] render_site.py"
.\.venv\Scripts\python.exe site_builder\render_site.py 2>&1 | Tee-Object -FilePath $log -Append

Log "=== nightly build done ==="
Log "next step (manual): git add docs/ output/site/data/games.json output/site/positions*.js && git commit && git push"
