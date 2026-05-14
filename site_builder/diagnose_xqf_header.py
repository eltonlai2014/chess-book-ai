"""Compare XQF headers by reading filenames from games.json (avoids glob encoding traps)."""
from pathlib import Path
import struct
import json

REPO = Path(__file__).resolve().parent.parent
SRC = Path(r"D:\Elton\TestArea\chess-book")
games = json.loads((REPO / 'output/site/data/games.json').read_text(encoding='utf-8'))

for g in games:
    rel = g.get('rel_path', g['file'])
    fp = SRC / rel
    if not fp.exists():
        # Try just the filename in the root or recursive
        cands = list(SRC.rglob(g['file']))
        if cands:
            fp = cands[0]
    if not fp.exists():
        print(f"NOT FOUND: {g['file']}")
        continue
    d = fp.read_bytes()
    version = d[2]
    parsed = struct.unpack("<BIBBBBBBBB", d[3:16])
    print(f"{g['file']}: size={len(d)}  version=0x{version:02x}")
    print(f"  KeyMask=0x{parsed[0]:02x}  KeysSum=0x{parsed[6]:02x}  KeyXY=0x{parsed[7]:02x}  KeyXYf=0x{parsed[8]:02x}  KeyXYt=0x{parsed[9]:02x}")
