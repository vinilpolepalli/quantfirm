# Polymarket 15m next to Kalshi (2026-09-12)

Read-only. No Poly orders. Live Kalshi book stays `desk_book`.

## Why look

BTC/ETH 15m is the weekend book. Polymarket runs the same ET quarter-hour
(`btc-updown-15m-{unix}`, `eth-updown-15m-{unix}`, plus SOL/XRP/DOGE we
do not trade). A second favorite tape can:

1. Confirm a Kalshi ≥60¢ favorite (both venues same side).
2. Sit out an early Kalshi flicker the other venue already faded.
3. Measure lead-lag (who reprices first).

It cannot be used as Kalshi fair. The contracts differ.

## Contract map (verified live 12:51Z)

| | Kalshi `KXBTC15M` / `KXETH15M` | Polymarket `{btc,eth}-updown-15m` |
|---|---|---|
| Window | 15 min, ET quarters, close on the hour/:15/:30/:45 | Same clock (title 8:45–9:00AM ET = 12:45–13:00Z) |
| YES / Up | close print ≥ strike (open) | Chainlink 60s TWAP over the **whole** window ≥ start |
| Index | CF Benchmarks 60s average | Chainlink streams TWAP |
| Payoff | last print vs K | path TWAP vs start |

A spike-then-dump can pay Up on Poly and NO on Kalshi. Copying Poly's
price onto a Kalshi order is a different bet.

No Poly 15m gold / silver / copper / WTI / natgas.

## Live snapshot 2026-09-12T12:51Z (09:00 ET window)

| | Kalshi YES | Poly Up CLOB | Poly Down CLOB | Same favorite? |
|---|---|---|---|---|
| BTC | 21 / 22 | ~29 / 30 | ~71 / 74 | yes — both Down/NO |
| ETH | 21 / 22 | ~20 / 21 | ~79 / 80 | yes — both Down/NO |

Gamma `outcomePrices` can be stale vs the CLOB (BTC Up last 62.5¢ while
the book was ~30¢). The feed uses CLOB BBO only.

~9¢ BTC basis (Kalshi YES cheaper than Poly Up) is the kind of number to
log, not to arb blindly: different settlement.

## What shipped

* `quantfirm/kalshi/poly.py` — Gamma slug + CLOB BBO, 3s cache.
* Paper engine logs `poly_up` / `poly_down` on BTC/ETH decision ticks.
* `python -m quantfirm.kalshi.cli poly` compares both venues.
* `poly_confirm` — `desk_book` but crypto sits when Poly's ≥55¢ favorite
  is the other side. **Off the live loop.** Missing Poly quote does not
  sit (outage ≠ a signal).
* SOL/XRP/DOGE stay off.

## What would change the live book

A few days of `state/kalshi_paper_decisions.jsonl` with Poly fields, then
score: would `poly_confirm` have sat the 08:30 BTC NO that lost, without
sitting the 08:15 NOs that paid? Until that table exists, do not switch
`PAPER_STRATEGY`.
