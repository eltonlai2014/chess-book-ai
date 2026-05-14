"""Quick stats: how garbled are the annotations, and try alternative codecs.

Mojibake symptom: chars decode as a mix of Chinese, Japanese hiragana, Cyrillic,
Greek, PUA — suggests bytes are post-XOR but mis-encoded, OR XOR key is wrong
for those files, OR the source was originally non-GB18030.
"""
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GAMES_JSON = REPO / "output/site/data/games.json"


def char_kind(ch):
    cp = ord(ch)
    if 0xE000 <= cp <= 0xF8FF:
        return 'PUA'
    if 0x4E00 <= cp <= 0x9FFF:
        return 'CJK'
    if 0x3040 <= cp <= 0x30FF:
        return 'JP-kana'
    if 0x0400 <= cp <= 0x04FF:
        return 'Cyrillic'
    if 0x0370 <= cp <= 0x03FF:
        return 'Greek'
    if ch.isascii():
        return 'ASCII'
    return f'other-U+{cp:04X}'


def garble_score(text):
    if not text:
        return 0, {}
    counts = defaultdict(int)
    for ch in text:
        counts[char_kind(ch)] += 1
    total = len(text)
    cjk = counts['CJK']
    pua = counts['PUA']
    suspicious = sum(v for k, v in counts.items() if k not in ('CJK', 'ASCII'))
    return suspicious / total, dict(counts)


def main():
    games = json.loads(GAMES_JSON.read_text(encoding='utf-8'))

    by_file = defaultdict(lambda: {'total': 0, 'has_annote': 0, 'clean': 0, 'partial': 0, 'garbled': 0, 'samples': []})
    for g in games:
        f = g['file']
        for v in g['variations']:
            for p in v:
                if not p.get('annote'):
                    continue
                by_file[f]['has_annote'] += 1
                ratio, _ = garble_score(p['annote'])
                if ratio < 0.05:
                    by_file[f]['clean'] += 1
                elif ratio < 0.3:
                    by_file[f]['partial'] += 1
                else:
                    by_file[f]['garbled'] += 1
                    if len(by_file[f]['samples']) < 3:
                        by_file[f]['samples'].append(p['annote'])

    for f, st in by_file.items():
        total = st['has_annote']
        if total == 0:
            continue
        print(f"\n=== {f}  ({total} annotations) ===")
        for k in ('clean', 'partial', 'garbled'):
            pct = st[k] / total * 100
            print(f"  {k:8}: {st[k]:3}  ({pct:.0f}%)")
        for i, s in enumerate(st['samples']):
            print(f"  garbled sample {i+1}: {s[:50]!r}")


if __name__ == '__main__':
    main()
