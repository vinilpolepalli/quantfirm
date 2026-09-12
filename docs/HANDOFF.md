# HANDOFF — Kalshi 15M metals desk

For whoever (or whatever) picks this up next. Read §0 before changing code:
this desk has already produced two spectacular false positives, and both came
from the *fill model*, never from the signal.

Repo scope: `quantfirm/kalshi/`, `scripts/kalshi_*`, `docs/KALSHI.md`,
`research/kalshi_*.md`, `tests/test_kalshi.py`, `data/kalshi/`, `state/`.

---

## 0. Read this first — the two traps

This desk is a **paper/shadow** system. No real money is at risk anywhere, and
none should be added without clearing §5.

Two backtests looked excellent and were both artifacts:

| what it printed | why it was wrong |
| :--- | :--- |
| taker **+103.7%** | Kalshi 1-min candle *opens* are carry-forward quotes, so the "fill only if the next candle confirms" gate was zero-latency. At realistic latency: **−14.6%**. |
| maker **+944%** | The fill test read the *quote* range. We post at `best_bid + 1c`, so `bid_low <= our_price` is true **by construction** — every quote filled instantly. |

The maker one survived the first fix (+793% after requiring real trade prints)
and was only killed by a **null-model control**: a market-mid quoter with no
model at all earned *more* (+1268%, t=12.05). That control is shipped:

```bash
python3 -m quantfirm.kalshi.cli maker-control --data data/kalshi
```

**If you change anything about fills, re-run that control.** If the null model
earns comparably to the strategy, your P&L is mechanics, not edge — regardless
of how good the number looks. `tests/test_kalshi.py::TestMakerFillRealism`
pins both regressions; do not delete those tests to make a suite pass.

A number going *up* after a change to the fill model is the single strongest
signal that the change is wrong.

---

## 1. Setup

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.11
pip install -r requirements.txt
python3 -m unittest tests.test_kalshi -v             # 21 tests, all should pass
```

No credentials are needed for backtests, the audit, or `status`. The live
paper engine reads public prod data unauthenticated. Credentials are only
needed to place demo orders:

| var | purpose |
| :--- | :--- |
| `KALSHI_DEMO_KEY_ID` / `KALSHI_DEMO_PRIVATE_KEY` (or `_PATH`) | demo order placement |
| `KALSHI_PROD_KEY_ID` / `KALSHI_PROD_PRIVATE_KEY` | **not needed; do not set** |

`.gitignore` excludes `*.pem`. Never commit a key.

---

## 2. Run it

```bash
# venue + feed + credential health
python3 -m quantfirm.kalshi.cli status

# honest taker backtest (the losing one — this is the correct number)
python3 -m quantfirm.kalshi.cli backtest --data data/kalshi --split test \
    --fill-mode lag --theta 0.07 --tau-min-s 120 --tau-max-s 600 \
    --price-min 0.35 --price-max 0.92

# the guard that invalidated the maker backtest
python3 -m quantfirm.kalshi.cli maker-control --data data/kalshi

# audit the live shadow P&L against pessimistic fill assumptions
python3 scripts/kalshi_fill_audit.py --adapter maker

# one live paper session (public data, no creds, ~exits after N minutes)
python3 -m quantfirm.kalshi.cli paper --minutes 60 --no-demo --log-decisions

# continuous: supervisor + staleness watchdog (writes state/*.pid, *.log)
./scripts/kalshi_paper_loop.sh &
```

The desk only trades when a 15-minute metals market is open; outside those
hours `status` reports no open market and the supervisor sleeps 10 min.

---

## 2a. Supervisor gotchas (both cost real uptime)

Two bugs bit within 24h of running unattended; the shape of each generalises.

**`grep -c` fails open.** `grep -c` prints `0` *and* exits 1 when nothing
matches, so `open_count=$(... | grep -c ... || echo 0)` yields `"0\n0"`, the
`[ -eq ]` test errors, and the no-open-market guard **fails open**. The
supervisor launched a full engine into a closed weekend market every ~5 min
(79 sessions, 69 watchdog kills) before this was caught. Assign on failure
(`) || open_count=0`) rather than piping a second value in.

**SIGKILL is never forwarded.** The engine runs under `timeout`, and
`kill -9 <timeout pid>` does not reach the python child — every watchdog kill
**orphaned a live engine**. 70 accumulated, all polling the API and all writing
`state/kalshi_paper_{state.json,trades.csv}`. They did no damage only because
the market was shut; mid-session that is concurrent writers to the files the
whole experiment is measured from. The watchdog now also `pkill`s the engine by
name, and the loop sweeps for strays after every session.

Both are pinned by `TestSupervisorScript` in `tests/test_kalshi.py`. If you
touch the supervisor, keep them passing. There is one known artifact of
overlapping engines in the data: a double-entry on `KXGOLD15M-26SEP111115-15`
(2026-09-11 15:16Z, two maker fills at 0.58 and 0.57, $21.25 total).

## 3. Where it stands

Live shadow, paper money, $0 real:

| leg | n | P&L | hit | break-even | t |
| :-- | --: | --: | --: | --: | --: |
| maker | 120 | +$314.21 | 0.725 | 0.655 | 1.50 |
| taker | 34 | +$78.80 | 0.735 | 0.676 | 0.72 |

Neither clears t = 1.96. The maker row is an **upper bound** — the shadow
grants itself free queue priority (see `docs/KALSHI.md` §3b). The audit shows
only **28% of winning fills need to be phantom** for the edge to reach zero,
which is not a comfortable margin for a model with that flaw.

The discriminating statistic is the **t-stat, not the P&L**: at the observed
fill rate a week lands near t≈3.1 if the edge is real and t≈0 if it is not,
while P(week > 0) exceeds 76% even under a no-edge null. Do not celebrate a
green week.

---

## 4. Open problems, ranked

1. ~~**Persist the trades tape.**~~ **DONE** (2026-09-12). The paper engine
   now records `GET /markets/trades` for every open market to
   `state/kalshi_tape_<UTC date>.jsonl` — deduped by `trade_id`, polled every
   `--tape-poll` seconds (default 15), rotated daily, gitignored (~340 bytes
   per print). Recorded for every open market on a timer, **not** only while a
   quote is resting: a tape captured only when we have an order in the book is
   exactly the biased sample that cannot answer the question. Note the rows
   carry `taker_book_side` and `is_block_trade`, both of which a serious queue
   model wants — a block print is not ordinary queue-clearing flow.
   **The desk must run through a full session before there is data to use.**
2. **Replace the `3 * q.count` guess — now unblocked, and the top priority.**
   Replay `_maker_filled` offline against the recorded tape and model queue
   position properly (volume ahead of us, decay, partial fills) instead of a
   magic multiplier. Then re-run `scripts/kalshi_fill_audit.py`: the honest
   haircut should stop being a guess. Cross-check against
   `cli maker-control` — if a null model still earns comparably, the new fill
   model is wrong too.
3. **Fix the daily-stop baseline.** `_entries_allowed` resets at 00:00 UTC,
   mid-session for metals, so a drawdown spanning midnight re-arms the stop at
   full size halfway through (this happened on 2026-09-11/12 and cost roughly
   a second full stop-loss). Use a rolling window or a session baseline. Risk
   control, not a tunable.
4. **Investigate the NO side.** n=96 for -$4.09 lifetime vs YES n=39 for
   +$57.10, and NO is 71% of fills. Either the fair value is biased on that
   side or the desk is systematically selling trend continuation. Diagnose
   before changing anything — do NOT just disable NO, that is curve-fitting to
   one regime.
5. **Measure the cancel race.** The engine cancels on a 2c adverse move and
   always wins in shadow. Log intended-cancel vs next-print timestamps to
   estimate how many of those cancels a real venue would have refused.
6. **Get the demo key** (one manual web signup, `docs/KALSHI.md` §7) and run
   real resting orders. This is the only thing that actually settles the
   queue-priority question, and it still risks no real money.
7. **Copper.** `KXCOPPER15M` is plumbed but not traded (`--metals gold,silver`).
   Thinner book; check it is not just wider spreads.
8. Taker leg is dead unless a genuinely faster signal appears. Do not tune
   `theta` to revive it — that is how PBO 0.40 happened.

---

## 5. Promotion gate (do not skip)

Real capital requires **all** of:

- [ ] ≥2 weeks of live maker fills with t ≥ 1.96 *after* an adverse-selection haircut
- [ ] a fill model rebuilt on the per-print tape, not on candles
- [ ] the null control (§0) clearly weaker than the strategy
- [ ] demo plumbing green end-to-end with real resting orders
- [ ] `docs/FIRM.md` §2 eval passing (DSR, PBO, walk-forward)

Current status: **none of these are met.**
