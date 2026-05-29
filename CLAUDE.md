# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Sibling doc**: [AGENTS.md](AGENTS.md) is the cross-machine / cross-agent onboarding playbook (also written for Codex). When state diverges, AGENTS.md is the more recent and detailed source.
>
> **Integration doc**: [SQLITE_EVAL_DB.md](SQLITE_EVAL_DB.md) — read this if you are touching anything that produces eval data (build_data, enrich_decisive, verify_traps, chessdb_query, render_site) or if you are working from the sibling [chess-book-editor](../chess-book-editor/) repo. The editor consumes `output/positions.db` read-only; this repo's pipeline still owns the source-of-truth `.js` / `.json` files.

## Project

Parses XQF Chinese-chess opening-book files from `D:\Elton\TestArea\chess-book\`, evaluates each pre-move position with Pikafish at two depths (12 + 22), and renders a static HTML site that surfaces book vs. engine disagreements — particularly "human traps" where shallow analysis says the book move is fine but a deeper search reveals a blunder.

Public demo: <https://eltonlai2014.github.io/chess-book-ai/> (auto-deployed from `/docs/`).

Two code paths exist:

1. **One-off Markdown analyser** ([analyze.py](analyze.py)) — original CLI, single XQF → single Markdown report.
2. **Static-site pipeline** ([site_builder/](site_builder/)) — what the public demo uses. All ongoing work happens here.

The site has three main pages:

- `index.html` — list of all games, with per-folder ⚠ trap badges + ✨ brilliant badges + per-game ★ decisive count + 深 coverage%.
- `traps.html` — every "human trap" the pipeline found (shallow loss < 50, deep loss > 100, ply ≥ 16), grouped by 目錄 → 棋譜. Currently 591 traps across 42 games.
- `brilliants.html` — inverse: plies where the mover's choice beat the engine's depth-22 best (gain 50–300cp, narrower band avoids horizon-effect noise). 481 candidates.

## Commands

Run on Windows via the per-repo venv at `.\.venv\Scripts\python.exe` (created with `py -m venv .venv`, cchess pinned to **1.25.5** — `from cchess import read_from_xqf` was dropped from public exports in 1.26). If Chinese output prints as mojibake, set `$env:PYTHONIOENCODING="utf-8"` before running.

```powershell
# --- one-off Markdown report ---
.\.venv\Scripts\python.exe analyze.py "D:\Elton\TestArea\chess-book\中砲對單提馬.XQF" -d 14 -o "output\中砲對單提馬.md"

# --- static-site pipeline (typical order) ---
.\.venv\Scripts\python.exe site_builder\build_data.py -d 12              # XQF → games.json + positions.js (shallow depth-12)
.\.venv\Scripts\python.exe site_builder\enrich_decisive.py --depth 22 --threads 4 --threshold 300
                                                  # depth-22 on variations whose final |shallow_score| > 300
.\.venv\Scripts\python.exe site_builder\chessdb_query.py                 # optional: fetch chessdb.cn winrate/score for plies 10-25
.\.venv\Scripts\python.exe site_builder\render_site.py                   # writes output/site/, mirrors → docs/ for GitHub Pages
.\.venv\Scripts\python.exe site_builder\render_site.py --fast            # skip [enrich] step; reuses existing positions_view.js.
                                                  # Auto-engages when positions_view.js is newer than every
                                                  # eval source — typical case for annote-only XQF edits.
.\.venv\Scripts\python.exe site_builder\sync_assets.py                   # FASTEST iteration: copy ONLY style.css + board.js to
                                                  # output/site + docs (<1s). Use for CSS/JS-only changes.
.\.venv\Scripts\python.exe site_builder\migrate_to_sqlite.py             # rebuild output/positions.db from positions*.js +
                                                  # chessdb_cache.json. Run after any enrich/render so the
                                                  # sibling chess-book-editor sees fresh evals. See SQLITE_EVAL_DB.md.

# --- depth-28 verification of traps ---
.\.venv\Scripts\python.exe site_builder\verify_traps.py                  # depth 28 over every (fen_before, fen_after) trap pair.
                                                  # Resumable, checkpoints every 5 FENs, auto-renders
                                                  # and pushes when done. See run_verify_traps.ps1 +
                                                  # the ChessBookVerifyDepth28 schtask for scheduled runs.

# --- analysis utilities ---
.\.venv\Scripts\python.exe site_builder\find_trap_plies.py               # CLI variant of the trap detector (top-20 print)
.\.venv\Scripts\python.exe site_builder\scan_brilliants.py               # CLI variant of the brilliant detector
.\.venv\Scripts\python.exe site_builder\depth_probe.py --game 牛頭滾 --variation 10 --ply 31 --depths 12,16,20,24
                                                  # convergence-vs-depth probe for one position
.\.venv\Scripts\python.exe site_builder\probe_depth28.py                 # time-probe depth 28 on a sample of trap FENs

# --- annote-fix helpers (for the ~209 broken-encoding annotes) ---
.\.venv\Scripts\python.exe site_builder\list_broken_annotes.py           # → output/broken_annotes.md (checklist for XQStudio)
.\.venv\Scripts\python.exe site_builder\suggest_annotes.py               # → output/suggested_annotes.md (engine-derived placeholders)
.\.venv\Scripts\python.exe site_builder\compare_annotes.py               # → output/annote_compare.md (AI/ vs original recovery)

# --- smoke tests (the test suite) ---
.\.venv\Scripts\python.exe smoke_engine.py
.\.venv\Scripts\python.exe smoke_xqf.py
```

There is no test runner, linter, or build step. The two `smoke_*.py` scripts are the test suite — run them after touching engine glue or XQF parsing.

### RTK prefix (token saver)

The master has `rtk` (Rust Token Killer) installed at `D:\tools\rtk\rtk.exe`. **Default to prefixing read-only / high-noise commands with `rtk`** when invoking via shell — it compresses stdout 60–98% before it reaches the model context. Windows native has no auto-hook, so the prefix must be explicit.

- ✅ Worth prefixing: `rtk git status`, `rtk find … -name "*.py"`, `rtk grep …`, `rtk read output/verify_traps_run_*.log`, `rtk pytest`, `rtk cargo …`.
- ⏸ No benefit (skip the prefix): `git diff` of real code, `git log` (already compact), Pikafish `info depth …` streams piped through Python scripts (rtk can't intercept Python stdout — pipe through `rtk pipe` or `rtk log` only if you specifically want log filtering).
- 🚫 Broken on Windows: `rtk tree` (Windows `tree.com` rejects rtk's unix-style ignore list — use `rtk find` instead).
- Check lifetime savings any time with `rtk gain`.

## Architecture

### One-off analyser ([analyze.py](analyze.py))

Three stages: XQF parse (`cchess.read_from_xqf` → `Game`), per-FEN dedup, Pikafish drive, Markdown render. Uses the legacy `cchess.UciEngine` driver, which still works fine for the single-position cadence of this CLI.

### Static-site pipeline ([site_builder/](site_builder/))

**Engine driver** — [`clean_eval.py`](site_builder/clean_eval.py):
- `CleanUciEngine` is a single-threaded synchronous Pikafish wrapper. **Use this everywhere instead of `cchess.UciEngine`** for batch evaluations: the cchess driver has a dual-stdout-reader race that corrupted ~85% of depth-22 entries before we caught it (memory note `project_cchess_engine_bug`). build_data.py, enrich_decisive.py, and verify_traps.py all use CleanUciEngine.

**Data layer** — [`build_data.py`](site_builder/build_data.py):
- Scans XQF library recursively, dedupes by filename (`_dedupe_by_name` keeps the cleanest-annotations version when case-duplicates exist).
- Per variation, walks plies with a fresh `ChessBoard`. Records pre-move FEN, ICCS, Chinese notation, `Move.annote`. `fen_after` is **NOT stored** — `hydrateGame()` in board.js derives it via `applyIccs()` at page load (saves ~25 MB on games.json).
- Builds a move-tree (`build_move_tree`) alongside the flat variations so the "本步可選" panel can list alternative continuations.
- Two text-fix-up helpers, both applied automatically:
  - `_recover_annote()` — many XQF annotations are Big5 bytes that cchess wrongly decodes as GB18030 (producing garbage like `磷砆溃`). Re-encode → decode-as-Big5, then score against an in-domain vocabulary whitelist (`common_chars.py`). ~20% of annotes need this fix.
  - `_to_trad()` — `cchess.to_text()` outputs Simplified (马/进/车); we substitute back to Traditional.
- Resumable: writes to `output/site/positions.js`, skips FENs already evaluated, checkpoints every 50 FENs.

**Deep-eval layer** — [`enrich_decisive.py`](site_builder/enrich_decisive.py):
- Targets variations whose final position has `|shallow_score| > 300` (one side clearly winning). Deep-evaluates every position in those variations to find where the score actually swung.
- Skips plies 1..`SKIP_OPENING_PLIES` (= 15) — opening theory comparison is misframed.
- Writes to `output/site/positions_deep.js`.

**Cloud-database layer** — [`chessdb_query.py`](site_builder/chessdb_query.py):
- Fetches chessdb.cn community winrate/score for FENs in plies 10–25 (the band where cloud coverage is dense). Caches in `output/site/data/chessdb_cache.json`.
- Watch for NUL-byte responses: the parser strips them before JSON-decode (fixed 2026-05-15).

**Trap-verification layer** — [`verify_traps.py`](site_builder/verify_traps.py):
- For each detected trap, re-evaluates both `fen_before` and `fen_after` at depth 28 (default). Saves to `output/site/positions_very_deep.js`.
- Resumable (skips FENs already at target depth). Supports `--max-hours` self-deadline for bounded overnight runs.
- The [`run_verify_traps.ps1`](site_builder/run_verify_traps.ps1) wrapper disables sleep/hibernate via `powercfg` and tees output to `output/verify_traps_run_<ts>.log`.
- Registered as Windows scheduled task `ChessBookVerifyDepth28` for nightly 21:00 → 10:00 runs. **594 FENs done / 1013 total as of 2026-05-20.**

**Render layer** — [`render_site.py`](site_builder/render_site.py):
- Loads positions + deep + very_deep + chessdb. Computes per-game stats (traps, brilliants, decisive count, deep coverage). Generates `index.html`, `traps.html`, `brilliants.html`, and one game page per XQF.
- `pv_detail` ships `iccs` + `chinese` only; `applyIccs()` in board.js derives the FEN each step (saves ~44 MB on positions_view.js).
- ASCII slug per game (`game-<sha1-10>.html`) avoids Live Server / GitHub Pages bugs on Chinese URLs.
- **`_enrich_is_current()` fast-path**: if `positions_view.js` is newer than positions.js + positions_deep.js + chessdb_cache.json, skip the slow `[enrich]` step entirely. Auto-engaged; explicit `--fast` flag also available.
- `positions_very_deep.js` is intentionally NOT in the source-mtime check — only the trap-stats panel consumes it, no enrich rebuild needed.
- **Mirrors `output/site/` → `docs/`** at the end. GitHub Pages source dropdown only allows `/(root)` or `/docs`.

**Front-end** — [`assets/board.js`](site_builder/assets/board.js), [`assets/style.css`](site_builder/assets/style.css):
- Board SVG, score chart, ply table, PV demo animation, annote box, 本步可選 panel, 3 themes (amber/emerald/ink), multiple board styles.
- All client-side, served via `<script src>` (no `fetch()`) so it works from `file://` too.
- `applyIccs(fen, iccs)` is the in-browser xiangqi mover used to derive `fen_after` on demand for PV demos and tree-lookup hydration.
- The "human trap" highlight (orange row + ⚠) and the ⑂ branch badge are computed in `annotateTable`. **Keep `SKIP_OPENING_PLIES` constant in sync with [`enrich_decisive.py`](site_builder/enrich_decisive.py), [`find_trap_plies.py`](site_builder/find_trap_plies.py), [`verify_traps.py`](site_builder/verify_traps.py), and [`render_site.py`](site_builder/render_site.py).**

### Engine binary + NNUE

`EXE` is hard-coded to `engine\Windows\pikafish-avx2.exe` (chosen for i7-8700 AVX2). Pikafish loads `pikafish.nnue` from the **same directory as the exe**. If you swap binaries, the `.nnue` must travel with it.

`engine/` is git-ignored (~120 MB binaries). Anyone cloning needs to grab Pikafish + NNUE separately.

### Score-display convention

`fmt_score()` reports centipawns from the **side-to-move's** perspective. The chart uses red-perspective via `redPerspectiveScore()`. The "loss" / "失分" formula in [`board.js:deltaCp`](site_builder/assets/board.js) is `red_perspective(i) - red_perspective(i+1)` then sign-flipped for black-to-move — positive means the moving side gave up cp.

For trap/brilliant computation server-side, `_ply_loss(plies, pi, table)` in render_site.py uses the simpler mover-POV formula: `score(fen[pi]) + score(fen[pi+1])` (both POV-relative).

## Gotchas worth knowing before editing

- **Never use `cchess.UciEngine` for batch work** — the dual-stdout-reader race corrupts entries silently. Use `CleanUciEngine` from `site_builder/clean_eval.py`.
- `ChessBoard.move_iccs(iccs)` MUTATES the board and returns a `Move` or `None`. Always check for `None` and follow with `board.next_turn()` to flip side-to-move. To get notation without mutating, clone via `ChessBoard(board.to_fen())` first.
- `info_move` events from the engine arrive continuously as depth deepens; only `bestmove` is terminal. Never return on the first `info_move`.
- The Markdown column header in [analyze.py](analyze.py) uses Chinese full-width characters — keep the column count stable, the trailing `|` matters for GFM table parsing.
- `Move.annote` is preserved by `game.dump_moves()` but **not** by `game.dump_iccs_moves()`. The site pipeline uses `dump_moves()` for this reason.
- Pikafish defaults to `Threads=1` and `Hash=16MB`. Multi-thread scaling at depth 22 is weak (~1.3× for 4 threads, not 4×). Larger `Hash` didn't help in shallow tests; depth-28 uses 512 MB by convention but no measured benefit.
- **Depth-28 timing has huge variance**: probe gave 31.5s/FEN, real runs averaged ~120s/FEN with individual FENs ranging 5s to 18min. Don't trust short probes for large overnight estimates.
- **Windows Update can hard-kill scheduled tasks**: on 2026-05-18 night, WU triggered three reboots between 00:30–00:37, killing verify_traps after 12/1013 FENs. Active Hours doesn't cover the 00:00–08:00 window. Use the schtask-friendly nightly window 21:00 → midnight, or manually pause updates for the duration of a long run.
- Two helpers in `build_data.py` (`_recover_annote`, `_to_trad`) are also imported into `render_site.py` and `fix_annotes.py`. If their signatures change, update both call sites.
- Game pages support deep-linking via `?v=&p=` (0-indexed). traps.html and brilliants.html generate these URLs to drop the user straight onto the right ply.
