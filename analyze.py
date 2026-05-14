"""Analyse XQF opening book files with Pikafish engine.

For every position before each book move, compute engine's preferred move and
score. Output a Markdown report comparing book to engine.
"""
import argparse
import time
import sys
from pathlib import Path

import cchess
from cchess import read_from_xqf, UciEngine, ChessBoard

EXE = r"D:\Elton\TestArea\chess-book-ai\engine\Windows\pikafish-avx2.exe"


def run_engine(eng, fen, depth):
    """Drive engine to depth, return final bestmove action dict."""
    eng.go_from(fen, params={'depth': depth})
    t0 = time.time()
    last_info = None
    while time.time() - t0 < 60:
        act = eng.get_action()
        if act is None:
            time.sleep(0.01)
            continue
        if act['action'] == 'info_move':
            last_info = act
        elif act['action'] == 'bestmove':
            # Engine fills score from cache on bestmove already
            return act
        elif act['action'] in ('dead', 'draw'):
            return act
    return last_info or {'action': 'timeout'}


def iccs_to_text(board, iccs):
    """Convert ICCS to Chinese notation by looking up move on board (no mutation)."""
    # Use a clone to avoid mutating board state
    clone = ChessBoard(board.to_fen())
    move = clone.move_iccs(iccs)
    if move is None:
        return iccs
    try:
        return move.to_text()
    except Exception:
        return iccs


def analyze_file(xqf_path, exe_path, depth=14, verbose=True):
    game = read_from_xqf(xqf_path)
    info = dict(game.info)
    init_board = game.init_board
    init_fen = init_board.to_fen() if hasattr(init_board, 'to_fen') else str(init_board)
    lines = game.dump_iccs_moves()

    # Dedupe positions across all variations
    unique_positions = {}  # fen_before -> {'book_moves': set(iccs), 'first_seen': (line, ply)}
    for li, line in enumerate(lines):
        board = ChessBoard(init_fen)
        for pi, iccs in enumerate(line):
            fen = board.to_fen()
            slot = unique_positions.setdefault(fen, {'book_moves': set(), 'first_seen': (li, pi)})
            slot['book_moves'].add(iccs)
            mv = board.move_iccs(iccs)
            if mv is None:
                if verbose:
                    print(f"  ! invalid move {iccs} at line {li} ply {pi}", file=sys.stderr)
                break
            board.next_turn()

    if verbose:
        total_plies = sum(len(l) for l in lines)
        print(f"  positions: {len(unique_positions)} unique / {total_plies} total plies")

    # Engine
    eng = UciEngine()
    eng.load(exe_path)
    if not eng.wait_for_ready(timeout=15):
        raise RuntimeError("engine not ready")

    eval_cache = {}
    t_start = time.time()
    for idx, (fen, slot) in enumerate(unique_positions.items(), 1):
        result = run_engine(eng, fen, depth)
        eval_cache[fen] = result
        if verbose and (idx % 5 == 0 or idx == len(unique_positions)):
            elapsed = time.time() - t_start
            rate = idx / elapsed if elapsed > 0 else 0
            print(f"  [{idx}/{len(unique_positions)}] {elapsed:.1f}s ({rate:.1f}/s)")
    eng.quit()

    return {
        'file': str(xqf_path),
        'info': info,
        'init_fen': init_fen,
        'lines': lines,
        'eval': eval_cache,
    }


def fmt_score(act):
    if not isinstance(act, dict):
        return '?'
    if 'mate' in act:
        m = act['mate']
        return f"M{m}" if m > 0 else f"-M{-m}"
    s = act.get('score')
    return f"{s:+d}" if isinstance(s, int) else '?'


def render_markdown(result, depth):
    info = result['info']
    init_fen = result['init_fen']
    lines = result['lines']
    cache = result['eval']
    fname = Path(result['file']).name

    out = []
    out.append(f"# {fname}")
    out.append("")
    out.append(f"- 起始局面: `{init_fen}`")
    out.append(f"- 變例數: {len(lines)}  /  branches: {info.get('branchs', '?')}")
    out.append(f"- 引擎: Pikafish 2026-01-02, depth={depth}")
    out.append(f"- 結果欄: {info.get('result', '*')}")
    out.append("")

    for li, line in enumerate(lines, 1):
        out.append(f"## 變例 {li}  ({len(line)} 步)")
        out.append("")
        out.append("| # | 方 | 書譜(中文) | 書譜(ICCS) | 引擎首選 | 引擎分(cp) | 同? | 主要變化 |")
        out.append("|---|----|-----------|-----------|---------|-----------|----|---------|")
        board = ChessBoard(init_fen)
        for pi, iccs in enumerate(line, 1):
            fen = board.to_fen()
            side = '紅' if board.move_player == cchess.RED else '黑'
            chinese = iccs_to_text(board, iccs)
            act = cache.get(fen, {})
            best_iccs = act.get('move', '?')
            best_text = iccs_to_text(board, best_iccs) if best_iccs != '?' else '?'
            score = fmt_score(act)
            pv = ' '.join(act.get('moves', [])[:6])
            same = '✓' if best_iccs == iccs else '✗'
            out.append(f"| {pi} | {side} | {chinese} | `{iccs}` | {best_text} `{best_iccs}` | {score} | {same} | `{pv}` |")
            mv = board.move_iccs(iccs)
            if mv is None:
                out.append(f"| ! | | invalid: {iccs} | | | | | |")
                break
            board.next_turn()
        out.append("")

    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('xqf', help='Path to XQF file')
    ap.add_argument('-d', '--depth', type=int, default=14)
    ap.add_argument('-o', '--output', help='Output Markdown path (default: stdout)')
    args = ap.parse_args()

    print(f"[analyzing] {args.xqf}  depth={args.depth}", file=sys.stderr)
    t0 = time.time()
    result = analyze_file(args.xqf, EXE, depth=args.depth)
    md = render_markdown(result, args.depth)
    elapsed = time.time() - t0
    print(f"[done] {elapsed:.1f}s", file=sys.stderr)

    if args.output:
        Path(args.output).write_text(md, encoding='utf-8')
        print(f"[written] {args.output}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(md.encode('utf-8'))


if __name__ == '__main__':
    main()
