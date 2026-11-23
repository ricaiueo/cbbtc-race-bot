#!/usr/bin/env python3
"""Survey strategy families on the dev window and on its four 6-hour quarters.

Dev-only. A rule that only works on the whole window is a rule fitted to one
24-hour sample; the quarters are here to show which rules survive being cut up.
"""
from __future__ import annotations

import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from backtest import load, run, START


def sma(c, i, n):
    if i + 1 < n:
        return None
    return sum(c[i + 1 - n:i + 1]) / n


def ema_series(c, span):
    k = 2 / (span + 1)
    out, v = [], None
    for i, x in enumerate(c):
        if v is None:
            if i + 1 < span:
                out.append(None)
                continue
            v = sum(c[: span]) / span
        else:
            v += k * (x - v)
        out.append(v)
    return out


def mk_ema_cross(fast, slow):
    cache = {}
    def f(i, c, s):
        key = id(c)
        if key not in cache:
            cache[key] = (ema_series(c, fast), ema_series(c, slow))
        ef, es = cache[key]
        if ef[i] is None or es[i] is None:
            return 0.0
        return 1.0 if ef[i] > es[i] else 0.0
    return f


def mk_sma_filter(n):
    def f(i, c, s):
        m = sma(c, i, n)
        return 0.0 if m is None else (1.0 if c[i] > m else 0.0)
    return f


def mk_momentum(n):
    def f(i, c, s):
        if i < n:
            return 0.0
        return 1.0 if c[i] > c[i - n] else 0.0
    return f


def mk_donchian(n):
    def f(i, c, s):
        if i + 1 < n:
            return 0.0
        hi = max(c[i + 1 - n:i + 1])
        lo = min(c[i + 1 - n:i + 1])
        held = s["qty"] > 0
        if c[i] >= hi:
            return 1.0
        if c[i] <= lo:
            return 0.0
        return 1.0 if held else 0.0
    return f


def mk_revert(n, k):
    def f(i, c, s):
        if i + 1 < n:
            return 0.0
        w = c[i + 1 - n:i + 1]
        m = sum(w) / n
        sd = statistics.pstdev(w)
        if sd == 0:
            return 1.0 if s["qty"] > 0 else 0.0
        z = (c[i] - m) / sd
        if z < -k:
            return 1.0
        if z > k:
            return 0.0
        return 1.0 if s["qty"] > 0 else 0.0
    return f


CANDIDATES = [
    ("buy-and-hold", lambda i, c, s: 1.0),
    *[(f"sma-filter({n})", mk_sma_filter(n)) for n in (30, 60, 120, 180, 240, 360)],
    *[(f"ema-cross({a},{b})", mk_ema_cross(a, b)) for a, b in
      ((8, 21), (10, 60), (20, 120), (30, 180), (60, 240), (60, 360))],
    *[(f"momentum({n})", mk_momentum(n)) for n in (30, 60, 120, 240, 360)],
    *[(f"donchian({n})", mk_donchian(n)) for n in (30, 60, 120, 240)],
    *[(f"revert({n},{k})", mk_revert(n, k)) for n, k in
      ((30, 1.5), (60, 1.5), (60, 2.0), (120, 2.0))],
]

if __name__ == "__main__":
    bars = load(pathlib.Path(sys.argv[1]))
    q = len(bars) // 4
    quarters = [bars[j * q:(j + 1) * q] for j in range(4)]
    print(f"{'strategy':<22}{'full':>9}{'Q1':>8}{'Q2':>8}{'Q3':>8}{'Q4':>8}{'trd':>6}{'DD%':>7}")
    for qi, qb in enumerate(quarters):
        r = (int(qb[-1]['c']) / int(qb[0]['c']) - 1) * 100
        print(f"  (Q{qi+1} move {r:+.2f}%)", end="  ")
    print()
    rows = []
    for name, fn in CANDIDATES:
        full = run(bars, fn)
        qs = [run(qb, fn)["net_pnl"] for qb in quarters]
        rows.append((full["net_pnl"], name, full, qs))
    for pnl, name, full, qs in sorted(rows, reverse=True):
        print(f"{name:<22}{pnl:>9.2f}" + "".join(f"{x:>8.2f}" for x in qs) +
              f"{full['trades']:>6}{full['max_dd']*100:>7.2f}")
