# cbbtc-race-bot

[![make.fun · btc-race-24h-20261123-0511](https://make.fun/badge/btc-race-24h-20261123-0511.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![rank](https://make.fun/badge/btc-race-24h-20261123-0511/ricaiueo/cbbtc-race-bot/rank.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![reward](https://make.fun/badge/btc-race-24h-20261123-0511/ricaiueo/cbbtc-race-bot/reward.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)

A long-only bot that trades Coinbase Wrapped BTC (cbBTC) against USDC on
1-minute on-chain bars, for make.fun's 24-hour live race. Paper money only:
it starts with $1,000 of simulated capital and nothing is traded for real.

`main.py` is the entry point (Python 3.13, standard library only).
`vendor/makefun_bars.py` is a byte-for-byte copy of the kit's SDK shim.

## The idea: the edge is in the cost model, not in a signal

**Every ordinary 1-minute signal loses money here.** On the published dev
window I tested EMA crossovers, SMA filters, momentum, Donchian breakouts and
z-score mean reversion across a parameter grid — all 25 of them finished below
zero, most far below, while simply holding made +$32:

| strategy | net PnL | trades |
| --- | --- | --- |
| buy-and-hold | **+$32.17** | 1 |
| ema-cross(60,240) | −$2.18 | 5 |
| sma-filter(180) | −$15.80 | 25 |
| donchian(120) | −$16.22 | 25 |
| revert(60,2.0) | −$78.44 | 53 |
| momentum(30) | −$182.67 | 127 |

The reason is arithmetic. A round trip pays 4 bps of fee, 2 bps of modelled
slippage and its own price impact on both legs — about **42 bps at full size**
on this pool's depth. A rule must catch a 0.42% move just to break even, and
1-minute bars do not offer those often enough to pay for the ones it gets
wrong. So this bot takes no view on direction at all.

**Where the edge actually is.** Price impact is the one cost that is not
linear in size: a fill worth `S` against pool depth `D` pays about `S²/D`, and
every bar's pool starts again from its own depth. The same `S` split across
`n` different bars therefore pays `S²/(nD)` — impact falls by a factor of `n`,
while fee and slippage are unchanged. The bot ramps into its position over the
first 10 bars and back out over the last 10, rather than taking one full-size
fill at each end as a plain buy-and-hold does.

That saving is arithmetic, not a forecast. Measured against a single full-size
fill over **26 disjoint sub-windows** of the dev data, the ramp won **26 times
out of 26** — worst case +$0.05, median about +$3 on $1,000.

## Risk

One trailing stop, 7% below the highest close since the first fill; after it
the bot ramps out and stays in cash. The dev window's deepest drawdown was
2.06%, so at 7% it never fires there and costs the dev grade nothing. It
exists for a crash in the race window, where it caps the loss and keeps the
entry far inside the 25% drawdown guardrail.

## Knowing where the window ends

`hello` carries no bar count, so the end comes from bar time: the window is 24
hours of 1-minute bars, so it ends 1,439 minutes after the first bar closes.
Bar time is the only clock the bot reads — never the wall clock — and using
time rather than counting batches keeps the exit ramp correctly placed even if
the recorder drops a minute.

## Result on the dev window

```
net pnl   $37.82      (buy-and-hold: $32.17)
trades     19
max dd     2.07%      (guardrail 25%)
dev gate   PASS
determinism OK: both runs identical
```

## Reproducing it

```sh
python3 tools/replay.py <kit>/dataset/bars/CBBTC.ndjson.gz   # runs main.py over the wire protocol
python3 tools/explore.py <kit>/dataset/bars/CBBTC.ndjson.gz  # the signal survey above
python3 tools/validate.py <kit>/dataset/bars/CBBTC.ndjson.gz # the 26-sub-window ramp test
```

`tools/backtest.py` reimplements the harness's fill arithmetic in integers
(`sim/bars/engine.ts`: `barsBuyFill` / `barsSellFill`); `tools/replay.py` adds
the wire and runs `main.py` as a real subprocess, so what it measures is the
bot itself. Dev tools only — the graded bot never runs them.
