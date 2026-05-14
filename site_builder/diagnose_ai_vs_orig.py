"""Compare encryption + annote quality across AI/ vs non-AI/ XQF files.

Asks: does the AI/ subset use a different XQF variant (zero crypt keys,
indicating the user re-saved them after manual fixes)?
"""
import struct
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyze import iccs_to_text  # noqa: E402
from cchess import read_from_xqf  # noqa: E402

SRC = Path(r"D:\Elton\TestArea\chess-book")


def char_kind(ch):
    cp = ord(ch)
    if 0xE000 <= cp <= 0xF8FF: return 'PUA'
    if 0x4E00 <= cp <= 0x9FFF: return 'CJK'
    if 0x3040 <= cp <= 0x30FF: return 'JP'
    if 0x0400 <= cp <= 0x04FF: return 'Cyr'
    if 0x0370 <= cp <= 0x03FF: return 'Grk'
    if ch.isascii(): return 'ASCII'
    return 'other'


def garble_ratio(text):
    if not text:
        return 0.0
    sus = sum(1 for ch in text if char_kind(ch) not in ('CJK', 'ASCII'))
    return sus / len(text)


def annote_stats(game):
    total = 0
    clean = 0
    partial = 0
    garbled = 0
    for mv in game.iter_moves():
        a = getattr(mv, 'annote', None)
        if not a:
            continue
        total += 1
        r = garble_ratio(a)
        if r < 0.05: clean += 1
        elif r < 0.3: partial += 1
        else: garbled += 1
    return total, clean, partial, garbled


def inspect(fp: Path):
    d = fp.read_bytes()
    if d[:2] != b'XQ':
        return None
    version = d[2]
    parsed = struct.unpack("<BIBBBBBBBB", d[3:16])
    # Try reading via cchess too
    try:
        g = read_from_xqf(str(fp))
        n, clean, partial, garbled = annote_stats(g)
    except Exception as e:
        n = clean = partial = garbled = -1
    return {
        'size': len(d),
        'version': version,
        'KeyMask': parsed[0],
        'ProductId': parsed[1],
        'KeysSum': parsed[6],
        'KeyXY': parsed[7],
        'KeyXYf': parsed[8],
        'KeyXYt': parsed[9],
        'annote_n': n, 'clean': clean, 'partial': partial, 'garbled': garbled,
    }


def main():
    rows = []
    for fp in SRC.rglob("*"):
        if not fp.is_file() or fp.suffix.lower() != '.xqf':
            continue
        info = inspect(fp)
        if info is None:
            continue
        rel = fp.relative_to(SRC)
        ai = str(rel).startswith('AI')
        info['rel'] = str(rel)
        info['ai'] = ai
        rows.append(info)

    rows.sort(key=lambda r: (not r['ai'], r['rel']))

    print(f"{'AI?':>3} {'KMask':>6} {'KSum':>5} {'KXY':>5} {'KXYf':>5} {'KXYt':>5} {'annote':>7} {'clean':>5} {'gbld':>4}  rel_path")
    print("-" * 110)
    for r in rows:
        ai = 'AI' if r['ai'] else '   '
        print(f"{ai:>3} 0x{r['KeyMask']:02x}  0x{r['KeysSum']:02x}  0x{r['KeyXY']:02x}  0x{r['KeyXYf']:02x}  0x{r['KeyXYt']:02x}  "
              f"{r['annote_n']:>5}  {r['clean']:>5}  {r['garbled']:>4}  {r['rel']}")

    # Summary
    print()
    for label, subset in [('AI/', [r for r in rows if r['ai']]),
                           ('non-AI', [r for r in rows if not r['ai']])]:
        n = len(subset)
        zero_keys = sum(1 for r in subset if (r['KeysSum'] | r['KeyXY'] | r['KeyXYf'] | r['KeyXYt']) == 0)
        total_annote = sum(max(r['annote_n'], 0) for r in subset)
        total_clean = sum(max(r['clean'], 0) for r in subset)
        total_garbled = sum(max(r['garbled'], 0) for r in subset)
        pct_clean = total_clean / total_annote * 100 if total_annote else 0
        pct_garbled = total_garbled / total_annote * 100 if total_annote else 0
        print(f"[{label}] {n} files  | zero-key files: {zero_keys}/{n} "
              f"| annote: {total_annote} (clean {pct_clean:.0f}%, garbled {pct_garbled:.0f}%)")


if __name__ == '__main__':
    main()
