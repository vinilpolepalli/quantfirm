# Copy Polymarket leaders onto Kalshi (2026-09-22)

**Verdict: paper watcher only. Do not send real orders.** The kill switch
stays. `KALSHI_LIVE` is not a green light for this book.

One public week of copying prior sports winners is positive on paper.
Three contracts are almost the entire net. That is not a bankroll.

No Polymarket key is required. The leaderboard and each wallet's trades
are public (`data-api.polymarket.com`). Do not paste a key into chat.
This code never places a Polymarket order and never places a Kalshi order.

## Headline ($250, snapshot 2026-09-22T16:21Z)

Decision trial: `honest_pnl_equal`. Leaders ranked on sports-moneyline
closes in the 30 days **before** 2026-09-15, then copied only after that
cutoff. Fill is the Kalshi ask (or no-ask) on the first two-sided 1-minute
candle that ends at least 60s later. Taker fee `ceil(0.07 · multiplier ·
C · P · (1−P))`. Sports multiplier is 1, MLB is 0.5. Spread wider than
15¢, or a price outside 2–98¢, is skipped.

| trial | what it is | closes | mtm | settled | t | max DD | fees |
|---|---|---:|---:|---:|---:|---:|---:|
| **honest_pnl_equal** | **decision**, equal weight, $250 | 54 | **+$131.62** | +$133.03 | 1.42 | $55.40 | $15.26 |
| honest_pnl_weighted | same leaders, weight by prior pnl | 48 | +$110.79 | +$111.95 | 1.43 | $47.54 | $12.50 |
| honest_pnl_equal_500 | same as decision, $500 | 68 | +$232.05 | +$234.87 | 1.35 | $112.26 | $30.84 |
| honest_pnl_pricegate | skip if Kalshi is >3¢ worse than their price | 50 | +$148.12 | +$149.53 | 1.51 | $55.24 | $15.34 |
| honest_pnl_equal_adverse | pay the worse extreme of that minute | 53 | +$108.76 | +$110.17 | 1.32 | $56.78 | $15.19 |
| honest_vol_equal | rank by prior sports stake, not pnl | 6 | +$53.87 | +$53.87 | 1.79 | $5.57 | $5.99 |
| fade_pnl_equal | same timing, opposite Kalshi side | 23 | **−$99.96** | −$99.96 | −2.20 | $99.96 | $7.32 |
| biased_week_pnl | this week's pnl leaderboard, same week | 15 | **−$15.77** | −$15.77 | −0.18 | $68.09 | $14.32 |

Ticker P&L sums to the settled figure ($133.03). A rerun a few minutes
earlier printed +$134.65. One baseball game was still open, and the candle
pull is anchored at "now", so the last minute can move. Do not annualize
a 7-day print. +$132 on $250 is not +50% a week forever.

## Where the +$133 came from

23 Kalshi contracts, 15 up and 8 down. Hit rate on the 54 closes is 41%.
The net is three contracts:

| contract | side that paid | pnl |
|---|---|---:|
| `KXMLBGAME-26SEP211835TORBAL-BAL` | Baltimore | +$53.78 |
| `KXMLBGAME-26SEP212145MINSF-SF` | San Francisco | +$48.78 |
| `KXLALIGAGAME-26SEP19OSARVC-RVC` | Rayo Vallecano | +$26.82 |

Those three are $129.38. The other 20 contracts net about +$3.65.
`t = 1.42` does not clear a promotion bar. Leaders also took **both**
sides of Toronto/Baltimore; Baltimore's gain and Toronto's −$16.62 are
in the same game.

The fade of the same signals lost money on the clips that were inside
the 2–98¢ band (fewer fills than the follow, because the other side of a
heavy favorite is often too cheap to trade). That argues against a pure
bookkeeping bug. It does not make three games a strategy.

Copying **this week's** leaderboard through the same week lost $15.77.
The people at the top of https://polymarket.com/leaderboard/overall/all/volume
right now are not the same bet as "people who had already won before the
week started." Volume rank is a different book again (6 closes).

## What was actually copied

Public trades after the cutoff for the selected wallets: 10,912 prints.
About $2.9M notional mapped onto a Kalshi moneyline. Much more did not:

| reason | notional left on the table |
|---|---:|
| no Kalshi twin (wrong date, props, or a game we do not list) | $11.0M |
| not a moneyline (spreads, totals, set bets) | $3.6M |
| no game date (crypto up/down, weather, politics) | $1.5M |
| league prefix we do not map | $0.1M |

5-minute Bitcoin, temperature ladders, and Fed parlays are not Kalshi
15-minute crypto and they are not this sleeve. A 70¢ Polymarket "Up" is
not a Kalshi YES. Same rule as `research/kalshi_poly.md`.

Mapping that does count: Polymarket `sportsMarketType=moneyline` plus a
Kalshi game on the same date whose subtitle matches the team (or Tie for
a draw). "No" on Chelsea is NO on `KXEPLGAME-…-CFC`, not a bet on
Brentford. That Chelsea NO settled in our favor for +$18.69 on the
contract. Sizing is not their size. Each of five leaders gets an equal
sleeve. One name is capped at 35% of the bankroll. Their buys inside a
5-minute bucket become one taker clip at the bucket close plus 60s.

Decision leaders, equal weight, prior sports pnl before 15 Sep (their
Polymarket dollars, not ours): vito3corleone, SPCEXBUYER, 00gringo00,
wr0ngw4yb3tt0r, totoro3miyazaki.

The candidate pool is today's leaderboard (week pnl, week volume, month
pnl, all-time pnl). Anyone who was good in August and then blew up is
missing. That survivorship biases this week up. There is no historical
leaderboard endpoint to fix it. A paid key would not add one.

## Paper watcher

```bash
python3 -m quantfirm.kalshi.copybacktest          # the table above
python3 -m quantfirm.kalshi.copybacktest paper-tick
# or
KALSHI_LIVE=0 ./scripts/kalshi_copy_paper_tick.sh
```

`paper-tick` ranks sports closes over the trailing 30 days, writes
`state/kalshi_copy_paper_state.json`, and sets the cursor to now. It
does not buy positions they already hold. Later ticks copy only new
trades, at the Kalshi touch at that moment, and replay the paper book.
`--live` is refused. The script forces `KALSHI_LIVE=0`.

Armed once at this snapshot: five wallets, cursor set, zero fills,
`state/KILL_SWITCH_KALSHI` present. State stays local (gitignored), same
as the other paper books.

## What would change this

A forward sample with the watcher, not another cut of the same week.
Promote nothing unless that sample is positive after fees with more than
a handful of games, the fade of those same signals does not also make
money, and someone other than this desk signs the promotion. Until then
the $250 and the $500 stay off the venue.
