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


def load_chessdb():
    """Cloud database from chessdb.cn (see site_builder/chessdb_query.py)."""
    path = DATA_DIR / "chessdb_cache.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def _iccs_to_chinese(fen: str, iccs: str) -> str:
    """Convert an ICCS move to its Chinese notation using a throwaway board."""
    try:
        clone = ChessBoard(fen)
        mv = clone.move_iccs(iccs)
        return _to_trad(mv.to_text()) if mv else iccs
    except Exception:
        return iccs


def enrich_positions(positions: dict, deep: dict | None = None, chessdb: dict | None = None) -> dict:
    """Per-position: add `best_chinese`, `pv_detail`, and optional deep-eval +
    chessdb cloud-database fields.

    pv_detail enables the JS client to animate the engine's principal variation
    without needing a chess library in the browser.
    Deep-eval fields (`deep_score`, `deep_mate`, `deep_best_iccs`,
    `deep_best_chinese`, `deep_depth`) let the client mark plies where the
    deeper search disagrees with the shallow one.
    Chessdb fields (`cdb_best_iccs`, `cdb_best_chinese`, `cdb_best_score`,
    `cdb_best_winrate`, `cdb_moves`) expose the cloud database's view per FEN.
    """
    deep = deep or {}
    chessdb = chessdb or {}
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

        cdb = chessdb.get(fen)
        if cdb and cdb.get('status') == 'ok' and cdb.get('moves'):
            top = cdb['moves'][0]
            e['cdb_best_iccs'] = top.get('iccs')
            e['cdb_best_chinese'] = _iccs_to_chinese(fen, top.get('iccs')) if top.get('iccs') else None
            e['cdb_best_score'] = top.get('score')
            e['cdb_best_winrate'] = top.get('winrate')
            # Keep all moves so the UI can look up the book move's winrate too.
            e['cdb_moves'] = [
                {'iccs': m['iccs'], 'score': m.get('score'), 'winrate': m.get('winrate')}
                for m in cdb['moves']
            ]

        def _build_pv_detail(pv_iccs):
            out = []
            try:
                board = ChessBoard(fen)
                for iccs in pv_iccs or []:
                    chinese = _iccs_to_chinese(board.to_fen(), iccs)
                    mv = board.move_iccs(iccs)
                    if mv is None:
                        break
                    board.next_turn()
                    out.append({
                        'iccs': iccs,
                        'chinese': chinese,
                        'fen_after': board.to_fen(),
                    })
            except Exception:
                pass
            return out

        e['pv_detail'] = _build_pv_detail(e.get('pv'))
        if d:
            e['deep_pv_detail'] = _build_pv_detail(d.get('pv'))
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=IBM+Plex+Sans+TC:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&family=Noto+Serif+TC:wght@400;500;600&display=swap">
<link rel="stylesheet" href="style.css">
<script>
  // Apply theme before stylesheet kicks in to prevent flash-of-wrong-theme.
  (function() {{
    var t = localStorage.getItem('chessbookTheme') || 'amber';
    document.documentElement.dataset.theme = t;
  }})();
</script>
</head>
<body>
<header><h1>象棋書譜 × Pikafish 對照</h1>
<p class="meta">共 {n_games} 個棋譜檔 · {n_positions} 個唯一局面已分析</p>
<label class="theme-picker">主題
<select id="themePicker" onchange="setTheme(this.value)">
<option value="amber">琥珀 Amber</option>
<option value="emerald">翡翠 Emerald</option>
<option value="ink">墨拓 Ink</option>
</select>
</label>
</header>
<script>
  function setTheme(name) {{
    document.documentElement.dataset.theme = name;
    localStorage.setItem('chessbookTheme', name);
  }}
  document.addEventListener('DOMContentLoaded', function() {{
    var t = localStorage.getItem('chessbookTheme') || 'amber';
    var p = document.getElementById('themePicker');
    if (p) p.value = t;
  }});
</script>
<main class="categories">
{items}
</main>
</body>
</html>
"""

GAME_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=IBM+Plex+Sans+TC:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&family=Noto+Serif+TC:wght@400;500;600&display=swap">
<link rel="stylesheet" href="../style.css">
<script>
  (function() {{
    var t = localStorage.getItem('chessbookTheme') || 'amber';
    document.documentElement.dataset.theme = t;
  }})();
</script>
</head>
<body>
<header class="game-header">
<a class="back" href="../index.html">← 回到列表</a>
<h1>{title}</h1>
<span class="meta">變例 {n_var} 條 · 結果 {result}</span>
<label class="theme-picker">主題
<select id="themePicker" onchange="setTheme(this.value)">
<option value="amber">琥珀 Amber</option>
<option value="emerald">翡翠 Emerald</option>
<option value="ink">墨拓 Ink</option>
</select>
</label>
</header>
<script>
  function setTheme(name) {{
    document.documentElement.dataset.theme = name;
    localStorage.setItem('chessbookTheme', name);
  }}
  document.addEventListener('DOMContentLoaded', function() {{
    var t = localStorage.getItem('chessbookTheme') || 'amber';
    var p = document.getElementById('themePicker');
    if (p) p.value = t;
  }});
</script>
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
<button class="demo-play" id="demoBtnShallow" data-mode="shallow" title="播放 depth-12 引擎主變">▶ 演示 淺12</button>
<button class="demo-play demo-deep" id="demoBtnDeep" data-mode="deep" title="播放 depth-22 引擎主變（只有深算過的局面）">▶ 演示 深22</button>
<label class="redp"><input type="checkbox" id="redPerspective" checked> 紅方視角</label>
</div>
<div class="step-info" id="stepInfo">
<span class="placeholder">點選表格任一步，或變例選單切換變例</span>
</div>
<div class="game-body">
<div class="plies-host">
{variation_tables}
</div>
<div class="right-col">
<div class="annote-box" id="annoteBox"></div>
<div class="alts-box" id="altsBox">
<div class="alts-head">💡 本步可選</div>
<div class="alts-body"></div>
</div>
</div>
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
            f'<td class="cdb"></td>'
            f'<td class="same"></td>'
            f'</tr>'
        )
    style = '' if vi == 0 else ' style="display:none"'
    return (
        f'<div class="plies-wrap" data-var="{vi}"{style}>'
        f'<table class="plies"><thead><tr>'
        '<th>#</th><th>方</th><th>書譜</th>'
        '<th>引擎首選</th>'
        '<th title="局面評分（紅方視角；正=紅優，負=黑優）">分(cp)</th>'
        '<th title="depth 12 紅方分數變化（正=紅得 cp，負=紅失 cp）">Δ</th>'
        '<th title="depth 22 紅方分數變化（與 Δ 差很大 = 人類陷阱）">深Δ</th>'
        '<th title="chessdb.cn 雲庫評分（紅方視角；hover 看最佳替代）">雲庫</th>'
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


def _group_key(rel_path: str) -> str:
    """Group by chess-category subdirectory. Strip the 'AI\\' provenance prefix
    so manually-fixed copies sort with their semantic family."""
    p = rel_path.replace('/', '\\')
    if p.startswith('AI\\'):
        p = p[3:]
    if '\\' in p:
        return p.rsplit('\\', 1)[0]
    return '主目錄'


def render_index(games: list, n_positions: int) -> str:
    groups = {}
    for g in games:
        key = _group_key(g.get('rel_path', g['file']))
        groups.setdefault(key, []).append(g)

    # 主目錄 first, then alphabetical Chinese
    sorted_keys = sorted(groups.keys(), key=lambda k: (k != '主目錄', k))

    sections = []
    for key in sorted_keys:
        members = sorted(groups[key], key=lambda x: x['file'])
        items = []
        for g in members:
            slug = ascii_slug(g['file'])
            title = display_title(g['file'])
            ply_total = sum(len(v) for v in g['variations'])
            ai_mark = ' <span class="ai-mark" title="已手動修正註解的版本">✎</span>' if g.get('rel_path', '').replace('/', '\\').startswith('AI\\') else ''
            items.append(
                f'<li><a href="games/{slug}.html">{title}</a>{ai_mark} '
                f'<span class="dim">· {len(g["variations"])} 變例 · {ply_total} 步</span></li>'
            )
        sections.append(
            f'<section class="category"><h2>{key} <span class="dim">({len(members)})</span></h2>'
            f'<ul class="game-list">{"".join(items)}</ul></section>'
        )

    return INDEX_HTML.format(
        n_games=len(games),
        n_positions=n_positions,
        items='\n'.join(sections),
    )


def main():
    games = load_games()
    positions = load_positions()
    deep = load_deep()
    chessdb = load_chessdb()
    print(f"[load] {len(games)} games, {len(positions)} positions, {len(deep)} deep, {len(chessdb)} chessdb", file=sys.stderr)

    print("[enrich] computing Chinese notation + PV fen-after + deep + chessdb overlay", file=sys.stderr)
    positions = enrich_positions(positions, deep, chessdb)

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
