#!/usr/bin/env python3
"""Would a slow, banded trend filter be worth adding on top of the ramp?

The plain filters in explore.py all lose because they trade constantly. A wide
hysteresis band around a slow average cuts the trade count; the question is
whether what it saves in a downtrend beats what the whipsaws cost. Trade count
is the thing to watch: each round trip is about 42 bps.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from backtest import load, run
from spread import mk


def mk_banded(n, band_bps, ramp, total):
    """The ramp, gated by close vs SMA(n) with a +/- band_bps dead zone."""
    base = mk(ramp, ramp, total)
    state = {"on": True}
    def f(i, c, s):
        if i + 1 >= n:
            m = sum(c[i + 1 - n:i + 1]) / n
            if c[i] < m * (1 - band_bps / 10_000):
                state["on"] = False
            elif c[i] > m * (1 + band_bps / 10_000):
                state["on"] = True
        return base(i, c, s) if state["on"] else 0.0
    return f


if __name__ == "__main__":
    bars = load(pathlib.Path(sys.argv[1]))
    n = len(bars)
    plain = run(bars, mk(10, 10, n))
    print(f"{'rule':<30}{'net pnl':>9}{'vs ramp':>9}{'trades':>8}{'maxDD':>8}")
    print(f"{'ramp only (the entry)':<30}{plain['net_pnl']:>9.2f}{0.0:>9.2f}"
          f"{plain['trades']:>8}{plain['max_dd']*100:>7.2f}%")
    for span in (120, 240, 360, 480):
        for band in (25, 50, 100, 200):
            r = run(bars, mk_banded(span, band, 10, n))
            print(f"{'sma(%d) band %dbps' % (span, band):<30}{r['net_pnl']:>9.2f}"
                  f"{r['net_pnl']-plain['net_pnl']:>+9.2f}{r['trades']:>8}{r['max_dd']*100:>7.2f}%")
