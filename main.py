#!/usr/bin/env python3
"""A cost-shaped long-only bot for CBBTC on 1-minute on-chain bars.

The strategy follows from what the replay charges rather than from a signal.

Why no signal. On the published dev window every ordinary 1-minute rule loses
money: EMA crossovers, SMA filters, momentum, Donchian breakouts and z-score
mean reversion were all tested (tools/explore.py) and every one of them ended
below zero, most far below, while simply holding made +$32. A round trip pays
4 bps of fee, 2 bps of modelled slippage and its own price impact on both
legs - about 42 bps at full size on this pool's depth - so a rule has to catch
a 0.42% move just to break even, and 1-minute bars do not offer those often
enough to pay for the ones it gets wrong. Trading on noise is how a bot loses
here, so this one does not.

Where its edge is instead. Price impact is the one cost that is not linear in
size: a fill worth S against pool depth D pays about S*S/D, and *every bar's
pool starts again from its own depth*. So the same S split over n different
bars pays S*S/(nD) - the impact cost falls by a factor of n, while fee and
slippage are unchanged. This bot therefore ramps into its position over the
first RAMP_BARS bars and back out over the last RAMP_BARS, instead of taking
one full-size fill at each end as a plain buy-and-hold does. The saving is
arithmetic, not a forecast: measured against a single full-size fill over 26
disjoint sub-windows of the dev data it won 26 times (tools/validate.py),
worst case +$0.05, median about +$3 on $1,000.

The one risk rule. A trailing stop at STOP_BPS below the highest close seen
since the first fill, after which the bot ramps out and stays in cash. On the
dev window the deepest drawdown was 2.06%, so at 7% this never fires there and
costs the dev grade nothing; it exists for a crash in the race window, where
it caps the loss and keeps the entry far inside the 25% drawdown guardrail.

Knowing where the window ends. The protocol's hello carries no bar count, so
the end is taken from bar time: the window is 24 hours of 1-minute bars, so it
ends 1,439 minutes after the first bar closes. Bar time is the only clock read
- never the wall clock - and using time rather than counting batches keeps the
exit ramp correctly placed even if the recorder drops a minute or two.

Determinism: integer arithmetic throughout, no clock, no environment, no
randomness, no file or network access. Two executions on the same bars send
the same orders.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

SYMBOL = "CBBTC"
BPS = 10_000
#: Bars to spread the entry over, and the exit: impact per bar falls as 1/n.
RAMP_BARS = 10
#: Minutes from the first bar's close to the last bar's close (24 hours of bars).
WINDOW_MINUTES = 1_439
MINUTE_MS = 60_000
#: Trailing stop below the highest close since the first fill.
STOP_BPS = 700
#: Slippage caps: a buy will not chase, a sell wants to be filled.
BUY_SLIPPAGE_BPS = 150
SELL_SLIPPAGE_BPS = 500


class Bot:
    def __init__(self) -> None:
        self.first_t = -1
        self.peak = 0
        self.stopped = False

    def target_bps(self, t: int, close: int) -> int:
        """The share of equity to hold in CBBTC, in bps, decided on this close."""
        if self.stopped:
            return 0

        elapsed = (t - self.first_t) // MINUTE_MS
        remaining = WINDOW_MINUTES - elapsed

        # ramp in over the first RAMP_BARS bars
        weight = BPS if elapsed >= RAMP_BARS - 1 else BPS * (elapsed + 1) // RAMP_BARS
        # ramp out over the last RAMP_BARS bars
        if remaining < RAMP_BARS:
            out = 0 if remaining <= 0 else BPS * remaining // RAMP_BARS
            weight = min(weight, out)
        return max(0, min(BPS, weight))

    def on_batch(self, state, batch):
        bar = None
        for b in batch.get("bars", ()):
            if b["symbol"] == SYMBOL:
                bar = b
        if bar is None or state.warming_up:
            return []

        t = int(bar["t"])
        close = int(bar["c"])
        if self.first_t < 0:
            self.first_t = t

        held = state.positions.get(SYMBOL)
        qty = held.qty if held is not None else 0
        if qty > 0:
            self.peak = max(self.peak, close)
            if self.peak > 0 and close * BPS <= self.peak * (BPS - STOP_BPS):
                self.stopped = True

        want = self.target_bps(t, close)
        equity = state.equity
        held_value = state.value(SYMBOL, qty) if qty > 0 else 0
        delta = equity * want // BPS - held_value
        min_notional = int(state.hello["fees"]["min_notional_quote_units"])

        if delta > 0:
            notional = min(delta, state.cash)
            if notional < min_notional:
                return []
            return [{
                "side": "buy",
                "symbol": SYMBOL,
                "notional_quote_units": notional,
                "max_slippage_bps": BUY_SLIPPAGE_BPS,
            }]

        if delta < 0 and qty > 0:
            scale = 10 ** (state.hello["symbols"][0]["qty_scale"]
                           + state.hello["symbols"][0]["price_scale"]
                           - state.hello["capital"]["quote_scale"])
            sell_qty = min(qty, (-delta) * scale // close)
            if sell_qty <= 0:
                return []
            # too small to be accepted unless it empties the position
            if state.value(SYMBOL, sell_qty) < min_notional and sell_qty != qty:
                return []
            return [{
                "side": "sell",
                "symbol": SYMBOL,
                "qty": sell_qty,
                "max_slippage_bps": SELL_SLIPPAGE_BPS,
            }]

        return []


makefun_bars.run(Bot().on_batch)
