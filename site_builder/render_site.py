"""Generate static HTML site from games.json + positions.js.

Output layout (everything under output/site/):
  index.html
  style.css
  board.js
  positions.js   (already produced by build_data.py)
  games/<file>.html
"""
import json
import re
import sys
import shutil
from pathlib import Path

from cchess import ChessBoard

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_data import _to_trad  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "output" / "site"
DATA_DIR = OUT_DIR / "data"
GAMES_DIR = OUT_DIR / "games"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def load_games():
    return json.loads((DATA_DIR / "games.json").read_text(encoding='utf-8'))


def load_positions():
    text = (OUT_DIR / "positions.js").read_text(encoding='utf-8')
    m = re.search(r'window\.POSITIONS\s*=\s*(\{.*\});\s*$', text, re.DOTALL)
    return json.loads(m.group(1)) if m else {}


def load_deep():
    path = OUT_DIR / "positions_deep.js"
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8')
    m = re.search(r'window\.POSITIONS_DEEP\s*=\s*(\{.*\});\s*$', text, re.DOTALL)
    return json.loads(m.group(1)) if m else {}


def _iccs_to_chinese(fen: str, iccs: str) -> str:
    """Convert an ICCS move to its Chinese notation using a throwaway board."""
    try:
        clone = ChessBoard(fen)
        mv = clone.move_iccs(iccs)
        return _to_trad(mv.to_text()) if mv else iccs
    except Exception:
        return iccs


def enrich_positions(positions: dict, deep: dict | None = None) -> dict:
    """Per-position: add `best_chinese`, `pv_detail`, and optional deep-eval fields.

    pv_detail enables the JS client to animate the engine's principal variation
    without needing a chess library in the browser.
    Deep-eval fields (`deep_score`, `deep_mate`, `deep_best_iccs`,
    `deep_best_chinese`, `deep_depth`) let the client mark plies where the
    deeper search disagrees with the shallow one.
    """
    deep = deep or {}
    enriched = {}
    for fen, entry in positions.items():
        e = dict(entry)
        best = e.get('best_iccs')
        e['best_chinese'] = _iccs_to_chinese(fen, best) if best else None

        d = deep.get(fen)
        if d:
            e['deep_score'] = d.get('score')
            e['deep_mate'] = d.get('mate')
            e['deep_best_iccs'] = d.get('best_iccs')
            e['deep_best_chinese'] = _iccs_to_chinese(fen, d.get('best_iccs')) if d.get('best_iccs') else None
            e['deep_depth'] = d.get('depth')

        pv_detail = []
        try:
            board = ChessBoard(fen)
            for iccs in e.get('pv') or []:
                chinese = _iccs_to_chinese(board.to_fen(), iccs)
                mv = board.move_iccs(iccs)
                if mv is None:
                    break
                board.next_turn()
                pv_detail.append({
                    'iccs': iccs,
                    'chinese': chinese,
                    'fen_after': board.to_fen(),
                })
        except Exception:
            pass
        e['pv_detail'] = pv_detail
        enriched[fen] = e
    return enriched


def save_positions_view(path: Path, positions: dict):
    payload = json.dumps(positions, ensure_ascii=False, separators=(',', ':'))
    path.write_text(f"window.POSITIONS = {payload};\n", encoding='utf-8')


def display_title(name: str) -> str:
    if name.lower().endswith('.xqf'):
        name = name[:-4]
    return name


def ascii_slug(name: str) -> str:
    """Stable ASCII slug derived from filename — avoids tooling that chokes on
    Unicode URLs (Live Server, some static hosts)."""
    import hashlib
    return 'game-' + hashlib.sha1(name.encode('utf-8')).hexdigest()[:10]


INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>象棋書譜 AI 對照</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<header><h1>象棋書譜 × Pikafish 對照</h1>
<p class="meta">共 {n_games} 個棋譜檔，{n_positions} 個唯一局面已分析</p></header>
<main>
<ul class="game-list">
{items}
</ul>
</main>
</body>
</html>
"""

GAME_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<link rel="stylesheet" href="../style.css">
</head>
<body>
<header class="game-header">
<a class="back" href="../index.html">← 回到列表</a>
<h1>{title}</h1>
<span class="meta">變例 {n_var} 條 · 結果 {result}</span>
</header>
<main class="game">
<aside class="board-panel">
<svg id="board" viewBox="0 0 540 600" xmlns="http://www.w3.org/2000/svg"></svg>
<svg id="chart" viewBox="0 0 540 140" xmlns="http://www.w3.org/2000/svg"></svg>
</aside>
<section class="game-panel">
<div class="control-bar">
<select id="variation-select">{variation_options}</select>
<button class="nav-first" title="跳到第一步">|◀</button>
<button class="nav-prev" title="上一步">◀</button>
<span class="nav-status" id="navStatus">第 0 / 0 步</span>
<button class="nav-next" title="下一步">▶</button>
<button class="nav-last" title="跳到末步">▶|</button>
<button class="demo-play" id="demoBtn">▶ 演示推演</button>
<label class="redp"><input type="checkbox" id="redPerspective" checked> 紅方視角</label>
</div>
<div class="step-info" id="stepInfo">
<span class="placeholder">點選表格任一步，或變例選單切換變例</span>
</div>
<div class="game-body">
<div class="plies-host">
{variation_tables}
</div>
<div class="annote-box" id="annoteBox"></div>
</div>
</section>
</main>
<script src="../positions_view.js"></script>
<script src="../board.js"></script>
<script>
const GAME = {game_json};
initGamePage(GAME);
</script>
</body>
</html>
"""


def render_variation_table(vi: int, plies: list) -> str:
    rows = []
    for pi, p in enumerate(plies):
        if not p.get('fen'):
            rows.append(f'<tr class="invalid"><td>!</td><td colspan="5">{p["chinese"]}</td></tr>')
            continue
        side_cls = 'red' if p['side'] == 'red' else 'black'
        side_label = '紅' if p['side'] == 'red' else '黑'
        rows.append(
            f'<tr data-var="{vi}" data-ply="{pi}" data-fen="{p["fen"]}" class="{side_cls}">'
            f'<td class="num">{pi + 1}</td>'
            f'<td class="side">{side_label}</td>'
            f'<td class="book-cn">{p["chinese"]}</td>'
            f'<td class="eng-best"></td>'
            f'<td class="score"></td>'
            f'<td class="delta"></td>'
            f'<td class="deep-delta"></td>'
            f'<td class="same"></td>'
            f'</tr>'
        )
    style = '' if vi == 0 else ' style="display:none"'
    return (
        f'<div class="plies-wrap" data-var="{vi}"{style}>'
        f'<table class="plies"><thead><tr>'
        '<th>#</th><th>方</th><th>書譜</th>'
        '<th>引擎首選</th><th>分(cp)</th>'
        '<th title="depth 12 淺算失分">失分</th>'
        '<th title="depth 22 深算失分；有時與淺算差很多 = 人類陷阱">深失</th>'
        '<th>同?</th>'
        '</tr></thead><tbody>' + '\n'.join(rows) + '</tbody></table></div>'
    )


def render_game(game: dict) -> str:
    title = display_title(game['file'])
    options = []
    tables = []
    for vi, plies in enumerate(game['variations']):
        options.append(f'<option value="{vi}">變例 {vi + 1} ({len(plies)} 步)</option>')
        tables.append(render_variation_table(vi, plies))
    return GAME_HTML.format(
        title=title,
        result=game.get('result', '*'),
        n_var=len(game['variations']),
        variation_options='\n'.join(options),
        variation_tables='\n'.join(tables),
        game_json=json.dumps(game, ensure_ascii=False),
    )


def render_index(games: list, n_positions: int) -> str:
    items = []
    for g in sorted(games, key=lambda x: x['file']):
        slug = ascii_slug(g['file'])
        title = display_title(g['file'])
        ply_total = sum(len(v) for v in g['variations'])
        items.append(
            f'<li><a href="games/{slug}.html">{title}</a> '
            f'<span class="dim">· {len(g["variations"])} 變例 · {ply_total} 步</span></li>'
        )
    return INDEX_HTML.format(
        n_games=len(games),
        n_positions=n_positions,
        items='\n'.join(items),
    )


def main():
    games = load_games()
    positions = load_positions()
    deep = load_deep()
    print(f"[load] {len(games)} games, {len(positions)} positions, {len(deep)} deep", file=sys.stderr)

    print("[enrich] computing Chinese notation + PV fen-after + deep overlay", file=sys.stderr)
    positions = enrich_positions(positions, deep)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    view_path = OUT_DIR / "positions_view.js"
    save_positions_view(view_path, positions)
    print(f"[write] {view_path}", file=sys.stderr)

    # Copy static assets
    for asset in ('style.css', 'board.js'):
        src = ASSETS_DIR / asset
        if src.exists():
            shutil.copy2(src, OUT_DIR / asset)
            print(f"[copy] {asset}", file=sys.stderr)

    # Per-game pages — clean old Chinese-named files first
    for old in GAMES_DIR.glob('*.html'):
        old.unlink()
    for g in games:
        slug = ascii_slug(g['file'])
        path = GAMES_DIR / f"{slug}.html"
        path.write_text(render_game(g), encoding='utf-8')
    print(f"[write] {len(games)} game pages", file=sys.stderr)

    # Index
    (OUT_DIR / "index.html").write_text(render_index(games, len(positions)), encoding='utf-8')
    print(f"[write] index.html", file=sys.stderr)

    # Mirror to /docs/ so GitHub Pages can serve it (Pages source dropdown only
    # lets you pick `/(root)` or `/docs`, not arbitrary subfolders).
    docs_dir = REPO / "docs"
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    shutil.copytree(OUT_DIR, docs_dir)
    print(f"[mirror] {OUT_DIR} → {docs_dir}  (for GitHub Pages)", file=sys.stderr)

    print(f"[done] open {OUT_DIR / 'index.html'} in browser", file=sys.stderr)


if __name__ == '__main__':
    main()
