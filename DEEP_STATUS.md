# 深算狀態追蹤

> 棋譜庫覆蓋率 + 深度計算進度的單一事實來源。更新規則見最後一節。
>
> Last updated: <!--auto-date-->2026-06-10<!--/auto-date-->

## 一、棋譜庫總覽

- 來源：`D:\Elton\TestArea\chess-book\`（git 外）
- `build_data.py` 用 `rglob('*.xqf'|'*.XQF')` 全掃，`_dedupe_by_name` 按 case-folded 檔名挑 annote 最乾淨那份。

| 範圍 | 檔數 | 備註 |
|---|---:|---|
| 全庫 (XQF on disk) | 866 | |
| dedupe 後 (build_data 收的) | **864** | 兩對撞名留乾淨版本 |
| 公開站 (`docs/` & GitHub Pages) | **42** | `PUBLIC_EXCLUDE_KEYWORDS = ('中貴棋譜',)` |
| 本地保留分析 | **822** | `中貴棋譜/` 子樹（梅花譜、過宮炮、後手順包局、後手河頭堡壘、屏風馬勝五七炮進三兵、陽信名人象棋賽…）|

公開站排除這 822 個實戰對局是因為 `docs/data/games.json` 全量會到 115 MB（過 GitHub 100 MB 硬限）+ 沖淡開局陷阱焦點。本地 SQLite (`positions.db`) 仍包含全部 864 games 的 evals — 供 sibling `chess-book-editor` 讀。

## 二、各深度覆蓋率

unique FEN by depth（`output/site/positions*.js` + `output/site/data/chessdb_cache.json`）：

| Depth | 來源檔 | 範圍 / 用途 | Rows |
|---|---|---|---:|
| 12 | `positions.js` | 全部 864 局棋譜、每一步的淺算分數（基線資料） | <!--auto-d12-->110,101<!--/auto-d12--> |
| 22 | `positions_deep.js` | 公開 42 本書（不含中貴）全 ply≥15 局面，跑到 \|d12\| 首次 > 500cp 那步為止（決定點之後不再深算） | <!--auto-d22-->39,310<!--/auto-d22--> (sweeping → ~37,000) |
| 28 | `positions_very_deep.js` | (a) 已偵測 trap 的前後兩格再深算驗證；(b) 順包/ 5 本 + 牛頭滾 2 本 ply≥15 全掃，同樣套 \|d12\|>500 截斷 | <!--auto-d28-->8,436<!--/auto-d28--> |
| 32 | `positions_d32.js` | 順包/ 中 d28 已跑過的 FEN，再加深到 32 做交叉驗證（看 d28 結論穩不穩） | <!--auto-d32-->3,263<!--/auto-d32--> |
| chessdb | `data/chessdb_cache.json` | 雲端 chessdb.cn 社群勝率資料，只查 ply 10–25 區間（雲端覆蓋密的範圍） | <!--auto-chessdb-->7,630<!--/auto-chessdb--> |

**深算共通政策（2026-06-01 起）：**
- 中貴棋譜/（822 本實戰書）只跑 d12，d22/d28/d32 全部跳過
- 變例走到 |d12 score| > 500cp 那一步為止（含該步），後續局面不再深算 — 局勢已決，再算無分析價值
- d22 PV 只存前 10 步（Pikafish d22 PV 約前 10 步精準，後面飄）

**公開站 positions_view.js 瘦身（2026-06-02）：**
render_site enrich 階段對放進 `positions_view.js`（公開站消費）的資料瘦身：
- chessdb 完整 `moves[]` 改為每 ply 寫 `cdb_played_score`/`cdb_played_winrate`（best-move 已在 entry）
- view 端 PV 截短：d12 [:6]、d22 [:4]、d28 [:8]；master files 不變（8/10/16）
- entry.pv 原始 iccs list 拿掉（pv_detail 才是 board.js 真的讀的）

結果：52.6 MB → 25.9 MB（-51%）。d22 sweep 完估 ~38 MB，仍遠低於 50 MB 警告線。
**positions.db 與 chess-book-editor 完全不受影響**（讀 master files / SQLite，沒動）。

`positions.db` 重新 migrate 後總 43.9 MB（gitignored，每台機器各自 build）。

## 三、d28 涵蓋計畫

d28 不是要做全庫 89832 FEN（CPU 太貴），而是**兩條互補路線**：

### 3.1 by-trap：`verify_traps.py` → ChessBookVerifyDepth28

對所有被偵測為 trap 的 `(fen_before, fen_after)` 兩格跑 d28，確認深層搜尋仍認定壞步。

- 全庫 642 traps × 2 ≈ 1284 trap FENs（dedupe 後 ~1,013）
- 完成率：**~100% trap pairs covered**
- 結果：traps.html「深28失」欄位
- 觸發：偵測到新 trap（重 render 後）或手動

### 3.2 by-book：`verify_d28_shunbao.py` → ChessBookVerifyD28Shunbao

對指定的精讀書全部 ply≥15 unique FEN 跑 d28，找出 d22 沒發現、d28 才浮現的 trap。

`TARGET_REL_KEYWORDS = ('順包\\', '牛頭滾')` (substring match on rel_path)

當前涵蓋（2026-06-01）：

| 檔案 | ply≥15 FEN | d28 done | 狀態 |
|---|---:|---:|---|
| 順包/順包兩頭蛇對雙橫車 | 1,082 | 1,082 | ✅ 100% |
| 順包/順包直車3兵對橫車邊馬 | 1,142 | 1,142 | ✅ 100% |
| 順包/順包直車3兵對橫車3卒 | ~480 | ~480 | ✅ 100% |
| 順包/順包直車3兵對橫車4進5 | ~140 | ~140 | ✅ 100% |
| 順包/順砲橫車對直車 | ~250 | ~250 | ✅ 100% |
| 牛頭滾 | ~80 | ~80 | ✅ 100% |
| 牛頭滾_意大利包 | ~85 | ~85 | ✅ 100% |
| **合計** | **7,256** | **7,256** | **✅ 100%** |

2026-06-01 03:06 掃完。新浮現 8 個 trap（642 → 650）。後續 d22 sweep 又補 36 個（650 → 686）。

### 3.3 全庫其他書

剩 **~12 個遊戲** 完全沒 d28 entries（連 trap 都未偵測到）+ **~26 個 partial**（只跑 trap pairs）。要全跑需擴 `TARGET_REL_KEYWORDS` 或加新 sweep 腳本。CPU 預估全跑 ~30,000 FEN × 75s ≈ **625 hr CPU**。**目前不計畫**。

## 四、d32 涵蓋計畫

`verify_d32.py` → ChessBookVerifyD32

目的：cross-check d28 verdicts at depth 32。只挑「d28 已 done AND 在 順包/」的 FEN。

`TARGET_REL_KEYWORDS = ('順包\\',)`

當前：**2,224 / 2,224** ✅（含 順包 兩書 + 之前由 verify_traps 順手得到的零星 FEN）

d28 sweep 跑完後 d32 候選會擴張到 ~2,273（新 49 FEN）+ 還會隨後追加新的 d28 FENs，schtask 隔日自動續跑。

## 五、排程作業

| schtask | 腳本 | 排程 | 動作 |
|---|---|---|---|
| `ChessBookNightlyBuild` | `nightly_build.ps1` | 排程未確認 | 重 render 全站 + push |
| `ChessBookVerifyDepth28` | `verify_traps.py` | 21:00 daily | 對 <!--auto-traps-->731<!--/auto-traps--> traps × 2 跑 d28 |
| `ChessBookEnrichD22` | `run_enrich_d22.ps1` | 22:30 daily, `--max-hours 8` | **公開 42 本 d22 全掃**（2026-06-01 啟，~5-7 晚完成 22,395 todo） |
| `ChessBookVerifyD28Shunbao` | `verify_d28_shunbao.py` | 22:30 daily（**已暫停**） | 順包/ + 牛頭滾 全 ply≥15 d28，d22 sweep 完後再啟用 |
| `ChessBookVerifyD32` | `verify_d32.py` | 21:00 daily | 順包/ d28 entries 的 d32 cross-check |

所有腳本：resumable, `--max-hours 8` 自我截止，跑完自動 `render_site.py` + `migrate_to_sqlite.py` + commit + push。

Schtask 防電源管理：`WakeToRun=True`, `DisallowStartIfOnBatteries=False`, `StopIfGoingOnBatteries=False`（2026-05-29 修），wrapper 內 `powercfg` 把 standby/monitor/hibernate timeout 全設 0。

## 六、進行中

| 任務 | 狀態 | 預計完成 |
|---|---|---|
| ChessBookEnrichD22（22:30 daily, 8h/晚） | **第 1 夜跑完**：9,157/22,395 = 41%，commit `b5200c3` | 再 ~3-4 晚（實測 3.1s/FEN，比預估 5.5 快） |

期間 ChessBookVerifyD28Shunbao 已暫停（避免 22:30 撞）。d22 sweep 完後再 `schtasks /Change /TN ChessBookVerifyD28Shunbao /ENABLE` 恢復。

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
