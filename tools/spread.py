#!/usr/bin/env python3
"""How much does spreading the entry and the exit across bars save?

Impact costs a fill S^2/D, and every bar's pool starts again from its own
depth, so n equal slices on n different bars cost S^2/(nD): the saving is
deterministic, while the drift over those n minutes is noise.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from backtest import load, run


def mk(enter_bars: int, exit_bars: int, total: int):
    """Ramp 0 -> 1 over the first `enter_bars`, hold, ramp 1 -> 0 before the end."""
    def f(i, c, s):
        if i < enter_bars:
            return (i + 1) / enter_bars
        start_exit = total - 1 - exit_bars
        if exit_bars > 0 and i >= start_exit:
            left = (total - 1 - i)
            return max(0.0, left / exit_bars)
        return 1.0
    return f


if __name__ == "__main__":
    bars = load(pathlib.Path(sys.argv[1]))
    n = len(bars)
    print(f"{'entry/exit bars':<22}{'net pnl':>10}{'vs B&H':>10}{'trades':>8}{'maxDD':>8}")
    base = run(bars, mk(1, 0, n))["net_pnl"]
    for e, x in ((1, 0), (2, 0), (5, 0), (10, 0), (20, 0), (40, 0),
                 (1, 10), (5, 5), (10, 10), (20, 20), (40, 40), (10, 20), (20, 10)):
        r = run(bars, mk(e, x, n))
        print(f"enter {e:<4} exit {x:<10}{r['net_pnl']:>10.2f}{r['net_pnl']-base:>+10.2f}"
              f"{r['trades']:>8}{r['max_dd']*100:>7.2f}%")
