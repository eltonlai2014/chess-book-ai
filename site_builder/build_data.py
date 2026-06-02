"""Scan all XQF files, evaluate every unique pre-move position with Pikafish,
emit JSON game manifest + positions JS for the static site to consume.

Outputs:
  output/site/data/games.json   - list of games with variations (each ply has pre-move fen)
  output/site/positions.js      - window.POSITIONS = { fen: {best_iccs, score, mate, pv, depth} }

Resumable: existing positions.js is loaded and only missing FENs are evaluated.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import cchess
from cchess import read_from_xqf, ChessBoard
from clean_eval import CleanUciEngine

# Reuse engine driver from analyze.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyze import iccs_to_text  # noqa: E402


def _cjk_ratio(s: str) -> float:
    if not s:
        return 0.0
    return sum(1 for c in s if 0x4E00 <= ord(c) <= 0x9FFF) / len(s)


# Top-216 chars covering 100% of usage in clean annotations — derived from
# site_builder/common_chars.py. Acts as a "looks like real chess commentary"
# vocabulary score, used to disambiguate when both GB18030 and Big5 produce
# valid-but-different Chinese (rare-archaic GB18030 false hits like "磷砆溃"
# vs the real Big5 reading "避被壓").
_COMMON_TRAD = set(
    "法的方馬路走紅抗勢有優中後兌對較黑利手車無充分用性壓著子六加厚攻軟件局衡招要下棄可動此面"
    "最計畫化出主翼多棋之勝奪大易機求線謀底佳準備右得但先行好錯很容現力卒相取以再爭定簡位不交"
    "換符合人類思維會直接貫徹長距離進變與比頭兵矛盾頑強砲包只能和推薦退解反應具觀死急吃陣型弱"
    "點虧左一保留均搶支援呆滯回益等伺而帥其他都為集擊殘必雙制占過河略佔逼實質上並明顯收送被視"
    "臥槽傌穩空門巧消拆飛認威脅抽趨緩足宜輕健跳避免七開放未戰術成功平妙叫將確立雖置欠"
)


def _vocab_score(s: str) -> int:
    """Count chars that match our in-domain vocabulary."""
    return sum(1 for c in s if c in _COMMON_TRAD)


# cchess.to_text() outputs Simplified — patch the small vocabulary used in
# Chinese-chess move notation to Traditional so it matches the rest of the UI.
_SIMP_TO_TRAD = str.maketrans({
    '马': '馬', '车': '車', '进': '進', '后': '後',
    '红': '紅',
})


def _to_trad(s: str | None, side: str | None = None) -> str | None:
    """Simplified → Traditional, plus xiangqi-side spelling: black cannons
    are written 包 (current/historical 黑包) while red stays 炮. Caller
    passes `side='black'` to apply the substitution."""
    if not s:
        return s
    s = s.translate(_SIMP_TO_TRAD)
    if side == 'black':
        s = s.replace('炮', '包').replace('砲', '包')
    return s


def _recover_annote(text: str | None) -> str | None:
    """cchess decodes XQF annote bytes as GB18030. If the original was actually
    Big5 (Traditional Chinese typed in a Big5-mode editor), GB18030 produces
    either obvious garbage (PUA + foreign script) or *plausible* archaic chars
    (磷砆溃) that pass a naive CJK-ratio test. Always recompute via Big5 and
    pick whichever decoding hits more in-domain vocabulary.
    """
    if not text:
        return text
    try:
        raw = text.encode('gb18030', errors='replace')
        alt = raw.decode('big5', errors='replace')
    except Exception:
        return text
    if alt == text:
        return text
    if _vocab_score(alt) > _vocab_score(text):
        return alt
    # Fallback: if current is clearly garbled (many non-CJK) and alt has
    # any vocabulary hits, take alt
    if _cjk_ratio(text) < 0.7 and _cjk_ratio(alt) > _cjk_ratio(text):
        return alt
    return text


def _annote_score(game):
    """Lower = better. Tuple (garbage_ratio, -total_chars).
    Garbage = chars in Unicode PUA, which is what cchess emits on decode failure."""
    total = 0
    garbage = 0
    for mv in game.iter_moves():
        a = getattr(mv, 'annote', None)
        if not a:
            continue
        total += len(a)
        for ch in a:
            if 0xE000 <= ord(ch) <= 0xF8FF:
                garbage += 1
    ratio = (garbage / total) if total else 0.0
    return (ratio, -total)


def _dedupe_by_name(paths):
    """Among files sharing the same case-folded name, keep the one with the cleanest annotations."""
    groups = defaultdict(list)
    for p in paths:
        groups[p.name.lower()].append(p)
    kept = []
    for name, members in groups.items():
        if len(members) == 1:
            kept.append(members[0])
            continue
        scored = []
        for p in members:
            try:
                g = read_from_xqf(str(p))
                scored.append((_annote_score(g), p))
            except Exception:
                continue
        if not scored:
            continue
        scored.sort(key=lambda x: x[0])
        winner = scored[0][1]
        kept.append(winner)
        losers = [p for _, p in scored[1:]]
        print(f"  dedup: kept {winner} ({len(losers)} duplicate(s) ignored)", file=sys.stderr)
    return sorted(kept)

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
SRC_DIR = Path(r"D:\Elton\TestArea\chess-book")
OUT_DIR = REPO / "output" / "site"
DATA_DIR = OUT_DIR / "data"
POSITIONS_JS = OUT_DIR / "positions.js"


def build_move_tree(variations):
    """Fold a flat list of variations into a move-tree.

    Each non-root node = one move played from its parent's position. Children
    of a node are the alternative continuations seen in any variation.
    Shared prefixes (e.g. an opening sequence common to 200 variations) collapse
    into a single path. Result has no "fen" on internal nodes — fen_after is
    enough for the client to look up engine eval.

    Returned shape:
      { "children": [
          { "iccs": "h2e2", "chinese": "炮二平五", "side": "red",
            "fen_after": "...", "annote": null,
            "children": [ ...same shape... ] }
        ] }
    """
    root = {'children': []}
    for plies in variations:
        node = root
        for p in plies:
            # Skip invalid markers (no fen) — they break the chain.
            if not p.get('fen'):
                break
            iccs = p.get('iccs')
            existing = next((c for c in node['children'] if c['iccs'] == iccs), None)
            if existing is None:
                # fen_after omitted — hydrateGame() in board.js derives it via
                # applyIccs from each parent's FEN at page load. Saves ~25 MB
                # on games.json.
                existing = {
                    'iccs': iccs,
                    'chinese': p.get('chinese'),
                    'side': p.get('side'),
                    'annote': p.get('annote'),
                    'children': [],
                }
                node['children'].append(existing)
            node = existing
    return root


def scan_games(src_dir: Path):
    """Parse every XQF file into a serialisable game dict. No engine work yet.

    Also extracts each Move.annote so the static site can show it. Case-duplicate
    filenames are deduped, keeping the version with the cleanest annotations.
    """
    games = []
    fens_needed = set()
    all_files = [p for p in src_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".xqf"]
    files = _dedupe_by_name(all_files)
    print(f"  files: {len(all_files)} on disk, {len(files)} after dedup", file=sys.stderr)

    for fp in files:
        try:
            game = read_from_xqf(str(fp))
        except Exception as e:
            print(f"  ! parse fail {fp.name}: {e}", file=sys.stderr)
            continue

        info = dict(game.info)
        init_board = game.init_board
        init_fen = init_board.to_fen() if hasattr(init_board, 'to_fen') else str(init_board)
        # dump_moves preserves the Move objects (not just ICCS strings) so we can pull annote
        move_lines = game.dump_moves()

        variations = []
        for line_obj in move_lines:
            board = ChessBoard(init_fen)
            plies = []
            for mv in line_obj['moves']:
                iccs = str(mv)
                fen = board.to_fen()  # position BEFORE this move
                side = 'red' if board.move_player == cchess.RED else 'black'
                chinese = _to_trad(iccs_to_text(board, iccs), side)
                annote = _recover_annote(getattr(mv, 'annote', None) or None)
                fens_needed.add(fen)
                applied = board.move_iccs(iccs)
                if applied is None:
                    # fen_after intentionally omitted; hydrateGame() derives
                    # it client-side. Invalid moves break the chain so the
                    # hydrator stops at the previous step.
                    plies.append({
                        'fen': fen,
                        'side': side, 'iccs': iccs,
                        'chinese': f'!invalid {iccs}', 'annote': None,
                    })
                    break
                board.next_turn()
                plies.append({
                    'fen': fen,
                    'side': side,
                    'iccs': iccs,
                    'chinese': chinese,
                    'annote': annote,
                })
            variations.append(plies)

        games.append({
            'file': fp.name,
            'rel_path': str(fp.relative_to(src_dir)),
            'init_fen': init_fen,
            'result': info.get('result', '*'),
            'branches': info.get('branchs', len(variations)),
            'variations': variations,
            'tree': build_move_tree(variations),
        })
    return games, fens_needed


def load_existing_positions(path: Path):
    """Parse the JSON object embedded in positions.js so reruns are incremental."""
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8')
    m = re.search(r'window\.POSITIONS\s*=\s*(\{.*\});\s*$', text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def save_positions(path: Path, positions: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(positions, ensure_ascii=False, indent=0, separators=(',', ':'))
    path.write_text(f"window.POSITIONS = {payload};\n", encoding='utf-8')


def collect_fens_dfs(games):
    """Walk every game's variations in order, emit FENs in first-seen order
    (DFS-like preorder per game). Replaces the old unordered `set` collection
    which destroyed TT locality (see D12_TT_SWEEP.md):

    - Within a game: variation 0 (main line) walks linearly first, then
      variation 1, etc. cchess emits variations in branch-order, so siblings
      of a node tend to appear right after their parent's deepest descendant.
    - Across games: one game's FENs all complete before the next game starts,
      so shared opening positions get TT-warmed by the first game and then
      reused (cache hit, skipped) for subsequent ones.

    Global first-seen dedup preserves DFS locality — earlier appearances win,
    and the resulting list is fed to the engine in that exact order.
    """
    seen = set()
    out = []
    for g in games:
        for plies in g['variations']:
            for p in plies:
                fen = p.get('fen')
                if fen and fen not in seen:
                    seen.add(fen)
                    out.append(fen)
    return out


def evaluate(ordered_fens, depth, existing, threads=1, hash_mb=1024,
             save_path=None, checkpoint_every=50):
    """Run Pikafish at `depth` on every FEN in `ordered_fens` not already in
    `existing`. The order of `ordered_fens` is preserved (DFS preorder from
    collect_fens_dfs) so TT entries from parent positions are still hot when
    we hit their children/siblings — the whole point of the rewrite.

    TT is shared across the entire run: no `ucinewgame` between FENs. With
    Hash=1024MB the warm entries actually survive long enough to be reused.

    Stored `depth` = engine-reported `info_depth` (not the requested depth);
    when search ran longer due to extensions, that's the real depth we got.

    Uses CleanUciEngine (single-threaded synchronous driver) — cchess.UciEngine
    has a stdout-reader race that corrupted ~85% of depth-22 evals."""
    todo = [f for f in ordered_fens if f not in existing]
    n_cached = len(ordered_fens) - len(todo)
    print(f"  positions: {len(ordered_fens)} unique, {len(todo)} new, {n_cached} cached "
          f"(DFS order, Hash={hash_mb}MB, TT not cleared)", file=sys.stderr)
    if not todo:
        return existing

    eng = CleanUciEngine(str(EXE))
    eng.set_option('Threads', str(threads))
    eng.set_option('Hash', str(hash_mb))
    eng.isready()

    results = dict(existing)
    t0 = time.time()
    try:
        for idx, fen in enumerate(todo, 1):
            act = eng.go(fen, depth)
            entry = {
                'best_iccs': act.get('move'),
                'score': act.get('score') if isinstance(act.get('score'), int) else None,
                'mate': act.get('mate'),
                'pv': (act.get('pv') or [])[:8],
                'depth': act.get('depth') or depth,
            }
            results[fen] = entry
            if idx % 10 == 0 or idx == len(todo):
                elapsed = time.time() - t0
                rate = idx / elapsed if elapsed > 0 else 0
                eta = (len(todo) - idx) / rate if rate > 0 else 0
                print(f"  [{idx}/{len(todo)}] {elapsed:.1f}s ({rate:.1f}/s) eta {eta:.0f}s", file=sys.stderr)
            if save_path and idx % checkpoint_every == 0:
                save_positions(save_path, results)
    finally:
        try:
            eng._send('quit')
        except Exception:
            pass
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-d', '--depth', type=int, default=14)
    ap.add_argument('--threads', type=int, default=1, help='Pikafish Threads option (default 1 to keep CPU free)')
    ap.add_argument('--hash-mb', type=int, default=1024,
                    help='Pikafish Hash MB. Default 1024 — needs to be large enough that warm '
                         'TT entries survive until siblings of the originating position are evaluated. '
                         '16 MB (Pikafish default) gave zero TT reuse; see D12_TT_SWEEP.md.')
    ap.add_argument('--limit', type=int, default=None, help='Process only first N files (smoke test)')
    ap.add_argument('--src', default=str(SRC_DIR))
    ap.add_argument('--scan-only', action='store_true',
                    help='Write games.json + report FEN counts, skip Pikafish evaluation')
    ap.add_argument('--no-migrate', action='store_true',
                    help='Skip the post-build migrate_to_sqlite step')
    ap.add_argument('--single-file', default=None,
                    help='Substring-match against rel_path/file; build only that game(s) '
                         'into a sidecar cache positions_single_test.js (no global mutation). '
                         'Smoke-test new DFS evaluator before committing to a full re-eval.')
    args = ap.parse_args()

    src = Path(args.src)
    print(f"[scan] {src}", file=sys.stderr)
    games, fens = scan_games(src)
    print(f"[scan] {len(games)} games, {len(fens)} unique FENs", file=sys.stderr)

    if args.limit:
        games = games[:args.limit]
        print(f"[limit] {len(games)} games", file=sys.stderr)

    if args.single_file:
        sf = args.single_file
        matched = [g for g in games
                   if sf in (g.get('rel_path') or '') or sf in (g.get('file') or '')]
        if not matched:
            print(f"[single-file] no game matched '{sf}'", file=sys.stderr)
            return
        games = matched
        print(f"[single-file] {len(games)} game(s) matched '{sf}' — "
              f"writing to positions_single_test.js (no global cache mutation)",
              file=sys.stderr)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    games_path = DATA_DIR / 'games.json'
    if not args.single_file:
        games_path.write_text(json.dumps(games, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f"[write] {games_path}", file=sys.stderr)

    out_js = POSITIONS_JS if not args.single_file else (OUT_DIR / 'positions_single_test.js')
    existing = load_existing_positions(out_js)
    print(f"[cache] {len(existing)} positions in {out_js.name}", file=sys.stderr)

    ordered = collect_fens_dfs(games)
    print(f"[order] DFS preorder: {len(ordered)} unique FENs", file=sys.stderr)

    if args.scan_only:
        new_fens = sum(1 for f in ordered if f not in existing)
        print(f"[scan-only] {len(ordered)} unique FENs, {new_fens} not yet in cache — skipping engine",
              file=sys.stderr)
        return

    results = evaluate(ordered, args.depth, existing,
                       threads=args.threads, hash_mb=args.hash_mb,
                       save_path=out_js)
    save_positions(out_js, results)
    print(f"[write] {out_js} ({len(results)} positions)", file=sys.stderr)

    if args.single_file:
        print(f"[single-file] done. Inspect {out_js} and compare to current "
              f"positions.js before approving full re-eval.", file=sys.stderr)
        return

    if not args.no_migrate:
        print("[post] migrate_to_sqlite.py", file=sys.stderr)
        subprocess.run([sys.executable, str(REPO / 'site_builder' / 'migrate_to_sqlite.py')],
                       check=True, cwd=str(REPO))


if __name__ == '__main__':
    main()
