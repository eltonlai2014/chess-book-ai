# ARCHITECTURE.md

本檔是「重開 session 不失憶」的單一事實來源：**系統有哪些功能、為什麼這樣設計、每個功能的程式碼在哪**。
擴充／修改前先讀這裡定位，再跳到對應 `file:line`。行號會漂移——**以函式名為準**，行號只是起點。

- 設計原則／陷阱的「為什麼」散在 [CLAUDE.md](CLAUDE.md)、[AGENTS.md](AGENTS.md)；本檔聚焦「在哪裡、做什麼」並彙整原則速查。
- SQLite 評估 DB 與姊妹 repo [chess-book-editor](../chess-book-editor/) 的介面見 [SQLITE_EVAL_DB.md](SQLITE_EVAL_DB.md)。
- 深算進度／TT 政策見 [DEEP_STATUS.md](DEEP_STATUS.md)、[D12_TT_SWEEP.md](D12_TT_SWEEP.md)。

> 與 editor 的關係：editor 是「鑽研單一盤面（輸入＋深算＋註解）」的本機 Flask 工具，**唯讀**消費本 repo 產出的 `output/positions.db`。本 repo 是「批量掃庫找書 vs 引擎分歧」的離線管線 + 公開靜態站。兩者面向與程式都不同，只共享 DB 介面與一份會漂移的 `board.js` 渲染器血緣。別在這裡重建 editor 的即時分析，也別在 editor 重建這裡的批量管線。

---

## 1. 系統總覽

把 XQF 開局書逐步用 Pikafish 多深度評估，找出「書 vs 引擎」分歧——尤其是**人類陷阱**（淺算說書步沒事、深算才現血崩）。產出公開靜態站。

```
XQF 開局書庫  D:\Elton\TestArea\chess-book\  (41 原檔 + AI/ 重存子集)
   │  cchess 1.25.5  read_from_xqf
   ▼
┌─ 離線管線 (site_builder/*.py，Pikafish 驅動，全部寫 output/site/) ──────────┐
│                                                                              │
│  build_data.py ──► games.json  (走子樹 + 變化 + 每步 ICCS/中文/annote)        │
│      │  d12 全量 (DFS preorder, Hash 1024, TT 不清)  ──► positions.js  (d12)   │
│      ▼                                                                        │
│  enrich_decisive.py ──► positions_deep.js  (d22; 只算 |d12|>300 的變化,          │
│      │                   走到 |d12|>500 那步為止; PV[:10])                       │
│      ▼                                                                        │
│  chessdb_query.py ──► data/chessdb_cache.json  (雲庫勝率, 僅 ply 10–25)          │
│      ▼                                                                        │
│  verify_traps.py / verify_d28_shunbao.py ──► positions_very_deep.js  (d28)     │
│  verify_d32.py ──────────────────────────► positions_d32.js  (d32 交叉驗證)     │
│      ▼                                                                        │
│  render_site.py ──► output/site/  →(mirror)→ docs/   (公開站, GitHub Pages)     │
│      │   合併各 depth + chessdb → positions_view.js (window.POSITIONS, 截短 PV) │
│      │   算每局 trap/brilliant/decisive/深算覆蓋率 → index/traps/brilliants/game│
│      ▼                                                                        │
│  migrate_to_sqlite.py ──► output/positions.db   (給 editor 唯讀消費)            │
└──────────────────────────────────────────────────────────────────────────────┘
   ▲ 引擎: engine/Windows/pikafish-avx2.exe + pikafish.nnue (git-ignored, 同目錄)
   ▲ 所有批量評估都走 site_builder/clean_eval.py 的 CleanUciEngine（單執行緒同步, 不可換 cchess.UciEngine）

公開站前端 (vanilla JS, 無框架, <script src> 無 fetch 故 file:// 也能跑):
   game 頁 = 內嵌 GAME(games.json 片段) + positions_view.js(全域 POSITIONS) + board.js
   board.js: 棋盤 SVG、走勢圖、棋譜列、PV 演示、本步可選、分支箭頭、3 主題 × 多棋盤樣式

另一條獨立 code path: analyze.py — 單 XQF → 單 Markdown 報告的舊 CLI (legacy, 用 cchess.UciEngine)
```

**深度階梯**（同一盤面可有多個 depth 評估，render 時由淺到深疊加）：

| depth | 檔案 | 產生者 | 角色 | PV master / view |
|---|---|---|---|---|
| 12 | `positions.js` | build_data.py | 指標（非真理），全量 | `[:8]` / `[:6]` |
| 22 | `positions_deep.js` | enrich_decisive.py | **trap 真正裁判**，只算決定性變化 | `[:10]` / `[:4]` |
| 28 | `positions_very_deep.js` | verify_traps / verify_d28_shunbao | trap pair 驗證 | `[:16]` / `[:8]` |
| 32 | `positions_d32.js` | verify_d32.py | d28 結論交叉驗證 | — |
| 雲庫 | `data/chessdb_cache.json` | chessdb_query.py | 社群勝率/分數 | 僅 ply 10–25 |

**資料檔角色**（全在 `output/site/`，都是 `window.VAR = {...};` 的 JS 或純 JSON）：

| 檔案 | 格式 | 內容 | 備註 |
|---|---|---|---|
| `data/games.json` | JSON | 走子樹 + 變化陣列 + 每步 | **不存 `fen_after`**——前端 `applyIccs()` 載入時現推（省 ~25MB） |
| `positions.js` | `window.POSITIONS` | FEN→d12 評估 | build_data 全量（管線源，僅 Python 讀） |
| `positions_deep.js` | `window.POSITIONS_DEEP` | FEN→d22 | enrich 增量 |
| `positions_very_deep.js` | `window.POSITIONS_VERY_DEEP` | FEN→d28 | 只 trap pair |
| `positions_d32.js` | `window.POSITIONS_D32` | FEN→d32 | 交叉驗證 |
| `positions_view.js` | `window.POSITIONS` | render 時合併 + 截短 PV 的前端視圖 | **僅含公開 42 本引用的 FEN**；瘦身過（chessdb moves[] 拿掉）。與 positions.js 同名但永不同時載入——前端只載 view，管線源只 Python 讀 |
| `positions.db` | SQLite | 上面全部 migrate 進去 | editor 唯讀消費，schema 見 SQLITE_EVAL_DB.md |

---

## 2. 設計原則速查（違反就會壞）

| 原則 | 細節 | 強制點 |
|---|---|---|
| **批量評估只用 CleanUciEngine** | `cchess.UciEngine` 有雙 stdout reader race，depth22+Threads4 會靜默毀掉 ~85% 深算 entry。 | [clean_eval.py](site_builder/clean_eval.py)；memory `project_cchess_engine_bug` |
| **跳過前 15 ply** | 開局理論期比「書 vs 引擎」是錯框；trap/brilliant 從 ply 16 起算。 | `SKIP_OPENING_PLIES=15`（Python 4 處）+ board.js 區域 `SKIP_OPENING=15`，**5 處須同步**（見 §4） |
| **fen_after 不落地** | games.json 只存 pre-move FEN + ICCS；`hydrateGame()`/`applyIccs()` 前端現推。動了這個 games.json 會爆 ~25MB。 | [build_data.py](site_builder/build_data.py)、[board.js `applyIccs`](site_builder/assets/board.js#L70) |
| **annote 編碼兩段修復** | XQF annote 常是 Big5 bytes 被 cchess 誤當 GB18030（出 `磷砆溃`）→ 重編碼 decode-as-Big5，再用域內字表打分挑最佳。`to_text()` 出簡體→換回繁體。 | `_recover_annote`/`_to_trad`([build_data.py:73](site_builder/build_data.py#L73)/[:61](site_builder/build_data.py#L61)) + [common_chars.py](site_builder/common_chars.py) |
| **分數＝行棋方 POV cp** | `fmt_score` 出行棋方視角；走勢圖用紅方視角 `redPerspectiveScore`；失分 = 紅視角(i)−紅視角(i+1)，黑行棋翻號。server 端 trap 用 `_ply_loss` = score(i)+score(i+1)（皆 POV）。cp **不乘 100**。 | [board.js `deltaCp`](site_builder/assets/board.js#L152)、[render_site.py `_ply_loss`](site_builder/render_site.py#L722) |
| **中貴棋譜只 d12** | `中貴棋譜/` 822 本不深算、不進公開站。 | `PUBLIC_EXCLUDE_KEYWORDS`（render_site + enrich_decisive 兩處須一致） |
| **決定性 cutoff** | 公開 42 本 d22 全跑，但走到 `|d12|>500` 那步後跳過後續 ply。 | `DECISIVE_CUTOFF=500`([enrich_decisive.py:41](site_builder/enrich_decisive.py#L41)) |
| **view 只給瀏覽要的** | positions_view.js 截短 PV（VIEW_PV_*）、拿掉 chessdb `moves[]`，免推爆 GitHub 50MB/100MB 限。**transfer 已被 Pages 自動 gzip**（25.9MB→4MB）；真逼近 100MB 走 per-game 拆檔，**不要手動 zip**（會讓下載更大 + 破壞 file://）。 | `enrich_positions`/`save_positions_view`；HANDOFF §7 |
| **engine 與 nnue 同目錄** | Pikafish 從 exe 同目錄載 `pikafish.nnue`；換 binary 要連 nnue 一起搬。`engine/` git-ignored。 | `EXE` 各檔頂部硬編 |
| **靜態站無 fetch** | 全 `<script src>` 載入，故 `file://` 也能跑；別引進 `fetch()`/SSE（那是 editor 的事）。 | game 頁模板 [render_site.py:413](site_builder/render_site.py#L413) |
| **ASCII slug 檔名** | game 頁 `games/game-<sha1-10>.html`，避開 Live Server / Pages 對中文 URL 的 bug。 | `ascii_slug`([render_site.py:220](site_builder/render_site.py#L220)) |
| **move_iccs 會 mutate** | `ChessBoard.move_iccs` 改盤面且回 `Move`/`None`；要先檢查 None，再 `board.next_turn()` 翻邊。要不變動就先 `ChessBoard(board.to_fen())` clone。 | build_data / analyze 各 walk 處 |
| **annote 只在 dump_moves 保留** | `game.dump_moves()` 保 `Move.annote`，`dump_iccs_moves()` 不保——管線一律用前者。 | build_data `scan_games` |
| **info_move 非終結** | 引擎逐層送 `info`，只有 `bestmove` 是終點；別在第一個 info 就 return。 | clean_eval `_parse_info`/`go` |
| **render fast-path** | `positions_view.js` 比所有 eval 源新 → 跳過慢 enrich（annote-only XQF 改動的常況）。`positions_very_deep.js` **故意不在**源 mtime 檢查內。 | `_enrich_is_current`([render_site.py:1356](site_builder/render_site.py#L1356)) |
| **d12 重算一次性鎖** | recompute_d12_full 完成後 drop `output/.d12_dfs_recompute_done`；別手刪（除非要強制重跑）。d22/d28/d32 不依賴 d12，重算後仍有效。 | [recompute_d12_full.py](site_builder/recompute_d12_full.py)；HANDOFF §4.2 |

---

## 3. 功能 → 程式碼對照

### 引擎驅動（[clean_eval.py](site_builder/clean_eval.py)）

| 功能 | 函式:行 |
|---|---|
| 單執行緒同步 Pikafish wrapper | `CleanUciEngine`:23（`__init__`/`_send`/`_readline`/`_read_until`） |
| 設選項 / 就緒 / 跑深度 | `set_option`:51 / `isready`:54 / `go(fen, depth)`:58 |
| 逐行 info 解析（只認 bestmove 終結） | `_parse_info`:107 / `quit`:132 |

### 資料層（[build_data.py](site_builder/build_data.py)）— XQF → games.json + positions.js (d12)

| 功能 | 函式:行 |
|---|---|
| 掃庫（recursive）+ 同名去重（留註解最乾淨版） | `scan_games`:190 / `_dedupe_by_name`:115 / `_annote_score`:98 |
| 走子樹（給「本步可選」用，與扁平變化並存） | `build_move_tree`:149 |
| annote 修復 / 繁簡 / 字表打分 | `_recover_annote`:73 / `_to_trad`:61 / `_vocab_score`:48 / `_cjk_ratio`:28 |
| FEN 收集（**DFS preorder**，利於 TT 命中） | `collect_fens_dfs`:279 |
| 評估迴圈（resumable, checkpoint 每 50, `hash_mb=1024` TT 不清） | `evaluate`:306 |
| 載入/存檔（增量, skip 已評 FEN） | `load_existing_positions`:259 / `save_positions`:273 |

### 深算層（[enrich_decisive.py](site_builder/enrich_decisive.py)）— d22

| 功能 | 函式:行 |
|---|---|
| 挑要深算的 FEN（`|d12|>300` 變化, 排除中貴, skip 開局, cutoff 後停） | `collect_fens_to_eval`:45 |
| 主流程（支援 `--auto-d12-recompute`：跑完未撞 deadline 即觸發 d12 全量重算） | `main`:75 |
| 跑完自動 render + push（partial/完整） | `post_render_and_push`:209 |
| 常數 | `SKIP_OPENING_PLIES=15`:39 / `DECISIVE_CUTOFF=500`:41 / `PV_KEEP=10`:42 |

### 雲庫層（[chessdb_query.py](site_builder/chessdb_query.py)）

| 功能 | 函式:行 |
|---|---|
| 查單 FEN（NUL-byte 先剝再 JSON decode） | `query_one`:61 / `parse_queryall`:32 / `trim_fen`:26 |
| 批量 + 快取（`RATE_DELAY=0.2`） | `run_queries`:100 / `load_cache`:68 / `save_cache`:74 |
| 收集（僅 `PLY_RANGE=(10,25)`）+ 報告 | `collect_fens_for_game`:82 / `report`:136 / `fmt_chessdb`:124 |

### 深度驗證層

| 檔案 | 深度 | 函式:行 |
|---|---|---|
| [verify_traps.py](site_builder/verify_traps.py) | 28 | `collect_trap_fens`:47 / `is_valid_entry`:70 / `run_engine`(checkpoint每5, `--max-hours` 自限)`:80 / `post_render_and_push`:140 |
| [verify_d28_shunbao.py](site_builder/verify_d28_shunbao.py) | 28 | 順包（中貴）變體，與 verify_traps 同形 |
| [verify_d32.py](site_builder/verify_d32.py) | 32 | d28 結論交叉驗證 |

### 渲染層（[render_site.py](site_builder/render_site.py)）— 最大的檔

**載入 + 視圖合併**
| 功能 | 函式:行 |
|---|---|
| 載各源（games / d12 / d22 / d28 / chessdb） | `load_games`:49 / `load_positions`:53 / `load_deep`:59 / `load_very_deep`:68 / `load_chessdb`:78 |
| 公開判定（排中貴） | `is_public`:44 / `PUBLIC_EXCLUDE_KEYWORDS`:35 |
| 合併成前端視圖（疊 d12/d22/d28 + 截短 PV + 補中文著法） | `enrich_positions`:105 / `_iccs_to_chinese`:86 |
| 每步補 chessdb（**拿掉 moves[] 只留摘要**） | `annotate_game_plies_with_cdb`:188 |
| 存 view（限公開 FEN） | `save_positions_view`:209 / `VIEW_PV_BASE=6`/`_DEEP=4`/`_VDEEP=8`:100 |

**統計：trap / brilliant / 覆蓋率**
| 功能 | 函式:行 |
|---|---|
| 單步失分（mover POV: score(i)+score(i+1)） | `_ply_loss`:722 |
| brilliant 偵測（gain 50–300cp 窄帶避地平線雜訊） | `_compute_brilliants`:793 / `BRILLIANT_MIN=50`/`MAX=300`:789 |
| chessdb 失分（已走步） | `_cdb_loss_for_played`:754 / `_last_position_score`:743 |
| 每局統計（trap/brilliant/decisive/深算覆蓋率） | `compute_game_stats`:832 |

**HTML 產生**（模板都是 f-string，內嵌 `{}` 要 `{{}}`）
| 功能 | 函式:行 |
|---|---|
| 模板字串 | `INDEX_HTML`:227 / `TRAPS_HTML`:273 / `BRILLIANTS_HTML`:343 / `BROKEN_ANNOTES_HTML`:380 / `GAME_HTML`:413 |
| 變化表 / 變化樹（去重前綴, 折疊） | `render_variation_table`:519 / `_build_variation_tree`:583 / `_render_variation_tree`:632 / `_find_divergence_in_subset`:555 |
| 各頁 render | `render_game`:665 / `render_index`:1220 / `render_traps_page`:930 / `render_brilliants_page`:1053 / `render_broken_annotes_page`:1164 |
| slug / 標題 / 錨點 | `ascii_slug`:220 / `display_title`:214 / `_folder_anchor`:920 / `_file_anchor`:926 |

**收尾**
| 功能 | 函式:行 |
|---|---|
| fast-path 判定（view 比源新就跳 enrich） | `_enrich_is_current`:1356 |
| DEEP_STATUS.md 自動同步 7 欄 | `update_deep_status_md`:1330 / `_count_window_entries`:1316 |
| 主流程（含 mirror → docs/） | `main`:1376 |

### SQLite 遷移（[migrate_to_sqlite.py](site_builder/migrate_to_sqlite.py)）

| 功能 | 函式:行 |
|---|---|
| 各 JS 源 → DB（schema 固定，editor 依賴） | `main`:105 / `SCHEMA`:42 / `JS_SOURCES`:33 |
| 解 `window.VAR={...}` wrapper / 逐 depth row | `_strip_js_wrapper`:63 / `_load_js_dict`:77 / `_iter_eval_rows`:82 / `_iter_chessdb_rows`:96 |

### 自動化 / 排程

| 元件 | 位置 | 角色 |
|---|---|---|
| d22 夜跑 wrapper（停睡眠, tee log） | `site_builder/run_enrich_d22.ps1` + schtask `ChessBookEnrichD22` 22:30 | 增量深算 |
| trap d28 夜跑 | `site_builder/run_verify_traps.ps1` + schtask `ChessBookVerifyDepth28` 21:00 | trap pair 掃 |
| d32 / 順包 d28 | schtask `ChessBookVerifyD32`(21:00) / `ChessBookVerifyD28Shunbao`(22:30, ⏸ 暫停) | — |
| **d12 全量重算（自動觸發鏈）** | [recompute_d12_full.py](site_builder/recompute_d12_full.py) | d22 清空那夜由 enrich `--auto-d12-recompute` 觸發 |
| d12 重算步驟 | backup→刪 positions.js→build_data -d12 全量→enrich 補邊界→render→commit→push→drop `MARKER` | `step`:36 / `run`:40 / `main`:46 |

### 前端棋盤渲染器（[board.js](site_builder/assets/board.js)）

**FEN / 座標 / 評估 helper**
| 功能 | 函式:行 |
|---|---|
| FEN 解析 / 走一步並翻邊（前端現推 fen_after） | `parseFen`:44 / `applyIccs`:70 |
| ICCS↔座標 / 螢幕座標 | `iccsToCoord`:35 / `screenX`:25 / `screenY`:29 |
| 取評估 / 紅方視角分 / 深算 entry | `getEntry`:110 / `redPerspectiveScore`:115 / `deepEntry`:128 / `redPerspectiveDeepScore`:133 |
| 失分計算 / 格式 / 分級色 | `deltaCp`:152 / `deepDeltaCp`:138 / `redDelta`:198 / `fmtScore`:180 / `deltaClass`:163 / `fmtDelta`:171 |

**繪製**
| 功能 | 函式:行 |
|---|---|
| 棋子字形 / 字型載入 / 棋盤樣式表 / 回紋邊框 | `PIECE_CHAR`:7 / `ensurePieceFontLoaded`:262 / `BOARD_STYLES`:272 / `drawMeanderFrame`:373 |
| **載入脈動藥丸**（drawBoard 清空即消失） | `drawBoardLoading`:452 |
| 整盤渲染（末尾 `drawBranchArrows`） | `drawBoard`:465 / `currentBoardStyle`:346 / `redrawCurrentBoard`:852 |
| 分支提示箭頭（≥2 續著時扇出編號綠箭頭, 讀 `ALTS_BY_FEN`） | `drawBranchArrows`:831 / `boardArrow`:775 / `boardArrowBadge`:806 / `BRANCH_ARROW`:761 / `branchArrowColor`:769 |
| 走勢圖（cp clamp ±500） | `drawChart`:906 / `CHART_RANGE`:904 |
| 棋盤樣式選單注入 | `injectBoardPicker`:866 |

**狀態 / 導航 / 棋譜列 / 演示**
| 功能 | 函式:行 |
|---|---|
| 全域狀態 / 元素 ref | `STATE`:982 / globals:983 / `ALTS_BY_FEN`:1088 / `MOVE_LOOKUP`:1089 |
| 變化選單 | `VAR_PICKER`:989 |
| 標注棋譜表（trap 橘列+⚠、⑂ 分支徽章；**區域 `SKIP_OPENING=15` 在此**:1243） | `annotateTable`:1206 |
| 註解框 | `renderAnnote`:1328 |
| 水合 games / 建樹查找表 | `hydrateGame`:1366 / `buildTreeLookups`:1388 |
| 本步可選面板 | `renderAlts`:1414 / `navigateToAlternative`:1464 |
| 選變化 / 跳步 / 最近分支 | `selectVariation`:1485 / `activatePly`:1505 / `findNearestBranchPly`:1153 |
| PV 演示（淺12/深22/深28 三鈕） | `startDemo`:1533 / `stopDemo`:1093 / `updateDemoButtons`:1130 |
| **頁面啟動（4a：先畫藥丸 + rAF 推後重活）** | `initGamePage`:1590 / `initGamePageHeavy`:1601 |

> game 頁模板（[render_site.py:413](site_builder/render_site.py#L413)）在 `#board` SVG 後另有一段**自帶**內嵌 script（4b 早繪藥丸），不依賴 board.js，蓋住 25MB positions_view.js 下載空窗；board.js 首次 `drawBoard` 清空 SVG 時無縫接手。改它記得 f-string `{}`→`{{}}`。

### 樣式（[style.css](site_builder/assets/style.css)）

3 主題（amber/emerald/ink）色變數 `--accent`/`--accent-bright`/`--accent-soft`；`#board` 區塊含載入藥丸 `.boardBusyPill`/`@keyframes boardPulse`(L732+)。

### 舊 CLI（[analyze.py](analyze.py)，legacy，獨立 code path）

單 XQF → 單 Markdown。用 `cchess.UciEngine`（單盤面節奏下無 race 問題，但**別拿去批量**）。`analyze_file`:50 / `render_markdown`:112 / `run_engine`:17。Markdown 表頭用全形字撐欄寬，改動別動欄數。

### 工具 / 診斷腳本（一次性，非管線）

`find_trap_plies.py`/`scan_brilliants.py`（CLI 版偵測器）、`depth_probe.py`/`probe_depth28.py`（收斂探針）、`compare_d28_d32.py`、`list_broken_annotes.py`/`suggest_annotes.py`/`fix_annotes.py`（annote 修復助手）、`audit_deep_cache.py`/`validate_clean.py`（資料稽核）、`diagnose_*`/`try_recode.py`/`debug_pv_bug.py`/`scan_dups.py`/`redo_deep.py`/`enrich_depth.py`（歷史除錯，多已退役）。

### 煙霧測試（即測試套件）

`smoke_engine.py`（引擎 glue）、`smoke_xqf.py`（XQF 解析）。改引擎驅動或 XQF 解析後跑這兩個。無 test runner / linter / build step。

---

## 4. 改功能時的起手式

- **加深度層（如新 dN）** → 仿 `verify_traps.py` 寫 `verify_dN.py` 出 `positions_dN.js`（用 CleanUciEngine）→ `migrate_to_sqlite.JS_SOURCES`/`SCHEMA` 加一筆 → render `load_*` + `enrich_positions` 疊上 + `VIEW_PV_*` 設截短 → 視需要 board.js 加 `deepEntry` 變體。
- **改 trap / brilliant 門檻** → server: `_ply_loss`(722)/`_compute_brilliants`(793)/`compute_game_stats`(832)；前端: `annotateTable`(1206)。**ply 門檻五處同步**：`SKIP_OPENING_PLIES=15` 於 enrich_decisive、find_trap_plies、verify_traps、render_site；board.js 是 annotateTable 內的區域 `SKIP_OPENING=15`(:1243)。
- **改 view 大小 / 瘦身** → `enrich_positions`/`save_positions_view` + `VIEW_PV_*`；chessdb 摘要在 `annotate_game_plies_with_cdb`。真逼近 100MB 走 per-game 拆檔，**別 zip**（Pages 已 gzip）。
- **加棋盤樣式** → board.js `BOARD_STYLES`(272) 加一筆 + `BRANCH_ARROW`(761) 補對應分支箭頭色。
- **改著法字形 / annote 修復** → `_recover_annote`/`_to_trad`（build_data，**也被 render_site + fix_annotes import**，改簽名要更新所有 call site）+ `common_chars.py` 字表。
- **加 game 頁 UI 元件** → board.js 加函式 + `GAME_HTML`(render_site:413) 模板加 DOM；模板是 f-string，內嵌 JS 的 `{}` 要 `{{}}`，存好用 `py_compile` 驗證跳脫。
- **動引擎評估** → 一律 `CleanUciEngine`，**永不** `cchess.UciEngine` 批量。`info_move` 非終結，等 `bestmove`。
- **改公開站範圍** → `PUBLIC_EXCLUDE_KEYWORDS`（render_site + enrich_decisive 兩處一致）。
- **快速 iteration** → 只改 CSS/board.js 用 `sync_assets.py`(<1s)；改模板/統計用 `render_site.py --fast`（跳 enrich，重出 HTML）；改 eval 才跑完整鏈。
- **動排程夜跑** → `run_*.ps1`（停睡眠 + tee log）+ schtask；d12 重算靠 `--auto-d12-recompute` 旗標 + `.d12_dfs_recompute_done` 一次性鎖，別手刪 marker。
- **改 DB schema** → 動 `migrate_to_sqlite.SCHEMA` **必先**同步 editor（`eval_service.py` 唯讀依賴），見 SQLITE_EVAL_DB.md。
