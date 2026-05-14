import time
import cchess
from cchess import UciEngine

EXE = r"D:\Elton\TestArea\chess-book-ai\engine\Windows\pikafish-avx2.exe"

eng = UciEngine()
eng.load(EXE)
ok = eng.wait_for_ready(timeout=15)
print(f"[ready={ok}] ids={eng.ids}")

eng.go_from(cchess.FULL_INIT_FEN, params={'depth': 14})

best = None
t0 = time.time()
while time.time() - t0 < 30:
    act = eng.get_action()
    if act is None:
        time.sleep(0.05)
        continue
    if act['action'] == 'info_move':
        # Show progress on deepening
        if 'depth' in act and 'score' in act:
            print(f"  d={act['depth']:>2}  score={act['score']:>5}  pv={' '.join(act.get('moves', [])[:6])}")
    elif act['action'] == 'bestmove':
        best = act
        break

print("BEST:", best)
eng.quit()
