# chess-book-ai

把 `D:\Elton\TestArea\chess-book\` 的 41 個 **XQF 象棋棋譜**餵給 **Pikafish** 引擎做深淺兩段評分，
產出一個可瀏覽、可演示主變、可查雲庫的**靜態棋譜對照網站**，重點放在找出
書本作者「淺算覺得沒事但深算發現是大失誤」的「人類陷阱」位置。

**線上 demo**：<https://eltonlai2014.github.io/chess-book-ai/>
（每次本機跑完 `render_site.py` 會自動 mirror 到 `/docs/` 再 push 上 GitHub Pages）

---

## 兩條程式路徑

| 路徑 | 入口 | 用途 |
|---|---|---|
| 一次性 Markdown 分析 | [analyze.py](analyze.py) | 單一 XQF → 單一 Markdown 報告（最早期的工具，仍可用） |
| 靜態網站 pipeline | [site_builder/](site_builder/) | 批次掃描所有 XQF → 引擎深淺評分 → 渲染 HTML → 鏡像到 `/docs/` |

絕大多數新功能都在 site_builder 這條。

---

## 快速上手

需要 Python 3.10、Pikafish exe + NNUE（放在 `engine\Windows\` 下，git-ignored）。

### 第一次 setup（建 venv + 裝 cchess）

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install cchess==1.25.5
```

之後跑任何指令都用 `.\.venv\Scripts\python.exe …`（或先 `.\.venv\Scripts\Activate.ps1` 然後 `python …`）。
repo 內的 PowerShell 腳本一律用顯式路徑，不必啟動 venv。

中文輸出若亂碼：`$env:PYTHONIOENCODING="utf-8"`

```powershell
# --- 一次性 Markdown 報告 ---
.\.venv\Scripts\python.exe analyze.py "D:\Elton\TestArea\chess-book\中砲對單提馬.XQF" -d 14 `
    -o "output\中砲對單提馬.md"

# --- 靜態網站 pipeline（典型順序）---
.\.venv\Scripts\python.exe site_builder\build_data.py -d 12
#   ↑ XQF → games.json (含 tree 結構) + positions.js (淺算 depth 12)

.\.venv\Scripts\python.exe site_builder\redo_deep.py --depth 22 --threads 4 --hash-mb 512
#   ↑ 深算 depth 22（用乾淨的 clean_eval driver，~14h）

.\.venv\Scripts\python.exe site_builder\chessdb_query.py --game "."
#   ↑ 從 chessdb.cn 抓 plies 10-25 的雲庫評分（~45 分鐘）

.\.venv\Scripts\python.exe site_builder\render_site.py
#   ↑ 渲染 output/site/，並 mirror 到 docs/

# --- 分析輔助 ---
.\.venv\Scripts\python.exe site_builder\list_trap_plies.py --threshold 200 --shallow-blind-only
#   ↑ 產出 trap_plies_blind.csv / .md（每變例 top-3）

.\.venv\Scripts\python.exe site_builder\depth_probe.py --game 牛頭滾 --variation 10 --ply 31 `
    --depths 12,16,20,24
#   ↑ 比對單一位置不同深度的收斂

# --- 冒煙測試（就是 test suite）---
.\.venv\Scripts\python.exe smoke_engine.py
.\.venv\Scripts\python.exe smoke_xqf.py
```

---

## 網站功能一覽

- **多變例瀏覽**：左邊變例選單，右邊每步引擎首選 + 分數 + Δ（淺）+ 深Δ + 雲庫 + 是否相同
- **棋盤跟動**：點任一步 → 棋盤跳到該局面（紅黑視角可切換）
- **演示推演**：兩顆按鈕「淺12」「深22」分別播放對應深度引擎的主變
- **本步可選**：右下面板列出同位置在其他變例的走法（樹狀結構去重），點即跳
- **人類陷阱標記**：橘色底色 + ⚠ 三角形 = 淺算說沒事但深算說大失誤
- **三主題**：右上選單切換「琥珀」「翡翠」「墨拓」（design tokens 一處覆寫）
- **雲庫對照**：書譜 vs chessdb.cn 全球資料庫的最佳走法 + 勝率（hover 看詳情）

---

## 架構重點

完整細節見 [CLAUDE.md](CLAUDE.md)。核心觀念：

- `positions.js`（淺）和 `positions_deep.js`（深）以 **FEN 為 key**，重複位置只算一次
- `games.json` 同時保留 **flat variations** 跟 **tree 結構**（dedup 後 ~3x 壓縮）
- 引擎驅動：**只用 `cchess.UciEngine` 跑單發呼叫**；批次工作必須用 `site_builder/clean_eval.py` 的乾淨 driver（cchess 的 thread race 在 depth 22 會污染 85% 結果，已驗證）
- 跳過開局：trap 分析從 ply 16 起算（前 15 步是公認的開局理論，比較沒意義）
- 部署：渲染完 mirror `output/site/` → `docs/`，GitHub Pages 從 `/docs/` 出菜

---

## 為什麼存在這個工具

- 演播室介面 ~20 年沒大改，且看不到深算結果
- 自己手裡 41 個棋譜，想知道書本作者的某些「看似不錯」的著法是不是陷阱
- 引擎側已是商品化問題（Pikafish + NNUE 開源、cchess 開源），剩下的只是「把資料攤平攤好」

---

## 引用與來源

- [cchess](https://github.com/walker8088/cchess) — XQF 解析、棋盤規則、UCI 驅動
- [Pikafish](https://github.com/official-pikafish/Pikafish) — 引擎（neural net 強度 ~3200 Elo）
- [chessdb.cn](https://www.chessdb.cn/) — 全球象棋雲庫
- Tailwind CSS 色票（用 CSS 變數實作，沒裝框架）

---

## 已知 / 未做

- `positions_view.js` 已經 32 MB，全長 PV 解封後會到 ~60 MB（GitHub Pages 可吃，但首次載入慢）
- shallow（depth 12）尚未用 clean_eval 重跑驗證；audit 只看「最佳走法是否合法」(100% 通過)，分數沒比對
- 沒有 dark mode（`ink` 主題接近但不完全）；要新增主題只動 `:root[data-theme="xxx"]` 一塊 CSS
