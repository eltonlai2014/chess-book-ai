"""Find case-duplicate XQF files in the source library and report annotation quality.

A "garbage" character is anything in the Unicode PUA range (U+E000..U+F8FF) — that's
the fallback codepoint range cchess emits when it can't decode the original bytes.
Whichever file in a duplicate group has fewer garbage chars is the version to keep.
"""
import sys
from collections import defaultdict
from pathlib import Path

from cchess import read_from_xqf

SRC = Path(r"D:\Elton\TestArea\chess-book")


def is_garbage(ch: str) -> bool:
    cp = ord(ch)
    return 0xE000 <= cp <= 0xF8FF


def annote_quality(game) -> dict:
    """Return {n_moves_with_annote, total_chars, garbage_chars}."""
    n = 0
    total = 0
    garbage = 0
    for mv in game.iter_moves():
        a = getattr(mv, 'annote', None)
        if not a:
            continue
        n += 1
        total += len(a)
        for ch in a:
            if is_garbage(ch):
                garbage += 1
    return {'n_moves': n, 'total': total, 'garbage': garbage}


def main():
    # Group files by lowercased name
    groups = defaultdict(list)
    for fp in SRC.rglob("*"):
        if fp.is_file() and fp.suffix.lower() == ".xqf":
            groups[fp.name.lower()].append(fp)

    dups = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"Total unique-name files: {len(groups)}, duplicate-name groups: {len(dups)}")
    print()

    if not dups:
        print("No duplicates.")

    for name, paths in sorted(dups.items()):
        print(f"=== {name} ({len(paths)} copies) ===")
        rows = []
        for p in paths:
            try:
                g = read_from_xqf(str(p))
                q = annote_quality(g)
                rows.append((p, q, None))
            except Exception as e:
                rows.append((p, None, str(e)))

        for p, q, err in rows:
            if err:
                print(f"  {p.name}  [parse error: {err}]")
            else:
                ratio = (q['garbage'] / q['total'] * 100) if q['total'] else 0
                print(f"  {p.name}  moves-with-annote={q['n_moves']:3d}  "
                      f"chars={q['total']:5d}  garbage={q['garbage']:4d} ({ratio:5.1f}%)")
        # Recommend keeper: lowest garbage ratio, tiebreak by most chars
        valid = [(p, q) for p, q, err in rows if q is not None]
        if valid:
            valid.sort(key=lambda x: (x[1]['garbage'] / max(1, x[1]['total']), -x[1]['total']))
            keeper = valid[0][0]
            print(f"  → recommend keep: {keeper}")
        print()


if __name__ == '__main__':
    main()
