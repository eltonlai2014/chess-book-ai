"""Compare annote text between AI/<file> and the non-AI <file> root version
to find recoverable text. For each (variation, ply) pair, dump:

  - AI version annote (raw + after _recover_annote)
  - non-AI version annote (raw + after _recover_annote)
  - which one looks cleaner

Output goes to output/annote_compare.md as a per-file table.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_data import _recover_annote, _vocab_score, _cjk_ratio  # noqa: E402

import cchess

REPO = Path(__file__).resolve().parent.parent
SRC = Path(r"D:\Elton\TestArea\chess-book")

# (display name, ai_path, original_path)
PAIRS = [
    ("牛頭滾",                    SRC / "AI" / "牛頭滾.xqf",
                                  SRC / "牛頭滾.XQF"),
    ("順包直車3兵對橫車邊馬",      SRC / "AI" / "順包" / "順包直車3兵對橫車邊馬.xqf",
                                  SRC / "順包" / "順包直車3兵對橫車邊馬.XQF"),
    ("順包兩頭蛇對雙橫車",        SRC / "AI" / "順包" / "順包兩頭蛇對雙橫車.xqf",
                                  SRC / "順包" / "順包兩頭蛇對雙橫車.XQF"),
]


def extract_annotes(xqf_path):
    """Return list of (vi, pi, iccs, raw_annote, recovered_annote) for every
    ply that has an annote in this XQF."""
    game = cchess.read_from_xqf(str(xqf_path))
    out = []
    for vi, line_obj in enumerate(game.dump_moves()):
        for pi, mv in enumerate(line_obj['moves']):
            raw = getattr(mv, 'annote', None)
            if not raw:
                continue
            recovered = _recover_annote(raw)
            out.append((vi, pi, str(mv), raw, recovered))
    return out


def looks_garbled(s):
    if not s:
        return False
    if any(0xE000 <= ord(c) <= 0xF8FF for c in s):
        return True
    if '\x00' in s:
        return True
    core = re.sub(r'[\s,.，。、！？!?:：;；()（）\[\]【】「」<>《》\d-]', '', s)
    if len(core) >= 4 and _cjk_ratio(core) < 0.7:
        return True
    return False


def pretty(s):
    if s is None:
        return '(無)'
    return repr(s)[1:-1][:80]  # drop surrounding quotes from repr


def main():
    out_md = REPO / "output" / "annote_compare.md"
    out_md.parent.mkdir(exist_ok=True)
    lines = ["# AI 版 vs 原版 註解對照\n",
             "每列只顯示「AI 看起來有問題」的 ply。如果原版該位置乾淨，就是可以拿來修復的素材。\n"]

    for name, ai_path, orig_path in PAIRS:
        lines.append(f"\n## {name}\n")
        if not ai_path.exists():
            lines.append(f"AI 版不存在：`{ai_path}`\n")
            continue
        if not orig_path.exists():
            lines.append(f"原版不存在：`{orig_path}`\n")
            continue

        try:
            ai_list = extract_annotes(ai_path)
            orig_list = extract_annotes(orig_path)
        except Exception as e:
            lines.append(f"解析錯誤: {e}\n")
            continue

        # Key both by (vi, pi); assumes same variation tree structure between
        # AI re-save and original. Fall back to first-ply iccs if vi/pi mismatch.
        orig_map = {(vi, pi): (raw, rec) for vi, pi, iccs, raw, rec in orig_list}

        problems = [t for t in ai_list if looks_garbled(t[4])]
        lines.append(f"AI 版有問題的 annote 數：{len(problems)}（總 {len(ai_list)}）"
                     f"／原版總 annote 數：{len(orig_list)}\n\n")

        if not problems:
            lines.append("(全部乾淨)\n")
            continue

        lines.append("| 變例 | 步 | 走法 | AI（recover 後） | 原版（recover 後） | 原版乾淨? |\n")
        lines.append("|---|---|---|---|---|---|\n")
        for vi, pi, iccs, ai_raw, ai_rec in problems[:50]:
            orig = orig_map.get((vi, pi))
            if orig is None:
                orig_rec = '(原版同位置無註解)'
                orig_clean = '—'
            else:
                _, orig_rec = orig
                orig_clean = '✓' if not looks_garbled(orig_rec) else '✗'
            ai_disp = pretty(ai_rec).replace('|', '\\|')
            orig_disp = pretty(orig_rec).replace('|', '\\|')
            lines.append(f"| v{vi+1} | p{pi+1} | {iccs} | {ai_disp} | {orig_disp} | {orig_clean} |\n")

        if len(problems) > 50:
            lines.append(f"\n(還有 {len(problems)-50} 個未列出)\n")

        # Summary stat for this file
        recoverable = sum(1 for vi, pi, iccs, ar, arc in problems
                          if orig_map.get((vi, pi)) and not looks_garbled(orig_map[(vi, pi)][1]))
        lines.append(f"\n**可從原版回填：{recoverable} / {len(problems)}**\n")

    out_md.write_text(''.join(lines), encoding='utf-8')
    print(f"[md] {out_md}")
    print(f"      ({sum(1 for l in lines if l.startswith('| v'))} rows)")


if __name__ == '__main__':
    main()
