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
from enrich_depth import score_cp  # noqa: E402

# Keep this in sync with site_builder/find_trap_plies.py and assets/board.js.
SKIP_OPENING_PLIES = 15

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


def load_very_deep():
    """Optional depth-28 verification of trap positions (see verify_traps.py)."""
    path = OUT_DIR / "positions_very_deep.js"
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8')
    m = re.search(r'window\.POSITIONS_VERY_DEEP\s*=\s*(\{.*\});\s*$', text, re.DOTALL)
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
            # fen_after is intentionally omitted: applyIccs() in board.js
            # derives each step's FEN on the fly. Shipping it per step would
            # add ~30-40 MB to positions_view.js and push it past GitHub's
            # 100 MB file limit. Keep iccs + chinese only.
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
<p class="meta">共 {n_games} 個棋譜檔 · {n_positions} 個唯一局面已分析 · <a class="traps-link" href="traps.html">⚠ 全站陷阱 {n_traps}</a></p>
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

TRAPS_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>全站陷阱列表 — 象棋書譜 × Pikafish</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=IBM+Plex+Sans+TC:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&family=Noto+Serif+TC:wght@400;500;600&display=swap">
<link rel="stylesheet" href="style.css">
<script>
  (function() {{
    var t = localStorage.getItem('chessbookTheme') || 'amber';
    document.documentElement.dataset.theme = t;
  }})();
</script>
</head>
<body>
<header><h1>⚠ 全站陷阱列表</h1>
<p class="meta"><a class="back" href="index.html">← 回到列表</a> · 共 {n_traps} 個陷阱（淺算 &lt;50cp，深算 &gt;100cp，第 16 步起）</p>
</header>
<main class="traps-page">
<div class="traps-legend">
  <span class="leg-key">欄位</span>
  <span><span class="leg-label">變例·步</span><span class="leg-hint">v / 步序，點擊跳到局面</span></span>
  <span><span class="leg-label">方</span><span class="leg-hint">走子方</span></span>
  <span><span class="leg-label">走法</span><span class="leg-hint">中文記譜＋ICCS</span></span>
  <span><span class="leg-label deep">深失</span><span class="leg-hint">depth-22 評定的失分（cp）— 越大越糟</span></span>
  <span><span class="leg-label shallow">淺失</span><span class="leg-hint">depth-12 對同一步的判斷（cp，&lt;50 = 淺算看不出來）</span></span>
  <span><span class="leg-label vdeep">深28失</span><span class="leg-hint">depth-28 驗證（&gt;100=確認陷阱、30-100=減弱、&lt;30=深算翻案；—=尚未跑）</span></span>
  <span><span class="leg-label">原註解</span><span class="leg-hint">XQF 內既有註解</span></span>
</div>
{sections}
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
<a class="back back-traps" href="../traps.html#{traps_anchor}" title="跳到全站陷阱頁的此檔區段">⚠ 陷阱列表</a>
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
        traps_anchor=_file_anchor(game['file']),
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


def _count_tree_plies(tree: dict | None) -> int:
    """Total non-root nodes in the move tree = unique plies after dedup."""
    if not tree:
        return 0
    total = 0
    stack = list(tree.get('children') or [])
    while stack:
        node = stack.pop()
        total += 1
        stack.extend(node.get('children') or [])
    return total


def _ply_loss(plies: list, pi: int, table: dict) -> int | None:
    """Centipawn loss the mover at ply pi took, per `table` (shallow or deep).
    Uses the same formula as find_trap_plies.py: score(fen[pi]) + score(fen[pi+1]),
    both POV-relative to their respective side-to-move."""
    if pi >= len(plies) - 1:
        return None
    fa = plies[pi].get('fen')
    fb = plies[pi + 1].get('fen')
    if not fa or not fb:
        return None
    ea = table.get(fa)
    eb = table.get(fb)
    if not ea or not eb:
        return None
    sa = score_cp(ea)
    sb = score_cp(eb)
    if sa is None or sb is None:
        return None
    return sa + sb


def _last_position_score(plies: list, deep: dict, shallow: dict) -> int | None:
    """Score (mover-POV) of the variation's final position. Prefers deep."""
    if not plies:
        return None
    fen = plies[-1].get('fen')
    if not fen:
        return None
    entry = deep.get(fen) or shallow.get(fen)
    return score_cp(entry) if entry else None


def _cdb_loss_for_played(fen: str, played_iccs: str, chessdb: dict) -> dict | None:
    """Compare the played move against chessdb's best move at this FEN.

    Returns dict with cdb_best_score / cdb_played_score / cdb_loss (all in
    mover-POV cp, like the engine fields), or None if chessdb doesn't have
    this FEN or the played move isn't in its rated list.
    cdb_loss positive = chessdb agrees the played move was worse than its
    top suggestion (cross-validates the trap)."""
    entry = chessdb.get(fen) if chessdb else None
    if not entry:
        return None
    best = entry.get('best_iccs') or entry.get('cdb_best_iccs')
    best_score = entry.get('score') if entry.get('score') is not None else entry.get('cdb_best_score')
    if best_score is None:
        return None
    moves = entry.get('moves') or entry.get('cdb_moves') or []
    played_score = None
    played_winrate = None
    for m in moves:
        if m.get('iccs') == played_iccs:
            played_score = m.get('score')
            played_winrate = m.get('winrate')
            break
    return {
        'cdb_best_iccs': best,
        'cdb_best_score': best_score,
        'cdb_played_score': played_score,
        'cdb_played_winrate': played_winrate,
        'cdb_loss': (best_score - played_score) if played_score is not None else None,
    }


def compute_game_stats(game: dict, shallow: dict, deep: dict,
                       chessdb: dict | None = None,
                       very_deep: dict | None = None) -> dict:
    """Per-game roll-up surfaced on the index page and trap list."""
    traps = []
    decisive = 0
    fens_in_game = set()
    fens_with_deep = set()

    for vi, plies in enumerate(game['variations']):
        for p in plies:
            fen = p.get('fen')
            if fen:
                fens_in_game.add(fen)
                if fen in deep:
                    fens_with_deep.add(fen)
        # decisive = mover at the final ply is losing by >300cp (in red-POV).
        final = _last_position_score(plies, deep, shallow)
        if final is not None and abs(final) > 300:
            decisive += 1
        # walk plies looking for the "shallow-blind deep-blunder" pattern.
        for pi in range(SKIP_OPENING_PLIES, len(plies) - 1):
            d_loss = _ply_loss(plies, pi, deep)
            if d_loss is None or d_loss <= 100 or d_loss >= 2000:
                continue
            s_loss = _ply_loss(plies, pi, shallow)
            if s_loss is None or s_loss >= 50:
                continue
            p = plies[pi]
            iccs = p.get('iccs')
            fen = p.get('fen')
            cdb_view = _cdb_loss_for_played(fen, iccs, chessdb or {})
            vd_loss = _ply_loss(plies, pi, very_deep) if very_deep else None
            traps.append({
                'vi': vi, 'pi': pi,
                'fen': fen,
                'side': p.get('side'),
                'iccs': iccs,
                'chinese': p.get('chinese'),
                'annote': (p.get('annote') or '').strip(),
                'shallow_loss': s_loss,
                'deep_loss': d_loss,
                'very_deep_loss': vd_loss,
                'cdb_loss': cdb_view['cdb_loss'] if cdb_view else None,
                'cdb_best_score': cdb_view['cdb_best_score'] if cdb_view else None,
                'cdb_played_score': cdb_view['cdb_played_score'] if cdb_view else None,
            })

    # Dedupe traps by FEN — same blunder reached via different prefixes is one
    # finding. Keep the earliest (vi, pi) so deep-links jump to the natural
    # place in the variation list.
    seen = set()
    unique_traps = []
    for t in sorted(traps, key=lambda t: (t['vi'], t['pi'])):
        if t['fen'] in seen:
            continue
        seen.add(t['fen'])
        unique_traps.append(t)

    n_fens = len(fens_in_game)
    return {
        'unique_plies': _count_tree_plies(game.get('tree')),
        'traps': unique_traps,
        'trap_count': len(unique_traps),
        'decisive_count': decisive,
        'deep_coverage': (len(fens_with_deep) / n_fens) if n_fens else 0.0,
        'n_fens': n_fens,
        'n_deep': len(fens_with_deep),
    }


def _folder_anchor(folder: str) -> str:
    """ASCII-safe anchor id for a folder (handles 主目錄, AI/順包 etc.)."""
    import hashlib
    return 'folder-' + hashlib.sha1(folder.encode('utf-8')).hexdigest()[:10]


def _file_anchor(file: str) -> str:
    return 'file-' + ascii_slug(file).removeprefix('game-')


def render_traps_page(games: list, stats_by_file: dict, chessdb: dict | None = None) -> str:
    """Global trap list grouped by 目錄 → 棋譜.

    Each folder gets an anchor so the index page can deep-link to it
    (e.g. clicking the "順包 ⚠ 47" badge jumps straight to that section).
    Within a folder, each file becomes its own table with a header row,
    so the eye can stay inside one game while scanning rows.
    """
    games_by_file = {g['file']: g for g in games}

    # Group: folder -> [(file, traps_for_that_file)] in master's preferred order.
    by_folder: dict[str, list[tuple[str, list]]] = {}
    for g in games:
        traps = stats_by_file.get(g['file'], {}).get('traps') or []
        if not traps:
            continue
        folder = _group_key(g.get('rel_path', g['file']))
        by_folder.setdefault(folder, []).append((g['file'], traps))

    # Same ordering as the index page: 主目錄 first, then alphabetical.
    folder_keys = sorted(by_folder.keys(), key=lambda k: (k != '主目錄', k))

    sections_html = []
    for folder in folder_keys:
        files_in_folder = sorted(by_folder[folder], key=lambda x: display_title(x[0]))
        folder_trap_total = sum(len(ts) for _, ts in files_in_folder)
        folder_id = _folder_anchor(folder)

        file_blocks = []
        for file, traps in files_in_folder:
            slug = ascii_slug(file)
            title = display_title(file)
            file_id = _file_anchor(file)
            rows = []
            for t in traps:
                side_label = '紅' if t['side'] == 'red' else '黑'
                annote_cell = (escape_html(t['annote'][:40])
                               if t['annote'] else '<span class="dim">—</span>')
                href = f'games/{slug}.html?v={t["vi"]}&p={t["pi"]}'
                # depth-28 verification column (verify_traps.py).
                if t.get('very_deep_loss') is not None:
                    vd = t['very_deep_loss']
                    if vd > 100:
                        vd_cls = 'confirm'
                    elif vd > 30:
                        vd_cls = 'mild'
                    else:
                        vd_cls = 'reject'  # depth-28 says not actually a trap
                    vd_cell = f'<td class="loss vdeep {vd_cls}">{vd:+d}</td>'
                else:
                    vd_cell = '<td class="loss vdeep"><span class="dim">—</span></td>'
                rows.append(
                    f'<tr>'
                    f'<td class="vp"><a href="{href}">v{t["vi"] + 1}·第{t["pi"] + 1}步</a></td>'
                    f'<td class="side {t["side"]}">{side_label}</td>'
                    f'<td class="move">{escape_html(t["chinese"])} '
                    f'<code>{t["iccs"]}</code></td>'
                    f'<td class="loss deep">+{t["deep_loss"]}</td>'
                    f'<td class="loss shallow">{t["shallow_loss"]:+d}</td>'
                    f'{vd_cell}'
                    f'<td class="annote">{annote_cell}</td>'
                    f'</tr>'
                )
            file_blocks.append(
                f'<section class="file-block" id="{file_id}">'
                f'<h3 class="file-head">'
                f'<a class="file-link" href="games/{slug}.html">{escape_html(title)}</a>'
                f'<span class="file-count">{len(traps)} 筆</span>'
                f'</h3>'
                f'<table class="traps-table"><tbody>{"".join(rows)}</tbody></table>'
                f'</section>'
            )

        sections_html.append(
            f'<section class="folder-block" id="{folder_id}">'
            f'<h2 class="folder-head">{escape_html(folder)} '
            f'<span class="folder-count">{folder_trap_total} 筆 · {len(files_in_folder)} 檔</span></h2>'
            f'{"".join(file_blocks)}'
            f'</section>'
        )

    n_total = sum(s['trap_count'] for s in stats_by_file.values())
    body = '\n'.join(sections_html) if sections_html else '<p class="empty">尚無陷阱</p>'
    return TRAPS_HTML.format(n_traps=n_total, sections=body)


def escape_html(s: str) -> str:
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def render_index(games: list, n_positions: int, stats_by_file: dict, n_traps: int) -> str:
    groups = {}
    for g in games:
        key = _group_key(g.get('rel_path', g['file']))
        groups.setdefault(key, []).append(g)

    # 主目錄 first, then alphabetical Chinese
    sorted_keys = sorted(groups.keys(), key=lambda k: (k != '主目錄', k))

    sections = []
    for key in sorted_keys:
        members = sorted(groups[key], key=lambda x: x['file'])
        # Folder-level trap total; rendered next to the <h2> so master can jump
        # to traps.html#<folder> for "all the chest-thumping in this folder".
        folder_trap_total = sum(
            (stats_by_file.get(g['file']) or {}).get('trap_count', 0) for g in members
        )
        items = []
        for g in members:
            slug = ascii_slug(g['file'])
            title = display_title(g['file'])
            st = stats_by_file.get(g['file']) or {}
            ply_unique = st.get('unique_plies') or sum(len(v) for v in g['variations'])
            ai_mark = ' <span class="ai-mark" title="已手動修正註解的版本">✎</span>' if g.get('rel_path', '').replace('/', '\\').startswith('AI\\') else ''
            # Decisive + deep-coverage stay per-game (they describe the game's
            # own analysis state). Trap count moves up to the folder badge.
            badges = []
            if st.get('decisive_count'):
                badges.append(
                    f'<span class="badge badge-decisive" title="結局明顯勝負(>300cp)的變例數">'
                    f'★ {st["decisive_count"]}</span>'
                )
            dc = st.get('deep_coverage')
            if dc is not None and st.get('n_fens'):
                pct = round(dc * 100)
                cls = 'good' if pct >= 95 else ('partial' if pct >= 50 else 'low')
                badges.append(
                    f'<span class="badge badge-deep deep-{cls}" '
                    f'title="深算覆蓋率 — {st["n_deep"]} / {st["n_fens"]} 個局面有 depth-22 評分">'
                    f'深 {pct}%</span>'
                )
            badge_html = ' '.join(badges)
            items.append(
                f'<li><a href="games/{slug}.html">{title}</a>{ai_mark} '
                f'<span class="dim">· {len(g["variations"])} 變例 · {ply_unique} 步</span> '
                f'{badge_html}</li>'
            )

        folder_badge = ''
        if folder_trap_total:
            folder_id = _folder_anchor(key)
            folder_badge = (
                f' <a class="badge badge-trap folder-trap-link" '
                f'href="traps.html#{folder_id}" '
                f'title="跳到全站陷阱頁的此目錄區段">'
                f'⚠ {folder_trap_total}</a>'
            )
        sections.append(
            f'<section class="category"><h2>{escape_html(key)} '
            f'<span class="dim">({len(members)})</span>{folder_badge}</h2>'
            f'<ul class="game-list">{"".join(items)}</ul></section>'
        )

    return INDEX_HTML.format(
        n_games=len(games),
        n_positions=n_positions,
        n_traps=n_traps,
        items='\n'.join(sections),
    )


def _enrich_is_current() -> bool:
    """True iff positions_view.js exists AND is newer than every source it
    derives from. Lets us skip the slow `[enrich]` step when only games.json
    (annote text) changed — annote isn't in positions_view.js at all."""
    view = OUT_DIR / "positions_view.js"
    if not view.exists():
        return False
    # NOTE: positions_very_deep.js intentionally NOT here — it feeds the trap
    # stats panel only; enrich_positions doesn't consume it, so a new very-deep
    # cache doesn't invalidate positions_view.js.
    sources = [
        OUT_DIR / "positions.js",
        OUT_DIR / "positions_deep.js",
        DATA_DIR / "chessdb_cache.json",
    ]
    view_mtime = view.stat().st_mtime
    for src in sources:
        if src.exists() and src.stat().st_mtime > view_mtime:
            return False
    return True


def main():
    fast = '--fast' in sys.argv
    games = load_games()
    positions = load_positions()
    deep = load_deep()
    very_deep = load_very_deep()
    chessdb = load_chessdb()
    print(f"[load] {len(games)} games, {len(positions)} positions, "
          f"{len(deep)} deep, {len(very_deep)} very-deep, {len(chessdb)} chessdb",
          file=sys.stderr)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    view_path = OUT_DIR / "positions_view.js"

    skip_enrich = fast or _enrich_is_current()
    if skip_enrich:
        reason = "explicit --fast" if fast else "positions_view.js is newer than all eval sources"
        print(f"[skip] enrich — {reason} (reusing {view_path.name})", file=sys.stderr)
        enriched_count = len(positions)
    else:
        print("[enrich] computing Chinese notation + PV fen-after + deep + chessdb overlay", file=sys.stderr)
        enriched = enrich_positions(positions, deep, chessdb)
        save_positions_view(view_path, enriched)
        enriched_count = len(enriched)
        print(f"[write] {view_path}", file=sys.stderr)

    # Per-game stats need the raw shallow + deep tables, not the enriched ones.
    print("[stats] computing per-game traps + deep coverage", file=sys.stderr)
    stats_by_file = {
        g['file']: compute_game_stats(g, positions, deep, chessdb, very_deep)
        for g in games
    }
    n_traps = sum(s['trap_count'] for s in stats_by_file.values())
    print(f"[stats] {n_traps} unique traps across {len(games)} games", file=sys.stderr)

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

    # Index + global trap list
    (OUT_DIR / "index.html").write_text(
        render_index(games, enriched_count, stats_by_file, n_traps),
        encoding='utf-8',
    )
    (OUT_DIR / "traps.html").write_text(
        render_traps_page(games, stats_by_file, chessdb),
        encoding='utf-8',
    )
    print(f"[write] index.html + traps.html", file=sys.stderr)

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
