"""Per-file checklist of AI/ XQF annotes that contain NULL bytes or other
control-char garbage. Each row gives variation + ply coordinates so the user
can find the position in XQStudio (演播室) and rewrite the annote there.

Output: output/broken_annotes.md
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_data import _recover_annote, _to_trad, _cjk_ratio  # noqa: E402
from analyze import iccs_to_text  # noqa: E402

import cchess
from cchess import ChessBoard

REPO = Path(__file__).resolve().parent.parent
SRC = Path(r"D:\Elton\TestArea\chess-book")

PAIRS = [
    ("牛頭滾",                  SRC / "AI" / "牛頭滾.xqf"),
    ("順包直車3兵對橫車邊馬",    SRC / "AI" / "順包" / "順包直車3兵對橫車邊馬.xqf"),
    ("順包兩頭蛇對雙橫車",      SRC / "AI" / "順包" / "順包兩頭蛇對雙橫車.xqf"),
]


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


def display(s):
    """Replace control chars with visible placeholders so the table reads cleanly."""
    if s is None:
        return ''
    return (s.replace('\x00', '␀')
             .replace('\r\n', '↵')
             .replace('\n', '↵')
             .replace('\r', '↵')
             .replace('|', '\\|')
             .strip())


def md_escape(s):
    return str(s).replace('|', '\\|').replace('\n', ' ').strip()


def collect_broken(xqf_path):
    """Return list of dicts, one per broken-annote ply. Includes Chinese
    notation derived by replaying the move on a fresh board."""
    game = cchess.read_from_xqf(str(xqf_path))
    init_fen = game.init_board.to_fen() if hasattr(game.init_board, 'to_fen') else str(game.init_board)

    rows = []
    seen_fen_annote = set()  # dedupe identical (fen, annote) across variations
    for vi, line_obj in enumerate(game.dump_moves()):
        board = ChessBoard(init_fen)
        for pi, mv in enumerate(line_obj['moves']):
            iccs = str(mv)
            raw = getattr(mv, 'annote', None)
            recovered = _recover_annote(raw)
            if recovered and looks_garbled(recovered):
                key = (board.to_fen(), recovered)
                if key not in seen_fen_annote:
                    seen_fen_annote.add(key)
                    chinese = _to_trad(iccs_to_text(board, iccs))
                    rows.append({
                        'vi': vi + 1, 'pi': pi + 1,
                        'iccs': iccs, 'chinese': chinese,
                        'annote': recovered,
                    })
            applied = board.move_iccs(iccs)
            if applied is None:
                break
            board.next_turn()
    return rows


def main():
    out_md = REPO / "output" / "broken_annotes.md"
    out_md.parent.mkdir(exist_ok=True)
    lines = [
        "# 需要在演播室手動修正的註解\n\n",
        "對應檔案 = `D:\\Elton\\TestArea\\chess-book\\AI\\` 下的版本（site 跑的是這一份）。\n",
        "下表已按 (檔案, 變例, ply) 排序，去除重複的同局面同註解。\n\n",
        "**符號**：`␀` = NULL byte、`↵` = 換行（CR/LF）。\n",
        "**做法**：演播室開檔 → 切到對應變例 → 走到第 N 步 → 編輯註解 → 重存。\n",
    ]

    total = 0
    for name, ai_path in PAIRS:
        if not ai_path.exists():
            continue
        rows = collect_broken(ai_path)
        total += len(rows)
        lines.append(f"\n## {name}（{len(rows)} 筆需修）\n\n")
        lines.append(f"路徑：`{ai_path}`\n\n")
        if not rows:
            lines.append("(無需修)\n")
            continue
        lines.append("| 變例 | 步 | 方 | 走法 | ICCS | 目前壞文字 |\n")
        lines.append("|---|---|---|---|---|---|\n")
        # side derived from ply parity (assuming red first)
        for r in rows:
            side = '紅' if r['pi'] % 2 == 1 else '黑'
            lines.append(f"| v{r['vi']} | p{r['pi']} | {side} | {md_escape(r['chinese'])} "
                         f"| `{r['iccs']}` | {display(r['annote'])} |\n")

    lines.insert(2, f"共 **{total}** 筆需修。\n\n")
    out_md.write_text(''.join(lines), encoding='utf-8')
    print(f"[md] {total} broken annotes -> {out_md}")


if __name__ == '__main__':
    main()
