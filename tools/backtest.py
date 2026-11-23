#!/usr/bin/env python3
"""Replay a strategy over a kit window with the harness's own fill arithmetic.

Dev-only tool; the graded bot never runs it. The maths mirrors sim/bars/engine.ts
(barsBuyFill / barsSellFill) in integers, so a PnL here matches a local grade to
the micro-USDC on a one-order-per-bar strategy.

    buy:  spend = notional * (BPS - fee) / BPS
          price = open * (BPS + slip) * (D + spend) / (BPS * D)
          qty   = spend * 10^(qty_scale + price_scale) / (price * 10^quote_scale)
    sell: value = qty * open * 10^quote_scale / 10^(qty_scale + price_scale)
          price = max(1, open * (BPS - slip) * D / (BPS * (D + value)))
          gross = qty * price * 10^quote_scale / 10^(qty_scale + price_scale)
          proceeds = gross * (BPS - fee) / BPS
"""
from __future__ import annotations

import gzip
import json
import pathlib
import sys

BPS = 10_000
FEE_BPS = 4
SLIP_BPS = 2
QUOTE_SCALE = 6
PRICE_SCALE = 5
QTY_SCALE = 8
START = 1_000_000_000          # 1,000 USDC in micro-USDC
MIN_NOTIONAL = 1_000_000
VAL_DIV = 10 ** (QTY_SCALE + PRICE_SCALE - QUOTE_SCALE)   # 10^7


def load(path: pathlib.Path) -> list[dict]:
    with gzip.open(path, "rt") as fh:
        return [json.loads(line) for line in fh]


def value(qty: int, price: int) -> int:
    return qty * price // VAL_DIV


def buy_fill(notional: int, open_: int, depth: int) -> tuple[int, int]:
    """(qty received, spend) for a buy of `notional` quote units."""
    spend = notional * (BPS - FEE_BPS) // BPS
    price = open_ * (BPS + SLIP_BPS) * (depth + spend) // (BPS * depth)
    qty = spend * 10 ** (QTY_SCALE + PRICE_SCALE) // (price * 10 ** QUOTE_SCALE)
    return qty, price


def sell_fill(qty: int, open_: int, depth: int) -> tuple[int, int]:
    """(proceeds, price) for a sell of `qty` base units."""
    val = value(qty, open_)
    price = open_ * (BPS - SLIP_BPS) * depth // (BPS * (depth + val))
    price = max(1, price)
    gross = value(qty, price)
    return gross * (BPS - FEE_BPS) // BPS, price


def run(bars: list[dict], decide) -> dict:
    """Replay `decide(i, closes, state) -> target weight in [0,1]` over bars.

    The weight is the share of equity to hold in CBBTC, decided on bar i's close
    and filled at bar i+1's open, exactly as the harness does it.
    """
    closes = [int(b["c"]) for b in bars]
    cash, qty, trades = START, 0, 0
    equity_curve = []
    pending = None                       # (side, amount) decided on bar i, filled at i+1

    for i, bar in enumerate(bars):
        open_ = int(bar["o"])
        o_depth = int(bar["o_depth"][0])

        if pending is not None:
            side, amount = pending
            if side == "buy" and amount >= MIN_NOTIONAL and amount <= cash:
                got, _ = buy_fill(amount, open_, o_depth)
                if got > 0:
                    cash -= amount
                    qty += got
                    trades += 1
            elif side == "sell" and amount > 0 and amount <= qty:
                proceeds, _ = sell_fill(amount, open_, o_depth)
                cash += proceeds
                qty -= amount
                trades += 1
            pending = None

        close = closes[i]
        equity = cash + value(qty, close)
        equity_curve.append(equity)

        if i == len(bars) - 1:
            break                        # orders on the last batch are rejected

        want = decide(i, closes, {"cash": cash, "qty": qty, "equity": equity})
        want = min(max(want, 0.0), 1.0)
        held_val = value(qty, close)
        target_val = int(equity * want)
        delta = target_val - held_val
        if delta > 0:
            notional = min(delta, cash)
            if notional >= MIN_NOTIONAL:
                pending = ("buy", notional)
        elif delta < 0:
            sell_qty = min(qty, (-delta) * VAL_DIV // close)
            if sell_qty > 0 and (value(sell_qty, close) >= MIN_NOTIONAL or sell_qty == qty):
                pending = ("sell", sell_qty)

    # everything still held is sold at the last close against that close's depth
    if qty > 0:
        last = bars[-1]
        proceeds, _ = sell_fill(qty, closes[-1], int(last["c_depth"][0]))
        cash += proceeds
        qty = 0
    equity_curve.append(cash)

    peak, max_dd = START, 0.0
    for e in equity_curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / START)

    return {
        "net_pnl": (cash - START) / 1e6,
        "trades": trades,
        "max_dd": max_dd,
        "equity": equity_curve,
    }


def report(name: str, res: dict) -> None:
    flag = "" if res["trades"] >= 1 and res["max_dd"] <= 0.25 else "  <-- MISSES THE BAR"
    print(f"{name:<34} pnl ${res['net_pnl']:>8.2f}   trades {res['trades']:>4}   "
          f"maxDD {res['max_dd']*100:>5.2f}%{flag}")


if __name__ == "__main__":
    bars = load(pathlib.Path(sys.argv[1]))
    print(f"{len(bars)} bars, close {int(bars[0]['c'])/1e5:.2f} -> {int(bars[-1]['c'])/1e5:.2f} "
          f"({(int(bars[-1]['c'])/int(bars[0]['c'])-1)*100:+.2f}%)")
    report("buy-and-hold", run(bars, lambda i, c, s: 1.0))
    report("hold-cash", run(bars, lambda i, c, s: 0.0))
