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

    def go(self, fen, depth, movetime=None, decisive_cp=None,
           decisive_min_depth=18, decisive_stable=2):
        """Search `fen` to `depth`, with two optional early-stops:

          - movetime (ms): hard wall-time backstop. Pikafish stops at whichever
            of depth / movetime lands first.
          - decisive_cp: once a *completed* depth's |score| >= this (or any mate)
            AND depth >= decisive_min_depth, for `decisive_stable` consecutive
            depths, send `stop`. The position is already decided — deeper search
            won't flip the trap verdict, so don't grind it to the nominal depth.
            Undecided positions (|score| under the threshold) still run full depth.

        Returns the usual dict plus 'stopped_early': True iff the decisive stop
        fired (caller marks such entries done so resume doesn't re-grind them).
        """
        self._send(f'position fen {fen}')
        cmd = f'go depth {depth}'
        if movetime:
            cmd += f' movetime {int(movetime)}'
        self._send(cmd)

        score = mate = info_depth = None
        pv = []
        bestmove_line = None
        last_judged_depth = 0
        decisive_run = 0
        stopped_early = False

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
                # Judge decisiveness on completed-depth lines only (those carry
                # pv + the depth's final score), once per depth.
                if (decisive_cp and not stopped_early and info_depth
                        and info_depth != last_judged_depth):
                    last_judged_depth = info_depth
                    decided = (mate is not None) or (
                        score is not None and abs(score) >= decisive_cp)
                    if decided and info_depth >= decisive_min_depth:
                        decisive_run += 1
                        if decisive_run >= decisive_stable:
                            self._send('stop')
                            stopped_early = True
                    else:
                        decisive_run = 0

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
            'stopped_early': stopped_early,
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
