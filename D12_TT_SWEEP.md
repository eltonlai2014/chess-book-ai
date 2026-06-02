# D12 全局掃描：共享 TT 的問題與改進建議

> 分析日期 2026-06-02。對象：`site_builder/build_data.py` 的 d12 shallow 全庫
> 評估（由 `nightly_build.ps1` 步驟 1 以 `-d 12` 驅動）。本文記錄「目前怎麼算 →
> 問題在哪 → 怎麼改」，供後續實作。

## 1. 目前的計算方式（現況）

核心在 [`build_data.py:evaluate()`](site_builder/build_data.py#L279-L323)：

1. **範圍**：掃 41 個 XQF 全部變化的局面，**以 FEN 字串全域去重**後得到 unique
   FEN 集合；已在 `positions.js` 快取的跳過（增量式）。
2. **引擎設定**：單一 Pikafish 進程，`Threads=1`、`Hash=16MB`
   （[第 293–294 行](site_builder/build_data.py#L293-L294)；nightly 只傳 `-d 12`，其餘走預設）。
3. **每個 FEN**：[`CleanUciEngine.go()`](site_builder/clean_eval.py#L58-L60) 送
   `position fen <fen>` → `go depth 12`，取 bestmove 前最後一筆 info 的
   score/pv，存 `{best_iccs, score, mate, pv[:8], depth:12}`。分數為**走子方視角** cp。
4. **全程不送 `ucinewgame`** → 那顆 16MB 置換表（TT）整輪掃描共用、不清空。

## 2. 問題分析

### 2.1 共享 TT 是好事，但目前沒真正吃到

固定 `go depth 12` 下，前面相關局面在 TT 留下的高剩餘深度條目會被重用，讓這次
d12 搜尋的著手排序更好、剪枝更充分，**等效看得比冷算的 d12 深**（這是
「d12≈d21」現象的一半成因，另一半是 seldepth 延伸）。所以共享 TT 理論上
**又快又準**。

代價：結果**不可重現**——暖 TT 會微調固定深度的分數，與評估順序綁定。

### 2.2 ⚠ 核心問題：無序 `set` 讓 TT 紅利落空

TT 紅利來自**局面局部性**——一個局面緊接在它的父/兄局面後計算時，搜尋子樹高度
重疊、TT 命中率最高。但現在：

- `fens` 是 Python `set`（[`build_data.py:346`](site_builder/build_data.py#L346)），
  `todo` 直接照 set 迭代序（[第 287 行](site_builder/build_data.py#L287)）。
- 字串 set 有 hash 隨機化（PYTHONHASHSEED），**每次跑順序都不同，且相鄰 FEN
  彼此無關**。
- 配上只有 16MB 的小 TT，等算到某局面的親戚時，它們的條目早被淘汰了。

**結論：現況等於只承擔了共享 TT 的「不可重現」缺點，卻幾乎沒拿到 2.1 的速度/
準度好處。**

### 2.3 跨棋譜的 TT 紅利本來就低

跨到不相關的另一局，舊局的 TT 條目幫不上忙、還佔空間等被淘汰；TT 紅利本質是
局部的。所以應一局接一局連續算完、別把不同局交錯。

修正一個直覺：**不必主動清 TT**——因為 FEN 是全域去重的，跨局共用的開局局面只
算一次，留著反而讓不同棋譜共享的開局互相加速。

## 3. 改進建議（順序＝槓桿大小）

1. **改評估順序（最關鍵）**：用既有的 `games` / move-tree，做 **DFS（父→子、
   沿著每條線）依序展開 FEN**，一局算完再下一局。去重改用「保留首見順序的
   dict / seen-set」，**不要用無序 `set`**。這一步把 2.1 的紅利真正兌現。
2. **加大 Hash**：`16MB → 256–1024MB`（[第 294 行](site_builder/build_data.py#L294)
   的 `hash_mb` 預設，或 nightly 傳入）。否則暖條目撐不到被重用，排序也白排。
   這是讓 TT 真正生效的前提。
3. **TT 全程不清**（維持不送 `ucinewgame`）：全域去重下每個 unique 局面只算
   一次，跨局共享開局是額外加分。

### 附帶小修正
- 快取存的 `depth` 是寫死的 `12`（[第 307 行](site_builder/build_data.py#L307)），
  可改存引擎實際回報的 `info_depth`（`act.get('depth')`），提升保真。

## 4. 主要 Trade-off

即使做對，分數仍 **order-dependent、非位元級可重現**（暖 TT 改變固定深度的著手
排序 → 分數可能微動）。

- 若**陷阱/妙手門檻偵測**需要穩定可複現的分數，要權衡此風險（門檻常數見
  `editor` 與 `render_site.py`，需同步）。
- 若目標是**更準更快**，本方向正確。

## 5. 影響面 / 待決
- 改順序後第一次全量重算會讓 `positions.js` 整批刷新（分數可能與舊值有微小
  差異）；下游 traps/brilliants 統計需重新驗證（`verify_traps.py`）。
- 是否要為「可重現」另開一個 `--deterministic`（每局面 `ucinewgame`）模式，
  與「快速暖 TT」模式並存？—— 未決定。
