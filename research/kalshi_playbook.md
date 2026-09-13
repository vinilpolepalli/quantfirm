# Playbook scan — not live (2026-09-13)

Owner pasted a Sep 2026 Kalshi/perps playbook (pair-arb, imbalance,
BTC→alt lag, vol-reversion, Kalshi perps, Kalshi Pro). Live stays
`desk_book`. This page is lag-fill on our harvest.

```bash
python3 scripts/kalshi_playbook_scan.py
```

## Verdict

**Do not implement any of it on the live loop.** The ideas we can
measure on a 1-minute REST tape lose. The ones that need 2–10s
WebSocket depth are not this bot.

| idea | on this stack | tape |
|---|---|---|
| YES+NO pair under $1 | taker sum = 1 + spread | **0 / 190,032** minutes under $1; min sum **1.001**; **0** crossed books |
| Fade dumped YES (Turbine vol-reversion) | 3-min mid dump ≥15¢, buy YES 15–55¢ | test **−$1,539** n=1291 hit 17% |
| Fade 97¢ ATM last 1–5 min | buy the dog while S≈K | test **−$149** hit **1.1%** |
| BTC lead ETH | 1-min BTC jump ≥8¢, take ETH | test **−$26** last-7d **−$46** |
| 2–10s imbalance / BTC bleed | needs L2 WebSocket | **not in harvest** |
| Stale-quote / last-tick sniping | playbook says dead at 15m | already `oracle_lag` test red |
| `open_fade` (15 bp open impulse) | already registered | test **−$97** n=27 |
| Kalshi perps / funding | 12.0 bps Tier 0, separate margin | **off**. Not a 15m overlay |
| Kalshi Pro | UI, no fee cut, no API tier | irrelevant to the bot |

## Why pair-arb is empty

Kalshi YES/NO are reciprocal. A taker who lifts YES at `ask` and NO
at `1 − bid` pays **1 + spread**. That is ≥ $1 unless the book is
crossed. On 190k quoted minutes the cheapest both-leg take is **$1.001**.
Maker capture of the spread is a different book (maker stays off).

## Vol-reversion here is the longshot

Buying YES after a 15¢ dump is buying the 15–55¢ dog. Hit ~17%. Same
shape as registered `longshot` (test −$247). Turbine’s “fade the panic”
does not survive lag-fill + quadratic fees on this sample.

Fading a 97¢ favorite while spot is still near strike also dies: the
97¢ side was right (hit 1% on the fade). That matches “do not buy 99¢
last ticks.”

## BTC→ETH lag

A 1-minute candle cannot see a 2–10 second lead. The coarsest version
(wait a full minute, then take ETH with BTC) is **red**. Wiring
WebSocket imbalance overnight would be a new live path, not a
parameter on `desk_book`.

## What stays live

Wait 3 min, ≥75¢ FLB, crypto 4% / commodities 8%, Poly sit-if-disagree,
maker off, no perps, no SOL/XRP. `longshot_no` remains the only
sit-more overlay that was green on BTC+ETH+commodities, still t<1.5,
still **not** live.
