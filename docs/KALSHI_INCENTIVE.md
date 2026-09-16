# Kalshi incentive book — runbook

**Status: SHADOW. Not armed. No real money has ever been placed.**

Farming Kalshi's Liquidity Incentive Program: rest two-sided quotes in
subsidised markets and collect the subsidy, rather than trying to predict
anything. The owner deposited $257 for this on 2026-09-16; it is not deployed.

If you are a fresh session and the owner says *"start the kalshi incentive
cron agent"* or similar, this file is what they mean. Read all of it before
touching anything — the numbers in here have been wrong four times and the
traps section is why.

## The pieces

| file | what it does | needs credentials |
|---|---|---|
| `scripts/kalshi_incentive_scan.py` | ranks live programs by subsidy per $ of collateral | no |
| `scripts/kalshi_incentive_stress.py` | decay by program age, fill risk from the tape, dilution curve | no |
| `scripts/kalshi_incentive_paper.py` | the SHADOW book — accrues what we *would* have earned, emits the go/no-go verdict | no |
| `scripts/kalshi_incentive_quote.py` | the REAL quoter — dry run unless fully armed | yes, to send |
| `.github/workflows/kalshi_incentive.yml` | hourly: ticks the shadow book, reconciles the real one | via secrets |
| `research/kalshi_incentives.md` | the evidence, the method, and what killed each wrong number | — |

## How the subsidy actually works

From the [LIP rules](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program):

1. Order book snapshot once per second, at a random moment in the second.
2. A snapshot is **excluded unless both sides hold >= Target Size** (1,000
   contracts in ~98% of programs). Excluded snapshots pay **nobody** — this is
   the constraint small capital keeps tripping over.
3. **Reference Price** = walk *down from the best bid* until cumulative resting
   size reaches Target Size / 5 (200 contracts). It is set by cumulative depth,
   **not by the touch** — this is the part everyone gets wrong.
4. At or better than the Reference Price scores `size x 1.0`; `k` ticks below
   scores `size x DiscountFactor**k` (0.5 in ~97% of programs), so three ticks
   back is already 0.125x and five ticks is a rounding error.
5. Payout = your score / everyone's score, per side, each side worth half the
   pool. Minimum $1.00 per program, credited only after the program ends.

Because of (3), a 2c bid sitting 23c below the touch can still earn full credit
— which is the whole opportunity, and also why Kalshi would be within their
rights to kill it.

## Traps. Read these before quoting any number.

Four optimistic figures were produced on 2026-09-16 and **all four were wrong**,
each by roughly an order of magnitude, each caught only by a later test:

| wrong number | what killed it |
|---|---|
| "$350/day on $500" | annualised short programs — a $100 pool over 24 min is not $6,000/day |
| "56%/day, and it persists" | the cheap books were programs started 0.6–1.6h earlier. Thin because **new**, not inefficient. A 1-hour persistence test caught the same fresh programs twice and proved nothing |
| "$1,483/day rotating" | invented supply — `KXTEMPMIAH` is **10 programs totalling $1,000**, not 240/day |
| "qualifies nearly everywhere" | ignored the Target Size exclusion entirely |

Measured decay from a brand-new program to one over a week old is **119x**. A
thin book on a fresh program is an empty room, not an edge.

**The bound to trust** is an accounting identity, not a model: the board pays
**$106,033/day** against **$17,067,304** of capital resting on those books =
**0.62%/day**. A passive $257 earns about **$1.59/day**. Selection is the only
lever and it is bounded. Never present a higher figure as established.

## Can it lose the money?

Principal risk is small and checkable. Capital rests as **bids, not positions**;
an unfilled bid loses nothing and cancelling is free. A fill at 1c risks 1c per
contract. Across the 8 cheapest markets the tape carried 13 prints and **zero**
that would have hit our bid. YES and NO are complements, so if *both* legs fill
you hold a pair settling at exactly $1 — a win. Worst case on $257 is about
**-$125**; the realistic failure is earning nothing.

Fees are not the problem: `0.07 x C x (1-C)` per contract, maker is 25% of
taker, and the `C(1-C)` term collapses at the extremes — the fee at 50c is 25x
the fee at 1c. Fees are charged only on execution. No settlement fee. But
rounding is **per order and rounds UP**, so churning quotes is how you pay real
money for imaginary score. Quote few, large, long-lived orders.

## The go/no-go gate

Computed in `kalshi_incentive_paper.py`, deterministically, from the accrual
log. Code decides; agents report. Do not substitute your own read.

| verdict | condition | action |
|---|---|---|
| `STALLED` | no tick in 3h | collector is down — fix that first, nothing is being measured |
| `INSUFFICIENT` | < 48h of data | wait |
| `FALLING` | trailing 24h < 0.7x trailing 48h | still decaying, wait |
| **`GO`** | **trailing 24h >= $5.00/day, stable** | fund a SMALL real test, not the full $257 |
| `MARGINAL` | $1.55–$5.00/day | leave running; probably not worth the plumbing |
| `NO` | <= $1.55/day | shut it down |

Measured on a **trailing 24h window**, never since inception — early ticks
over-read enormously ($767/day at two minutes).

**Even a `GO` does not establish that Kalshi pays.** Accrual is an estimate from
the public book. Nobody has ever seen a credited reward from this program. That
is exactly what a small real allocation buys, and why the first real money
should be ~$40 across two long-duration markets, not $257 across eight.

## Running it

```bash
# always safe, no credentials, touches nothing
python3 scripts/kalshi_incentive_paper.py --capital 257 --slots 5 --sample 250
python3 scripts/kalshi_incentive_scan.py  --sample 400 --capital 257

# the real quoter — DRY RUN unless every gate below passes
python3 scripts/kalshi_incentive_quote.py --capital 40 --markets 2 --sample 400
```

To arm, **all five** are required, by design:

1. `KALSHI_PROD_KEY_ID` in the environment
2. `KALSHI_PROD_PRIVATE_KEY` (full PEM; one-line with `\n` is fine)
3. `KALSHI_LIVE=1`
4. `state/INCENTIVE_LIVE` exists — arms **this book only**
5. `--live` on the command line

and `state/KILL_SWITCH_KALSHI` must be absent.

`INCENTIVE_LIVE` is separate from `KALSHI_LIVE` on purpose: `KALSHI_LIVE` is
shared with the 15m metals desk, so without a separate flag, turning that desk
back on would silently start quoting $257 here. The flag is tracked, so git
blame shows who armed it.

For the **hourly loop**, credentials belong in GitHub Actions secrets
(`KALSHI_PROD_KEY_ID`, `KALSHI_PROD_PRIVATE_KEY`, `KALSHI_LIVE`) — the loop runs
in Actions, not in a Claude container. `kalshi.yml` already references the same
three names.

To stop everything: `touch state/KILL_SWITCH_KALSHI`, then
`python3 scripts/kalshi_incentive_quote.py --cancel-all --live` to pull resting
quotes.

## Rotation

The board turns over fast — 3,734 → 4,059 active programs in two hours, roughly
200+ new per hour, and every program ends. The quoter therefore **reconciles**
on each pass rather than firing once. It cancels for exactly three reasons:
program ended, our price fell more than `--max-ticks-below` under the current
Reference Price, or the book dropped under Target Size on either side. A quote
still scoring is left alone, because requoting costs a fee that rounds up.

## Risks that outrank the return

- **Program risk.** Kalshi self-certifies under CFTC Rule 40.6(a) and can end or
  modify any program instantly. A rule paying for orders 23c off the touch gets
  patched on their timetable.
- **Capacity.** $106k/day against $17M resting. There is no version where $257
  compounds meaningfully. Hard wall around $3k.
- **Conduct.** Coverage of the filings reads them as carrying a wash-trading
  warning. Resting non-competitive size purely to harvest a subsidy is
  defensible under the published rules but is not what the program is for.
  Rewards can be withheld.
- **Tax.** 1099 income, not capital gains.
