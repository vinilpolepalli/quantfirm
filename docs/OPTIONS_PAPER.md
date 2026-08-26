# OPTIONS_PAPER.md — options paper desk: pre-registered spec + runbook

**Status: PAPER ONLY. Nothing in this program places real orders. The
execution agent must never call `place_option_order` or `place_equity_order`
while operating this desk.**

Window: **2026-08-25 (bootstrap tick) → 2026-09-09**, i.e. ten trading days
2026-08-26 → 2026-09-08 plus the final compile (Labor Day 2026-09-07 is a
holiday). Paper bankroll: **$500**.
Owner mandate (2026-08-25): paper trade options for two weeks with daily and
weekly reports, then decide on a real options desk.

## Why this exists (and what it can't prove)

Two weeks of paper trading cannot validate a strategy — at this cadence it is
a handful of trades, statistically nothing. What it CAN measure, and what the
final report must answer:

1. **Costs** — modeled fill slippage + fees per ticket vs. the research
   estimates (docs: 0.3–6.6% of premium depending on liquidity).
2. **Ops reliability** — did the daily loop run unattended every trading day;
   quote freshness; state integrity; report delivery.
3. **Mechanics** — collateral math, strike availability, quote quality on the
   venue's own data, holiday handling (Labor Day 2026-09-07 falls inside).

The go/no-go for real capital still requires the full gauntlet (FIRM.md §2)
run against historical chains — the paper window is an ops rehearsal, not a
tournament substitute.

## Pre-registered strategy (locked 2026-08-25; changes require a reviewed commit)

The evidence base (see the Options Desk Feasibility memo, 2026-08-25): retail
option BUYING has documented negative expectancy; the credit side on liquid
index products is the only direction with positive net-of-cost evidence;
premium is an index phenomenon (insignificant in 32/35 single names); weekly
cadence underperformed monthly (WPUT vs PUT).

- **Structure:** SPY put credit spread, $1 wide, 1 contract per position.
- **Entry:** short leg nearest −0.18 delta within [−0.25, −0.12], expiry
  28–45 DTE; net mid credit ≥ $0.12; both legs OI ≥ 100; combined leg
  bid-ask width ≤ 80% of net mid; quotes ≤ 30 min old.
- **Exits (checked at the daily tick, first to trip):** buy back at ≤ 50% of
  entry credit; stop at ≥ 2.5× entry credit; time exit at ≤ 21 DTE.
- **Limits:** max 3 open, max 1 new per day, total open max-loss ≤ 60% of
  bankroll. Equity < 75% of bankroll: entries halt. < 50%: flatten all.
- **Fill model:** two-leg fill gives up 60% of the combined half-spread
  (net mid − 0.30 × Σ leg widths on entry; + on exit), plus $0.04 per
  contract per side regulatory fees. Marks at net mid.

All logic lives in `quantfirm/options/paper.py`. The agent has **zero**
discretion over trades: it fetches quotes, runs the tick, ships the outputs.

## Daily runbook (execution agent, weekdays ~15:45 ET)

Work on branch `claude/quantfirm-options-trading-y0yq67`:

```
git fetch origin claude/quantfirm-options-trading-y0yq67
git checkout -B claude/quantfirm-options-trading-y0yq67 origin/claude/quantfirm-options-trading-y0yq67
```

1. **Underlying:** `get_equity_quotes(["SPY"])` → spot `S`, note quote time.
2. **Expiry:** `get_option_chains("SPY")` → of the expirations with DTE in
   [28, 45] (compute DTE from today's ET date), use the ONE closest to 35 DTE
   — plus the expiries of any open positions.
3. **Strikes needed:** integer strikes from `floor(S × 0.94) − 1` to
   `ceil(S × 0.975)` for each candidate expiry (covers the delta band plus the
   $1-lower long legs), **plus every leg of open positions** in
   `state/options_paper_state.json`.
4. **Instrument IDs:** check the cache `state/options_registry.json`
   (`{"SPY|<expiry>|P|<strike>": option_id}`); fetch only missing ones via
   `get_option_instruments(chain_symbol="SPY", expiration_dates=<expiry>,
   strike_price="<strike>.0000", type="put")`. Update the cache file.
5. **Quotes:** `get_option_quotes` for all ids (batch ≤ 20 per call).
6. **Write** `state/options_quotes/<date>.json`:

   ```json
   {"asof": "<now UTC ISO8601>",
    "underlying": {"symbol": "SPY", "last": <S>},
    "contracts": {"<option_id>": {"strike": 736.0, "type": "put",
       "expiry": "2026-09-30", "bid": 2.10, "ask": 2.16,
       "delta": -0.18, "iv": 0.14, "oi": 1234,
       "updated_at": "<quote updated_at>"}, ...}}
   ```

7. **Tick:** `python scripts/options_paper.py tick --quotes <file> --date <date>`.
   The last stdout line is the daily report path.
8. **Dashboard:** `python scripts/gen_options_dashboard.py` — regenerates
   `dashboard/options.html` from the new state. Vercel redeploys it on push.
9. **Fridays:** also run
   `python scripts/options_paper.py report --weekly --date <date>` (the text
   file is committed; it feeds the final verdict).
10. **Commit + push** state, reports, quotes archive, registry and
    `dashboard/options.html` to the branch
    (`git push -u origin claude/quantfirm-options-trading-y0yq67`, retry with
    backoff on network errors). Commit message:
    `options-paper: tick <date>` plus a one-line summary. If no OPEN pull
    request exists for the branch (the original was merged), open a new
    draft PR to `main` titled `options-paper: daily ticks` so the running
    state stays reviewable; a merged PR is never reused.
11. **Email the reports** (owner's standing instruction, 2026-08-26: email
    yes, phone push no): send the daily report text to
    `vinil.polepalli@gmail.com` via Gmail, subject
    `quantfirm options paper — day N (<date>)`; on Fridays also email the
    weekly report, subject `quantfirm options paper — weekly (<date>)`. The
    dashboard is the always-on surface; the email is the daily digest. On
    failure, email what failed, commit whatever state is consistent, and
    record an incident — it shows on the dashboard. Never improvise trades;
    the tick script is the only decision-maker. A market holiday shows up as
    stale quotes — the tick records the incident and skips entries; say so
    in the email and move on.

## Files

| Path | What |
|---|---|
| `quantfirm/options/paper.py` | tick engine — all trading rules |
| `scripts/options_paper.py` | CLI: init / tick / report / status |
| `state/options_paper_state.json` | the paper book (committed each tick) |
| `state/options_quotes/*.json.gz` | daily quote snapshots (doubles as the live IV/spread dataset for future backtests) |
| `state/options_reports/*.txt` | daily/weekly report texts as emailed |
| `state/options_registry.json` | strike → option_id cache (agent-managed) |

## After the window (2026-09-09)

The final report compiles: equity curve, every trade with entry/exit vs mid,
cumulative slippage+fees as % of bankroll, incident log, and an ops verdict
(did the loop run unattended). Decision then returns to the owner with three
options: fund a real desk (needs L3 + capital), extend paper, or stop.
