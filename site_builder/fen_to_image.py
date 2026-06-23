"""FEN → 象棋盤面圖檔 (PNG/GIF)。獨立 Pillow 渲染器，無瀏覽器、無伺服器。

棋子用標楷體、紅黑分色、畫河界 + 九宮斜線，2x 超取樣抗鋸齒。

用法:
  py site_builder/fen_to_image.py "<fen>" -o board.png
  py site_builder/fen_to_image.py "<fen1>" "<fen2>" --labels "97m;87m" \
     --out-dir output/fen_shots --montage output/fen_shots/montage.png
  py site_builder/fen_to_image.py "<fen1>" "<fen2>" --gif output/fen_shots/slides.gif

FEN 子棋規格 (Pikafish/cchess)：R/N/B/A/K/C/P 紅、小寫黑；列由上(黑方)到下(紅方)。
"""
import argparse
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SS = 2            # 超取樣倍率
CELL = 64         # 交叉點間距(px, 1x)
MARGIN = 46
COLS, ROWS = 9, 10

FONT_PIECE = r"C:\Windows\Fonts\kaiu.ttf"   # 標楷體
FONT_TEXT = r"C:\Windows\Fonts\msjh.ttc"    # 微軟正黑

RED_SET = {'K': '帥', 'A': '仕', 'B': '相', 'N': '傌', 'R': '俥', 'C': '炮', 'P': '兵'}
BLK_SET = {'k': '將', 'a': '士', 'b': '象', 'n': '馬', 'r': '車', 'c': '包', 'p': '卒'}

BG = (236, 213, 160)      # 木色底
LINE = (96, 64, 32)
RED = (178, 34, 34)
BLACK = (28, 28, 28)
DISC = (246, 236, 212)    # 棋子圓盤底


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def parse_board(fen):
    grid = []
    for row in fen.split()[0].split('/'):
        line = []
        for ch in row:
            if ch.isdigit():
                line += [None] * int(ch)
            else:
                line.append(ch)
        grid.append((line + [None] * COLS)[:COLS])
    while len(grid) < ROWS:
        grid.append([None] * COLS)
    return grid[:ROWS]


def render_fen(fen, label=None):
    s = SS
    cell, margin = CELL * s, MARGIN * s
    W = (COLS - 1) * cell + 2 * margin
    cap = (38 if label else 10) * s
    H = (ROWS - 1) * cell + 2 * margin + cap
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    X = lambda c: margin + c * cell
    Y = lambda r: margin + r * cell
    lw = max(2, s)

    for r in range(ROWS):
        d.line([(X(0), Y(r)), (X(COLS - 1), Y(r))], fill=LINE, width=lw)
    for c in range(COLS):
        if c in (0, COLS - 1):
            d.line([(X(c), Y(0)), (X(c), Y(ROWS - 1))], fill=LINE, width=lw)
        else:  # 河界：內側直線在第4~5列間斷開
            d.line([(X(c), Y(0)), (X(c), Y(4))], fill=LINE, width=lw)
            d.line([(X(c), Y(5)), (X(c), Y(ROWS - 1))], fill=LINE, width=lw)
    for r0, r1 in [(0, 2), (7, 9)]:   # 九宮斜線
        d.line([(X(3), Y(r0)), (X(5), Y(r1))], fill=LINE, width=lw)
        d.line([(X(5), Y(r0)), (X(3), Y(r1))], fill=LINE, width=lw)

    rf = _font(FONT_PIECE, int(cell * 0.44))
    ry = (Y(4) + Y(5)) // 2
    d.text(((X(1) + X(2)) // 2, ry), "楚 河", font=rf, fill=LINE, anchor="mm")
    d.text(((X(6) + X(7)) // 2, ry), "漢 界", font=rf, fill=LINE, anchor="mm")

    pf = _font(FONT_PIECE, int(cell * 0.58))
    rad = int(cell * 0.42)
    grid = parse_board(fen)
    for r in range(ROWS):
        for c in range(COLS):
            ch = grid[r][c]
            if not ch:
                continue
            glyph = RED_SET.get(ch) or BLK_SET.get(ch)
            if not glyph:
                continue
            col = RED if ch in RED_SET else BLACK
            cx, cy = X(c), Y(r)
            d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                      fill=DISC, outline=col, width=max(2, s + 1))
            d.text((cx, cy - int(cell * 0.02)), glyph, font=pf, fill=col, anchor="mm")

    if label:
        tf = _font(FONT_TEXT, int(19 * s))
        side = fen.split()[1] if len(fen.split()) > 1 else ''
        suffix = '  （紅方走）' if side == 'w' else ('  （黑方走）' if side == 'b' else '')
        d.text((W // 2, H - cap // 2), label + suffix, font=tf, fill=(40, 40, 40), anchor="mm")

    return img.resize((W // s, H // s), Image.LANCZOS)


def montage(images, cols=3, pad=18, bg=(250, 246, 238)):
    n = len(images)
    rows = (n + cols - 1) // cols
    w = max(im.width for im in images)
    h = max(im.height for im in images)
    canvas = Image.new('RGB', (cols * w + (cols + 1) * pad, rows * h + (rows + 1) * pad), bg)
    for i, im in enumerate(images):
        r, c = divmod(i, cols)
        canvas.paste(im, (pad + c * (w + pad), pad + r * (h + pad)))
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('fens', nargs='+')
    ap.add_argument('-o', '--out', help='單一 FEN 的輸出 PNG 路徑')
    ap.add_argument('--out-dir', default='output/fen_shots')
    ap.add_argument('--labels', help='分號分隔的標籤，一個對一個 FEN')
    ap.add_argument('--montage', help='另輸出一張蒙太奇拼圖到此路徑')
    ap.add_argument('--cols', type=int, default=3, help='蒙太奇每列張數')
    ap.add_argument('--gif', help='輸出循環播放各 FEN 的 GIF 到此路徑')
    a = ap.parse_args()

    labels = a.labels.split(';') if a.labels else []
    imgs = [render_fen(f, labels[i] if i < len(labels) else None) for i, f in enumerate(a.fens)]

    Path(a.out_dir).mkdir(parents=True, exist_ok=True)
    if a.out and len(imgs) == 1:
        imgs[0].save(a.out)
        print('[write]', a.out)
    else:
        for i, im in enumerate(imgs):
            p = Path(a.out_dir) / f'board_{i + 1}.png'
            im.save(p)
            print('[write]', p)
    if a.montage:
        Path(a.montage).parent.mkdir(parents=True, exist_ok=True)
        montage(imgs, cols=a.cols).save(a.montage)
        print('[montage]', a.montage)
    if a.gif:
        Path(a.gif).parent.mkdir(parents=True, exist_ok=True)
        frames = [im.convert('P', palette=Image.ADAPTIVE) for im in imgs]
        frames[0].save(a.gif, save_all=True, append_images=frames[1:], duration=1400, loop=0)
        print('[gif]', a.gif)


if __name__ == '__main__':
    main()
