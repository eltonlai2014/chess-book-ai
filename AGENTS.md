# AGENTS.md

Onboarding playbook for any AI agent (Claude Code, Codex, etc.) picking up this repo — possibly from a different machine than the primary workstation.

If you're a brand-new agent: read this top-to-bottom once, then refer back to [CLAUDE.md](CLAUDE.md) for the architecture and gotchas deep-dive.

## What this project does

Take 42 Chinese-chess opening-book files (XQF format, hand-curated by master over years), run them through Pikafish at depths 12 + 22 + 28, and surface the positions where the book and the engine disagree on the right move. The headline finding is "human traps": moves the book recommends that depth-12 thinks are fine but depth-22 reveals as blunders.

Public demo: <https://eltonlai2014.github.io/chess-book-ai/> — auto-deployed from `/docs/`.

## Current state (as of 2026-05-20)

- **Shallow eval (depth 12)**: 37,316 unique FENs evaluated. Full coverage of every position in every variation.
- **Deep eval (depth 22)**: 15,035 FENs (decisive variations only). All clean after the [`CleanUciEngine`](site_builder/clean_eval.py) rewrite (the old `cchess.UciEngine` driver had a stdout race that corrupted ~85% of entries).
- **Very-deep eval (depth 28)**: in progress — 593 / 1013 FENs done (~58%). Running nightly 21:00 → 10:00 on master's PC via Windows scheduled task `ChessBookVerifyDepth28`.
- **chessdb.cn cloud DB**: 7,630 FENs cached for plies 10–25.
- **Traps detected**: 591 unique. **Brilliants detected**: 481 unique (gain 50–300cp band).
- **Annote fixing**: ~209 broken-encoding annotes still need manual touch-up in XQStudio. Master works through these case-by-case. See [`output/broken_annotes.md`](output/broken_annotes.md) for the checklist.

## Master's working style

- Address master as **「尊敬的主人」** (Traditional Chinese honorific). Master is fluent in tech English and Traditional Chinese — write in 繁體中文 by default.
- **Terse**. One- or two-sentence updates beat paragraphs. No "I'll now do X" preamble; just do it and report briefly.
- **Pushes back on sloppy interpretation of engine output** — don't claim a position is "winning" because depth-12 says +200; explain the depth and confidence.
- **Pre-authorized automation**: when a long-running engine task finishes, **automatically** run `render_site.py`, `git add docs/ output/site/`, `git commit`, `git push`. This pattern landed on 2026-05-16 with `redo_deep.py` and is the convention. The auto-commit message should be specific (what was added, why).
- Master sometimes runs **two Claude/Codex sessions in parallel** (e.g., main session here + a separate UI-design session). Don't be surprised if files change under your feet — `git pull --rebase` before any commit if you weren't the last one to write.

## Engine setup (needed on any machine that runs the heavy scripts)

The `engine/` directory is git-ignored (binaries too big). To bootstrap a fresh machine:

1. Download a recent Pikafish build matching the CPU (i7-8700 = AVX2). [pikafish/Pikafish](https://github.com/official-pikafish/Pikafish) releases.
2. Drop `pikafish-avx2.exe` (or platform equivalent) into `engine/Windows/`.
3. Drop the matching `pikafish.nnue` into the **same directory as the exe**. Pikafish loads NNUE relative to its own working directory; if the NNUE goes missing the engine silently runs without it and gives garbage scores.
4. Verify: `py smoke_engine.py` — should print a few `info depth N score cp X` lines and exit cleanly.

The repo hard-codes `engine/Windows/pikafish-avx2.exe`. If you're on macOS/Linux you'll need to either change `EXE` in [`site_builder/clean_eval.py`](site_builder/clean_eval.py), [`site_builder/verify_traps.py`](site_builder/verify_traps.py), etc., or symlink the binary. The site itself (output/, docs/) is platform-independent.

## Distributed verify_traps — multi-machine coordination

Master has a primary workstation (Windows) running verify_traps nightly. The depth-28 pass is the bottleneck (~120s/FEN average, ~1013 FENs total, ~33 hours total CPU time). Master may delegate part of this to a second machine running Codex.

**Coordination protocol (zero-code, git-only):**

1. The cache file is `output/site/positions_very_deep.js` — a single JSON dict keyed by FEN. Both machines read + write this file.
2. Before starting a run on machine B:
   ```bash
   git pull --rebase origin main
   ```
   This brings in whatever the primary machine has finished so far.
3. Run verify_traps as usual:
   ```bash
   py site_builder/verify_traps.py --max-hours <H>
   ```
   The script's `is_valid_entry` check skips any FEN already at depth ≥ 28, so the two machines naturally process disjoint subsets without explicit coordination.
4. When the run ends (or hits `--max-hours`), the script auto-runs render_site + git commit + git push. If push is rejected (the primary machine pushed in between), resolve via:
   ```bash
   git pull --rebase
   git push
   ```
   The merge is usually clean since both machines added different keys to the same dict — git treats it as a single-line conflict on the `window.POSITIONS_VERY_DEEP = {...}` line, and the script's checkpoint dict already contains everything in the on-disk copy at startup, so a simple "keep ours" resolves correctly.

**To minimize race overhead**, partition explicitly:

- Primary machine continues sequentially from index 0.
- Secondary (Codex) machine starts from the back: process FENs in reverse-sorted order. They'll converge in the middle.
- There's no CLI flag for this yet — if you want it, add `--reverse` to `run_engine()` in verify_traps.py (~3 lines: `for i, fen in enumerate(sorted(todo, reverse=True), 1):`).

**Status checking** without running anything:

```bash
py -c "import json,re; t=open('output/site/positions_very_deep.js',encoding='utf-8').read(); m=re.search(r'=\s*(\{.*\});',t,re.S); print(len(json.loads(m.group(1))), 'FENs at depth 28')"
```

## File layout cheat sheet

```
chess-book-ai/
├── analyze.py                          # one-off Markdown report (legacy CLI)
├── CLAUDE.md / AGENTS.md               # docs for AI agents
├── README.md                           # human-oriented overview
├── engine/Windows/                     # git-ignored; Pikafish + NNUE go here
│
├── site_builder/
│   ├── build_data.py                   # XQF → games.json + positions.js (depth 12)
│   ├── enrich_decisive.py              # depth 22 on decisive variations
│   ├── chessdb_query.py                # fetch chessdb.cn cloud DB
│   ├── verify_traps.py                 # depth 28 verification of traps  ← long-running
│   ├── render_site.py                  # all HTML generation
│   ├── sync_assets.py                  # fast-path: only copies style.css + board.js
│   ├── clean_eval.py                   # CleanUciEngine (use this, not cchess.UciEngine)
│   ├── find_trap_plies.py              # CLI trap detector (top-N print)
│   ├── scan_brilliants.py              # CLI brilliant detector
│   ├── list_broken_annotes.py          # → output/broken_annotes.md
│   ├── suggest_annotes.py              # → output/suggested_annotes.md
│   ├── run_verify_traps.ps1            # schtask wrapper (powercfg + log tee)
│   └── assets/
│       ├── board.js                    # client-side renderer (hydrateGame, applyIccs, demo)
│       └── style.css                   # 3 themes via :root[data-theme="..."]
│
├── output/
│   ├── site/                           # build outputs (source of truth)
│   │   ├── positions.js                # depth-12 cache  (~7.5 MB)
│   │   ├── positions_deep.js           # depth-22 cache  (~4.3 MB)
│   │   ├── positions_very_deep.js      # depth-28 cache  (in progress)
│   │   ├── positions_view.js           # enriched merge for the browser  (~42 MB)
│   │   ├── data/
│   │   │   ├── games.json              # ~50 MB; per-game variation tree + ply records
│   │   │   └── chessdb_cache.json      # ~8 MB
│   │   ├── index.html / traps.html / brilliants.html
│   │   └── games/game-<sha1>.html      # one per XQF
│   ├── verify_traps_run_<ts>.log       # per-run logs
│   └── *.md                            # broken_annotes, suggested_annotes, etc.
│
└── docs/                               # mirror of output/site/ for GitHub Pages
```

## Common task playbooks

### "Master edited an XQF file — pick up the change"

```powershell
py site_builder\build_data.py -d 12         # incremental; will report N new FENs
py site_builder\enrich_decisive.py --depth 22 --threads 4 --threshold 300
                                             # only runs if there are new FENs in decisive variations
py site_builder\chessdb_query.py             # optional, only useful for plies 10-25
py site_builder\render_site.py               # fast-path auto-engages if no engine work was needed
```

If `build_data.py` reports `0 new`, the edit was annote-only — just `render_site.py` is enough.

After render, commit with a message like `Absorb <filename> annote edit` or `Absorb <filename> new variation`.

### "Iterate on CSS or board.js"

```powershell
py site_builder\sync_assets.py   # <1 second
```

Refresh the browser. No HTML re-render needed unless you changed template strings in render_site.py.

### "Verify traps haven't regressed"

```powershell
py site_builder\find_trap_plies.py | head -30
```

Top-20 traps by deep-loss. Compare against the previous run's output to spot drift.

### "Check the depth-28 run status"

```powershell
Get-Content -Wait output/verify_traps_run_<latest>.log     # tail with follow
schtasks /Query /TN "ChessBookVerifyDepth28" /V /FO LIST   # next run time + status
```

### "Re-schedule verify_traps for tonight"

```powershell
schtasks /Delete /TN "ChessBookVerifyDepth28" /F
schtasks /Create /TN "ChessBookVerifyDepth28" `
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"d:\Elton\TestArea\chess-book-ai\site_builder\run_verify_traps.ps1`"" `
  /SC ONCE /ST 21:00 /SD <YYYY/MM/DD> /F
```

The wrapper passes `--max-hours 13` so it self-terminates by 10:00 next morning.

## Critical gotchas (full list in CLAUDE.md)

The five things that have actually bitten us:

1. **`cchess.UciEngine` corrupts entries silently** — dual stdout readers race. Use `CleanUciEngine` from [`site_builder/clean_eval.py`](site_builder/clean_eval.py).
2. **Pikafish NNUE must live next to the exe** — if `pikafish.nnue` isn't in the same directory, the engine silently runs without it and emits nonsense scores.
3. **Windows Update can hard-kill scheduled tasks** — on 2026-05-18 night WU triggered 3 reboots between 00:30–00:37, killing verify_traps after 12 FENs. Pause updates before any long overnight run, or accept partial progress (the script is resumable).
4. **Depth-28 timing variance is huge** — 5s to 18min per FEN. A 5-sample probe is not a reliable estimator for a 1000-FEN batch. Plan with the slow case.
5. **`SKIP_OPENING_PLIES = 15` is duplicated across files** — keep [`enrich_decisive.py`](site_builder/enrich_decisive.py), [`find_trap_plies.py`](site_builder/find_trap_plies.py), [`verify_traps.py`](site_builder/verify_traps.py), [`render_site.py`](site_builder/render_site.py), and [`assets/board.js`](site_builder/assets/board.js) in sync if you change it.

## Where memory lives (Claude Code only)

Local Claude Code sessions persist context across conversations via:

```
C:\Users\<user>\.claude\projects\d--Elton-TestArea-chess-book-ai\memory\
```

`MEMORY.md` is the index; individual `.md` files hold typed entries (user / feedback / project / reference). Other agents (Codex, etc.) don't share this memory — read AGENTS.md + CLAUDE.md instead.

If you're a Claude session, before recommending a specific file path or function name from memory, verify it still exists (grep/glob first). Memory snapshots can go stale.
