"""Try alternative decoding to recover Traditional Chinese typed in Simplified UI.

cchess decodes XQF annote bytes as GB18030. If the original input was Trad-typed
into a Simp-mode editor, the underlying bytes may represent Trad characters via
a different codepage (Big5, CP950) that GB18030 mis-interprets as garbage.
"""
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
games = json.loads((REPO / "output/site/data/games.json").read_text(encoding='utf-8'))

CODECS = ['big5', 'big5hkscs', 'cp950', 'gb18030', 'gbk']


def try_recode(text, src='gb18030'):
    """For each target codec, re-encode text via `src` then decode via `target`."""
    results = {}
    try:
        raw = text.encode(src, errors='replace')
    except Exception:
        return results
    for tgt in CODECS:
        if tgt == src:
            continue
        try:
            out = raw.decode(tgt)
        except Exception:
            continue
        results[tgt] = out
    return results


def cjk_ratio(s):
    if not s:
        return 0
    return sum(1 for c in s if 0x4E00 <= ord(c) <= 0x9FFF) / len(s)


def show_sample(label, annote):
    print(f"\n--- {label} ---")
    print(f"  原始 (GB18030 by cchess): {annote!r}")
    print(f"    CJK ratio: {cjk_ratio(annote):.0%}")
    for tgt, out in try_recode(annote).items():
        marker = '  ★' if cjk_ratio(out) > cjk_ratio(annote) + 0.2 else ''
        print(f"  重編 → {tgt:10}: {out!r}{marker}")


# Pick samples from each garble level
samples_by_file = {}
for g in games:
    f = g['file']
    samples_by_file.setdefault(f, [])
    for v in g['variations']:
        for p in v:
            a = p.get('annote')
            if not a:
                continue
            cjk = cjk_ratio(a)
            # pick "partial" range (some Chinese, but obviously garbled)
            if 0.3 < cjk < 0.85 and len(a) > 10:
                if len(samples_by_file[f]) < 2:
                    samples_by_file[f].append(a)

for f, samples in samples_by_file.items():
    print(f"\n========== {f} ==========")
    for s in samples:
        show_sample(f, s)
