# Research agent picks long/short, size, leverage — 2026-09-18

Owner asked whether the incumbent is just guessing, and whether a research
agent should instead deep-research BTC / ETH / commodities and then decide
direction, size, and leverage. **Nothing here was traded. No trial was
registered.**

## Verdict

| version | call |
|---|---|
| Weekly (or daily) writeup → agent longs/shorts and picks leverage | **out** | same object as Alpha Arena; public real-money results lost |
| Research agent finds a *mechanism*, freezes a rule, tournament tests it | **already how the desk works** | that is `CAMPAIGN.md`. The systematic version of “read the dollar and yields, then position gold” is `macro_gold`. It failed. |
| Let the agent set leverage on the fly (3–10x when “the research is strong”) | **out** | 5x BTC was liquidated within 30 days 14% of the time (Alexander–Deng–Zou). Policy cap is 1.5–2.0x. |
| Incumbent (vol target + slow trend gate) is a coin flip | **no** | `coin_flip` Sharpe −1.03. The return *is* a beta bet. The gate is insurance, not a forecast. |

## Why the incumbent is not a weekly guess

A guess is a fresh story each week. The incumbent is one frozen rule:

1. Hold BTC, ETH, gold, silver at equal *risk*, scaled to 12% vol.
2. If the multi-month trend combo is down, that name goes to cash. No shorts.
3. Look once a week. Trade only if a weight drifted ~3%.

The return comes from those four drifting up. That is a directional bet and
the docs say so. What is *not* a guess:

- Vol targeting is risk engineering (Moreira–Muir). It does not claim to
  know next month’s winner.
- The trend gate is a century-long futures prior (Moskowitz–Ooi–Pedersen;
  Hurst–Ooi–Pedersen) used here to cut 2018/2022-shaped holes, not to beat
  buy-and-hold on Sharpe. It doesn’t: 0.80 vs the control’s 1.13.
- The same machinery run as a coin flip loses money. If the “edge” were
  just the sizer, that control would have won.

So: we are not pretending to know Tuesday. We are taking a sized, gated
beta bet because nothing we tested beat that bet after costs.

## Why “deep research, then decide” is the worse guess

A research agent reading the tape, the dollar, CPI, ETF flows, and then
saying “long gold 2x, short ETH 1x this week” has no walk-forward, no
pre-registered grid, and no way to know whether the writeup used
information that was not available at the decision. The model’s training
data *is* the history. That is a look-ahead you cannot audit.

The public version of this object already ran with real money:

- nof1 Alpha Arena S1 (Hyperliquid perps): 4/6 frontier models lost 31–63%
  in 17 days. The winner paid ~6% of capital in fees in two weeks.
- S1 + S1.5 combined: 6 profitable model-tracks out of 32.
- nof1’s founder: handing money to an LLM to trade on its own “doesn’t
  work yet.”
- Replay on Binance perps: ungated LLM agent drawdown 46% vs 3% with a
  deterministic gate (arXiv 2603.10092).
- S1.5 model chat is the genre: “holding MSFT at 10x because AI tailwinds.”
  That is the proposal, already filmed.

A later simulated contest (TradeRank S2, Feb–Mar 2026) had 3 of 13 models
green, all of them *fading* the other models’ consensus, top return +1.88%
in 28 days. That is not an argument for letting our agent pick Kalshi
leverage. It is an argument that the consensus writeup is the thing to fade.

## We already ran the systematic form of this idea

“Research the macro, then long/short metals” is `macro_gold`: DXY, TIP
(real yields), VIX, five variants declared before the first run, including
a long/short score.

- Book OOS Sharpe **0.881** vs control **1.131**.
- Metals sleeve alone: Sharpe **−0.088**, less than the 3.25% collateral
  yield. Trading P&L net of fees ≈ 0.
- Always-long metals: Sharpe 0.779. The gate missed gold’s up years
  (2019/23/24/25) and caught a down year (2021).
- Timing-null percentile 0.583 — no timing skill.

Gold–silver ratio mean reversion: Sharpe **−0.80**. Long/short trend on
the majors: 0.4–0.5, short side did not pay.

So the *rule* version of “research commodities and take a view” already
lost to sitting long at the same risk. Replacing the rule with a weekly
essay does not add a fold. It removes the folds.

## Leverage is not a research output

Kalshi will let a gold long in at ~11×. That is the venue’s number, not a
target. At 50% vol, Monte Carlo: ≤2× keeps 90-day liquidation under ~1%;
3× ≈ 13%; 5× ≈ 40%. Bybit 2020–21: 5× BTC long liquidated within 30 days
14% of the time. The desk’s rungs cap gross at 1.0 / 1.5 / 2.0. An agent
that turns “high conviction” into 5× is picking the liquidation lottery.

At $257 the leverage debate is mostly academic anyway. The 12% vol book
holds a handful of contracts. One BTC is ~$8. You cannot express a 4×
view without making the clip the risk.

## What a research agent is for, on this desk

The useful job, already written in `docs/KALSHI_PERPS.md` §4:

- Propose **one** mechanism with a grid of at most two to six points,
  declared before the first backtest.
- Run it on DEV only, through the CLI, so it hits the trial registry.
- Report the printed numbers, including the bad folds.
- Do not touch `config/perps.json`, `risk.py`, or a kill switch.

The backlog that is still motivated is short: a BTC *funding-cost* overlay
once Kalshi-native history is longer (last-90 holding cost +15.1%/yr as of
2026-09-18); gold carry once metals have months of prints, not seven;
a listing that is not crypto. Another “read the news” family is not on
that list. It would raise the deflated-Sharpe bar for the things that are.

## What we are not doing

- No LLM in the order path.
- No new registered trial from this note.
- No leverage above the existing rungs.
