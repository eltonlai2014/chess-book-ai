#!/usr/bin/env python
"""detect_source_changes.py — 識別來源 XQF 棋譜庫自上次 ingest 以來的變動分類。

來源庫 D:\\Elton\\TestArea\\chess-book 自帶 git。本工具跨進去跑帶『改名偵測』的
git diff，把變動分成：搬資料夾 / 改名 / 疑似搬夾或改名+大改 / 新增 / 刪除 / 修改，
讓每次新貨到時一眼分得清哪些會沿用、哪些會重算、哪些只是換位置。

身分判定背景（與 build_data.py 一致）：一本棋譜的身分 = 檔名 basename
（_dedupe_by_name 以 p.name.lower() 分組；games 記 'file': fp.name）。資料夾路徑
不參與身分；evals 以 FEN 內容為鍵；games.json 每次全量重建。因此：
  • 搬資料夾（同檔名） → slug 不變、FEN 沿用 → 無痛
  • 改名（換檔名）     → 新 slug、舊頁變孤兒（render 自動清）、FEN 仍以內容沿用

唯讀工具：除 --update-marker 外不寫任何檔，不碰主線 pipeline。

用法：
  python site_builder/detect_source_changes.py                 # 比較 marker..HEAD（無 marker 則 HEAD~1）
  python site_builder/detect_source_changes.py --since f60871f # 明確指定比較基準
  python site_builder/detect_source_changes.py --update-marker # ingest 完成後，把目前 HEAD 記為下次基準
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# 鏡 build_data.py:143 的 SRC_DIR — 若來源庫搬家，兩處一起改。
SRC_DIR = Path(r"D:\Elton\TestArea\chess-book")
MARKER = REPO / "output" / ".last_source_ingest"


def git(*args):
    """在來源庫跑 git，回傳 CompletedProcess（quotepath 關閉以拿到可讀中文檔名）。"""
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(SRC_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def src_head():
    r = git("rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def is_xqf(path: str) -> bool:
    return path.lower().endswith(".xqf")


def basename(path: str) -> str:
    return Path(path).name.lower()


def resolve_base(since: str | None, head: str) -> tuple[str, str]:
    """回傳 (base_ref, 來源說明)。"""
    if since:
        return since, "--since"
    if MARKER.exists():
        marked = MARKER.read_text(encoding="utf-8").strip()
        if marked:
            return marked, "marker"
    return f"{head}~1", "fallback HEAD~1"


def short(ref: str) -> str:
    return ref[:10] if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref) else ref


def main() -> int:
    ap = argparse.ArgumentParser(description="識別來源棋譜庫的改名/搬夾/新增/刪除/修改")
    ap.add_argument("--since", help="比較基準 commit（預設讀 marker，無則 HEAD~1）")
    ap.add_argument("--update-marker", action="store_true",
                    help="把目前來源庫 HEAD 寫入 marker，當作下次比較基準")
    args = ap.parse_args()

    if not (SRC_DIR / ".git").exists():
        print(f"[err] {SRC_DIR} 不是 git repo（找不到 .git）", file=sys.stderr)
        return 1
    head = src_head()
    if not head:
        print(f"[err] 無法讀取 {SRC_DIR} 的 HEAD（空 repo？）", file=sys.stderr)
        return 1

    if args.update_marker:
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text(head, encoding="utf-8")
        print(f"[marker] 已記錄來源庫 HEAD {short(head)} → {MARKER}")
        return 0

    base, base_src = resolve_base(args.since, head)
    r = git("diff", "--find-renames", "-M", "--name-status", f"{base}..{head}")
    if r.returncode != 0:
        print(f"[err] git diff 失敗（base={base}）：{r.stderr.strip()}", file=sys.stderr)
        return 1

    moved, renamed, added, deleted, modified = [], [], [], [], []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0]
        if code.startswith("R") and len(parts) >= 3:
            old, new, sim = parts[1], parts[2], code[1:]
            if not (is_xqf(old) or is_xqf(new)):
                continue
            (moved if basename(old) == basename(new) else renamed).append((sim, old, new))
        elif code.startswith("A") and len(parts) >= 2:
            if is_xqf(parts[1]):
                added.append(parts[1])
        elif code.startswith("D") and len(parts) >= 2:
            if is_xqf(parts[1]):
                deleted.append(parts[1])
        elif code.startswith("M") and len(parts) >= 2:
            if is_xqf(parts[1]):
                modified.append(parts[1])

    # 二次啟發：同 basename 同時見於 A 與 D → git 因內容大改未認 rename，視為疑似搬夾/改名。
    del_by_name = {basename(p): p for p in deleted}
    suspected = []
    for a in list(added):
        bn = basename(a)
        if bn in del_by_name:
            suspected.append((del_by_name[bn], a))
            added.remove(a)
            deleted.remove(del_by_name[bn])
            del del_by_name[bn]

    print(f"[detect] 來源庫 {SRC_DIR}")
    print(f"[detect] 比較 {short(base)}..{short(head)}（基準來自 {base_src}）")
    print()

    def section(title, note, rows, fmt):
        print(f"{title}  {len(rows)}  （{note}）")
        for row in rows:
            print("  " + fmt(row))

    section("搬資料夾", "同檔名 → slug 不變、FEN 沿用、無痛",
            moved, lambda r: f"R{r[0]}  {r[1]}  →  {r[2]}")
    section("改名", "換檔名 → 新 slug、舊頁孤兒 render 自動清、FEN 沿用",
            renamed, lambda r: f"R{r[0]}  {r[1]}  →  {r[2]}")
    section("疑似搬夾/改名+大改", "git 未認 rename，同檔名見於新增&刪除",
            suspected, lambda r: f"{r[0]}  (D)  →  {r[1]}  (A)")
    section("新增", "帶新 FEN", added, lambda p: p)
    section("刪除", "games.json 自動汰除、舊頁 render 自動清", deleted, lambda p: p)
    section("修改", "可能帶新 FEN", modified, lambda p: p)

    print()
    print(f"[摘要] 搬夾 {len(moved)} / 改名 {len(renamed)} / 疑似 {len(suspected)} / "
          f"新增 {len(added)} / 刪除 {len(deleted)} / 修改 {len(modified)}")
    if not any((moved, renamed, suspected, added, deleted, modified)):
        print("[摘要] 無 .xqf 變動（來源庫自基準點以來乾淨）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
