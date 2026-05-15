"""Probe non-AI/ XQF files: read each with cchess, see how many annotes recover
via Big5 re-decode, sample a few before/after."""
import sys
from pathlib import Path
from cchess import read_from_xqf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_data import _recover_annote, _cjk_ratio, _vocab_score  # noqa: E402

SRC = Path(r"D:\Elton\TestArea\chess-book")


def classify(text):
    if not text:
        return 'empty'
    r = _cjk_ratio(text)
    if r >= 0.7:
        return 'clean'
    if r >= 0.3:
        return 'partial'
    return 'garbled'


def main():
    files = [p for p in SRC.rglob("*") if p.is_file() and p.suffix.lower() == '.xqf']
    non_ai = [p for p in files if 'AI' not in p.parts]
    print(f"non-AI files: {len(non_ai)}")

    totals = {'clean': 0, 'partial': 0, 'garbled': 0, 'empty': 0}
    recoveries = {'clean': 0, 'partial': 0, 'garbled': 0, 'empty': 0}
    samples = []
    for fp in non_ai:
        try:
            g = read_from_xqf(str(fp))
        except Exception:
            continue
        for mv in g.iter_moves():
            a = getattr(mv, 'annote', None)
            if not a:
                continue
            orig_cat = classify(a)
            new = _recover_annote(a)
            new_cat = classify(new)
            totals[orig_cat] += 1
            recoveries[new_cat] += 1
            if a != new and len(samples) < 6 and orig_cat == 'garbled' and new_cat in ('clean', 'partial'):
                samples.append((fp.name, a[:50], new[:50]))

    print(f"\nBefore recovery:")
    for k in ('clean', 'partial', 'garbled'):
        print(f"  {k:8}: {totals[k]:4}")
    print(f"\nAfter recovery:")
    for k in ('clean', 'partial', 'garbled'):
        print(f"  {k:8}: {recoveries[k]:4}")

    print(f"\nSample recoveries:")
    for name, before, after in samples:
        print(f"  {name}")
        print(f"    {before!r}")
        print(f" -> {after!r}")


if __name__ == '__main__':
    main()
