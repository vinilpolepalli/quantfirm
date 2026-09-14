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

Three results looked excellent and were all artifacts of the instrumentation:

| what it printed | why it was wrong |
| :--- | :--- |
| taker **+103.7%** | Kalshi 1-min candle *opens* are carry-forward quotes, so the "fill only if the next candle confirms" gate was zero-latency. At realistic latency: **−14.6%**. |
| maker **+944%** | The fill test read the *quote* range. We post at `best_bid + 1c`, so `bid_low <= our_price` is true **by construction** — every quote filled instantly. |
| passive edge **t=+23.3** | Pseudo-replication. ~1,000 tape prints inside one 15-minute market settle on ONE draw, so they are one observation counted a thousand times; t inflates ~30×. Clustered per market: **t=+0.38**. (§3d of `docs/KALSHI.md`.) |

The pattern is the point: **every time this desk produced a spectacular
number, the cause was our own measurement, not the market.** Four times now.
Before believing any result, ask what the independent unit of observation is
and whether the code is using it.

The +944% one survived the first fix (+793% after requiring real trade prints)
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

# maker edge from the tape, no queue model assumed (docs/KALSHI.md 3d)
python3 scripts/kalshi_passive_edge.py

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

## 2b. Duty cycle — this environment cannot run the desk continuously

Measured 2026-09-13, markets open: **10% uptime.** The engine ran 22:06-22:10,
the container was reclaimed, and nothing traded until the hourly check-in
restarted it at 23:06 — a 56-minute dark gap and zero settled fills in an open
market hour.

The container is reclaimed on **session** inactivity, not process activity.
Backgrounding the engine and ending the turn therefore kills it within minutes;
`nohup`/`setsid` do not help. Two partial mitigations, both in place:

* the hourly Routine restarts the supervisor (recovers from the reclaim), and
* it then runs the engine in the **foreground** for ~9 minutes, which keeps the
  container alive for that window. Verified: 8.5 min of continuous trading, tape
  +3,652 prints. Sub-hourly Routines are rejected (1 hour is the floor), so
  ~15-20% is the ceiling here.

**Anything that needs a real duty cycle must run somewhere persistent** — a VPS,
a laptop that stays awake, any always-on host — with `scripts/kalshi_paper_loop.sh`
under a process supervisor. Nothing about the desk code needs changing; it is
purely where it runs. Scale every fills-per-week projection by the duty cycle
rather than implying continuous operation.

## 2c. Two engines run at once — writes must be idempotent

The duty-cycle mitigation in 2b has a side effect: the supervisor keeps an
engine alive *and* the hourly check-in runs one in the foreground. Both read
the same `state/kalshi_paper_state.json`, so both settle the same positions.

`append_trade_log` used to append unconditionally, so each engine wrote its
own row. Three duplicates landed between 2026-09-13T23:06Z and
2026-09-14T13:06Z (+$7.49, +$11.88, −$25.91) before it was caught — small,
but it inflates `n`, double-counts P&L, and would have grown hourly.

It is now idempotent: a settled position is keyed on
`(adapter, ticker, side, count, fill_price)` and a repeat of that key is
dropped. The same book cannot hold two identical positions in one 15-minute
window, so the key is safe. The three bad rows were removed from the log.

**Any new writer to `state/` must assume a concurrent engine.** Appending
without a dedupe key will silently corrupt the record, and the corruption
looks like ordinary fills.

### The same race also corrupts `state["cash"]` — and it halted the desk

Fixing the log was not enough. `PaperState` loads the whole state file **once
at startup** and `save()` rewrites it wholesale. That is atomic per write
(`os.replace`) but **last-writer-wins across processes**: each engine's
settlements overwrite the other's. By 2026-09-14T17:00Z the maker book read

| source | maker P&L | trustworthy? |
| :--- | ---: | :--- |
| `state/kalshi_paper_trades.csv` (idempotent, append-only) | **+$5.22** | yes |
| `state["cash"]` (racy, last-writer-wins) | −$33.74 | no |

a **$38.96** divergence. That mattered because `_entries_allowed` captured its
00:00 UTC day baseline *from the drifted cash*: the book really started the day
at $557.51 and was down $52.29 (**−9.38%**, stop fires at −$55.75), but against
the recorded $518.55 baseline the same loss read **−10.08%** and tripped the
10% stop. The maker leg was silently blocked for hours. I misread the silence
at 16:05Z as the quote-churn finding in `docs/KALSHI.md` §3c; it was not.

**The daily stop is now derived from the trade log**, which holds both engines'
settlements exactly once, so it is deterministic and recomputable from history.
`TestDailyStopFromTradeLog` pins the incident numbers.

`state["cash"]` is still racy. It only feeds Kelly sizing, where drifting low
means sizing small — the safe direction — so it is filed as open problem 10
rather than patched in a hurry. **Do not build a new risk control on
`state["cash"]`.** Derive it from the trade log.

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
2. ~~**Replace the `3 * q.count` guess.**~~ **ANSWERED — don't do this yet**
   (2026-09-14, `scripts/kalshi_passive_edge.py`, `docs/KALSHI.md` §3d). The
   queue model is not the binding constraint. Every tape print had a real
   passive counterparty that actually filled, so the tape *is* the population
   of achievable maker fills at *perfect* queue priority — no assumption
   needed. Measured there, across 59 settled markets, the maker edge is
   **+1.86c/contract at t=1.98**, below the |t|≥3 gate, and the
   favorite/underdog split is flat (−0.02 / +1.20, |t|<0.4). Tuning the `3×`
   cannot rescue a strategy whose best-case fills have no measurable edge.
   **The replacement task is to accumulate tape**: the unconditional claim
   needs ~135 markets (~17h of uninterrupted 24h coverage on both metals) to
   reach t=3. The per-metal and per-side splits need 750–3,700 and are not
   worth targeting.
   ⚠️ Counted per *print* the same data says t=+23.3 for the underdog side.
   That is pseudo-replication — ~1,000 prints per 15-minute market share one
   settlement, inflating t ~30×. The script prints both columns and labels the
   fake one. Do not quote it.
3. **Fix the daily-stop *boundary*.** (The *baseline* half of this is fixed —
   the stop now derives from the trade log instead of racy cash, §2c.) What
   remains: the day still rolls at 00:00 UTC, mid-session for metals, so a
   drawdown spanning midnight re-arms the stop at full size halfway through
   (this happened on 2026-09-11/12 and cost roughly a second full stop-loss).
   Use a rolling window or a session baseline. Risk control, not a tunable.
4. **Investigate the NO side.** n=96 for -$4.09 lifetime vs YES n=39 for
   +$57.10, and NO is 71% of fills. Either the fair value is biased on that
   side or the desk is systematically selling trend continuation. Diagnose
   before changing anything — do NOT just disable NO, that is curve-fitting to
   one regime.
5. **The maker leg is churning quotes — diagnose before anything else.**
   `python3 scripts/kalshi_quote_churn.py` reports a 5s median quote lifetime
   with 100% of episodes ending in a cancel (docs/KALSHI.md 3c). `maker_fade`
   (2c) re-triggers on nearly every tick. Until a quote actually rests, the
   maker P&L describes the cancel logic rather than the strategy, and n=149 of
   it is already on the books. Treat any fade change as a fresh pre-registered
   run, not a tweak to the existing sample.
6. **Measure the cancel race.** The engine cancels on a 2c adverse move and
   always wins in shadow. Log intended-cancel vs next-print timestamps to
   estimate how many of those cancels a real venue would have refused.
7. **Get the demo key** (one manual web signup, `docs/KALSHI.md` §7) and run
   real resting orders. This is the only thing that actually settles the
   queue-priority question, and it still risks no real money.
8. **Copper.** `KXCOPPER15M` is plumbed but not traded (`--metals gold,silver`).
   Thinner book; check it is not just wider spreads.
10. **Reconcile `state["cash"]` with the trade log.** It drifts because two
   engines hold the state in memory and overwrite each other on save (§2c).
   Cheapest correct fix: recompute `cash[book] = bankroll0 + sum(pnl)` from the
   log on `PaperState.__init__`, so every 110-minute restart re-converges and
   drift is bounded by one session. Only Kelly sizing reads it today, and it
   errs small, so this is not urgent — but it is the last place the two
   concurrent engines can still disagree, and the daily stop already got
   burned by it once.

9. Taker leg is dead unless a genuinely faster signal appears. Do not tune
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
