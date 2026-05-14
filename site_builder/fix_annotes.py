"""One-shot: patch existing games.json with Big5-recovered annotations.

Avoids re-running the engine. Just fixes annote fields in-place.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_data import _recover_annote, _cjk_ratio, _to_trad  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
GAMES_JSON = REPO / "output/site/data/games.json"


def main():
    games = json.loads(GAMES_JSON.read_text(encoding='utf-8'))
    fixed_a = fixed_c = total_a = total_c = 0
    samples = []
    for g in games:
        for v in g['variations']:
            for p in v:
                a = p.get('annote')
                if a:
                    total_a += 1
                    new = _recover_annote(a)
                    if new != a:
                        fixed_a += 1
                        if len(samples) < 5:
                            samples.append((g['file'], a[:30], new[:30]))
                        p['annote'] = new
                c = p.get('chinese')
                if c:
                    total_c += 1
                    new_c = _to_trad(c)
                    if new_c != c:
                        fixed_c += 1
                        p['chinese'] = new_c
    GAMES_JSON.write_text(json.dumps(games, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"[fix] annotes recovered: {fixed_a}/{total_a}", file=sys.stderr)
    print(f"[fix] move notation simp→trad: {fixed_c}/{total_c}", file=sys.stderr)
    for f, before, after in samples:
        print(f"  {f}", file=sys.stderr)
        print(f"    before: {before!r}", file=sys.stderr)
        print(f"    after : {after!r}", file=sys.stderr)


if __name__ == '__main__':
    main()
