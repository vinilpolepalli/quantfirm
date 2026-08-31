# OPTIONS_PAPER_V2.md — high-risk mandate: spec + runbook

**Status: PAPER ONLY. Nothing in this program places real orders. The execution
agent must never call `place_option_order` / `place_equity_order` / `review_*` /
`cancel_*` / `exercise_*`.**

Window: **2026-09-01 → 2026-09-09**. Paper bankroll: **$500** (carried forward,
$496.84 at switchover). Supersedes `docs/OPTIONS_PAPER.md` (v1, archived).

## Mandate

Owner instruction, 2026-09-01: *"make the options trading thing hella risky."*
The conservative v1 spec is retired. This desk now runs for **maximum variance**,
not for edge.

**Honest expectation, stated up front.** Every sleeve below has *negative*
documented expected value:

| Sleeve behaviour | What the evidence says |
|---|---|
| Short-dated premium selling | Higher cadence made it *worse* — WPUT Sharpe 0.40 vs monthly PUT 0.65 |
| Buying OTM options | Retail option buyers lost $2.1B aggregate (JoF 2023); 0DTE debit positions −$364k/day |
| Single-name premium | Variance risk premium is insignificant in 32 of 35 single stocks (Carr & Wu, RFS 2009) |
| Buying into earnings | −5 to −9% average, −10 to −14% on high-vol prints (Review of Finance 2025) |
| Any of it, retail-sized | Effective spread ~11.6% of premium on sub-$250 tickets |

So the base case is that this book **loses money faster and swings harder** than
v1, and a total loss of the simulated $500 is a realistic outcome. That is the
accepted, deliberate point of the exercise. **Losses are bounded** — no naked
short options are simulated, so the book can reach $0 but never go below it.

## What this measures

The window is 7 sessions and a handful of trades — statistically nothing about
edge. What it *does* produce, and what the final report must answer:
realised execution costs on wide/short-dated/single-name contracts (where the
research says spreads are worst), whether the engine's expiry-settlement and
risk-cap machinery behaves correctly under real assignment scenarios, and an
empirical drawdown path for a maximally-levered version of this strategy family.
It is a stress test of the *machinery and the cost model*, not a hunt for alpha.

## Sleeves (pre-registered; the SLEEVES table in `quantfirm/options/paper.py` is the machine-readable copy)

### FAT — short-dated defined-risk strangles on index ETFs
| Parameter | Value | v1 was |
|---|---|---|
| Underlyings | SPY, QQQ | SPY |
| Sides | **put and call simultaneously** | put only |
| Width | $2 | $1 |
| Short-leg delta | 0.28–0.45, target **0.35** | 0.12–0.25, target 0.18 |
| DTE | **2–9** | 28–45 |
| Min credit | ≥12% of width ($0.24) | $0.12 |
| Min open interest | 250 per leg | 100 |
| Max concurrent | 3 | 3 |
| Profit target | buy back at 25% of credit (75% captured) | 50% |
| Stop | **none — ridden into expiry** | 2.5× credit |
| Time exit | **none** | 21 DTE |

Selling both sides at once means an adverse move in *either* direction hurts, and
with no stop and no time exit each ticket is carried through expiry — maximum
gamma exposure with no ability to react (the tick runs once a day).

### LOTTO — long OTM options on high-beta single names
| Parameter | Value |
|---|---|
| Underlyings | NVDA, TSLA, PLTR, AMD, COIN |
| Direction | sign of the 5-day return (`momentum`), deterministic |
| Delta | 0.15–0.35, target **0.25** (≈75% chance of expiring worthless) |
| DTE | 1–8 |
| Ticket size | ~$45, quantity = floor(ticket / premium), min 1 |
| Min open interest | 250 |
| Max concurrent | 3 |
| Profit target | sell at **+100%** |
| Stop / time exit | **none — ridden to zero** |
| Earnings | names printing inside the contract's life sort **first** |

### Account level
- Max open across sleeves: **8**; max new per tick: **3**
- Total capital at risk: **100% of bankroll** (v1: 60%). Sleeve maxima sum to
  $663, so this cap binds first and the book runs ~100% deployed.
- Drawdown ladder, loosened: entries **halt below $200** (40%), everything is
  **flattened below $100** (20%). v1 was 75%/50%.
- Fill model unchanged and still conservative: `paid = net_mid + 0.30 × Σ(leg
  bid-ask widths)`, plus $0.04/contract/side.

### Legacy positions
The two v1 spreads (SPY Oct-2 743/742 and 744/743, $88 risk each) were migrated
value-for-value into the v2 schema under sleeve `legacy` and are left to wind
down on their own. They are not re-priced or rewritten — `migrate` asserts
equity is unchanged.

## Engine mechanics new in v2

**Signed accounting** — one code path for credit and debit structures:
```
net_mark = Σ over legs of (+1 long / −1 short) × mid × ratio
equity   = cash + Σ (net_mark × 100 × qty)
paid_open      = net_mid + SLIP × legspread_sum      (slippage always hurts)
received_close = net_mid − SLIP × legspread_sum
pnl = (received_close − paid_open) × 100 × qty − fees
```

**Expiry settlement** — absent in v1, load-bearing now that sleeves run 1–9 DTE:
```
intrinsic(call, S) = max(0, S − K);   intrinsic(put, S) = max(0, K − S)
settle_value = Σ sign_leg × intrinsic × ratio
pnl = (settle_value − paid_open) × 100 × qty − fees_open     (no exercise fee at RH)
```
Two paths: a tick **on** expiry day force-closes at live quotes (mirroring
Robinhood's 15:45 ET sellout); anything that expired **unseen** settles from
`settle_prices` in the snapshot. A missing settle price logs an incident and
holds the position rather than guessing.

## Snapshot schema (changed — multi-underlying)

```json
{"asof": "<iso8601 UTC>",
 "underlyings": {
   "SPY":  {"last": 767.07, "momentum": 0.004},
   "NVDA": {"last": 184.2,  "momentum": -0.021, "earnings_in_days": 3}},
 "settle_prices": {"SPY|2026-09-04": 765.12},
 "contracts": {
   "<option_id>": {"underlying": "SPY", "strike": 760.0, "type": "put",
                   "expiry": "2026-09-04", "bid": 1.98, "ask": 2.02,
                   "delta": -0.35, "iv": 0.20, "oi": 5000,
                   "updated_at": "<quote updated_at>"}}}
```
`underlying` on each contract is **required** (multi-symbol chains). `momentum`
is the 5-day return from daily bars. `earnings_in_days` is optional.

## Daily runbook (execution agent, weekdays ~15:45 ET)

Branch `claude/quantfirm-options-trading-y0yq67`.

1. **Underlyings:** `get_equity_quotes` for SPY, QQQ, NVDA, TSLA, PLTR, AMD, COIN
   (one call). For each, `get_equity_historicals` (interval=day, ~7 bars) →
   `momentum` = last close / close 5 bars ago − 1.
2. **Earnings:** `get_earnings_calendar` for the LOTTO names (optional but
   preferred) → `earnings_in_days`.
3. **Expiries:** `get_option_chains` per symbol → pick expiries covering DTE 2–9
   (FAT: SPY, QQQ) and 1–8 (LOTTO names) — usually 1–2 each.
4. **Instruments — fetch a WHOLE EXPIRY IN ONE CALL.** Call
   `get_option_instruments(chain_symbol=SYM, expiration_dates=EXP, type=put|call)`
   **without** `strike_price` and paginate. This is the single biggest efficiency
   win over v1, which burned one call per strike (~30/tick). Cache into
   `state/options_registry.json` keyed `SYM|EXPIRY|P|STRIKE`.
5. **Strike ranges to quote** — *delta-aware, and narrower than intuition
   suggests*. Verified against the live 2026-09-04 SPY chain (4 DTE, IV ~15%):
   strike 750 with spot 767 carries delta **−0.069**, not −0.30. At 2–9 DTE the
   0.28–0.45 band sits within **~1% of spot**, so a "far OTM" range would return
   nothing and the sleeve would silently no-trade.
   - FAT: **one expiry per symbol** (nearest 5 DTE). Puts `S×0.975 … S×1.00`,
     calls `S×1.00 … S×1.025`, at the chain's strike increment (~19 + 19 per
     symbol). SPY and QQQ.
   - LOTTO: strikes within ±12% of spot on the momentum side only.
   - Plus **every leg of every open position**, always.
   Budget: ≈76 (FAT) + ≈30 (LOTTO) + open legs ≈ **115 contracts**, inside the
   120/day ceiling.
6. **Quotes:** `get_option_quotes` in batches ≤30.
7. **Settle prices:** for any open position whose expiry has passed since the last
   tick, add `SYM|EXPIRY → close` from `get_equity_historicals` on that date.
8. **Write** `state/options_quotes/<date>.json` in the schema above.
9. **Tick:** `python3 scripts/options_paper.py tick --quotes <file> --date <date>`
10. **Dashboard:** `python3 scripts/gen_options_dashboard.py`
11. **Fridays:** also `python3 scripts/options_paper.py report --weekly --date <date>`
12. **Commit + push** state, reports, quote archive, registry, dashboard. If no
    OPEN pull request exists for the branch, open a new draft PR titled
    `options-paper: daily ticks`; a merged PR is never reused.
13. **Email** the daily report to `vinil.polepalli@gmail.com`, subject
    `quantfirm options paper — day N (<date>)`; Fridays also the weekly. Email
    only — no phone push (owner instruction 2026-08-26).
14. **Failures:** email what failed, commit whatever state is consistent, record
    the incident. Never improvise a trade; the tick script is the only
    decision-maker. Market holidays surface as stale quotes — the tick logs an
    incident and skips entries.

## Files

| Path | What |
|---|---|
| `quantfirm/options/paper.py` | v2 engine — sleeves, signed accounting, expiry settlement |
| `scripts/options_paper.py` | CLI: init / migrate / tick / report / status |
| `scripts/gen_options_dashboard.py` | renders `dashboard/options.html` |
| `tests/test_options_paper.py` | 12 tests incl. every expiry-settlement path |
| `state/options_paper_state.json` | the paper book (v2 schema) |
| `state/options_quotes/*.json.gz` | daily snapshots — the growing IV/spread dataset |
| `docs/OPTIONS_PAPER.md` | v1 spec, archived for the record |
