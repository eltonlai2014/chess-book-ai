"""Batch-query chessdb.cn cloud database for one game's unique FENs.

Cached so re-runs are free. Rate-limited at 5 req/sec to be a good citizen.
Output: chessdb_cache.json (mirrors positions.js shape but with cloud data).

Usage:
  py site_builder/chessdb_query.py --game 牛頭滾
  py site_builder/chessdb_query.py --game 牛頭滾 --report   # comparison report
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GAMES_JSON = REPO / "output/site/data/games.json"
CACHE_JSON = REPO / "output/site/data/chessdb_cache.json"

API = "http://www.chessdb.cn/chessdb.php"
RATE_DELAY = 0.2  # seconds between queries


def trim_fen(fen: str) -> str:
    """chessdb expects 'position side', no halfmove/fullmove counters."""
    parts = fen.split()
    return ' '.join(parts[:2]) if len(parts) >= 2 else fen


def parse_queryall(text: str):
    """chessdb returns 'move:X,score:Y,rank:Z,note:N,winrate:W|move:...'
    or error strings like 'invalid board', 'unknown', 'checkmate', 'nobestmove'."""
    # chessdb sometimes appends a stray NUL byte to the response payload;
    # without stripping, float('50.08\x00') etc. blow up downstream.
    text = text.replace('\x00', '').strip()
    if not text:
        return None
    if text in ('invalid board', 'unknown', 'checkmate', 'stalemate', 'nobestmove'):
        return {'status': text, 'moves': []}
    moves = []
    for chunk in text.split('|'):
        kv = {}
        for pair in chunk.split(','):
            if ':' in pair:
                k, v = pair.split(':', 1)
                kv[k] = v.strip()
        if 'move' not in kv:
            continue
        moves.append({
            'iccs': kv.get('move'),
            'score': int(kv['score']) if kv.get('score', '').lstrip('-').isdigit() else None,
            'rank': int(kv['rank']) if kv.get('rank', '').isdigit() else None,
            'note': kv.get('note', ''),
            'winrate': float(kv['winrate']) if kv.get('winrate') else None,
        })
    return {'status': 'ok', 'moves': moves}


def query_one(fen: str, action: str = 'queryall'):
    q = urllib.parse.urlencode({'action': action, 'board': trim_fen(fen)})
    url = f"{API}?{q}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read().decode('utf-8', errors='replace')


def load_cache():
    if not CACHE_JSON.exists():
        return {}
    return json.loads(CACHE_JSON.read_text(encoding='utf-8'))


def save_cache(cache):
    CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
    CACHE_JSON.write_text(json.dumps(cache, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


PLY_RANGE = (10, 25)  # 1-based inclusive — book deviation only matters in this window


def collect_fens_for_game(games, needle):
    """Collect FENs from plies PLY_RANGE only. Before ply 10 is opening theory
    (covered by every reasonable line, deviation = different opening). After
    ply 25 cloud data is sparse and middlegame is past the book's framing."""
    lo, hi = PLY_RANGE
    fens = set()
    for g in games:
        if needle and needle not in g['file']:
            continue
        for v in g['variations']:
            for pi, p in enumerate(v, 1):  # 1-based to match UI
                if pi < lo or pi > hi:
                    continue
                if p.get('fen'):
                    fens.add(p['fen'])
    return fens


def run_queries(fens, cache):
    todo = [f for f in fens if f not in cache]
    print(f"[chessdb] {len(fens)} FENs total, {len(fens) - len(todo)} cached, {len(todo)} to query", file=sys.stderr)
    if not todo:
        return cache
    t0 = time.time()
    for idx, fen in enumerate(todo, 1):
        try:
            raw = query_one(fen)
            cache[fen] = parse_queryall(raw)
        except Exception as e:
            cache[fen] = {'status': f'error: {e}', 'moves': []}
        if idx % 20 == 0 or idx == len(todo):
            elapsed = time.time() - t0
            rate = idx / elapsed if elapsed > 0 else 0
            eta = (len(todo) - idx) / rate if rate > 0 else 0
            print(f"  [{idx}/{len(todo)}] {elapsed:.0f}s ({rate:.1f}/s) eta {eta:.0f}s", file=sys.stderr)
        if idx % 50 == 0:
            save_cache(cache)
        time.sleep(RATE_DELAY)
    save_cache(cache)
    return cache


def fmt_chessdb(entry):
    if not entry:
        return '—'
    if entry.get('status') != 'ok':
        return entry.get('status', '?')
    moves = entry.get('moves') or []
    if not moves:
        return 'no moves'
    best = moves[0]
    return f"{best['iccs']}/{best['score']:+d}/r{best['rank']}/{best['winrate']:.1f}%"


def report(games, needle, cache):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from enrich_depth import load_positions, score_cp  # noqa: E402

    shallow = load_positions(REPO / "output/site/positions.js")
    deep = load_positions(REPO / "output/site/positions_deep.js")

    rows = []
    for g in games:
        if needle not in g['file']:
            continue
        for vi, plies in enumerate(g['variations']):
            for pi, p in enumerate(plies):
                if pi < 15:
                    continue
                fen = p.get('fen')
                if not fen or fen not in cache:
                    continue
                cdb = cache[fen]
                if cdb.get('status') != 'ok' or not cdb.get('moves'):
                    continue
                # Compare book move's cdb entry against cdb's best
                book_iccs = p.get('iccs')
                book_cdb = next((m for m in cdb['moves'] if m['iccs'] == book_iccs), None)
                cdb_best = cdb['moves'][0]
                sh = score_cp(shallow.get(fen)) if fen in shallow else None
                dp = score_cp(deep.get(fen)) if fen in deep else None
                rows.append({
                    'vi': vi+1, 'pi': pi+1, 'side': p['side'], 'cn': p['chinese'],
                    'book_iccs': book_iccs,
                    'sh': sh, 'dp': dp,
                    'cdb_best': cdb_best,
                    'book_cdb': book_cdb,
                })

    # Filter to "interesting" rows: book differs from cdb best AND book has worse cdb score
    interesting = [r for r in rows if r['book_cdb'] and r['cdb_best']['iccs'] != r['book_iccs']
                   and r['book_cdb']['score'] < r['cdb_best']['score'] - 50]
    interesting.sort(key=lambda r: r['cdb_best']['score'] - r['book_cdb']['score'], reverse=True)

    print(f"\n=== {needle}: rows with chessdb data: {len(rows)} ===")
    print(f"=== where book differs from chessdb best AND scores >50cp apart: {len(interesting)} ===\n")
    print(f"{'var':>4} {'ply':>4} {'side':>5}  {'book':<10} {'cdb_best':<25}  {'本步雲庫':<25} 淺/深")
    def fmt_mv(m):
        wr = f"{m['winrate']:.0f}%" if m.get('winrate') is not None else '-'
        sc = f"{m['score']:+d}" if m.get('score') is not None else '?'
        return f"{m['iccs']}/{sc}/{wr}"

    for r in interesting[:25]:
        cdb_book = fmt_mv(r['book_cdb'])
        cdb_best = fmt_mv(r['cdb_best'])
        sh = f"{r['sh']:+d}" if r['sh'] is not None else '?'
        dp = f"{r['dp']:+d}" if r['dp'] is not None else '?'
        print(f"v{r['vi']:>3} p{r['pi']:>3} {r['side']:>5}  {r['cn']:<8}  {cdb_best:<22}  {cdb_book:<22} {sh}/{dp}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', required=True, help='Substring match on game filename')
    ap.add_argument('--report', action='store_true', help='Print comparison report (after querying)')
    args = ap.parse_args()

    games = json.loads(GAMES_JSON.read_text(encoding='utf-8'))
    fens = collect_fens_for_game(games, args.game)
    print(f"[scope] {args.game}: {len(fens)} unique FENs", file=sys.stderr)

    cache = load_cache()
    cache = run_queries(fens, cache)

    if args.report:
        report(games, args.game, cache)


if __name__ == '__main__':
    main()
