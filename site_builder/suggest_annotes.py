"""For broken annotes in a re-parsed XQF, generate a plausible Chinese
annotation based on the engine evaluation of the position before/after.
Output: output/suggested_annotes.md — checklist with both the broken
text (for context — partial chars may hint at the user's original intent)
and a proposed replacement string the user can paste into XQStudio.

We do NOT modify the XQF. Source-of-truth stays with the user.
"""
import json
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
OUT_DIR = REPO / "output" / "site"
SRC = Path(r"D:\Elton\TestArea\chess-book")

# Target file(s) the user wants suggestions for. Add more if needed.
TARGETS = [
    ("牛頭滾", SRC / "牛頭滾.XQF"),
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


def load_positions(name):
    path = OUT_DIR / name
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8')
    m = re.search(r'window\.\w+\s*=\s*(\{.*\});\s*$', text, re.DOTALL)
    return json.loads(m.group(1)) if m else {}


def score_cp(entry):
    if not entry:
        return None
    if entry.get('mate') is not None:
        m = entry['mate']
        return 30000 - abs(m) if m > 0 else -(30000 - abs(m))
    s = entry.get('score')
    return s if isinstance(s, int) else None


def red_pov(score, side):
    """Convert mover-POV to red-POV."""
    if score is None:
        return None
    return -score if side == 'black' else score


def fmt_score(s):
    if s is None:
        return '?'
    return f"{s:+d}"


def situation_label(red_score):
    """Human-readable position assessment from red POV."""
    if red_score is None:
        return '局勢不明'
    a = abs(red_score)
    if a < 60:
        return '均勢'
    side = '紅' if red_score > 0 else '黑'
    if a < 150:
        return f'{side}方略優'
    if a < 350:
        return f'{side}方優勢'
    if a < 700:
        return f'{side}方大優'
    return f'{side}方勝勢'


def move_quality(mover_loss):
    """mover_loss = how many cp the mover lost relative to best continuation.
    Positive = mover gave up cp (bad), negative = mover gained (rare, means
    the engine first-choice was actually inferior to what was played)."""
    if mover_loss is None:
        return None
    if mover_loss >= 300:
        return '敗著'
    if mover_loss >= 150:
        return '失誤'
    if mover_loss >= 70:
        return '欠佳'
    if mover_loss >= 30:
        return '次選'
    return '正著'


def suggest_annote(side, played_iccs, fen_before, fen_after, shallow, deep):
    """Build a plausible 1-2 sentence Chinese annote from engine signals."""
    e_before = shallow.get(fen_before)
    e_after = shallow.get(fen_after)
    d_before = deep.get(fen_before)
    d_after = deep.get(fen_after)

    sh_red_before = red_pov(score_cp(e_before), side)
    sh_red_after = red_pov(score_cp(e_after), 'black' if side == 'red' else 'red')
    dp_red_before = red_pov(score_cp(d_before), side)
    dp_red_after = red_pov(score_cp(d_after), 'black' if side == 'red' else 'red')

    # Pick the more reliable scores: prefer deep where available.
    red_before = dp_red_before if dp_red_before is not None else sh_red_before
    red_after = dp_red_after if dp_red_after is not None else sh_red_after

    # mover-POV loss caused by this move (positive = mover lost cp)
    if red_before is not None and red_after is not None:
        red_loss = red_before - red_after
        mover_loss = red_loss if side == 'red' else -red_loss
    else:
        mover_loss = None

    # Was this move the engine's first choice?
    engine_first = e_before.get('best_iccs') if e_before else None
    is_engine_pick = engine_first == played_iccs
    deep_first = d_before.get('best_iccs') if d_before else None
    is_deep_pick = deep_first == played_iccs

    qual = move_quality(mover_loss)
    sit_before = situation_label(red_before)
    sit_after = situation_label(red_after)

    # Detect "human trap": shallow said fine, deep says blunder
    sh_loss = None
    if sh_red_before is not None and sh_red_after is not None:
        sh_red_loss = sh_red_before - sh_red_after
        sh_loss = sh_red_loss if side == 'red' else -sh_red_loss
    is_trap = (sh_loss is not None and mover_loss is not None
               and sh_loss < 50 and mover_loss > 100)

    parts = []
    if is_trap:
        parts.append(f"陷阱（淺算{fmt_score(sh_loss)}cp、深算{fmt_score(mover_loss)}cp）")
    elif qual:
        parts.append(qual)

    if mover_loss is not None and abs(mover_loss) >= 30 and not is_trap:
        parts.append(f"失分 {mover_loss:+d}cp")

    if not is_deep_pick and deep_first and deep_first != played_iccs:
        # Convert engine's deep first choice to Chinese for readability
        try:
            cn = _to_trad(iccs_to_text(ChessBoard(fen_before), deep_first))
        except Exception:
            cn = deep_first
        parts.append(f"引擎首選：{cn}")

    # Always show the resulting situation
    if sit_after and sit_after != sit_before:
        parts.append(f"局勢轉為{sit_after}")
    elif sit_after:
        parts.append(sit_after)

    return '；'.join(parts) if parts else '(無法判斷)'


def main():
    shallow = load_positions('positions.js')
    deep = load_positions('positions_deep.js')

    out_md = REPO / "output" / "suggested_annotes.md"
    lines = [
        "# 引擎推測註解 — 給主人在演播室手動套用\n\n",
        "**重要**：這些是用引擎評分**反推**寫出的註解，不是主人原意。"
        "主人覺得跟自己想法吻合再用；否則自己重寫。\n\n",
        "格式：每筆顯示變例 / ply / 走法 / 目前壞文字 / **建議文字**。\n\n",
    ]

    total = 0
    for name, ai_path in TARGETS:
        if not ai_path.exists():
            lines.append(f"\n## {name}\n\n(檔案不存在)\n")
            continue
        game = cchess.read_from_xqf(str(ai_path))
        init_fen = game.init_board.to_fen() if hasattr(game.init_board, 'to_fen') else str(game.init_board)

        rows = []
        seen = set()
        for vi, line_obj in enumerate(game.dump_moves()):
            board = ChessBoard(init_fen)
            for pi, mv in enumerate(line_obj['moves']):
                iccs = str(mv)
                fen_before = board.to_fen()
                side = 'red' if board.move_player == cchess.RED else 'black'
                raw = getattr(mv, 'annote', None)
                recovered = _recover_annote(raw)
                # apply move so we can look up fen_after even if no annote
                applied = board.move_iccs(iccs)
                if applied is None:
                    break
                board.next_turn()
                fen_after = board.to_fen()
                if not recovered or not looks_garbled(recovered):
                    continue
                key = (fen_before, recovered)
                if key in seen:
                    continue
                seen.add(key)
                chinese = _to_trad(iccs_to_text(ChessBoard(fen_before), iccs))
                suggestion = suggest_annote(side, iccs, fen_before, fen_after, shallow, deep)
                rows.append({
                    'vi': vi + 1, 'pi': pi + 1, 'side': side,
                    'chinese': chinese, 'iccs': iccs,
                    'broken': recovered, 'suggestion': suggestion,
                })

        total += len(rows)
        lines.append(f"\n## {name}（{len(rows)} 筆建議）\n\n")
        lines.append(f"路徑：`{ai_path}`\n\n")
        lines.append("| 變例 | 步 | 方 | 走法 | ICCS | 目前壞文字 | 建議文字 |\n")
        lines.append("|---|---|---|---|---|---|---|\n")
        for r in rows:
            side_label = '紅' if r['side'] == 'red' else '黑'
            lines.append(
                f"| v{r['vi']} | p{r['pi']} | {side_label} "
                f"| {md_escape(r['chinese'])} | `{r['iccs']}` "
                f"| {display(r['broken'])} | **{md_escape(r['suggestion'])}** |\n"
            )

    lines.insert(2, f"共 **{total}** 筆建議。\n\n")
    out_md.write_text(''.join(lines), encoding='utf-8')
    print(f"[md] {total} suggestions -> {out_md}")


if __name__ == '__main__':
    main()
