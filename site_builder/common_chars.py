"""Build a list of in-domain common characters from clean annotations.

These chars become the 'vocabulary score': annote recovery prefers whichever
decoding hits more of these common chars.
"""
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
games = json.loads((REPO / "output/site/data/games.json").read_text(encoding='utf-8'))


def cjk_ratio(s):
    if not s:
        return 0
    return sum(1 for c in s if 0x4E00 <= ord(c) <= 0x9FFF) / len(s)


counter = Counter()
for g in games:
    for v in g['variations']:
        for p in v:
            a = p.get('annote')
            if not a or cjk_ratio(a) < 0.9:  # only the high-confidence-clean ones
                continue
            for ch in a:
                if 0x4E00 <= ord(ch) <= 0x9FFF:
                    counter[ch] += 1

top = counter.most_common(300)
print(f"Total distinct chars from clean annotes: {len(counter)}")
print(f"Top 300 covers {sum(c for _, c in top) / sum(counter.values()) * 100:.0f}% of usage")
chars = ''.join(ch for ch, _ in top)
print(f"\nCommon set:\n{chars}")
