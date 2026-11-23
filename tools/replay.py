#!/usr/bin/env python3
"""Run the real bot as a subprocess over agent-fun/bars-replay/v1.

Dev-only. The fill arithmetic is backtest.py's, which mirrors sim/bars/engine.ts;
this adds the wire, so what is measured here is main.py itself - its orders, its
rejections and its flatten - rather than a model of it.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from backtest import (BPS, FEE_BPS, MIN_NOTIONAL, PRICE_SCALE, QTY_SCALE, QUOTE_SCALE,
                      SLIP_BPS, START, VAL_DIV, buy_fill, load, sell_fill, value)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SYMBOL = "CBBTC"


def hello_msg(first_close_ms: int) -> dict:
    return {
        "type": "hello", "protocol": "agent-fun/bars-replay/v1", "seed": "12345",
        "symbols": [{"symbol": SYMBOL, "mint": "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij",
                     "price_scale": PRICE_SCALE, "qty_scale": QTY_SCALE}],
        "capital": {"quote": "USDC", "quote_scale": QUOTE_SCALE, "quote_units": str(START)},
        "bar_interval": "1m", "first_close_ms": first_close_ms,
        "caps": {"max_open_positions": 1, "max_orders_per_bar": 16,
                 "max_weight_bps": 10000, "shorts": False, "leverage": False},
        "fees": {"fee_bps": FEE_BPS, "slippage_bps": SLIP_BPS,
                 "min_notional_quote_units": str(MIN_NOTIONAL)},
        "latency_bars": 1,
    }


def replay(bars: list[dict], cmd: list[str]) -> dict:
    proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)

    def send(obj):
        proc.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
        proc.stdin.flush()

    send(hello_msg(int(bars[0]["t"])))

    cash, qty, trades = START, 0, 0
    pending: list[dict] = []
    fills: list[dict] = []
    equity_curve, log = [], []

    for i, bar in enumerate(bars):
        open_, o_depth, close = int(bar["o"]), int(bar["o_depth"][0]), int(bar["c"])

        for o in pending:
            cid = o.get("client_id", "?")
            if o["side"] == "buy":
                notional = int(o["notional_quote_units"])
                if notional > cash or notional < MIN_NOTIONAL:
                    fills.append({"client_id": cid, "symbol": SYMBOL, "side": "buy",
                                  "status": "rejected",
                                  "reason": "insufficient_cash" if notional > cash else "below_min_notional"})
                    continue
                got, price = buy_fill(notional, open_, o_depth)
                cap = int(o["max_slippage_bps"])
                if price * BPS > int(bars[i - 1]["c"]) * (BPS + cap):
                    fills.append({"client_id": cid, "symbol": SYMBOL, "side": "buy",
                                  "status": "rejected", "reason": "max_slippage"})
                    continue
                cash -= notional
                qty += got
                trades += 1
                fills.append({"client_id": cid, "symbol": SYMBOL, "side": "buy", "status": "filled",
                              "reason": None, "qty": str(got), "price": str(price)})
            else:
                want = int(o["qty"])
                if want > qty or want <= 0:
                    fills.append({"client_id": cid, "symbol": SYMBOL, "side": "sell",
                                  "status": "rejected", "reason": "insufficient_position"})
                    continue
                proceeds, price = sell_fill(want, open_, o_depth)
                cap = int(o["max_slippage_bps"])
                if price * BPS < int(bars[i - 1]["c"]) * (BPS - cap):
                    fills.append({"client_id": cid, "symbol": SYMBOL, "side": "sell",
                                  "status": "rejected", "reason": "max_slippage"})
                    continue
                cash += proceeds
                qty -= want
                trades += 1
                fills.append({"client_id": cid, "symbol": SYMBOL, "side": "sell", "status": "filled",
                              "reason": None, "qty": str(want), "price": str(price)})
        pending = []

        equity = cash + value(qty, close)
        equity_curve.append(equity)
        positions = ([{"symbol": SYMBOL, "qty": str(qty), "cost_quote_units": "0"}] if qty > 0 else [])
        send({"type": "batch", "seq": i, "t": int(bar["t"]),
              "bars": [{"symbol": SYMBOL, "t": int(bar["t"]), "o": bar["o"], "h": bar["h"],
                        "l": bar["l"], "c": bar["c"], "v": bar["v"],
                        "o_depth": bar["o_depth"], "c_depth": bar["c_depth"]}],
              "fills": fills,
              "account": {"cash_quote_units": str(cash), "positions": positions,
                          "equity_quote_units": str(equity)}})
        fills = []

        line = proc.stdout.readline()
        if not line:
            raise SystemExit("bot closed stdout:\n" + proc.stderr.read())
        reply = json.loads(line)
        if reply.get("seq") != i:
            raise SystemExit(f"bot echoed seq {reply.get('seq')} for batch {i}")
        orders = reply.get("orders") or []
        if len(orders) > 16:
            raise SystemExit(f"batch {i}: {len(orders)} orders, over the cap")
        if i < len(bars) - 1:
            pending = orders
            for o in orders:
                log.append((i, o["side"], o.get("notional_quote_units") or o.get("qty")))

    if qty > 0:
        proceeds, _ = sell_fill(qty, int(bars[-1]["c"]), int(bars[-1]["c_depth"][0]))
        cash += proceeds
        qty = 0
    equity_curve.append(cash)

    send({"type": "done", "seq": len(bars),
          "account": {"cash_quote_units": str(cash), "positions": [],
                      "equity_quote_units": str(cash)}})
    proc.stdin.close()
    proc.wait(timeout=30)

    peak, max_dd = START, 0.0
    for e in equity_curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / START)
    return {"net_pnl": (cash - START) / 1e6, "trades": trades, "max_dd": max_dd,
            "orders": len(log), "log": log, "stderr": proc.stderr.read()}


if __name__ == "__main__":
    bars = load(pathlib.Path(sys.argv[1]))
    cmd = [sys.executable, "-P", "-s", str(ROOT / "main.py")]
    a = replay(bars, cmd)
    b = replay(bars, cmd)
    print(f"net pnl   ${a['net_pnl']:.2f}")
    print(f"trades     {a['trades']}   orders sent {a['orders']}")
    print(f"max dd     {a['max_dd']*100:.2f}%   (guardrail 25%)")
    print(f"guardrails {'OK' if a['trades'] >= 1 and a['max_dd'] <= 0.25 else 'MISSED'}")
    print(f"dev gate   {'PASS' if a['net_pnl'] > 0 else 'FAIL'} (needs > $0)")
    print(f"determinism {'OK: both runs identical' if a['log'] == b['log'] and a['net_pnl'] == b['net_pnl'] else 'FAILED'}")
    if a["stderr"].strip():
        print("stderr:", a["stderr"][:500])
