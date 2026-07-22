# 深算狀態追蹤

> 棋譜庫覆蓋率 + 深度計算進度的單一事實來源。更新規則見最後一節。
>
> Last updated: <!--auto-date-->2026-07-22<!--/auto-date-->

## 一、棋譜庫總覽

- 來源：`D:\Elton\TestArea\chess-book\`（git 外）
- `build_data.py` 用 `rglob('*.xqf'|'*.XQF')` 全掃，`_dedupe_by_name` 按 case-folded 檔名挑 annote 最乾淨那份。

| 範圍 | 檔數 | 備註 |
|---|---:|---|
| 全庫 (XQF on disk) | 886 | |
| dedupe 後 (build_data 收的) | **884** | 兩對撞名留乾淨版本（皆在中貴棋譜/）|
| 公開站 (`docs/` & GitHub Pages) | **62** | `PUBLIC_EXCLUDE_KEYWORDS = ('中貴棋譜',)` |
| 本地保留分析 | **822** | `中貴棋譜/` 子樹（梅花譜、過宮炮、後手順包局、後手河頭堡壘、屏風馬勝五七炮進三兵、陽信名人象棋賽…）|

公開站排除這 822 個實戰對局是因為 `docs/data/games.json` 全量會到 115 MB（過 GitHub 100 MB 硬限）+ 沖淡開局陷阱焦點。本地 SQLite (`positions.db`) 仍包含全部 884 games 的 evals — 供 sibling `chess-book-editor` 讀。

## 二、各深度覆蓋率

unique FEN by depth（`output/site/positions*.js` + `output/site/data/chessdb_cache.json`）：

| Depth | 來源檔 | 範圍 / 用途 | Rows |
|---|---|---|---:|
| 12 | `positions.js` | 全部 884 局棋譜、每一步的淺算分數（基線資料） | <!--auto-d12-->192,273<!--/auto-d12--> |
| 22 | `positions_deep.js` | 公開 62 本書（不含中貴）每一個局面（`--full-public` 全掃，不再 \|d12\|>500 截斷）；滾動補完中 | <!--auto-d22-->139,909<!--/auto-d22--> |
| 28 | `positions_very_deep.js` | (a) 已偵測 trap 的前後兩格再深算驗證；(b) 精讀書（順包 7 本 + 牛頭滾 2 本 + 半途列包 7 本）ply≥15 全掃、套 \|d12\|>500 截斷 — ✅ 2026-07-12 完工 | <!--auto-d28-->77,433<!--/auto-d28--> |
| 32 | `positions_d32.js` | 順包/ 中 d28 已跑過的 FEN，再加深到 32 做交叉驗證（看 d28 結論穩不穩） | <!--auto-d32-->4,796<!--/auto-d32--> |
| chessdb | `data/chessdb_cache.json` | 雲端 chessdb.cn 社群勝率資料，只查 ply 10–25 區間（雲端覆蓋密的範圍） | <!--auto-chessdb-->7,630<!--/auto-chessdb--> |

**深算共通政策（2026-06-01 起）：**
- 中貴棋譜/（822 本實戰書）只跑 d12，d22/d28/d32 全部跳過
- 變例走到 |d12 score| > 500cp 那一步為止（含該步），後續局面不再深算 — 局勢已決，再算無分析價值。**例外**：公開 62 本的 d22 自 `abcca19` 起改 `--full-public`，整本全掃、不套此截斷（見第六節）；截斷仍適用於 d28/d32 sweep
- d22 PV 只存前 10 步（Pikafish d22 PV 約前 10 步精準，後面飄）

**公開站 positions_view.js 瘦身（2026-06-02）：**
render_site enrich 階段對放進 `positions_view.js`（公開站消費）的資料瘦身：
- chessdb 完整 `moves[]` 改為每 ply 寫 `cdb_played_score`/`cdb_played_winrate`（best-move 已在 entry）
- view 端 PV 截短：d12 [:6]、d22 [:4]、d28 [:8]；master files 不變（8/10/16）
- entry.pv 原始 iccs list 拿掉（pv_detail 才是 board.js 真的讀的）

結果：52.6 MB → 25.9 MB（-51%）。d22 sweep 完估 ~38 MB，仍遠低於 50 MB 警告線。
**positions.db 與 chess-book-editor 完全不受影響**（讀 master files / SQLite，沒動）。

`positions.db` 重新 migrate 後總 67.2 MB（2026-06-13 重產，d12 175,466 rows；gitignored，每台機器各自 build）。

## 三、d28 涵蓋計畫

d28 不是要做全庫 89832 FEN（CPU 太貴），而是**兩條互補路線**：

### 3.1 by-trap：`verify_traps.py` → ChessBookVerifyDepth28

對所有被偵測為 trap 的 `(fen_before, fen_after)` 兩格跑 d28，確認深層搜尋仍認定壞步。

- 全庫 **2,418** traps 的前後兩格 trap FENs（dedupe 後較少）
- 完成率：**~100% trap pairs covered（todo=0）**
- 結果：traps.html「深28失」欄位
- 觸發：偵測到新 trap（重 render 後）或手動；`ChessBookVerifyDepth28` 仍 Ready（21:00 每晚增量守門）

### 3.2 by-book：`verify_d28_shunbao.py` → ChessBookVerifyD28Shunbao

對指定的精讀書全部 ply≥15 unique FEN 跑 d28（自 2026-06-30 起套 score-gated 早停
decisive_cp=800 / movetime=600s，與 verify_d32 一致），找出 d22 沒發現、d28 才浮現的 trap。

`TARGET_REL_KEYWORDS = ('順包\\', '牛頭滾', '半途列包\\')` — substring match on rel_path。
`collect_target_fens()` 依 **keyword 優先序**回傳（不再全域 FEN 排序），所以較早的書先掃完才換下一本。

**✅ 2026-07-12 完工：** 順包 7 本 + 牛頭滾 2 本 + 半途列包 7 本的 route-(b) 全掃全部跑完，**todo=0**。

| 書 | route-(b) 候選 | d28 | 狀態 |
|---|---:|---:|---|
| 順包/（7 本，含順包直車3兵對橫車邊馬 22k、順包橫車對直車 21k、…）| ~67,219 | 全數 | ✅ |
| 牛頭滾（2 本）| 4,044 | 全數 | ✅ |
| 半途列包/（7 本）| 3,977 | 3,977 | ✅ 100% |
| **合計** | **~75,240** | — | **todo=0** |

歷程：2026-06-30 查出順包資料夾長大、route-(b) 落後約 **66,729 顆**；6/30 起夜跑 + 兩輪週末併行
blitz（`run_parallel.ps1 -Job d28book`，+34,409 / +18,362）**約 2 週跑完**（原估 4 週～3 個月）。
d28 由 ~10,704 → **77,433**，深掃額外撈出 **+458 個新陷阱**（1,960 → 2,418）。
**`ChessBookVerifyD28Shunbao` 已於 2026-07-13 Disabled**（backlog 清完、避免夜間空轉）；日後有新書
ingest 需再補時手動 `/ENABLE`。

### 3.3 全庫其他書

中貴棋譜/（822 本實戰）只跑 d12，不在 by-book 全掃範圍。順包+牛頭滾+半途列包已清完；
其餘公開書若要全跑需再擴 `TARGET_REL_KEYWORDS`，**目前不計畫**。

## 四、d32 涵蓋計畫

`verify_d32.py` → ChessBookVerifyD32

目的：cross-check d28 verdicts at depth 32。只挑「d28 已 done AND 在目標書」的 FEN。

`TARGET_REL_KEYWORDS = ('順包\\', '半途列包\\')`（2026-06-30 加半途列包）

**⏸ 2026-07-13 暫停：** d28 by-book 完工後，d32 候選（順包/半途 已 d28 的 FEN 再加深到 32）
擴張到 **66,879 顆**。因 depth-32 更慢（估 3–4 週）、且 **UI 尚未呈現 d32**（純內部「d28 判決穩定度」
信心檢查），主人決定**先暫停、不急著開**。`ChessBookVerifyD32` 已 Disabled。
日後要動：抽樣複核（省）或全量 blitz（`run_parallel.ps1 -Job d32`）皆可。目前 d32 = 4,796。

## 五、排程作業

| schtask | 腳本 | 排程 | 動作 |
|---|---|---|---|
| `ChessBookNightlyBuild` | `nightly_build.ps1` | 排程未確認 | 重 render 全站 + push |
| `ChessBookVerifyDepth28` | `verify_traps.py` | 21:00 daily | 對 <!--auto-traps-->2418<!--/auto-traps--> traps × 2 跑 d28 |
| `ChessBookEnrichD22` | `run_enrich_d22.ps1` | 22:30 daily, `--max-hours 8`, `--full-public` | **公開 62 本每局面 d22 全掃**（滾動增量，候選隨灌譜成長；進度見第六節） |
| `ChessBookVerifyD28Shunbao` | `verify_d28_shunbao.py` | 22:30 daily（**Disabled** 2026-07-13）| 順包/牛頭滾/半途列包 全 ply≥15 d28 — ✅ 已完工 todo=0 |
| `ChessBookVerifyD32` | `verify_d32.py` | 21:00 daily（**Disabled** 2026-07-13）| 順包/半途 d28 entries 的 d32 cross-check（候選 66,879，暫停待命）|

所有腳本：resumable, `--max-hours 8` 自我截止，跑完自動 `render_site.py` + `migrate_to_sqlite.py` + commit + push。

Schtask 防電源管理：`WakeToRun=True`, `DisallowStartIfOnBatteries=False`, `StopIfGoingOnBatteries=False`（2026-05-29 修），wrapper 內 `powercfg` 把 standby/monitor/hibernate timeout 全設 0。

## 六、進行中 / 歷史紀錄

> **目前狀態（2026-07-22）**：深算主體皆已收尾 —— d22 full-public 已追平（滾動守門）、
> d28 by-book 完工（todo=0，見 §3.2）、d32 暫停待命（見 §4）。以下為各衝刺的歷史紀錄，保留供回溯。

| 任務 | 最新 | 形態 |
|---|---|---|
| ChessBookEnrichD22（夜間 22:30 daily） | d22 **139,909** rows，full-public 全掃已追平、無新灌譜待補 | **滾動全掃**，隨灌譜增量守門 |

> **2026-06-16~20 d22 衝刺（✅ 已完成、提早算完）**：d22 full-public 於 2026-06-20 07:00 全掃追平（todo 0）。`ChessBookEnrichD22`(22:30)、`ChessBookVerifyDepth28`(21:00)、`ChessBookVerifyD32`(23:00) 均已 `/ENABLE` 復原正常夜間節奏（原訂 6-22，因提早算完於 6-20 提前復原）。
>
> **多實例並行工具 `site_builder/parallel_runner.py`（統一 d22/d28/d32）**：Pikafish SMP 擴展弱，改 **N 引擎 × 少緒** 勝過 1 引擎多緒。單一 orchestrator+worker 核心 + job 註冊表（`--job d22|traps|d32`，wrapper `run_parallel.ps1 -Job`）。實測 3×2 ≈ 1×6 的 **2.1x**（thread-count 偏差 ~-3cp 可忽略）。d22 本輪 31,010 FEN @2.22s/FEN ~19h 掃完。**僅非工作日使用**（平日留 CPU 給主人）。shard 寫 `output/_shards`（須在 output/site/ 外）。
>
> **下週末待清（2026-06-22 dry-run）**：d28(traps) **1,325** FEN、d32 **323** FEN。屆時 `run_parallel.ps1 -Job traps` 再 `-Job d32`。（2026-06-19 的 `enrich_parallel.py`/`verify_parallel.py` 已收斂進 `parallel_runner.py`。）

舊框架（「22,395 todo / 5-7 晚跑完」）已作廢：自 commit `abcca19` 起 EnrichD22 改 `--full-public`——目標是**公開 62 本每一個局面都補 d22**（不再只到 \|d12\|>500 截斷），且候選集隨每晚 20:00 SourceSync 灌新譜而成長，所以這是**持續性夜間增量**而非有固定終點的一次掃描。每晚 commit 訊息為「Enrich d22 nightly progress — public 42 books」。

期間 ChessBookVerifyD28Shunbao 已暫停（避免 22:30 撞）。d22 全掃追平後再 `schtasks /Change /TN ChessBookVerifyD28Shunbao /ENABLE` 恢復。

## 七、更新本文件

每次以下事件後手動同步這份文件：

1. **TARGET_REL_KEYWORDS 異動**（verify_d28_shunbao.py / verify_d32.py）
2. **棋譜源目錄結構變化**（檔案搬移、子目錄增減）
3. **PUBLIC_EXCLUDE_KEYWORDS 異動**（render_site.py）
4. **schtask 加減或排程改動**
5. **單一書達成 100% d28/d32**（更新表格三、四的狀態欄）
6. **positions_view.js 結構變化**（render_site enrich 邏輯改寫、PV trim 調整、欄位增刪）

數字來源：

- 各 depth 總 rows：跑 `.\.venv\Scripts\python.exe site_builder\migrate_to_sqlite.py` 看 stderr 表格
- 全庫 game 數 / dedupe：build_data.py `--scan-only` 的 stderr
- 公開站 / 本地分割：render_site.py stderr 的 `[load] N games on disk (M excluded from public site)`
- 各書 ply≥15 unique FEN 與 d28 進度：verify_d28_shunbao 啟動訊息 `[d28-...] X candidates / Y new at depth N`
- d32 候選：verify_d32 啟動訊息同上格式
