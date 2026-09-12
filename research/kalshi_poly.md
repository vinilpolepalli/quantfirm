# Polymarket 15m next to Kalshi (2026-09-12)

Read-only on Polymarket. Live Kalshi book stays `desk_book`. A **paper**
sleeve (`poly_book`) simulates the same-side Kalshi clip when Poly and
Kalshi agree at ≥60¢. No Poly orders. Do not auto-promote.

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
* `poly_book` paper sleeve — Poly ≥60¢ picks the side; Kalshi shadow-fills
  that side only if Kalshi also has it ≥60¢. Missing Poly **sits**.
  Separate state (`--state-prefix kalshi_poly_paper`), **never `--live`**.
* `python -m quantfirm.kalshi.cli poly-compare` — today's live crypto
  fills vs that paper sleeve.
* Live `desk_book` overlay: wait first 3 minutes on **the whole book**
  (commodities + BTC + ETH). Crypto then sits if Poly disagrees. No
  Poly 15m gold/WTI — commodities wait only.


## Paper sleeve (not arb)

Not a locked arb: Chainlink TWAP ≠ CF last print. The sleeve is
"both venues already have the same ≥60¢ favorite — take it on Kalshi
at Kalshi size (4% / ~$10)." Disagreement sits. A 70¢ Poly Up with a
50¢ Kalshi YES sits (we do not copy Poly as Kalshi fair).

Supervisor: `scripts/kalshi_poly_paper_loop.sh`. Check-in heals it
without starting a second live agent. Scoreboard is UTC day in
`state/kalshi_poly_paper_trades.csv` (adapter `shadow`) vs live
`kalshi_paper_trades.csv` (`adapter=live`, BTC/ETH only).

## What would change the live book

Whole-book 3 min wait is now **in** `desk_book` (commodities + crypto).
Crypto also sits when Poly disagrees. Do not promote the whole book to
`poly_book` until EOD `poly-compare` is ahead with enough n (`ready`
needs ≥8 each).
