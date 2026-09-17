# Kalshi incentive farming — aged qualifying-depth, still paper (2026-09-17)

**SHADOW. Not armed. No LIP order has ever been sent.** The 2026-09-16
memo below is the autopsy of the first four wrong numbers. This section is
a new pass over live PRs, the live account, and a recomputed board.

```bash
python3 scripts/kalshi_incentive_stress.py --per-bucket 40 --capital 51.4
python3 scripts/kalshi_incentive_scan.py --sample 500 --capital 257 --min-age-hours 12 --min-hours-left 48
python3 scripts/kalshi_incentive_quote.py --capital 40 --markets 2 --min-age-hours 12   # dry run
python3 scripts/kalshi_incentive_paper.py --capital 257 --slots 5 --min-age-hours 12 --state /tmp/scratch.json
```

## Verdict (2026-09-17)

| | |
|---|---|
| **Do we arm?** | **No.** Gate is `INSUFFICIENT` on a new 48h clock. Nobody has seen a credited LIP reward. |
| **Account** | **$260.5449**, 0 resting orders, 0 positions. The $257 ACH is still cash. Fills on the account are 15m-desk gold/WTI/etc from Sep 16, not this book. |
| **Collector** | **Stalled.** Last main tick 16:31Z. GitHub dropped every `*/20` slot after that. Most historical ticks were manual `workflow_dispatch`. |
| **Old paper book** | $57.39 accrued over 24.3h, last pick `KXCLAUDE-CLAUDE6-27SEP30` at **1.5h old**. Measuring freshness. Clock void. |
| **Board pot, next 24h** | **$112,500** across 4,328 live LIP programs (was $106,033 on Sep 16). Almost all `df=0.50`, target 1,000. |
| **Volume incentives** | One live program, **$96/day** board-wide. Eligible prints are 3–97¢, cap $0.005/contract. Hard no at this size. |
| **Aged median** | $1.33/day per $51.40 slot on programs ≥12h (stress, 110 books). Five slots at the median is **~$6.65/day** and is still a snapshot. |
| **Aged decay** | Brand-new $21.29/day per slot → 12–48h $2.30 → >7d $0.71. **30x**. Cheap-≤4¢ share goes from 10% to **0%** after 2h. |
| **Canary dry-run** | Would rest **$40** on `KXYTVIEWSHIGH-DRA26OCT-14.0M` and `KXYTVIEWSW-MOR26SEP20-5.75M` (45–50h old, unit 8–10¢). Tape: 0 prints at our bid. Estimate ~$6/day on $40. **Estimate, not a credit.** |

A scan that prints "$52/day on $257" by taking the best 10 of 500 is the same
cherry-pick the 2026-09-16 memo already killed. The number that is allowed
to decide is the paper book's trailing 24h after `selection_since`, and it
does not exist yet.

## What the recent PRs actually did

| PR | what it was | what survived |
|---|---|---|
| #84 | scan / stress / paper | mechanism is real; every headline number was wrong |
| #87 | `orders()` 404; canary sized $40/2 | an armed book would have failed closed and silent; first pass is still the canary |
| #88 | `*/20` cron, interval cap, 48h-left filter | collector still dies when GitHub skips; paper was picking 18-minute-old programs |
| #89 (open) | own kill switch | folded in: `KILL_SWITCH_INCENTIVE`. Metals stay halted. |
| #90 (open) | `age_h_at_open` died after one tick | folded in: carried across ticks |

## What changed in the book

1. **Qualifying-depth score.** Help article + UI gray-dot: only orders that
   help reach Target Size are scored. Median qualifying/full score in this
   sample: **0.45**. The old scan counted the whole book and overstated
   competition. A quote at the T/5 reference still always qualifies.
2. **`--min-age-hours 12`.** New slots skip the empty room. A scratch paper
   tick opened five programs aged **18.9–44.7h** (mean 34.4h), not 0.3h.
3. **`selection_since`.** The 48h gate restarts so a GO cannot fire on a
   mix of freshness-book and aged-book ticks. Lifetime accrual is not rewritten.
4. **Shared module** `quantfirm/kalshi/incentive.py` so the four scripts
   cannot drift.

The 2025 CFTC backup filing set Reference Price to the touch. The 2026 help
article contradicts that on purpose ("a small order at the top does not set
it"). Production follows the help article. If Kalshi still uses the filing,
a 2¢ bid 23¢ under the touch earns ~0 — that is a reason the first money
is a canary, not a reason to skip paper.

## Account, this session, read-only

- Balance **$260.5449** (`249.9449` on exchange 0, `10.6000` on exchange 2).
- Deposits: $250 ACH + $257 ACH. Do not treat the $3.54 gap vs $257 as LIP P&L.
- 0 resting orders, 0 open positions, 0 LIP fills.
- Gate: `--live` false, `KALSHI_LIVE` unset, `INCENTIVE_LIVE` absent,
  credentials present, `KILL_SWITCH_INCENTIVE` absent → **DRY RUN**.

## Can $257 lose money?

Unchanged in structure: capital rests as bids. A fill at our reference
risks that price per contract. YES+NO both filling is a pair that settles
at $1. Worst case on $257 is about **-$125**.

What did change: the 2026-09-16 "13 prints, zero hits" is not the current
tape. In this session's cheap-reference stress sample, **8 of 12** prints
would have hit. The two canary names themselves had **zero** hits at our
bid. Fill risk is market-specific; do not inherit the old zero.

## What would make a GO

The same table as below, but the clock is `selection_since` under
`aged12_qualifying`, and the first real allocation is still **$40 / 2
markets** to test whether Kalshi pays. Volume programs stay off.

---

# Kalshi incentive farming — scan, not live (2026-09-16)

Owner asked whether agents can farm the Kalshi incentive programs, what the
minimum capital is, and whether $250 can lose money. **Nothing here has been
traded, on paper or live.**

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
