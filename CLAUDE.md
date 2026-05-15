# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Parses XQF Chinese-chess opening-book files from `D:\Elton\TestArea\chess-book\`, evaluates each pre-move position with Pikafish at two depths, and renders a static HTML site that surfaces book vs. engine disagreements — particularly "human traps" where shallow analysis says the book move is fine but a deeper search reveals a blunder.

Public demo: <https://eltonlai2014.github.io/chess-book-ai/> (auto-deployed from `/docs/`).

Two code paths exist:

1. **One-off Markdown analyser** ([analyze.py](analyze.py)) — original CLI, single XQF → single Markdown report.
2. **Static-site pipeline** ([site_builder/](site_builder/)) — what the public demo uses. Most new work happens here.

## Commands

Run on Windows with Python 3.10 (`py` launcher). If Chinese output prints as mojibake, set `$env:PYTHONIOENCODING="utf-8"` before running.

```powershell
# --- one-off Markdown report ---
py analyze.py "D:\Elton\TestArea\chess-book\中砲對單提馬.XQF" -d 14 -o "output\中砲對單提馬.md"

# --- static-site pipeline (typical order) ---
py site_builder\build_data.py -d 12              # XQF → games.json + positions.js (shallow depth-12 eval)
py site_builder\enrich_decisive.py --depth 22 --threads 4 --threshold 300
                                                  # deep-eval positions in "decisive" variations (skips first 15 plies)
py site_builder\render_site.py                   # writes output/site/, then mirrors → docs/ for GitHub Pages

# --- analysis utilities ---
py site_builder\find_trap_plies.py               # list "human traps": shallow OK + deep blunder + past opening
py site_builder\depth_probe.py --game 牛頭滾 --variation 10 --ply 31 --depths 12,16,20,24
                                                  # compare convergence across depths for one position

# --- smoke tests (the test suite) ---
py smoke_engine.py
py smoke_xqf.py
```

There is no test runner, linter, or build step. The two `smoke_*.py` scripts are the test suite — run them after touching engine glue or XQF parsing.

## Architecture

### One-off analyser ([analyze.py](analyze.py))

Three stages: XQF parse (`cchess.read_from_xqf` → `Game`), per-FEN dedup, Pikafish drive via `cchess.UciEngine` (NOT `UcciEngine` — Pikafish speaks UCI even though xiangqi convention is UCCI; `UcciEngine.wait_for_ready` hangs forever against Pikafish). Then Markdown render walks each variation and looks up cached engine results.

### Static-site pipeline ([site_builder/](site_builder/))

**Data layer** — [`build_data.py`](site_builder/build_data.py):
- Scans the XQF library recursively, dedupes by filename (`_dedupe_by_name` picks the version with the cleanest annotations across case-duplicates).
- Per variation, walks plies with a fresh `ChessBoard`, records pre-move FEN, post-move FEN, Chinese notation, ICCS, and `Move.annote`.
- Two text-fix-up helpers, both applied automatically:
  - `_recover_annote()` — many XQF annotations are Big5 bytes that cchess wrongly decodes as GB18030 (producing garbage like `磷砆溃`). Re-encode → decode-as-Big5, then score against an in-domain vocabulary whitelist (`common_chars.py`). About 20% of annotes need this fix.
  - `_to_trad()` — `cchess.to_text()` outputs Simplified (马/进/车); we substitute back to Traditional to match the rest of the UI.
- Resumable: writes to `output/site/positions.js` and skips FENs already evaluated. Periodic checkpoints every 50 FENs.

**Deep-eval layer** — [`enrich_decisive.py`](site_builder/enrich_decisive.py):
- Targets variations whose final position has `|shallow_score| > 300` (one side clearly winning). The mistake must be somewhere earlier; deep-search the whole variation to find where the score actually swung.
- Skips plies 1..`SKIP_OPENING_PLIES` (= 15) — opening theory comparison is misframed, see [`assets/board.js`](site_builder/assets/board.js) comment for the framing.
- Writes to `output/site/positions_deep.js`. The render step overlays these into `positions_view.js` so the UI can show both shallow and deep losses.

**Render layer** — [`render_site.py`](site_builder/render_site.py):
- Loads positions.js + positions_deep.js, computes `pv_detail` (each PV step with `fen_after` + Chinese notation) so the browser can animate without a chess library.
- Generates `output/site/games/game-<sha1-10>.html` per game (ASCII slug avoids Live Server / GitHub Pages bugs on Chinese URLs).
- **Mirrors `output/site/` → `docs/`** at the end. GitHub Pages source dropdown only allows `/(root)` or `/docs`, so mirroring is the simplest deploy path.

**Front-end** — [`assets/board.js`](site_builder/assets/board.js), [`assets/style.css`](site_builder/assets/style.css):
- Board SVG, score chart, ply table, PV demo animation, annote box. All client-side, served via `<script src>` (no `fetch()`) so it works from `file://` too.
- The "human trap" highlight (orange row + ⚠) fires when: shallow loss < 50, deep loss > 100, AND `pi >= SKIP_OPENING_PLIES`. **Keep this constant in sync with [`enrich_decisive.py`](site_builder/enrich_decisive.py) and [`find_trap_plies.py`](site_builder/find_trap_plies.py).**

### Engine binary + NNUE

`EXE` is hard-coded to `engine\Windows\pikafish-avx2.exe` (chosen for i7-8700 AVX2). Pikafish loads `pikafish.nnue` from the **same directory as the exe**. If you swap binaries, the `.nnue` must travel with it.

`engine/` is git-ignored (120 MB binaries). Anyone cloning needs to grab Pikafish + NNUE separately.

### Score-display convention

`fmt_score()` reports centipawns from the **side-to-move's** perspective. The chart uses red-perspective via `redPerspectiveScore()`. The "loss" / "失分" formula in [`board.js:deltaCp`](site_builder/assets/board.js) is `red_perspective(i) - red_perspective(i+1)` then sign-flipped for black-to-move — positive means the moving side gave up cp.

## Gotchas worth knowing before editing

- `ChessBoard.move_iccs(iccs)` MUTATES the board and returns a `Move` or `None`. Always check for `None` and follow with `board.next_turn()` to flip side-to-move. To get notation without mutating, clone via `ChessBoard(board.to_fen())` first.
- `info_move` events from the engine arrive continuously as depth deepens; only `bestmove` is terminal. Never return on the first `info_move`.
- The Markdown column header in [analyze.py](analyze.py) uses Chinese full-width characters — keep the column count stable, the trailing `|` matters for GFM table parsing.
- `Move.annote` is preserved by `game.dump_moves()` but **not** by `game.dump_iccs_moves()`. The site pipeline uses `dump_moves()` for this reason.
- Pikafish defaults to `Threads=1` and `Hash=16MB`. Multi-thread scaling at depth 22 is weak (~1.3× for 4 threads, not 4×). Larger `Hash` didn't help in tests — don't bother.
- Two helpers in `build_data.py` (`_recover_annote`, `_to_trad`) are also imported into `render_site.py` and `fix_annotes.py`. If their signatures change, update both call sites.
