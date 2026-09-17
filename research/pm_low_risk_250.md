# Prediction-market edges at $250 — research, not live (2026-09-17)

Owner asked for **various ways to make money consistently, relatively low
risk, on prediction markets with $250**.

Nothing here sends orders. The 15-minute book stays behind
`state/KILL_SWITCH_KALSHI`. The incentive book stays SHADOW. The $257
Kalshi deposit is not deployed.

```bash
python3 scripts/pm_low_risk_250.py
python3 scripts/pm_low_risk_250.py --live
python3 -m unittest tests.test_pm_low_risk_250
```

## Verdict

**The intersection of consistent + relatively low-risk + material P&L at
$250 is empty.** Families that are actually low-risk pay dollars a year.
Families that can print dollars a week are either variance machines or
races this stack already lost.

"Relatively low risk" here means: ruin is $125 (firm rule), per-trade
loss cap is 2% = $5, we do not buy longshots, we do not size a 15-minute
binary at 15–35% of the book, and we do not annualise a 24-minute pool.

| # | family | consistent? | low risk? | material at $250? | status |
|---|---|---|---|---|---|
| 0 | Kalshi idle APY (3.25%) | yes | **yes** | **$8.13/year** | already the floor; $250 is the eligibility cutoff |
| 1 | LIP subsidy (resting bids, not predictions) | unknown | small directional | $0–a few $/day if we qualify; board avg **$1.55/day** | SHADOW; do not arm |
| 2 | Whelan favorite-longshot, **maker**, slow markets ≥50¢ | no (sd 33%) | no | +2.6%/contract needs ~439 independent fills | paper candidate, **not 15m** |
| 3 | Executable dutch / combinatorial arb | rare | yes *when it exists* | Kalshi: still ~0 after fees; Poly: $40M already extracted by bots | keep the scanner |
| 4 | Sports CLV vs a sharp book | if +CLV persists | no | 1–3¢ net on a 1¢ NFL book, when it exists | blocked on a feed |
| 5 | Near-resolution "the news is in" | when the number is out | lowest *trading* risk | cents per event | opportunistic, not a loop |
| 6 | Volume-incentive churn | no | no | cap $0.005/ct; taker fee on a full-book 50¢ clip is $8.75 vs $2.50 cap | **no** |
| 7 | Weather ensemble / macro nowcast | no | no | weather tape −$12 / 12 days | scan only |
| 8 | 15m metals/crypto **taker** | no | no | lag-fill red; latency race | **do not revive** |
| 9 | Cross-venue "arb" (Kalshi vs Poly) | no | no | settlement differs; legging risk | **no** |

The only thing we should *do* with $250 on prediction markets right now
is: keep the idle APY, keep the LIP shadow running until its own gate
says `GO` or `NO`, and paper at most one slow-market maker sleeve. Do
not turn the 15-minute taker back on to "make the $250 work."

## Why $250 is the constraint, not the venue

A Kalshi contract pays $1 or $0. Quadratic taker fee is
`ceil(0.07·C·P·(1−P))` to the cent (`quantfirm/kalshi/fair.py`). Maker
fee is 0 on most series and 25% of taker on the ones that charge it.
The Help Center APY on cash **and** mark-to-market positions is **3.25%**
as of 2026-03-17, variable, **only if the balance stays ≥ $250**.

At the firm's 2% cap the clips look like this (recomputed, not inherited):

| price | lots | stake | fee | lose | win | breakeven hit | fee / stake |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10¢ | 47 | $4.70 | $0.30 | $5.00 | $42.00 | 10.6% | 6.4% |
| 50¢ | 9 | $4.50 | $0.16 | $4.66 | $4.34 | 51.8% | 3.6% |
| 75¢ | 6 | $4.50 | $0.08 | $4.58 | $1.42 | 76.3% | 1.8% |
| 90¢ | 5 | $4.50 | $0.04 | $4.54 | $0.46 | 90.8% | 0.9% |
| 97¢ | 5 | $4.85 | $0.02 | $4.87 | $0.13 | 97.4% | 0.4% |

Read the 90¢ row: a win is **46 cents**. A miss is **$4.54**. You need
the favorite to be *more* than 90.8% after the cent-ceil, and you cannot
compound 1% per 15-minute window — that pitch (`1.01^96`) sizes a 95¢
lock at ~19% of the book (`research/kalshi_one_pct_week.md`).

One contract at 50¢ pays a **2¢** fee on a 50¢ stake (4%) because of the
cent ceiling. The published $1.75 / 100 lots is a large-ticket number.
Retail clips live in the rounding.

## 0. Idle APY — the only honest low-risk return

Kalshi pays interest on cash and on the mark-to-market of open
positions. Help Center (2026-03-17): **3.25%**, daily accrual on net
portfolio value at 00:00 ET, paid the following month, US Klear-funded
accounts, **balance ≥ $250**, SSN above $10/year.

On $250 that is **$8.13/year = $0.022/day**.

This is not a strategy. It is the hurdle. Any trading book that dips
the account under $250 also shuts the APY off. Parking the $257 deposit
and not trading is currently the highest Sharpe thing the prediction
desk can do.

## 1. Liquidity Incentive Program — subsidy, not prediction

Already researched: `research/kalshi_incentives.md`, runbook
`docs/KALSHI_INCENTIVE.md`. Status: SHADOW, not armed.

Mechanism: Kalshi pays a fixed pool to people who rest two-sided size.
Snapshots once per second. **A snapshot pays nobody unless both sides
hold Target Size** (1,000 contracts on 4,366 / 4,421 programs tonight).
Reference price is a depth walk, not the touch, so a 1–2¢ bid can still
take full credit. Unfilled bids lose nothing. A 1¢ fill risks 1¢.

Live board this pass (2026-09-17T22:11Z, public API, no creds):

| | |
|---|---|
| active liquidity programs | 4,421 |
| volume programs | 1 |
| pool accruing next 24h | **$107,999** |
| target size p50 / min / max | 1,000 / 300 / 2,500 |
| reward p50 | $100 |
| duration p50 | 159h |
| $250 covers target at 1¢+1¢ | 4,421 programs ($20 locked per 1,000-lot book) |
| $250 covers target at 50¢+50¢ | **0** |

The 2026-09-16 accounting identity still bounds the *average*:
**$106,033 / $17,067,304 resting = 0.62%/day → $1.55 on $250**. This
pass did **not** re-sum resting capital (that is a full-book crawl).
Do not replace $1.55 with a selection-biased number.

What $250 can actually do:

- Rest 1,000 YES and 1,000 NO at 1¢: **$20** collateral, qualify on
  cheap books. Fill risk is 1¢ × filled lots. Worst case one-sided
  fills, repeatedly, across every market, is about −$125 on $250 — the
  ruin line. Realistic failure is **earning nothing**, because:
  - rewards under $1.00 per program are unpaid
  - fresh books (the cheap ones) decay **119×** into a 1¢-wide crowded
    market within a week
  - Target Size on both sides is the gate small capital trips
- Rest at 50¢: $1,000 to hit target. We cannot.

Program risk outranks return: Kalshi self-certifies under CFTC 40.6(a)
and can patch a rule that pays 23¢ off the touch on their timetable.
Conduct: resting non-competitive size to harvest a subsidy is allowed
under the published rules and is not what the program is for. Rewards
can be withheld. Tax is 1099 income.

**Keep the shadow.** The gate in `scripts/kalshi_incentive_paper.py`
already decides `GO` / `NO`. Do not arm on a number from this memo.

Polymarket US has a copy of the same idea (score = `discount^ticks ×
size`, Target Size, $1 minimum). Live NFL moneyline **live** pool on
2026-09-16 was $32,000 with **Target Size 150,000**. $250 does not
register. Skip.

## 2. Favorite-longshot as a *maker* on slow markets

This is the only documented statistical edge on Kalshi that is not a
subsidy.

Bürgi, Deng & Whelan, *Makers and Takers* (Jan 2026, 313k contracts,
2021 → Apr 2025):

- Prices are informative and get better into close.
- Favorite-longshot bias: **<10¢ contracts lose >60%**; ≥50¢ earn a
  small positive return.
- Average Kalshi contract: **about −20%**.
- Makers: **−9.64%** average; Takers: **−31.46%**.
- Makers on **≥50¢: +2.6%** per contract. Standard deviation **33%**.
- Sample **ends when Kalshi turned on maker fees**. The +2.6% is
  pre-fee. Sports, politics, entertainment, and econ all showed the
  same shape.

Why it is not "consistent low risk" at $250:

- 33% sd on 2.6% mean → you need **~439 independent fills** before
  P(sample mean > 0) ≈ 95% (`n_for_mean_ci` in the script). $250
  cannot run 439 concurrent binaries. A 2% clip that wins 46 cents
  (90¢ row) does not pay for a 2% miss.
- Samuelson / Pratt-Zeckhauser: stacking independent +EV gambles you
  would reject one-by-one is not a free lunch for CRRA utility. Whelan
  flags this explicitly as a reason the bias survives.
- **Taker** FLB on 15-minute books is what we already ran. `longshot`
  lag-fill: −$247 / 99% DD. `rich_fav` t-stats stay <1.5.
  `favorite_blind` cleared a one-off tournament gate and then decayed.
  See `research/kalshi_yolo.md`, `research/kalshi_tournament.md`,
  `research/kalshi_iterate.md`.
- Maker on **15-minute** metals: the +800% / +944% prints are fill-model
  artifacts. A market-mid quoter with no model earned *more*.
  `docs/HANDOFF.md` §0. Do not quote them. Do not revive that maker.

What a slow-market paper sleeve would look like, if we ever run one:

- Universe: sports moneylines, nested econ *after the print*,
  politics with days (not minutes) to close. **Not** 15m crypto/metals.
- Role: **maker only**. Rest on the favorite side at ≥55¢, join or
  improve the touch, never cross, never buy <30¢.
- Size: 2% of equity, hard 8% cap, ≤5 concurrent names, no correlated
  same-game parlay / combo (`KXMVECROSSCATEGORY` is a graveyard of
  1¢ asks).
- Hold to resolution. No 60¢ cash-out — that rule cut 14 winners to
  save 8 losers (`research/kalshi_cashout.md`).
- Gate: two weeks of *actual* resting fills (not tape-inferred),
  maker-fee-inclusive, null control (rest at mid with no FLB filter)
  must *not* match the sleeve. Same Knight lesson as the 15m maker.

This is RESEARCH, not PAPER. Do not wire it into `desk_book`.

## 3. Dutch books and combinatorial arb

**Intra-market (YES+NO under $1, or exclusive legs summing under $1).**

Kalshi YES/NO are reciprocal. A taker who lifts YES at the ask and NO
at `1 − bid` pays **1 + spread**. On 190,032 quoted 15m minutes the
cheapest both-leg take was **$1.001**. Zero crossed books
(`research/kalshi_playbook.md`).

Exclusive ladders: BTC hourly range sum(ask) ~$2–4 because the wings
are 1¢ ghost size with no volume. NYC high: one minute at $0.99, six
leg fees ~6¢ eat it. Nested CPI/GDP: **0** locked `bid(inner) > ask(outer)`
after fees (`research/kalshi_div_nowcast.md`).

Tonight's Pope book summed to 30¢ across seven named cardinals. That is
**not** a dutch: the set is not exhaustive (there is an "other"), and
the missing mass is the trade. Goldman-CEO six-leg sum(ask) 0.99 is
the same 6¢-fee trap. Keep `quantfirm/kalshi/ladder.py`; only trade a
`tradeable` exclusive dutch with count ≥ 1. Do not paper a scanner
that fires on mid-sums.

**Polymarket combinatorial (Saguillo et al., AFT 2025 / arXiv 2508.03474).**

Apr 2024 – Apr 2025, on-chain: ~**$39.6M** extracted. Intra-market
rebalancing plus a few dependent election pairs. Top wallet
**$2.01M / 4,049 txs**. Top 10 ~$8.2M. Politics (US election)
dominated; sports were almost absent. Fees were ~0 on global Poly in
that sample; they are not 0 on Polymarket US now. Non-atomic: one leg
can fill. This is a latency-and-inventory race with seven-figure
wallets. $250 is a round-off error on their clip size.

## 4. Sports closing-line value

NFL moneylines tonight are 1¢ wide (PHI 47/48, CHI 52/53, LAR 54/55)
with a few thousand contracts of volume — usable *if* a sharp book
is 3¢+ away after Kalshi's fee (~1.7¢ at 50¢, ~1.1¢ at 80¢).

The edge, when it exists, is: Kalshi's sports book is more retail than
Pinnacle / PS3838. Devig the sharp two-way, subtract fee, require
≥2¢ net, rest a maker on the cheap side. That is a real family in
sports betting. It is **not** low risk: one 9-lot 50¢ miss is a $4.66
day, and NFL weeks cluster.

Blocked on: we do not have a licensed, causal sharp-book feed in this
repo. Do not scrape a sportsbook. Do not paper CLV against last week's
close (lookahead). If a feed shows up, register the family *before*
the first backtest.

## 5. Near-resolution, news-is-in

After CPI prints 0.40%, every nested `T0.3` is YES and `T0.4` is NO.
After a game ends, the moneyline is 99¢. After NWS posts the Central
Park high, five of six bands are 1¢.

This is the lowest-risk *trade* on the venue: you are not predicting,
you are picking up a contract the book has not finished repricing.
Capacity is tiny (often 1-lot asks), the race is measured in seconds,
and a 99¢ buy that misses pays −$4.87 at our clip. Last-minute 15m
"locks" are this idea applied to a market that is *not* resolved —
they lose (`research/kalshi_one_pct_week.md`: lag n=3, hit 0%).

Use: a human or an agent, after a scheduled print, checks whether the
book has moved. Not a 24/7 loop. Not 15m.

## 6. Volume incentive — do not farm

One active volume program tonight, $500 pool, ~5 days left, **$96** of
that pool sits in the next 24h. Eligible volume is CLOB trades between
3¢ and 97¢. Cap **$0.005 per contract**.

Spend the whole $250 once at 50¢: 500 lots, max reward **$2.50**,
taker fee **$8.75**. Churning for volume is negative EV unless you are
already making for another reason and the rebate is free. Affiliates,
contracted MMs, IB/FCM customers, and non-US users are excluded.
Wash-adjacent by construction. **No.**

## 7. Information trading (weather, nowcasts, "we know more")

Tried. `research/kalshi_div_nowcast.md`.

- Open-Meteo 80-member ensemble → NYC/CHI/BOS daily-high bands, 12
  city-days: modal hit 2/12 = chance, **−$12.29**. Station-vs-grid
  basis (Central Park ≠ model cell) is the trap, not a slow book.
- Cleveland Sep CPI 0.37% vs Kalshi `T0.4` at 58–61¢ looked like a
  NO. That is a **print-week** trade with 18 lots on the ask, not a
  clip. Do not hold it over a weekend.
- Atlanta GDPNow 4.4% vs `T4.0` at 14–19¢ is the loudest number and
  the most likely GDPNow-vs-consensus trap. RMSE 1.17 pp. Do not paper.

Information edges on prediction markets are real for people who have
them (domain specialists, faster data). They are not a $250 systematic
book, and they are not low risk: one wrong CPI is the week.

## 8. 15-minute taker — do not revive

This is the desk we already built. Honest record:

- Oracle taker: Score = 0 under `docs/FIRM.md` §2. DSR 0.27, PBO 0.40,
  walk-forward −$250. Edge lives inside a 2–5s race REST loses
  (`research/kalshi_review.md`).
- `one_pct` last-minute 90–97¢: lag 7d **−$3.11** n=3 hit 0%; touch
  **−$79** (the race). BTC 54 fills −$55 (`research/kalshi_one_pct_week.md`).
- `yolo_lock` 18% of book: two weeks doubled, train wiped, W36 −$183.
  `nuke_lock` 35%: W36 **−$962**. Not a plan (`research/kalshi_yolo.md`).
- `desk_book` wait-3 / ≥75¢: a 2-week local peak on a 147-point search,
  weekend ETH red at every bar (`research/kalshi_bar.md`). Live canary
  is halted.
- Pair-arb, dump-fade, 97¢ fade, BTC→ETH lag: all red or empty on the
  harvest (`research/kalshi_playbook.md`).

Maker on the same 15m tape is a *live* experiment whose shadow fill
model grants itself queue priority. 13% haircut on winning fills
zeroed the edge last time we measured (`docs/KALSHI.md` §3b). Re-run
the audit; do not quote a number from that file.

Tonight the 18:15Z BTC 15m window did 104k volume at a 1¢ spread. That
is a liquid casino, not an empty room. Empty rooms were the LIP trap.

## 9. Cross-venue Kalshi vs Polymarket

Same headline event, different contract. BTC 15m: Kalshi is last CF
print vs strike; Polymarket is Chainlink TWAP over the window. A
spike-then-dump can pay Up on one and NO on the other
(`research/kalshi_poly.md`). Copying Poly's price onto a Kalshi order
is a different bet.

Even when settlement *is* the same (Fed, some politics), you have:
legging, ACH vs USDC, Polymarket US vs global geo, fee on both legs,
and "the question text is slightly different." Blogs that call this
risk-free are selling a bot. Hold-to-maturity 2% on $250 is **$5**
tied up for months. Trading the spread to "increase IRR" is stat-arb
with the usual left tail.

US-legal note: Kalshi is the CFTC DCM this firm already has money on.
Polymarket US is a separate exchange (48 states + DC). Global
Polymarket is not a US book. Do not route around that.

## What "consistent" would actually require

A 90¢ favorite at 2% size pays $0.46 when it wins. To make $5/day you
need ~11 clean wins and **zero** misses, every day, after fees. One
miss wipes ten wins. That is not a 15-minute problem you can grind
with more windows; it is the payoff of a binary.

Whelan's maker +2.6% at 33% sd becomes "pretty sure" only after
hundreds of independent fills. Sports can supply independent events.
15-minute gold and silver in a trend are **one** event. We already
watched that tail: three windows, both metals, −$176 in 30 minutes.

Idle APY is the only line on this page whose monthly P&L you can
forecast to the dollar.

## Ranked next actions (still not live)

1. **Do nothing with the $257 except leave it on Kalshi.** Collect 3.25%.
   This is the low-risk consistent return. It is small. It is real.
2. **Leave the LIP shadow up.** Reconcile estimated vs credited. Arm
   only if `scripts/kalshi_incentive_paper.py` returns `GO`, and then
   only the canary (`--capital 40 --markets 2`), never $257 × 8.
3. **Do not revive 15m taker, 15m last-second locks, yolo sizing,
   volume farming, weather paper, or Poly/Kalshi "arb."** Dead table
   below.
4. **Optional PAPER (new family, registered before a tick):** slow-market
   FLB *maker* on sports moneylines / post-print econ, ≥55¢, 2% size,
   hold to resolve, maker-fee-in, null-mid control. Promotion bar is
   the firm's: two weeks of real fills, null weaker than the sleeve,
   DSR/PBO later. Expect this to fail. Run it anyway so we stop
   relitigating Whelan by quoting the PDF.
5. **Keep the dutch scanner.** Trade only `tradeable` exclusive books
   with depth ≥1 on every leg after fees. Tonight: none.

## Do not re-litigate

| family | kill | one-line reason |
|---|---|---|
| 15m oracle taker | latency | uncontested fills lose; contested fills are the race REST loses |
| 15m `one_pct` / last-90s 90–97¢ | winner's curse | lag n≈0; touch is red once crypto is in |
| 15m candle maker P&L | fill model | null mid-quoter beats it; 13% win-haircut zeros it |
| YES+NO taker pair under $1 | microstructure | taker sum = 1+spread; 0/190k minutes |
| Longshot taker 8–22¢ | Whelan + our tape | −60% in the paper; −$247 / 99% DD here |
| `1.01^96` compounding | arithmetic | 95¢ pays 5¢; 1% of $250 is 19% of the book |
| Volume-incentive churn | fee > cap | $8.75 taker vs $2.50 cap on a $250 50¢ clip |
| Weather ensemble clip | measured | 12 city-days −$12; park vs grid |
| GDPNow fade | trap | RMSE 1.17 pp; consensus, not a lock |
| Cross-venue 15m copy | different contract | TWAP ≠ last print |
| Exclusive mid-sum < 1 | ghosts | 1¢ wings with no bid; fees on 6–188 legs |
| Yolo 15–35% of book | ruin | W36 −$962 on `nuke_lock` |

A family leaves this table only with **new evidence of the kind named
in the kill**, presented to research — not by re-reading Whelan or a
blog that still thinks YES+NO can be lifted for 97¢.

## Sources (this pass)

- Live Kalshi public API, 2026-09-17T22:11Z: incentive programs,
  `KXBTC15M` / `KXETH15M` / `KXGOLD15M` windows, NFL moneylines, CPI
  / GDP / claims, Pope event book.
- Bürgi, Deng, Whelan 2026, *Makers and Takers*
  (https://www.karlwhelan.com/Papers/Kalshi.pdf).
- Saguillo, Ghafouri, Kiffer, Suarez-Tangil 2025, *Unravelling the
  Probabilistic Forest* (arXiv 2508.03474).
- Kalshi Help: LIP, Volume Incentive, APY 3.25% (2026-03-17), fee
  schedule (quadratic 0.07 / maker 0.0175 on designated series).
- This repo: `research/kalshi_*.md`, `docs/KALSHI.md`,
  `docs/KALSHI_INCENTIVE.md`, `docs/HANDOFF.md`.
