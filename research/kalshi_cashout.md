# Cash-out replay — sell if the 15m favorite dies (2026-09-12)

Replay only. **Not on the live loop.** `PaperEngine.tick` still
buy-and-holds to settlement. Re-run:

```bash
python -m quantfirm.kalshi.cli cashout-replay --no-poly
python -m quantfirm.kalshi.cli cashout-replay
```

## Rule

Same as `desk_book` entry, ignoring the 3-minute wait:

* held YES is dead when `yes_ask < price_min` (default 60¢)
* held NO is dead when `1 - yes_bid < price_min`
* crypto + Poly (optional): Poly's ≥55¢ favorite is missing or the
  other side. Missing Poly does **not** sell. Gold ignores Poly.
* sell the bid of the held side (YES bid, or NO bid = `1 - yes_ask`),
  taker fee on entry and exit
* 15s min-hold so we do not sell the same second we bought the spread

Tape: 30 settled **live** fills from `state/kalshi_paper_loop.log`
(2026-09-12 03:07Z–14:46Z). 5 commodity + 25 BTC/ETH. Hold-to-settle
on that set is **+$9.64**.

## Headline: 60¢ cash-out is worse than holding

Favorites flicker through 55–59¢ and still pay. Selling the first
break below 60¢ cuts those winners for a few cents of bid, and the
losers it "saves" still exit around 50–57¢ — not 0.

| variant | n | n_exit | saved losers | cut winners | hold | exit | delta | ahead |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| hold-to-settle | 30 | 0 | 0 | 0 | **+$9.64** | +$9.64 | 0 | — |
| Kalshi <60¢, 15s hold | 30 | 22 | 8 | **14** | +$9.64 | **−$39.80** | **−$49.43** | no |
| same, crypto only | 25 | 20 | 7 | 13 | +$12.85 | −$29.40 | **−$42.25** | no |
| Kalshi + Poly disagree | 30 | 24 | 8 | 16 | +$9.64 | −$40.07 | **−$49.71** | no |

Poly on top only adds two extra sells (BTC YES still ~99¢ while Poly
was a coin-flip). That is noise, not a reason to wire Poly into exits.

## What the 60¢ rule did on today's losers vs winners

It **does** catch the names that died and settled 0. Selling ~54–57¢
beats a full −$10:

| fill (UTC) | name | side | hold | exit @ | delta |
|---|---|---|---:|---|---:|
| 03:19 | gold | NO | −$8.87 | −$6.22 @ 27¢ | +$2.65 |
| 12:16 | BTC | NO | −$10.28 | −$4.69 @ 39¢ | +$5.59 |
| 12:35 | BTC | YES | −$9.55 | −$2.02 @ 54¢ | +$7.53 |
| 12:47 | BTC | YES | −$9.69 | −$1.41 @ 57¢ | +$8.28 |
| 13:15 | ETH | NO | −$8.77 | −$1.19 @ 56¢ | +$7.58 |
| 13:46 | ETH | NO | −$10.65 | −$1.27 @ 57¢ | +$9.38 |
| 13:48 | BTC | NO | −$10.18 | −$1.51 @ 56¢ | +$8.67 |
| 14:33 | ETH | YES | −$10.18 | −$1.83 @ 54¢ | +$8.35 |

It also **sells 14 winners** the first time they dip under 60¢. Those
books came back and paid. Typical haircut is −$6 to −$11 (sold ~55¢
instead of collecting $1). ETH 12:16 NO is the worst: hold **+$6.13**,
cash-out **−$5.15** (sold 31¢). WTI 03:25 YES: hold +$1.97, sold 55¢
for **−$7.86**.

Eight saves of ~$3–9 cannot pay fourteen cuts of ~$6–11.

## Tighter thresholds (still off the live loop)

Same tape, Kalshi-only, no Poly:

| price_min | min-hold | n_exit | saved | cut | exit pnl | delta vs hold |
|---:|---:|---:|---:|---:|---:|---:|
| 60¢ | 15s | 22 | 8 | 14 | −$39.80 | −$49.43 |
| 60¢ | 180s | 19 | 8 | 11 | −$19.78 | −$29.42 |
| 50¢ | 15s | 19 | 8 | 11 | −$40.83 | −$50.47 |
| 40¢ | 180s | 12 | 8 | 4 | +$5.81 | −$3.83 |
| **30¢** | 15s | 10 | 8 | **2** | +$16.20 | **+$6.56** |

30¢ is the only green cell. It still sold two winners that went to
27–28¢ and then paid:

* ETH 12:47 YES @ 66¢ → sold 27¢ **−$5.88** vs hold **+$4.54** (−$10.42)
* BTC 13:02 NO @ 64¢ → sold 28¢ **−$5.47** vs hold **+$4.81** (−$10.28)

One Saturday, n=30, two ~$10 recoveries from the 20s. That is not a
promotion bar. Do not put 30¢ cash-out on the live agent either.

## Live loop

Unchanged: `desk_book --live`, hold to settlement. Replay is
`quantfirm/kalshi/cashout.py` + `cashout-replay`. No import from
`paper.py`.
