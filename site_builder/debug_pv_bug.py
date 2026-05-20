"""Reproduce the bad-PV bug by sending a single FEN to Pikafish and dumping
all raw UCI output."""
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXE = REPO / "engine" / "Windows" / "pikafish-avx2.exe"
FEN = "r1b1kabr1/4a4/1cn3nc1/p3p2Rp/2p3p2/4P4/P1P3P1P/1CN1C1N2/9/R1BAKAB2 w"

proc = subprocess.Popen([str(EXE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        text=True, encoding='utf-8', errors='replace', bufsize=1)


def send(cmd):
    print(f">> {cmd}", flush=True)
    proc.stdin.write(cmd + "\n")
    proc.stdin.flush()


send("uci")
send("setoption name Threads value 4")
send("setoption name Hash value 256")
send("isready")
send(f"position fen {FEN}")
send("go depth 22")

deadline = time.time() + 60
while time.time() < deadline:
    line = proc.stdout.readline()
    if not line:
        time.sleep(0.05)
        continue
    line = line.rstrip()
    print(f"<< {line}", flush=True)
    if line.startswith("bestmove"):
        break
send("quit")
