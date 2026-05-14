# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Single-purpose CLI tool: parse XQF Chinese-chess opening-book files from `D:\Elton\TestArea\chess-book\`, feed each pre-move position to the Pikafish engine, and emit a per-step Markdown comparison of book move vs. engine choice. See [README.md](README.md) for full user-facing documentation (output format, score conventions, roadmap).

## Commands

Run on Windows with Python 3.10 (`py` launcher) — paths in this repo are absolute Windows paths.

```powershell
# Analyse one XQF file → Markdown
py analyze.py "D:\Elton\TestArea\chess-book\中砲對單提馬.XQF" -d 14 -o "output\中砲對單提馬.md"

# Smoke-test engine (UCI handshake + depth-14 search from initial position)
py smoke_engine.py

# Smoke-test XQF parsing (dump cchess Game attrs + ICCS variation list)
py smoke_xqf.py
```

There is no test suite, linter, or build step. The two `smoke_*.py` scripts ARE the test suite — run them after changes to engine glue or XQF parsing.

If Chinese output prints as mojibake, set `$env:PYTHONIOENCODING="utf-8"` before running.

## Architecture

The whole pipeline lives in [analyze.py](analyze.py) — ~180 lines, no package layout. Three stages:

1. **XQF parse** (`analyze_file`): `cchess.read_from_xqf(path)` returns a `Game` whose `.dump_iccs_moves()` flattens the variation tree into a list of ICCS move-strings per line. `game.init_board` is a `ChessBoard` object — call `.to_fen()` on it, never `str()`.

2. **Position dedup**: walk every variation with a fresh `ChessBoard`, collect each pre-move FEN into a dict (`unique_positions[fen]`). Book variations share long prefixes, so this typically cuts engine calls by ~2×. After dedup, the engine sees each unique FEN exactly once; results are stored in `eval_cache[fen]` and looked up again during rendering.

3. **Engine drive** (`run_engine`): uses `cchess.UciEngine`, NOT `UcciEngine` — Pikafish speaks UCI even though Chinese-chess convention is UCCI. `UcciEngine.wait_for_ready` hangs forever against Pikafish. The loop polls `eng.get_action()` with a 60 s wall-clock cap and returns on `bestmove` / `dead` / `draw`.

4. **Markdown render** (`render_markdown`): re-walks each variation, looks up cached engine result by FEN, formats one row per ply. Uses a throwaway `ChessBoard` clone inside `iccs_to_text` so move-to-Chinese conversion never mutates the rendering board.

### Engine binary + NNUE

`EXE` is hard-coded at the top of [analyze.py](analyze.py) to `engine\Windows\pikafish-avx2.exe` (chosen for i7-8700 AVX2, no AVX-512). Pikafish loads `pikafish.nnue` from the **same directory as the exe** — `engine\pikafish.nnue` exists at the repo root for reference, and a copy lives next to the exe in `engine\Windows\`. If you move or swap the exe (e.g. to `pikafish-bmi2.exe` on a newer CPU), the `.nnue` must travel with it.

### Score-display convention

`fmt_score()` reports centipawns from the **side-to-move's** perspective — so the same row's "+50" means red is up half a pawn on red's turn, but black is up half a pawn on black's turn. This is the engine's native convention; do NOT silently normalise to red-perspective unless the user asks (README §8.2 tracks this as a deferred feature).

## Gotchas worth knowing before editing

- `ChessBoard.move_iccs(iccs)` MUTATES the board and returns a `Move` or `None` (illegal). Always check for `None` and follow with `board.next_turn()` to flip side-to-move. If you need notation without mutating, clone via `ChessBoard(board.to_fen())` first — `iccs_to_text` already does this.
- `info_move` events from the engine arrive continuously as depth deepens; only `bestmove` is terminal. Don't return on the first `info_move` or you'll get a depth-1 result.
- The output column header line uses Chinese full-width characters — keep the column count stable when editing `render_markdown`, the trailing `|` matters for GFM table parsing.
