# chess-book-ai

把 `D:\Elton\TestArea\chess-book\` 底下的 **XQF 象棋棋譜**餵給 **Pikafish** 引擎，
對書譜的每一步做獨立分析，輸出 Markdown 報告。

---

## 1. 目的

XQF 是「象棋演播室」用的二進位棋譜格式，肉眼不能讀、外部 AI 工具也不認。
本專案的工作流程：

1. **解析** XQF → 取出元資料、初始局面、所有變例的着法序列（ICCS）
2. **送進 Pikafish** → 對每一個書譜「走子前」的局面，獨立算出引擎首選與分數
3. **產生對照報告** → 每一步把「書譜走法」與「引擎首選」並排，方便比對

---

## 2. 環境

| 元件 | 來源 | 位置 |
|---|---|---|
| Python | 已安裝 3.10.10 | `C:\Users\EltonYM_Lai\AppData\Local\Programs\Python\Python310\` |
| cchess (Python 套件) | `pip install cchess` (v1.25.5) | site-packages |
| Pikafish 引擎 | 官方 release 2026-01-02 | `engine\Windows\pikafish-avx2.exe` |
| NNUE 神經網路檔 | 與引擎同梱 | `engine\Windows\pikafish.nnue` |

CPU 是 i7-8700（Coffee Lake，AVX2、無 AVX-512），故選 `avx2` build。
換機器時若 CPU 支援 BMI2 / VNNI / AVX-512，可改用對應的 exe（同目錄都有）。

---

## 3. 目錄結構

```
chess-book-ai\
├── README.md              <- 本檔
├── analyze.py             <- 主分析腳本（單檔）
├── smoke_engine.py        <- 引擎連線冒煙測試
├── smoke_xqf.py           <- XQF 解析冒煙測試
├── engine\
│   ├── pikafish.nnue      <- (原始位置；已複製到 Windows\)
│   └── Windows\
│       ├── pikafish-avx2.exe   <- 預設使用這顆
│       ├── pikafish-bmi2.exe
│       ├── pikafish-avx512.exe ... (其他 build)
│       └── pikafish.nnue       <- 引擎啟動會在 exe 同層找這個檔
└── output\
    └── 中砲對單提馬.md     <- 範例輸出
```

---

## 4. 怎麼跑

### 分析單一檔案

```powershell
# 基本用法（depth 預設 14，輸出到 stdout）
py D:\Elton\TestArea\chess-book-ai\analyze.py "D:\Elton\TestArea\chess-book\中砲對單提馬.XQF"

# 指定深度、寫入檔案
py D:\Elton\TestArea\chess-book-ai\analyze.py `
   "D:\Elton\TestArea\chess-book\中砲對單提馬.XQF" `
   -d 18 `
   -o "D:\Elton\TestArea\chess-book-ai\output\中砲對單提馬.md"
```

### 批次分析 41 個檔（尚未寫，留待延伸）

目前只有單檔腳本；批次包裝待後續加（見「延伸方向」）。

---

## 5. 輸出格式說明

範例：[output\中砲對單提馬.md](output\中砲對單提馬.md)

### 檔頭區

```
# 中砲對單提馬.XQF
- 起始局面: rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w
- 變例數: 6 / branches: 6
- 引擎: Pikafish 2026-01-02, depth=14
```

- **起始局面**：FEN 字串。`w` = 紅方先走。
- **變例數**：書譜中總共幾條着法線。每條獨立列出（彼此可能前綴重疊）。

### 對局表格欄位

| 欄位 | 意義 |
|---|---|
| `#` | 本變例中的第幾步（ply，半步） |
| `方` | 該手由「紅」或「黑」走 |
| `書譜(中文)` | 書譜記載的這一步，傳統中文記譜（例：`炮二平五`） |
| `書譜(ICCS)` | 同一步的 ICCS 座標表示（例：`h2e2`） |
| `引擎首選` | Pikafish 在這個局面想走的最佳步（中文 + ICCS） |
| `引擎分(cp)` | 引擎對「自己這一步走完後」局面的評估，**單位 centipawn (cp)** |
| `同?` | ✓ = 書譜與引擎首選相同；✗ = 不同 |
| `主要變化` | 引擎預估的後續走法（PV，前 6 步），ICCS 表示 |

### 分數（cp）怎麼讀

- **單位**：1 兵 ≈ 100 cp（centipawn = 「百分之一兵」）
- **視角**：當前**輪到走子的一方**的視角
  - 紅方走子那行：`+50` = 紅方優勢約半個兵
  - 黑方走子那行：`+50` = 黑方優勢約半個兵
  - 黑方走子那行：`-22` = 黑方劣勢 22cp（=紅方優勢 22cp）
- 換言之：**正數永遠代表「該行的那一方」佔優**
- 若有殺著會顯示 `M3` / `-M5`（M = mate，正負代表是己方殺 or 被殺，數字是步數）

> ⚠️ 視角會隨方變，初看會以為「+ 一直變 - 」很奇怪。
> 如尊敬的主人偏好「永遠以紅方視角」，可在 `analyze.py` 的 `fmt_score()` 裡，
> 偵測該行是黑方走子時把分數取負號（待擴充）。

### ICCS 座標

- 直棋格 9 列 × 10 行；列以英文字母 `a..i`（左到右，紅方視角），行以數字 `0..9`（紅方底線 0、黑方底線 9）
- 一手寫成 4 字元：`(起點列)(起點行)(終點列)(終點行)`
- 例：`h2e2` = 紅方 h 列第 2 行的子，平移到 e 列第 2 行 → 對應中文「炮二平五」

---

## 6. 設計重點

### XQF 解析直接用 `cchess.read_from_xqf`

- `read_from_xqf(path)` 回傳 `Game` 物件
- `game.info` — dict，含 `branchs` / `result` / `version` / `move_player` 等
- `game.init_board` — `ChessBoard` 物件（呼叫 `.to_fen()` 取 FEN 字串；不是字串本身）
- `game.dump_iccs_moves()` — list of list，每條變例一個 list，元素為 ICCS 字串

### Pikafish 講 UCI、不是 UCCI（重要！）

雖然中國象棋圈常用 UCCI 協議，**Pikafish 用的是 UCI 變體**。
cchess 提供兩個類別：

- ✅ `cchess.UciEngine` — Pikafish 用這個
- ❌ `cchess.UcciEngine` — 不適用，會永遠 `wait_for_ready` 失敗

### 局面去重

書譜常見多條變例前綴重疊（例：6 條都從 `炮二平五 馬②進３ 馬二進三 …` 開始）。
腳本會收集所有「走子前 FEN」做 dict 去重，引擎只跑唯一局面，再回填到各變例的表格。

- 範例檔（中砲對單提馬）：總步數 82，唯一局面僅 38，**~2.2× 加速**
- 大檔加速比可能更高

### NNUE 路徑

Pikafish 啟動時會在 **exe 同目錄**找 `pikafish.nnue`。
解壓後 `.nnue` 預設在 `engine\` 根目錄，已複製一份到 `engine\Windows\`。
若移動 exe，要連 `.nnue` 一起搬。

---

## 7. 已驗證

- [x] cchess 解析 XQF（中砲對單提馬.XQF，6 條變例，82 步）
- [x] Pikafish UCI 握手 + depth=14 分析
- [x] 中文記譜轉換（`Move.to_text()`）
- [x] 對照報告 Markdown 輸出
- [x] 局面去重節省引擎時間

效能基準：i7-8700, depth 14 → ~7 局面/秒；單檔 ~10 秒。

---

## 8. 延伸方向（給未來的尊敬的主人 / Claude）

排序大致依「最有用 → 最豪華」：

### 8.1 批次跑全部 41 個檔
- 簡單包一層 `batch.py` 走訪 `chess-book\**\*.XQF`
- 加入跨檔的全域 FEN cache（共用的開局走法只算一次，省更多時間）
- 失敗檔記在 log，不阻斷整批
- 輸出總索引 `output\INDEX.md`

### 8.2 分數視角正規化
- `analyze.py:fmt_score()` 加一個「永遠以紅方視角」模式
- 黑方走子時把 score 取負

### 8.3 標記「書譜偏差大」的步
- 一個位置兩件事：
  - 書譜走法的分數（要把書譜走法 push 進引擎用 `searchmoves` 限定）
  - 引擎首選的分數
- 兩者差值 > 50cp 就標紅，> 200cp 標「⚠️ 可疑」
- 目前腳本只跑「引擎首選」一次，沒跑「書譜限定」的對照

### 8.4 餵到網站 / API
- xiangqiai.com 走的也是 Pikafish，自己本地跑已等價，但若要上傳：
  - 多半是把 FEN 貼到 UI，目前沒看到公開 API
  - 若以後找到 API endpoint，可寫一個 send_to_xiangqiai.py

### 8.5 變例樹合併
- 目前 `dump_iccs_moves()` 把樹「拍扁」成多條線，前綴重複
- 改用 `game.iter_moves()` 之類走樹狀結構，輸出更緊湊的報告

### 8.6 加入勝率視角
- cp 對非引擎玩家不直觀
- 可用常見的 `winrate = 50 + 50 * (2 / (1 + exp(-0.004 * cp)) - 1)` 轉換成「估計勝率 %」

### 8.7 圖形化盤面
- 用 cchess 或 matplotlib 把關鍵局面畫成圖嵌入 Markdown
- 便於離線複習

### 8.8 PGN 匯出
- 順手把 XQF 轉成通用 PGN，方便丟到其他棋藝軟體
- cchess 有 `read_from_pgn` / `save_to`（pgn）

### 8.9 升級成完整象棋軟體（最大躍進）

目前的「引擎側」其實已完備：cchess（規則、記譜、棋譜 I/O）+ Pikafish（AI）+ XQF 解析。
剩下要做的只是「殼」——UI、操作流程、資料庫。可分三階段：

#### 階段 A：MVP「棋譜瀏覽器 + AI 即時評分」（建議起點）
**目標**：把現有 41 個 XQF 變成可瀏覽、可即時看引擎評分的 Web App。

- 後端：FastAPI（Python）直接重用 `cchess` + Pikafish 子程序
- 前端：Vue 3 / React + Canvas / SVG 畫盤面（200 行內畫得出來）
- 載入 `chess-book\` 整個資料夾 → 樹狀列表 → 點開看變例樹 → 每步側欄顯示 Pikafish 評分與 PV
- 工作量：原型約一兩百行後端 + 五百行前端
- **建議放在獨立目錄** `chess-book-ai-app\`，與本目錄（CLI 分析工具）分開

> 為何不用 Tkinter/PyQt：盤面圖形需求高、美感差；Web 棧好擴充、跨平台。
> 想要桌面打包再用 Tauri 包一層。

#### 階段 B：對弈 + 復盤
- 人機對弈（時間控制可省）
- 對弈結束自動深度分析 → 標記疑問步 / 失誤 / 妙手
- 類似 chess.com「Game Review」的中國象棋版

#### 階段 C：豪華擴充
- 雲端棋庫（多人協作、標籤系統）
- 行動版（PWA 或 React Native）
- 多人對弈、引擎強度調整、開局訓練模式

#### 為什麼這條路值得走
- 市場現況：象棋演播室介面老舊（~20 年沒大改）、Windows-only、無雲端
- 引擎側成本幾乎是零（Pikafish 開源 + cchess 開源）
- 直接吃掉尊敬的主人現有的 41 個棋譜檔，自用即有價值

---

## 9. 故障排除

| 症狀 | 可能原因 | 解法 |
|---|---|---|
| `wait_for_ready=False` | 用了 UcciEngine | 改 `UciEngine` |
| `Unknown command: '﻿uci'` | PowerShell 管線加了 BOM | 用 Python 驅動而不是 `"cmd`n" \| & engine.exe` |
| `'str' object has no attribute 'isinstance'` | 把 `game.init_board`（ChessBoard 物件）當 FEN 字串用 | 呼叫 `.to_fen()` |
| 分析超慢 | 用了非最佳 build / NNUE 沒載到 | 確認 `pikafish.nnue` 在 exe 同目錄；CPU 對得上 build |
| 中文顯示亂碼 | PowerShell 編碼 | `$env:PYTHONIOENCODING="utf-8"` |

---

## 10. 來源 / 參考

- cchess 套件：https://github.com/walker8088/cchess
- Pikafish：https://github.com/official-pikafish/Pikafish
- XQF 格式（cchess 內建解碼，已驗證 v1.8 / version=18 可讀）
