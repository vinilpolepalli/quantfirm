# Kalshi incentive farming — scan, not live (2026-09-16)

Owner asked whether agents can farm the Kalshi incentive programs, what the
minimum capital is, and whether $250 can lose money. **Nothing here has been
traded, on paper or live.** How LIP sits next to the other $250
prediction-market families is `research/pm_low_risk_250.md`.

```bash
python scripts/kalshi_incentive_scan.py --sample 400 --capital 250
python scripts/kalshi_incentive_stress.py --per-bucket 45
```

## Verdict

**The mechanism is real. The headline numbers were not.** Three separate
errors inflated the first pass, each caught by a later test, and the honest
answer is a wide range that only a shadow run can close.

| claim (first pass) | what killed it |
|---|---|
| "$350/day on $500" | annualised short programs — a $100 pool on a 24-min program is not $6,000/day |
| "56%/day, persists" | the cheap books were programs **started 0.6–1.6h earlier**. Thin because new, not because inefficient |
| "$1,483/day rotating" | invented supply — `KXTEMPMIAH` has **10 programs totalling $1,000**, not 240/day |
| "qualifies everywhere" | ignored the Target Size exclusion: a snapshot pays **nobody** unless both sides hold >= 1,000 contracts |

## The board is a fixed pot

This is the number that bounds everything, and it is the one to trust:

| | |
|---|---|
| reward paid board-wide, next 24h | **$106,033** |
| capital resting on those books | **$17,067,304** |
| board-wide return on resting capital | **0.62%/day** (227%/yr) |
| a passive $250 earning the board average | **$1.55/day** |

You cannot beat that by much, because it is an accounting identity: the pot
is split by score, and score is bought with resting capital. Selection is the
only lever, and it is bounded.

## How the scoring actually works

From the [LIP rules](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program):

1. Snapshot once per second, at a random moment in the second.
2. **Excluded unless both sides hold >= Target Size** (1,000 contracts in 98%
   of programs). Excluded snapshots pay nobody — this is the constraint that
   small capital keeps tripping over.
3. **Reference Price** = walk down from the best bid until cumulative resting
   size reaches Target Size / 5 (200 contracts).
4. At or better than Reference Price scores `size x 1.0`; `k` ticks below
   scores `size x DiscountFactor**k` (0.50 in 97% of programs).
5. Payout = your score / all scores, per side, each side worth half.

Point 3 is genuinely exploitable. The Reference Price is set by *cumulative
depth*, not by the touch, so a thin top over a fat 1c layer puts the Reference
Price at 1c. Real book, `KX30YMORTW-26SEP17-T6.92`, trading 0.25 / 0.35:

```
YES bids: 0.25 x100 | 0.02 x780 | 0.01 x1000   <- the 200-contract walk lands at 0.02
NO  bids: 0.65 x100 | 0.02 x200 | 0.01 x1175
```

A 2c bid there is 23c below the touch, will never fill, and still collects
full credit at $0.04/contract-pair instead of ~$0.99.

## But the cheap books are new, not inefficient

Competition vs. how long the program has been running (173 books priced):

| program age | median unit cost | median yes-score | yield per $100 |
|---|---|---|---|
| **0–2h (brand new)** | **$0.43** | **726** | **$40.11/day** |
| 2–12h | $0.91 | 1,042 | $12.11/day |
| 12–48h | $0.87 | 1,305 | $1.47/day |
| 2–7d | $0.97 | 1,100 | $1.39/day |
| >7d | $0.99 | 3,796 | $0.34/day |

**119x decay from fresh to settled.** The books converge on a 1c-wide market
with heavy competition. A one-hour persistence test showed "no decay" only
because both snapshots caught the same fresh programs — that test was worthless
and is the reason this memo exists in its current form.

## Can $250 lose money?

Principal risk is genuinely small, for a specific and checkable reason.

- The capital sits as **resting bids**, not positions. Unfilled bids lose nothing.
- A fill at 1c risks **1c per contract**. Across 8 cheap markets the tape
  carried 13 prints and **zero** that would have hit a bid at our price.
- YES and NO are complements. If **both** legs fill you hold a pair that
  settles at exactly $1 — a large win, not a loss.
- Ruin requires only the losing leg to fill, repeatedly, in every market.

| adverse fill rate | loss on $250 |
|---|---|
| 10% | $12.50 |
| 50% | $62.50 |
| 100% (worst case) | $125.00 |

**The realistic failure is earning ~nothing, not losing the $250.**

## What $250 actually earns

| scenario | $/day | $/month |
|---|---|---|
| passive, board average | $1.55 | ~$47 |
| realistic selection, halved for competition | ~$70 | ~$2,100 |

That spread is two orders of magnitude and **this memo cannot close it.** The
upper end cherry-picks the best 2 of 597 markets with hindsight and assumes the
book does not react to us. The lower end assumes no skill at all. Only a
shadow run that reconciles *credited* rewards against *estimated* ones will say
which is true — and credited-vs-estimated is the only scorecard that counts,
because estimates update live but are not final until a program ends.

## Risks that outrank the return

| risk | note |
|---|---|
| **Program risk** | Kalshi self-certifies under CFTC Rule 40.6(a) and can end or modify any program instantly. A rule paying for orders 23c off the touch gets patched on their timetable. |
| **Capacity** | Board pays $106k/day against $17M resting. There is no version of this where $250 compounds meaningfully. |
| **Conduct** | Coverage of the filings reads them as carrying a wash-trading warning. Resting non-competitive size purely to harvest a subsidy is defensible under the published rules but is not what the program is for; rewards can be withheld. |
| **Tax** | 1099 income, not capital gains. SSN verification above IRS thresholds. |
| **Payment lag** | Rewards are credited only after a program ends, in a later processing run. |

## The go/no-go gate

Encoded in `scripts/kalshi_incentive_paper.py` as arithmetic on the accrual
log, not left to an agent's judgement — the firm's rule is that code decides
and agents report. `--exit-on-go` returns 10 so a cron can branch on it.

| verdict | condition | means |
|---|---|---|
| `STALLED` | no tick in 3h | collector is down; nothing is being measured |
| `INSUFFICIENT` | < 48h of data | early ticks over-read badly — at 2 minutes this book implied $767/day |
| `FALLING` | trailing 24h < 0.7x trailing 48h | still decaying; the current number is not the number |
| **`GO`** | **trailing 24h >= $5.00/day, stable** | **2%/day on $250. Fund a small real test** |
| `MARGINAL` | $1.55–$5.00/day | above the board average but under the cost of the plumbing |
| `NO` | <= $1.55/day | what a passive book earns anyway |

$1.55/day is the board-wide average return on resting capital ($106,033/day of
reward against $17,067,304 resting). Earning it is earning nothing special.

The rate is measured on a **trailing 24h window**, never since inception, and
a window with more than half its span missing returns nothing rather than a
flattering partial. Observed so far: $767/day at 2 minutes, $113/day at 1.3h,
$124/day at 1.5h. It is still falling and the gate will not read it until 48h.

**What even a GO does not establish:** that Kalshi pays. Accrual here is an
estimate from the public book; rewards are credited only after a program ends.
A GO justifies a small real allocation to test *payment*, not the full $250.

## Gate

Shadow first: `scripts/kalshi_incentive_paper.py` logs what it would have
quoted and what it would have scored, once an hour, with no credentials and no
orders. Two weeks of that, reconciled against the real rewards page, decides
whether the number is $1.55/day or $70/day. Nothing goes live before then.
