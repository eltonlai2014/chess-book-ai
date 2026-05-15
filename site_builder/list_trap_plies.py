"""Dump trap plies (|deep mover-POV loss| > THRESHOLD, pi >= 15) for review.

Writes a CSV + a human-readable text table. Uses the same trap definition as
find_trap_plies.py but with a configurable threshold and richer output:

  loss      = mover-POV loss (positive = the side that just moved gave up cp)
  shallow_d = same metric using depth-12 scores (small = shallow was fooled)
  swing     = loss - shallow_d (how much only deep can see)

Usage:
  py site_builder/list_trap_plies.py --threshold 200
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_depth import load_positions, score_cp  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "output" / "site"
GAMES_JSON = OUT_DIR / "data" / "games.json"
POSITIONS_JS = OUT_DIR / "positions.js"
DEEP_JS = OUT_DIR / "positions_deep.js"
SKIP_OPENING_PLIES = 15


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--threshold', type=int, default=200,
                    help='mover-POV loss threshold (cp)')
    ap.add_argument('--out', default=str(REPO / "output" / "trap_plies.md"),
                    help='Markdown table output path')
    ap.add_argument('--csv', default=str(REPO / "output" / "trap_plies.csv"),
                    help='CSV output path (UTF-8 with BOM for Excel)')
    ap.add_argument('--shallow-blind-only', action='store_true',
                    help='also require shallow_d < 50 (true "human traps")')
    ap.add_argument('--top-per-variation', type=int, default=3,
                    help='keep at most N highest-loss traps per (file, variation)')
    ap.add_argument('--md-rows-per-file', type=int, default=1500,
                    help='max rows per Markdown file; if total exceeds this, '
                         'split into _part01.md, _part02.md, ... '
                         '(VSCode preview chokes on giant tables)')
    # Kept for backward-compat with older invocations; unused now (we emit
    # one table per file and chunk by --md-rows-per-file instead).
    ap.add_argument('--md-top', type=int, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    games = json.loads(GAMES_JSON.read_text(encoding='utf-8'))
    shallow = load_positions(POSITIONS_JS)
    deep = load_positions(DEEP_JS)

    # Map filename -> rel_path so we can show the subdirectory in headings.
    rel_paths = {g['file']: g.get('rel_path', g['file']) for g in games}

    rows = []
    for g in games:
        for vi, plies in enumerate(g['variations']):
            d_scores = [score_cp(deep[p['fen']]) if p.get('fen') in deep else None for p in plies]
            s_scores = [score_cp(shallow[p['fen']]) if p.get('fen') in shallow else None for p in plies]
            for pi in range(SKIP_OPENING_PLIES, len(plies) - 1):
                if d_scores[pi] is None or d_scores[pi + 1] is None:
                    continue
                loss = d_scores[pi] + d_scores[pi + 1]
                # Only count positive losses — those are actual blunders. A
                # negative "loss" means the mover gained cp (engine sees an
                # improvement after the move was made), which isn't a trap.
                if loss < args.threshold:
                    continue
                if loss >= 2000:
                    continue  # skip mate-zone
                sh_loss = (s_scores[pi] + s_scores[pi + 1]
                           if s_scores[pi] is not None and s_scores[pi + 1] is not None
                           else None)
                # If either shallow side already sees a mate (score_cp returns
                # ±(30000-|mate|), so |abs| >> 2000), the diff is meaningless.
                # Treat as "no data" so review tables don't show ±29xxx noise.
                if sh_loss is not None and abs(sh_loss) > 2000:
                    sh_loss = None
                if args.shallow_blind_only and (sh_loss is None or sh_loss >= 50):
                    continue
                p = plies[pi]
                # Strip control chars from annote — they break CSV record
                # parsing and Markdown table rows.
                annote = re.sub(r'[\x00-\x1f]+', ' ',
                                (p.get('annote') or '').strip())[:80]
                _ = annote  # for clarity below; used in row dict
                rows.append({
                    'file': g['file'],
                    'variation': vi + 1,
                    'ply': pi + 1,
                    'side': p['side'],
                    'move_cn': p['chinese'],
                    'move_iccs': p['iccs'],
                    'fen': p.get('fen'),
                    'deep_loss': loss,
                    'shallow_loss': sh_loss if sh_loss is not None else '',
                    'swing': (loss - sh_loss) if sh_loss is not None else '',
                    'annote': annote,
                })

    # Dedupe by FEN — same position reached via different variation prefixes
    # is conceptually the same trap. Keep the occurrence with the lowest
    # (file, variation, ply) so it points to the earliest example.
    rows.sort(key=lambda r: (r['file'], r['variation'], r['ply']))
    seen = set()
    unique = []
    for r in rows:
        if r['fen'] in seen:
            continue
        seen.add(r['fen'])
        unique.append(r)

    # Per (file, variation), keep top-N traps by loss magnitude. Browsing the
    # raw list is too noisy when one variation contributes 20+ trap plies;
    # picking 3 representative low points per variation is plenty for review.
    from collections import defaultdict
    groups = defaultdict(list)
    for r in unique:
        groups[(r['file'], r['variation'])].append(r)
    capped = []
    for key, group_rows in groups.items():
        group_rows.sort(key=lambda r: -r['deep_loss'])
        capped.extend(group_rows[:args.top_per_variation])

    # Final order: by filename, then (variation, ply) ascending — so each
    # variation's traps appear in natural play order, which is how the user
    # actually reads through a game.
    capped.sort(key=lambda r: (r['file'], r['variation'], r['ply']))
    unique = capped

    def md_escape(s):
        return str(s).replace('|', '\\|').replace('\n', ' ')

    cols = ['file', 'variation', 'ply', 'side', 'move_cn', 'move_iccs',
            'deep_loss', 'shallow_loss', 'swing', 'annote']

    header_label = {
        'file': '檔案', 'variation': '變例', 'ply': '步',
        'side': '方', 'move_cn': '走法', 'move_iccs': 'ICCS',
        'deep_loss': '深Δ', 'shallow_loss': '淺Δ', 'swing': '差', 'annote': '註解',
        'fen': 'FEN',
    }

    def dir_label(rel_path):
        rp = (rel_path or '').replace('\\', '/').strip('/')
        return rp.rsplit('/', 1)[0] if '/' in rp else ''

    # Group by file, preserving final sort order.
    file_groups = []  # list of (file, rel_path, [rows])
    last_file = None
    for r in unique:
        if r['file'] != last_file:
            file_groups.append((r['file'], rel_paths.get(r['file'], r['file']), []))
            last_file = r['file']
        file_groups[-1][2].append(r)

    # CSV mirrors the MD layout: section-heading row before each file's block,
    # then a column-header row, then data rows. "file" is dropped as a column
    # since it's in the heading. Blank row separates blocks.
    csv_cols = [c for c in cols if c != 'file']
    csv_path = Path(args.csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        for fi, (fname, rel_path, group_rows) in enumerate(file_groups):
            if fi > 0:
                w.writerow([])  # blank separator between blocks
            dl = dir_label(rel_path)
            section = (f"=== {dl}／{fname}  ({len(group_rows)} 點) ==="
                       if dl else f"=== {fname}  ({len(group_rows)} 點) ===")
            w.writerow([section])
            w.writerow([header_label[c] for c in csv_cols])
            for r in group_rows:
                w.writerow([r[c] for c in csv_cols])
    print(f"[csv] {len(unique)} rows, {len(file_groups)} files -> {csv_path}",
          file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    md_cols = csv_cols  # MD and CSV use the same column set sans "file"

    def write_chunk(chunk_path, chunk_groups, part_idx, part_total):
        with chunk_path.open('w', encoding='utf-8') as f:
            title = f"# 陷阱清單（|深Δ| >= {args.threshold} cp, |Δ| < 2000, "
            title += f"ply >= {SKIP_OPENING_PLIES}"
            if args.shallow_blind_only:
                title += ', 淺算盲區'
            title += '）'
            if part_total > 1:
                title += f' — 第 {part_idx}/{part_total} 份'
            f.write(title + '\n\n')
            f.write(f"每 (檔案, 變例) 至多 {args.top_per_variation} 點。"
                    f"深Δ 為走子方視角失分（正 = 該方丟了多少 cp）。"
                    f"完整資料 CSV：`{csv_path.name}`。\n\n")
            for fname, rel_path, group_rows in chunk_groups:
                dl = dir_label(rel_path)
                heading = f"## {dl}／{fname}" if dl else f"## {fname}"
                heading += f"  ({len(group_rows)} 點)"
                f.write(heading + '\n\n')
                f.write('| ' + ' | '.join(header_label[c] for c in md_cols) + ' |\n')
                f.write('|' + '|'.join(['---'] * len(md_cols)) + '|\n')
                for r in group_rows:
                    f.write('| ' + ' | '.join(md_escape(r[c]) for c in md_cols) + ' |\n')
                f.write('\n')

    # Chunk file_groups so each chunk has at most md_rows_per_file rows.
    # A single file's table is never split (would be confusing for review).
    chunks = []
    current = []
    current_rows = 0
    for grp in file_groups:
        n = len(grp[2])
        if current and current_rows + n > args.md_rows_per_file:
            chunks.append(current)
            current = []
            current_rows = 0
        current.append(grp)
        current_rows += n
    if current:
        chunks.append(current)

    if len(chunks) <= 1:
        write_chunk(out_path, chunks[0] if chunks else [], 1, 1)
        print(f"[md] {len(unique)} rows, {len(file_groups)} files -> {out_path}",
              file=sys.stderr)
    else:
        stem = out_path.with_suffix('')
        suffix = out_path.suffix
        for i, chunk in enumerate(chunks, 1):
            cp = Path(f"{stem}_part{i:02d}{suffix}")
            write_chunk(cp, chunk, i, len(chunks))
            print(f"[md] part {i}/{len(chunks)}: "
                  f"{sum(len(g[2]) for g in chunk)} rows, "
                  f"{len(chunk)} files -> {cp}", file=sys.stderr)

    print(f"\n=== TOP 30 TRAPS (|deep_loss| >= {args.threshold}cp, "
          f"|loss| < 2000, pi >= {SKIP_OPENING_PLIES}"
          f"{', shallow_blind' if args.shallow_blind_only else ''}) ===")
    print(f"{'file':<24} {'var':>3} {'ply':>3} {'side':>4} {'move':<8} "
          f"{'deepΔ':>6} {'淺':>6} {'swing':>6}  annote")
    for r in unique[:30]:
        print(f"{r['file'][:24]:<24} {r['variation']:>3} {r['ply']:>3} "
              f"{r['side']:>4} {r['move_cn']:<8} "
              f"{r['deep_loss']:>+6} {str(r['shallow_loss']):>6} "
              f"{str(r['swing']):>6}  {r['annote']}")


if __name__ == '__main__':
    main()
