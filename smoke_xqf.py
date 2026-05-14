import sys, inspect
import cchess
from cchess import read_from_xqf

XQF = r"D:\Elton\TestArea\chess-book\中砲對單提馬.XQF"

game = read_from_xqf(XQF)
print(f"type: {type(game).__name__}")
print(f"attrs: {[a for a in dir(game) if not a.startswith('_')][:40]}")
print()

# Try common attribute names
for attr in ['info', 'init_board', 'init_fen', 'start_fen', 'headers', 'tags', 'result', 'red', 'black', 'event', 'title', 'name']:
    if hasattr(game, attr):
        v = getattr(game, attr)
        if callable(v):
            continue
        s = repr(v)
        if len(s) > 200:
            s = s[:200] + '...'
        print(f"{attr}: {s}")

print()
# Move tree
for attr in ['moves', 'main_line', 'mainline', 'first', 'root', 'variations']:
    if hasattr(game, attr):
        v = getattr(game, attr)
        print(f"{attr}: type={type(v).__name__}")

# Try walking
if hasattr(game, 'dump_iccs_moves'):
    print('dump_iccs_moves:', game.dump_iccs_moves())
