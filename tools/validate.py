#!/usr/bin/env python3
"""Is the ramp's gain structural or just this window's drift?

Runs the ramp against a single full-size fill over many disjoint sub-windows.
The impact saving is deterministic (S^2/D -> S^2/nD); anything beyond it is the
path, and the path does not repeat. A gain that shows up in nearly every
sub-window is the structural part.
"""
from __future__ import annotations

import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from backtest import load, run

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from spread import mk


def sweep(bars, size):
    wins, diffs = 0, []
    chunks = [bars[i:i + size] for i in range(0, len(bars) - size + 1, size)]
    for ch in chunks:
        n = len(ch)
        base = run(ch, mk(1, 0, n))["net_pnl"]
        ramp = run(ch, mk(10, 10, n))["net_pnl"]
        diffs.append(ramp - base)
        if ramp > base:
            wins += 1
    return wins, len(chunks), diffs


if __name__ == "__main__":
    bars = load(pathlib.Path(sys.argv[1]))
    for size in (120, 180, 360, 720):
        wins, total, diffs = sweep(bars, size)
        med = statistics.median(diffs)
        print(f"sub-window {size:>4} bars: ramp beat the single fill in {wins}/{total}"
              f"   median {med:+.2f}   mean {statistics.fmean(diffs):+.2f}"
              f"   worst {min(diffs):+.2f}   best {max(diffs):+.2f}")
