"""Minimal single-threaded UCI driver for Pikafish.

Replaces cchess.UciEngine for the deep re-evaluation pass. The cchess driver
uses a background thread to read stdout while the main thread also calls
readline via get_action(); under depth 22 + Threads=4 the race trashes ~85%
of bestmove outputs (audit_deep_cache.py output). This driver is dumb on
purpose: one process, one stdin, one stdout, synchronous readline.

API:
    eng = CleanUciEngine(exe_path)
    eng.set_option('Threads', '4')
    eng.set_option('Hash', '512')
    eng.isready()
    result = eng.go(fen, depth)
    # result: {'move': str|None, 'score': int|None, 'mate': int|None,
    #          'pv': [iccs...], 'depth': int|None}
    eng.quit()
"""
import subprocess
from pathlib import Path


class CleanUciEngine:
    def __init__(self, exe_path):
        self.proc = subprocess.Popen(
            [str(exe_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            cwd=str(Path(exe_path).parent),
        )
        self._send('uci')
        self._read_until(lambda l: l == 'uciok')

    def _send(self, cmd):
        self.proc.stdin.write(cmd + '\n')
        self.proc.stdin.flush()

    def _readline(self):
        return self.proc.stdout.readline().rstrip('\r\n')

    def _read_until(self, predicate):
        while True:
            line = self._readline()
            if predicate(line):
                return line

    def set_option(self, name, value):
        self._send(f'setoption name {name} value {value}')

    def isready(self):
        self._send('isready')
        self._read_until(lambda l: l == 'readyok')

    def go(self, fen, depth, movetime=None):
        self._send(f'position fen {fen}')
        # movetime (ms) caps wall-time per position. Pikafish stops at whichever
        # of depth / movetime lands first — used to stop grinding already-decided
        # positions all the way to a deep nominal target.
        cmd = f'go depth {depth}'
        if movetime:
            cmd += f' movetime {int(movetime)}'
        self._send(cmd)

        score = mate = info_depth = None
        pv = []
        bestmove_line = None

        while True:
            line = self._readline()
            if not line:
                continue
            if line.startswith('bestmove'):
                bestmove_line = line
                break
            if not line.startswith('info '):
                continue
            tokens = line.split()
            if len(tokens) >= 2 and tokens[1] == 'string':
                continue
            # Only treat as info_move if it has depth + (score|mate) + pv
            info = self._parse_info(tokens)
            if info is None:
                continue
            if 'score' in info:
                score = info['score']
                mate = None
            if 'mate' in info:
                mate = info['mate']
                score = None
            if 'depth' in info:
                info_depth = info['depth']
            if info.get('pv'):
                pv = info['pv']

        # Parse "bestmove X" or "bestmove X ponder Y" or "bestmove (none)"
        parts = bestmove_line.split()
        move = parts[1] if len(parts) > 1 else None
        if move in ('(none)', 'null', 'resign', 'draw'):
            move = None

        return {
            'move': move,
            'score': score,
            'mate': mate,
            'pv': pv,
            'depth': info_depth,
        }

    def _parse_info(self, tokens):
        # `info depth N seldepth M [multipv 1] score cp X|mate K
        #  nodes ... time ... pv A B C ...`
        info = {}
        i = 1  # skip leading 'info'
        n = len(tokens)
        while i < n:
            tok = tokens[i]
            if tok == 'depth' and i + 1 < n and tokens[i+1].lstrip('-').isdigit():
                info['depth'] = int(tokens[i+1])
                i += 2
            elif tok == 'score' and i + 2 < n:
                kind, val = tokens[i+1], tokens[i+2]
                if kind == 'cp' and val.lstrip('-').isdigit():
                    info['score'] = int(val)
                elif kind == 'mate' and val.lstrip('-').isdigit():
                    info['mate'] = int(val)
                i += 3
            elif tok == 'pv':
                info['pv'] = tokens[i+1:]
                break
            else:
                i += 1
        return info if info else None

    def quit(self):
        try:
            self._send('quit')
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
