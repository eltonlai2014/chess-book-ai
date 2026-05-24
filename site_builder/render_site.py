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
    """Convert an ICCS move to its Chinese notation using a throwaway board.
    Side-aware: black cannons get written 包 (via _to_trad's side path)."""
    try:
        clone = ChessBoard(fen)
        # move_player BEFORE applying — that's whose move we're labeling.
        import cchess
        side = 'red' if clone.move_player == cchess.RED else 'black'
        mv = clone.move_iccs(iccs)
        return _to_trad(mv.to_text(), side) if mv else iccs
    except Exception:
        return iccs


def enrich_positions(positions: dict, deep: dict | None = None,
                     chessdb: dict | None = None,
                     very_deep: dict | None = None) -> dict:
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
    very_deep = very_deep or {}
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

        vd = very_deep.get(fen)
        if vd:
            e['very_deep_score'] = vd.get('score')
            e['very_deep_mate'] = vd.get('mate')
            e['very_deep_best_iccs'] = vd.get('best_iccs')
            e['very_deep_best_chinese'] = (
                _iccs_to_chinese(fen, vd.get('best_iccs'))
                if vd.get('best_iccs') else None
            )
            e['very_deep_depth'] = vd.get('depth')

        e['pv_detail'] = _build_pv_detail(e.get('pv'))
        if d:
            e['deep_pv_detail'] = _build_pv_detail(d.get('pv'))
        if vd:
            e['very_deep_pv_detail'] = _build_pv_detail(vd.get('pv'))
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
<p class="meta">共 {n_games} 個棋譜檔 · {n_positions} 個唯一局面已分析 · <a class="traps-link" href="traps.html">⚠ 全站陷阱 {n_traps}</a> · <a class="traps-link brilliants-link" href="brilliants.html">✨ 妙手榜 {n_brilliants}</a>{broken_link}</p>
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
<p class="meta"><a class="back" href="index.html">← 回到列表</a> · 共 {n_traps} 個候選（{verdict_breakdown}）·  淺算 &lt;50cp，深算 &gt;100cp（d22 或 d28），第 16 步起；<span class="src-d28">隱</span>= d22 沒抓到、d28 才看出</p>
</header>
<main class="traps-page">
<div class="traps-filter" role="tablist">
  <span class="filter-label">篩選</span>
  <button class="filter-btn active" data-filter="all">顯示全部</button>
  <button class="filter-btn" data-filter="confirm">只 ✓ confirm（depth-28 確認）</button>
  <button class="filter-btn" data-filter="mild">△ mild（減弱）</button>
  <button class="filter-btn" data-filter="reject">✗ reject（depth-28 翻案）</button>
  <button class="filter-btn" data-filter="pending">? 未驗證</button>
</div>
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
<script>
(function () {{
  const root = document.body;
  document.querySelectorAll('.traps-filter .filter-btn').forEach((b) => {{
    b.addEventListener('click', () => {{
      const f = b.dataset.filter;
      root.dataset.trapFilter = f;
      document.querySelectorAll('.traps-filter .filter-btn').forEach((x) =>
        x.classList.toggle('active', x === b));
      // After filtering, hide file-blocks whose visible rows count == 0,
      // and hide folder-blocks whose visible file-blocks count == 0.
      document.querySelectorAll('.file-block').forEach((blk) => {{
        const anyVisible = Array.from(blk.querySelectorAll('tr.trap-row'))
          .some((tr) => getComputedStyle(tr).display !== 'none');
        blk.style.display = anyVisible ? '' : 'none';
      }});
      document.querySelectorAll('.folder-block').forEach((blk) => {{
        const anyVisible = Array.from(blk.querySelectorAll('.file-block'))
          .some((fb) => fb.style.display !== 'none');
        blk.style.display = anyVisible ? '' : 'none';
      }});
    }});
  }});
}})();
</script>
</main>
</body>
</html>
"""

BRILLIANTS_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>妙手榜 — 象棋書譜 × Pikafish</title>
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
<header><h1>✨ 妙手榜</h1>
<p class="meta"><a class="back" href="index.html">← 回到列表</a> · 共 {n_total} 個妙手候選（gain {gain_min}-{gain_max}cp，超過 {gain_max} 多為 horizon-effect 雜訊，第 16 步起）</p>
</header>
<main class="traps-page">
<div class="traps-legend">
  <span class="leg-key">欄位</span>
  <span><span class="leg-label">變例·步</span><span class="leg-hint">v / 步序，點擊跳到局面</span></span>
  <span><span class="leg-label">方</span><span class="leg-hint">走子方</span></span>
  <span><span class="leg-label">走法</span><span class="leg-hint">中文記譜＋ICCS</span></span>
  <span><span class="leg-label deep">深得</span><span class="leg-hint">depth-22 mover 比 engine 預估多賺到的 cp — 越大越亮眼但也越可能是雜訊</span></span>
  <span><span class="leg-label shallow">淺Δ</span><span class="leg-hint">depth-12 對同一步的判斷（cp，&lt;50 = 淺算看不出這是妙手）</span></span>
  <span><span class="leg-label vdeep">深28得</span><span class="leg-hint">depth-28 驗證（&gt;50=確認妙手、0-50=減弱、&lt;0=深算翻案；—=尚未跑）</span></span>
  <span><span class="leg-label">原註解</span><span class="leg-hint">XQF 內既有註解</span></span>
</div>
{sections}
</main>
</body>
</html>
"""

BROKEN_ANNOTES_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>中文亂碼註解 — 象棋書譜 × Pikafish</title>
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
<header><h1>✏ 中文亂碼註解</h1>
<p class="meta"><a class="back" href="index.html">← 回到列表</a> · 共 {n_total} 筆需在演播室手動修正 · 點擊跳到對應局面</p>
</header>
<main class="traps-page">
<div class="traps-legend">
  <span class="leg-key">符號</span>
  <span><span class="leg-label">␀</span><span class="leg-hint">NULL byte（最常見的亂碼來源）</span></span>
  <span><span class="leg-label">↵</span><span class="leg-hint">原文換行（CR/LF）</span></span>
  <span><span class="leg-label">變例·步</span><span class="leg-hint">點擊跳到該局面</span></span>
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
<a class="back back-brilliants" href="../brilliants.html#{traps_anchor}" title="跳到妙手榜的此檔區段">✨ 妙手榜</a>
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
{variation_picker}
<button class="nav-first" title="跳到第一步">|◀</button>
<button class="nav-branch" id="navBranchBtn" title="往前回到此變例最近的分歧步（3 條以上叉路優先）">⑂ 跳分支</button>
<button class="nav-prev" title="上一步">◀</button>
<span class="nav-status" id="navStatus">第 0 / 0 步</span>
<button class="nav-next" title="下一步">▶</button>
<button class="nav-last" title="跳到末步">▶|</button>
<button class="demo-play" id="demoBtnShallow" data-mode="shallow" title="播放 depth-12 引擎主變">▶ 演示 淺12</button>
<button class="demo-play demo-deep" id="demoBtnDeep" data-mode="deep" title="播放 depth-22 引擎主變（只有深算過的局面）">▶ 演示 深22</button>
<button class="demo-play demo-vdeep" id="demoBtnVeryDeep" data-mode="verydeep" title="播放 depth-28 引擎主變（只有陷阱驗證過的局面）">▶ 演示 深28</button>
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


def _find_divergence_in_subset(variations: list, vis: list, start_pi: int = 0) -> dict | None:
    """First ply ≥ start_pi where this subset of variations splits into
    ≥2 distinct iccs values. Returns the same shape as _find_first_divergence."""
    if len(vis) <= 1:
        return None
    max_pi = max(len(variations[vi]) for vi in vis)
    for pi in range(start_pi, max_pi):
        groups: dict[str, list[int]] = {}
        for vi in vis:
            if pi >= len(variations[vi]):
                continue
            iccs = variations[vi][pi].get('iccs')
            if iccs:
                groups.setdefault(iccs, []).append(vi)
        if len(groups) >= 2:
            chinese = {iccs: variations[vis_[0]][pi].get('chinese', iccs)
                       for iccs, vis_ in groups.items()}
            return {'pi': pi, 'groups': groups, 'chinese': chinese}
    return None


# Recursive grouping: when a bucket has > MAX_PER_GROUP variations, find the
# next divergence within that bucket and sub-group. Limits depth so the UI
# doesn't become a 10-level russian doll.
MAX_PER_GROUP = 10
MAX_TREE_DEPTH = 5


def _build_variation_tree(variations: list, vis: list | None = None,
                          start_pi: int = 0, depth: int = 0) -> dict:
    """Returns either {'leaf': [vi,...]} or {'group': [{'label',
    'count', 'child', 'pi', 'chinese'}, ...]}."""
    if vis is None:
        vis = list(range(len(variations)))
    if len(vis) <= MAX_PER_GROUP or depth >= MAX_TREE_DEPTH:
        return {'leaf': sorted(vis)}
    div = _find_divergence_in_subset(variations, vis, start_pi)
    if not div:
        return {'leaf': sorted(vis)}
    children = []
    grouped_vis: set[int] = set()
    order = sorted(div['groups'].keys(),
                   key=lambda k: (-len(div['groups'][k]), k))
    for iccs in order:
        sub_vis = div['groups'][iccs]
        sub = _build_variation_tree(variations, sub_vis, div['pi'] + 1, depth + 1)
        children.append({
            'pi': div['pi'],
            'chinese': div['chinese'].get(iccs, iccs),
            'label': f"第 {div['pi'] + 1} 步 · {div['chinese'].get(iccs, iccs)}",
            'count': len(sub_vis),
            'child': sub,
        })
        grouped_vis.update(sub_vis)
    leftover = sorted(set(vis) - grouped_vis)
    if leftover:
        children.append({
            'pi': -1, 'chinese': '其他',
            'label': '其他（未達分歧步）',
            'count': len(leftover),
            'child': {'leaf': leftover},
        })
    return {'group': children}


def _render_variation_tree(tree: dict, variations: list) -> str:
    """Render the variation tree as nested <details> + option buttons.
    Each leaf becomes a <button.varpicker-option> the JS hooks click on."""
    if 'leaf' in tree:
        return ''.join(
            f'<button type="button" class="varpicker-option" data-vi="{vi}">'
            f'變例 {vi + 1} <span class="vp-plycount">{len(variations[vi])} 步</span>'
            f'</button>'
            for vi in tree['leaf']
        )
    parts = []
    for node in tree['group']:
        inner = _render_variation_tree(node['child'], variations)
        parts.append(
            f'<details open class="vp-group">'
            f'<summary>{escape_html(node["label"])}'
            f'<span class="vp-count">{node["count"]} 條</span></summary>'
            f'<div class="vp-children">{inner}</div>'
            f'</details>'
        )
    return ''.join(parts)


def render_game(game: dict) -> str:
    title = display_title(game['file'])
    variations = game['variations']
    tables = [render_variation_table(vi, plies)
              for vi, plies in enumerate(variations)]

    tree = _build_variation_tree(variations)
    tree_html = _render_variation_tree(tree, variations)
    initial_total = len(variations[0]) if variations else 0
    # The picker widget — a trigger button + a hidden panel containing the
    # nested <details> tree. JS toggles `hidden` on the panel and dispatches
    # selectVariation when an option button is clicked.
    picker = (
        f'<div class="varpicker" id="varpicker">'
        f'<button type="button" class="varpicker-trigger" id="varpickerTrigger" '
        f'aria-haspopup="true" aria-expanded="false">'
        f'<span class="varpicker-current" id="varpickerCurrent">變例 1 ({initial_total} 步)</span>'
        f'<span class="varpicker-caret">▾</span>'
        f'</button>'
        f'<div class="varpicker-panel" id="varpickerPanel" hidden>'
        f'{tree_html}'
        f'</div>'
        f'</div>'
    )

    return GAME_HTML.format(
        title=title,
        result=game.get('result', '*'),
        n_var=len(variations),
        variation_picker=picker,
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


# Range for the "妙手榜": below this we're in noise; above it we're in
# horizon-effect territory where the depth-22 PV almost certainly mis-evaluated
# the position rather than the human finding a genuine engine-beating move.
BRILLIANT_MIN = 50
BRILLIANT_MAX = 300


def _compute_brilliants(game: dict, shallow: dict, deep: dict,
                        very_deep: dict | None = None) -> list:
    """Inverse of the trap rule: plies where the mover's choice came out
    better than the engine's depth-22 best at that position (i.e. mover gain).
    Clamped to BRILLIANT_MIN..BRILLIANT_MAX so we keep the credible band and
    filter horizon-effect noise."""
    out = []
    seen = set()
    for vi, plies in enumerate(game['variations']):
        for pi in range(SKIP_OPENING_PLIES, len(plies) - 1):
            d_loss = _ply_loss(plies, pi, deep)
            if d_loss is None:
                continue
            gain = -d_loss
            if gain < BRILLIANT_MIN or gain > BRILLIANT_MAX:
                continue
            s_loss = _ply_loss(plies, pi, shallow)
            vd_loss = _ply_loss(plies, pi, very_deep) if very_deep else None
            p = plies[pi]
            fen = p.get('fen')
            if fen in seen:
                continue
            seen.add(fen)
            out.append({
                'vi': vi, 'pi': pi,
                'fen': fen,
                'side': p.get('side'),
                'iccs': p.get('iccs'),
                'chinese': p.get('chinese'),
                'annote': (p.get('annote') or '').strip(),
                'gain': gain,
                'shallow_delta': (-s_loss) if s_loss is not None else None,
                'very_deep_gain': (-vd_loss) if vd_loss is not None else None,
            })
    # Sort earliest-ply first so each file reads top-to-bottom in playing order.
    out.sort(key=lambda b: (b['vi'], b['pi']))
    return out


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
        # Two detection rules — d22-trap and d28-trap. The d28 rule catches
        # blunders that d22 itself missed (i.e. cases where d22 was the
        # horizon victim, not just d12). Same dedupe by FEN downstream.
        for pi in range(SKIP_OPENING_PLIES, len(plies) - 1):
            s_loss = _ply_loss(plies, pi, shallow)
            if s_loss is None or s_loss >= 50:
                continue
            d_loss = _ply_loss(plies, pi, deep)
            vd_loss = _ply_loss(plies, pi, very_deep) if very_deep else None

            # Rule A: classic d22 trap.
            d22_trap = (d_loss is not None and 100 < d_loss < 2000)
            # Rule B: d28-only trap — d28 sees the blunder, d22 didn't.
            # Requires BOTH fen_before and fen_after at d28 (vd_loss not None)
            # AND the d22 rule did NOT already fire on this pi.
            d28_trap = (not d22_trap
                        and vd_loss is not None and 100 < vd_loss < 2000)

            if not (d22_trap or d28_trap):
                continue

            p = plies[pi]
            iccs = p.get('iccs')
            fen = p.get('fen')
            cdb_view = _cdb_loss_for_played(fen, iccs, chessdb or {})
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
                'source': 'd22' if d22_trap else 'd28',
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
    brilliants = _compute_brilliants(game, shallow, deep, very_deep)
    return {
        'unique_plies': _count_tree_plies(game.get('tree')),
        'traps': unique_traps,
        'trap_count': len(unique_traps),
        'brilliants': brilliants,
        'brilliant_count': len(brilliants),
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

    # depth-28 verdict classifies each trap into one of four buckets — drives
    # both the per-row CSS class (for the filter toggle) and the breakdown
    # counter in the header.
    def _verdict(t):
        vd = t.get('very_deep_loss')
        if vd is None:
            return 'pending'        # depth-28 not yet run for this FEN
        if vd > 100:
            return 'confirm'        # depth-28 still says trap
        if vd > 30:
            return 'mild'           # depth-28 reduces severity but keeps it
        return 'reject'             # depth-28 翻案

    verdict_totals = {'confirm': 0, 'mild': 0, 'reject': 0, 'pending': 0}

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
                verdict = _verdict(t)
                verdict_totals[verdict] += 1
                side_label = '紅' if t['side'] == 'red' else '黑'
                annote_cell = (escape_html(t['annote'][:40])
                               if t['annote'] else '<span class="dim">—</span>')
                href = f'games/{slug}.html?v={t["vi"]}&p={t["pi"]}'
                # depth-28 verification column (verify_traps.py).
                if t.get('very_deep_loss') is not None:
                    vd_cell = (
                        f'<td class="loss vdeep {verdict}">'
                        f'{t["very_deep_loss"]:+d}</td>'
                    )
                else:
                    vd_cell = '<td class="loss vdeep"><span class="dim">—</span></td>'
                # d22 might say nothing or even +/-X — show whatever it
                # has, "—" if absent. Only d28-source rows hit the absent path.
                if t.get('deep_loss') is None:
                    deep_cell = '<td class="loss deep"><span class="dim">—</span></td>'
                else:
                    deep_cell = f'<td class="loss deep">{t["deep_loss"]:+d}</td>'
                src = t.get('source', 'd22')
                src_badge = (' <span class="src-d28" title="d22 沒抓到，d28 才看出的隱形陷阱">隱</span>'
                             if src == 'd28' else '')
                rows.append(
                    f'<tr class="trap-row trap-{verdict} src-{src}">'
                    f'<td class="vp"><a href="{href}">v{t["vi"] + 1}·第{t["pi"] + 1}步</a>{src_badge}</td>'
                    f'<td class="side {t["side"]}">{side_label}</td>'
                    f'<td class="move">{escape_html(t["chinese"])} '
                    f'<code>{t["iccs"]}</code></td>'
                    f'{deep_cell}'
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

    # Header breakdown — surfaces what depth-28 verification told us about the
    # candidate set without forcing master to skim the colour-coded rows.
    parts = [f'{verdict_totals["confirm"]} ✓']
    if verdict_totals['mild']:
        parts.append(f'{verdict_totals["mild"]} △')
    parts.append(f'{verdict_totals["reject"]} ✗')
    if verdict_totals['pending']:
        parts.append(f'{verdict_totals["pending"]} ?')
    verdict_breakdown = ' / '.join(parts)

    return TRAPS_HTML.format(
        n_traps=n_total,
        verdict_breakdown=verdict_breakdown,
        sections=body,
    )


def render_brilliants_page(games: list, stats_by_file: dict) -> str:
    """「妙手榜」— mirror of render_traps_page but for credible mover-gains
    (BRILLIANT_MIN..BRILLIANT_MAX cp).

    Same folder → file → table layout, only the column semantics flip:
    here positive numbers mean the mover *gained* cp vs the engine's
    depth-22 best estimate. Outside the credible band most candidates
    are horizon-effect artefacts, so we cap at BRILLIANT_MAX.
    """
    by_folder: dict[str, list[tuple[str, list]]] = {}
    for g in games:
        items = stats_by_file.get(g['file'], {}).get('brilliants') or []
        if not items:
            continue
        folder = _group_key(g.get('rel_path', g['file']))
        by_folder.setdefault(folder, []).append((g['file'], items))

    folder_keys = sorted(by_folder.keys(), key=lambda k: (k != '主目錄', k))

    sections_html = []
    for folder in folder_keys:
        files_in_folder = sorted(by_folder[folder], key=lambda x: display_title(x[0]))
        folder_total = sum(len(items) for _, items in files_in_folder)
        folder_id = _folder_anchor(folder)

        file_blocks = []
        for file, items in files_in_folder:
            slug = ascii_slug(file)
            title = display_title(file)
            file_id = _file_anchor(file)
            rows = []
            for b in items:
                side_label = '紅' if b['side'] == 'red' else '黑'
                annote_cell = (escape_html(b['annote'][:40])
                               if b['annote'] else '<span class="dim">—</span>')
                href = f'games/{slug}.html?v={b["vi"]}&p={b["pi"]}'
                # Shallow delta: positive = shallow already saw the gain;
                # negative or near-zero = shallow missed it (the interesting case).
                if b['shallow_delta'] is not None:
                    s_cell = f'<td class="loss shallow">{b["shallow_delta"]:+d}</td>'
                else:
                    s_cell = '<td class="loss shallow"><span class="dim">—</span></td>'
                # depth-28 verification (very_deep_gain).
                if b['very_deep_gain'] is not None:
                    vg = b['very_deep_gain']
                    if vg >= BRILLIANT_MIN:
                        vd_cls = 'confirm'
                    elif vg > 0:
                        vd_cls = 'mild'
                    else:
                        vd_cls = 'reject'  # depth-28 retracts the gain
                    vd_cell = f'<td class="gain vdeep {vd_cls}">{vg:+d}</td>'
                else:
                    vd_cell = '<td class="gain vdeep"><span class="dim">—</span></td>'
                rows.append(
                    f'<tr>'
                    f'<td class="vp"><a href="{href}">v{b["vi"] + 1}·第{b["pi"] + 1}步</a></td>'
                    f'<td class="side {b["side"]}">{side_label}</td>'
                    f'<td class="move">{escape_html(b["chinese"])} '
                    f'<code>{b["iccs"]}</code></td>'
                    f'<td class="gain deep">+{b["gain"]}</td>'
                    f'{s_cell}'
                    f'{vd_cell}'
                    f'<td class="annote">{annote_cell}</td>'
                    f'</tr>'
                )
            file_blocks.append(
                f'<section class="file-block" id="{file_id}">'
                f'<h3 class="file-head">'
                f'<a class="file-link" href="games/{slug}.html">{escape_html(title)}</a>'
                f'<span class="file-count">{len(items)} 筆</span>'
                f'</h3>'
                f'<table class="traps-table"><tbody>{"".join(rows)}</tbody></table>'
                f'</section>'
            )

        sections_html.append(
            f'<section class="folder-block" id="{folder_id}">'
            f'<h2 class="folder-head">{escape_html(folder)} '
            f'<span class="folder-count">{folder_total} 筆 · {len(files_in_folder)} 檔</span></h2>'
            f'{"".join(file_blocks)}'
            f'</section>'
        )

    n_total = sum(s['brilliant_count'] for s in stats_by_file.values())
    body = '\n'.join(sections_html) if sections_html else '<p class="empty">尚無妙手候選</p>'
    return BRILLIANTS_HTML.format(
        n_total=n_total,
        gain_min=BRILLIANT_MIN,
        gain_max=BRILLIANT_MAX,
        sections=body,
    )


def escape_html(s: str) -> str:
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _broken_annote_display(s: str) -> str:
    """Same substitution as list_broken_annotes.display() — make control
    chars visible inline."""
    if not s:
        return ''
    return (s.replace('\x00', '␀')
             .replace('\r\n', '↵')
             .replace('\n', '↵')
             .replace('\r', '↵')
             .strip())


def render_broken_annotes_page(games: list) -> str:
    """Clickable version of broken_annotes.md. Each row deep-links into the
    game page via ?v=&p= so master can jump straight to the position."""
    src = OUT_DIR / 'data' / 'broken_annotes.json'
    if not src.exists():
        return ''
    data = json.loads(src.read_text(encoding='utf-8'))
    n_total = data.get('total', 0)

    # filename → slug map so each row can link to its game page.
    slug_by_file = {g['file']: ascii_slug(g['file']) for g in games}

    sections = []
    for f in data.get('files', []):
        name = f.get('name', '')
        file = f.get('file', '')
        rows = f.get('rows', [])
        slug = slug_by_file.get(file)
        if not rows:
            continue
        # Header: file title (clickable to game page) + count.
        title_cell = (
            f'<a class="file-link" href="games/{slug}.html">{escape_html(name)}</a>'
            if slug else escape_html(name)
        )
        body_rows = []
        for r in rows:
            # vi/pi in JSON are 1-indexed; subtract 1 for the URL params.
            vi1, pi1 = r['vi'], r['pi']
            side_label = '紅' if pi1 % 2 == 1 else '黑'
            side_cls = 'red' if pi1 % 2 == 1 else 'black'
            href = (f'games/{slug}.html?v={vi1 - 1}&p={pi1 - 1}'
                    if slug else '#')
            body_rows.append(
                f'<tr class="trap-row">'
                f'<td class="vp"><a href="{href}">v{vi1}·第{pi1}步</a></td>'
                f'<td class="side {side_cls}">{side_label}</td>'
                f'<td class="move">{escape_html(r["chinese"])} '
                f'<code>{r["iccs"]}</code></td>'
                f'<td class="annote">{escape_html(_broken_annote_display(r["annote"]))}</td>'
                f'</tr>'
            )
        sections.append(
            f'<section class="file-block">'
            f'<h3 class="file-head">'
            f'{title_cell}'
            f'<span class="file-count">{len(rows)} 筆</span>'
            f'</h3>'
            f'<table class="traps-table"><tbody>{"".join(body_rows)}</tbody></table>'
            f'</section>'
        )

    body = '\n'.join(sections) if sections else '<p class="empty">無亂碼</p>'
    return BROKEN_ANNOTES_HTML.format(n_total=n_total, sections=body)


def render_index(games: list, n_positions: int, stats_by_file: dict,
                 n_traps: int, n_brilliants: int) -> str:
    groups = {}
    for g in games:
        key = _group_key(g.get('rel_path', g['file']))
        groups.setdefault(key, []).append(g)

    # 主目錄 first, then alphabetical Chinese
    sorted_keys = sorted(groups.keys(), key=lambda k: (k != '主目錄', k))

    sections = []
    for key in sorted_keys:
        members = sorted(groups[key], key=lambda x: x['file'])
        # Folder-level trap + brilliant totals; rendered next to the <h2> so
        # master can jump straight into traps/brilliants pre-filtered to this
        # folder via the section anchor.
        folder_trap_total = sum(
            (stats_by_file.get(g['file']) or {}).get('trap_count', 0) for g in members
        )
        folder_brilliant_total = sum(
            (stats_by_file.get(g['file']) or {}).get('brilliant_count', 0) for g in members
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

        folder_id = _folder_anchor(key)
        folder_badge = ''
        if folder_trap_total:
            folder_badge += (
                f' <a class="badge badge-trap folder-trap-link" '
                f'href="traps.html#{folder_id}" '
                f'title="跳到全站陷阱頁的此目錄區段">'
                f'⚠ {folder_trap_total}</a>'
            )
        if folder_brilliant_total:
            folder_badge += (
                f' <a class="badge badge-brilliant folder-trap-link" '
                f'href="brilliants.html#{folder_id}" '
                f'title="跳到妙手榜的此目錄區段">'
                f'✨ {folder_brilliant_total}</a>'
            )
        sections.append(
            f'<section class="category"><h2>{escape_html(key)} '
            f'<span class="dim">({len(members)})</span>{folder_badge}</h2>'
            f'<ul class="game-list">{"".join(items)}</ul></section>'
        )

    # Only show the broken-annotes link if the JSON exists AND has rows.
    broken_link = ''
    bj = OUT_DIR / 'data' / 'broken_annotes.json'
    if bj.exists():
        try:
            n_broken = json.loads(bj.read_text(encoding='utf-8')).get('total', 0)
        except Exception:
            n_broken = 0
        if n_broken:
            broken_link = (f' · <a class="traps-link" href="broken_annotes.html">'
                           f'✏ 待修註解 {n_broken}</a>')

    return INDEX_HTML.format(
        n_games=len(games),
        n_positions=n_positions,
        n_traps=n_traps,
        n_brilliants=n_brilliants,
        broken_link=broken_link,
        items='\n'.join(sections),
    )


def _enrich_is_current() -> bool:
    """True iff positions_view.js exists AND is newer than every source it
    derives from. Lets us skip the slow `[enrich]` step when only games.json
    (annote text) changed — annote isn't in positions_view.js at all."""
    view = OUT_DIR / "positions_view.js"
    if not view.exists():
        return False
    sources = [
        OUT_DIR / "positions.js",
        OUT_DIR / "positions_deep.js",
        OUT_DIR / "positions_very_deep.js",
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
        enriched = enrich_positions(positions, deep, chessdb, very_deep)
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
    n_brilliants = sum(s['brilliant_count'] for s in stats_by_file.values())
    print(f"[stats] {n_traps} traps + {n_brilliants} brilliants across {len(games)} games", file=sys.stderr)

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
        render_index(games, enriched_count, stats_by_file, n_traps, n_brilliants),
        encoding='utf-8',
    )
    (OUT_DIR / "traps.html").write_text(
        render_traps_page(games, stats_by_file, chessdb),
        encoding='utf-8',
    )
    (OUT_DIR / "brilliants.html").write_text(
        render_brilliants_page(games, stats_by_file),
        encoding='utf-8',
    )
    broken_html = render_broken_annotes_page(games)
    if broken_html:
        (OUT_DIR / "broken_annotes.html").write_text(broken_html, encoding='utf-8')
        print(f"[write] index.html + traps.html + brilliants.html + broken_annotes.html",
              file=sys.stderr)
    else:
        print(f"[write] index.html + traps.html + brilliants.html "
              f"(broken_annotes.json missing — skipped)", file=sys.stderr)

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
