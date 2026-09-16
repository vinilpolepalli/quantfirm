# Kalshi incentive farming — scan, not live (2026-09-16)

Owner asked: can agents farm the Kalshi incentive programs, and what is the
minimum capital. This is the scan. **Nothing here has been traded, on paper
or live.** The numbers are gross subsidy from one afternoon's book snapshot;
they are not P&L and they do not survive contact with competition.

```bash
python scripts/kalshi_incentive_scan.py --sample 400 --capital 1000 --max-unit-cost 0.04
```

## What the board actually pays

Pulled from the public `/incentive_programs` endpoint (no auth):

| | |
|---|---|
| live liquidity programs | **3,734** (3,819 forty minutes later — the board churns fast) |
| live volume programs | 6 |
| total pool sitting on the board | $506k |
| pool that actually **accrues in the next 24h** | **$104k** |
| median pool per market per 24h | $14.29 |
| markets with zero 24h volume | **50%** |
| per-market-per-day cap | $1,000 (open tier); $50k/series/week needs a Market Maker Agreement |
| minimum payout | $1.00 per program, rounded down, else nothing |

Naively annualising short programs says $241k/day. That is **2.3x
overstated** — a $100 pool on a 24-minute program is $6,000/day only if you
can redeploy into another one for the other 23.6 hours. The scanner
time-weights pool accrual against the horizon instead.

## The scoring rule is the whole game

From the [LIP rules](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program):

1. Book snapshot **once per second, at a random moment within the second**.
2. Snapshot is **excluded** unless both sides carry >= Target Size (1,000
   contracts in 98% of programs). Excluded snapshots pay nobody.
3. **Reference Price** = walk down from the best bid until cumulative resting
   size reaches **Target Size / 5** (200 contracts).
4. At or better than the Reference Price scores `size x 1.0`. `k` ticks below
   scores `size x DiscountFactor**k`. DiscountFactor is 0.50 in 97% of
   programs, 0.05 in the rest.
5. Payout = your score / everyone's score, per side, each side worth half.

Point 3 is the exploitable one, and I had it backwards at first. The
`0.5**k` decay looks like it kills parking size at a penny — five ticks back
is worth 3% of the same size at the touch. It does, **but only when a deep
top-of-book layer sets a high Reference Price.** The Reference Price is
defined by *cumulative depth*, not by the touch. So a book with a thin top
and a fat 1c layer puts the Reference Price **at 1c**, and size resting there
earns the full 1.0 multiplier.

Real book, `KX30YMORTW-26SEP17-T6.92`, target 1,000:

```
YES bids: 0.25 x100 | 0.02 x780 | 0.01 x1000     <- 200-contract walk lands at 0.02
NO  bids: 0.65 x100 | 0.02 x200 | 0.01 x1175     <- so ref = 0.02, not 0.25
implied market 0.25 bid / 0.35 ask (10c wide)
```

Bidding 2c for YES here is 23c below the touch, will never be filled, and
still collects **full credit**. Collateral is 2c + 2c = **$0.04 per
contract-pair** instead of the ~$0.99 a real two-sided quote costs.

`KXUSUKCOREINF-26OCT21-USVUK` is the pure case — 3,300 YES at 1c, 2,700 NO at
1c, nothing else on the book. Somebody is already running this.

## Numbers

Sampled 339 live programs (9% of board), priced every book, scored against
the competition already resting.

| segment | share of board | pool/24h (sampled) | collateral for 1,000 lots/side | gross return |
|---|---|---|---|---|
| **ref price <= 2c both sides** | **2%** (~88 board-wide) | $430 (~$4.7k board-wide) | **$20–40/market** | **56%/day**, top name 112%/day |
| unit cost 2–20c | 3% | $571 | $20–200 | high but thinner |
| unit cost > 20c | **97%** | $7,729 | $200–990/market | ~0.5%/day median |

So the board splits into a tiny sliver of near-free money and a large
majority where you are doing real market making for ~0.5%/day gross against
real inventory risk.

### Minimum capital

Driven by the $1 minimum payout and by how much size it takes to matter, not
by any Kalshi account minimum:

| capital | what it buys | gross, current snapshot |
|---|---|---|
| **$500** | top ~5 cheap-ref markets, ~3,300 lots/side each | ~$350/24h |
| **$1,000** | top ~10 | ~$375/24h |
| **~$2,600** | **saturates every penny-farmable market on the board** | ~$1–2k/24h |
| $10k+ | forced into the 97% segment — real quotes, real fills | ~0.5%/day, and now you need a fill model |

**The honest minimum is ~$500, and the honest ceiling is ~$3k.** Past $3k the
cheap-ref segment is full and marginal capital earns the 0.5%/day that the
crowded books pay. This is a small-capital strategy with a hard capacity wall,
not something that scales into the $104k/day board pool.

### Why fill risk is small *in this segment specifically*

Resting a 1c bid on both sides caps the damage. Filled on one side: you paid
1c for something worth 0 or $1, max loss **1c/contract**. Filled on *both*
sides: you own a YES+NO pair for 2c that settles at exactly $1 — a 98c gain.
Bids at 1c and 1c cannot cross (2c < 100c), so there is no self-match.

This is why the segment is worth anything at all, and it is exactly why it
should not last.

## Verdict

**Do not fund this yet.** It scans well and the mechanism is real, but
every number above is one snapshot with no competition modelled, and the
failure mode is the one this desk already has a file about
(`quantfirm/kalshi/maker.py`): a maker backtest that reports a huge number
because the fill assumption is doing the work.

| risk | severity |
|---|---|
| **Program risk** | Kalshi self-certifies under CFTC Rule 40.6(a) and can end or modify any program instantly. A rule paying 100%/day for orders 23c off the touch gets patched. Assume weeks, not quarters. |
| **Competition** | Returns exist because ~88 markets are unfarmed. The segment's total pool is ~$4.7k/day *split among all farmers*. Two more entrants at our size roughly thirds it. |
| **Capacity** | Hard wall around $3k. Not a growth strategy. |
| **Conduct** | Regulatory coverage of the filings reads them as carrying a wash-trading warning. Resting non-competitive size purely to harvest a subsidy is defensible under the published rules but is plainly not what the program is for; rewards can be withheld. |
| **Tax** | Rewards are 1099 income, not capital gains. SSN verification above IRS thresholds. |

## What would make this go-live-able

1. **Shadow it first.** Log the scanner hourly for two weeks; record what the
   cheap-ref set looks like over time and how fast new entrants dilute it.
   Persistence of the segment is the entire thesis and is currently untested.
2. **Reconcile against actual credited rewards**, not estimates. The rewards
   page shows live estimates that only become final after the program ends.
   Estimate-vs-credited is the only honest scorecard.
3. **Then** size it, with a kill switch on the first program-terms change.

## Notes for a live loop

Programs churn continuously and the Reference Price re-derives every second,
so this is a scan-rank-requote loop, not a set-and-forget book. Shape that
fits the existing desks:

- **scanner** — poll `/incentive_programs?status=active`, diff against last
  pass, price new books. Cheap: 2 public requests per market.
- **allocator** — rank by subsidy per dollar of collateral, respect the $1
  floor, cap per-market exposure.
- **quoter** — place/replace resting bids; the only component that needs keys.
- **reconciler** — credited rewards vs. estimate, per program.

The scanner is built (`scripts/kalshi_incentive_scan.py`). The rest is not,
and should not be until step 1 above has two weeks of evidence.
