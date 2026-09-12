# KALSHI 15M METALS DESK — research charter & venue dossier

Status: **PAPER** (shadow vs prod book + demo-env plumbing). No real money.
Built 2026-09-10 on branch `claude/kalshi-commodity-strategy-sr27jr`.

## 1. The instrument

`KXGOLD15M / KXSILVER15M / KXCOPPER15M`: one $1 binary per 15-minute window —
"will the Pyth metals index close this window at or above its open print?"
(`strike_type: greater_or_equal`, tie → YES). Strike = Pyth 1-min candle close
at window open (public immediately); settlement = the 1-min close at window
close; both 2dp-rounded. Settlement sources: Pyth `Metal.Index.GOLD/USD`
(USD/t.oz), `Metal.Index.SILVER/USD`, `Commodities.Index.CU/USD` (USD/lb).

Hours (empirical, from the full print history): windows every :00/:15/:30/:45,
~96/weekday; dark Sat 04:00Z → Sun 22:00Z and Thu 07:00–09:00Z (exchange
maintenance). Series live since 2026-07-31 (gold/silver) and 2026-08-27
(copper). Liquidity (prod, Sep 2026): gold ≈ 190k contracts/window, 1¢
spreads near the money, deci-cent ticks in the wings; silver ≈ 50k; copper ≈ 19k.

Fees (verified per-series): `fee_type quadratic, multiplier 1` → taker
`ceil(0.07·C·P·(1−P))` (≤ 1.75¢/contract at P=0.50), **maker $0, no
settlement fee**. A taker entry held to settlement pays exactly one fee.

## 2. Venue mechanics that matter

* Public market data (markets, orderbook, candlesticks, trades) needs **no
  credentials** on prod AND demo. All prices are decimal STRINGS
  (`*_dollars`/`*_fp`); legacy integer-cent fields are null.
* Order writes: V2 only — `POST /portfolio/events/orders` (`side: bid|ask` in
  YES-price terms, fixed-point strings, `time_in_force` required, no market
  orders — use aggressive limit + IOC). Legacy `/portfolio/orders` → HTTP 410.
* Auth: per-request RSA-PSS(SHA-256) over `ts_ms + METHOD + path` (no query),
  headers `KALSHI-ACCESS-KEY/-SIGNATURE/-TIMESTAMP`.
* Demo env (`demo-api.kalshi.co`) mirrors prod tickers/strikes for metals but
  its books are empty/fake: **demo validates order plumbing only; economics
  are measured against prod public data.**
* Rate limits: token bucket, ~20 reads/s + 10 writes/s at Basic; free
  self-serve upgrade to Advanced via `POST /account/api_usage_level/upgrade`.

> **VERDICT (2026-09-10, post-review): the taker strategy below has no
> demonstrable edge and loses at realistic latency.** Kept here as the
> registered hypothesis and for the live shadow measurement; the honest
> numbers and the adversarial review are in `research/kalshi_backtest.md`
> and `research/kalshi_review.md`. The **maker leg (§3a)** is the only
> surviving candidate and is a live, not backtested, experiment.

## 3. Strategy (pre-registered; quantfirm/kalshi/strategy.py is the spec)

**Oracle repricer (S1)** with flow-fade tagging (S3) and macro gates (S4):
fair value `P = N(ln(S/K)/(σ₁ₘ√τ))` with a causal EWMA 1-min vol ×
hour-of-week diurnal multiplier; S from a real-time settlement proxy
(Swissquote XAU/XAG, measured ~1 bp from the Pyth print; copper has no
keyless realtime feed and is DISABLED for live entries). Enter taker-only
when the executable price diverges from fair by ≥ θ net of fee, inside the
τ/price/spread/liquidity gates; hold to settlement (no exit fee). Sizing:
quarter-Kelly capped at 5% of bankroll/trade; ≤ 2 concurrent positions;
gold+silver same-direction share one slot; −10%/day stop halts entries.

Why it can earn: the strike is public, a ~1 bp settlement proxy exists, much
of the flow is slower/retail, and near expiry small spot moves imply large
fair-value moves. Whelan's 313k-obs Kalshi study: makers/favorites earn,
longshot takers lose >60% — our gates put us on the right side of that.

Why it looked plausible and why it fails: the strike is public and a ~1 bp
proxy exists, but the divergence the model sees is repriced by faster bots
within ~1–5 s, so a REST-latency taker only reliably fills the trades where
the signal was already wrong (winner's curse). See §5.

### 3a. Maker leg (the surviving direction — live experiment)

On these same markets, resting a passive quote inverts the latency problem:
you are filled *by* the impatient taker, so being slow is an asset. The desk
rests a quote on the favorite side (fair ≥ 0.55 → YES; fair ≤ 0.45 → NO) at
fair − 4¢, joining or improving the touch but never crossing; books a fill
only when the public tape trades THROUGH our level or sweeps 3× our size at
it (queue position is unknowable, so the 3× is a guess — see §3b); fades the quote
on a 2¢ adverse fair move; posts nothing in the last 3 minutes (gamma). Maker
fee is $0, so a favorite held to settlement keeps its whole edge. Whelan's
313k-obs Kalshi study (makers in ≥50¢ favorites +2.6%, longshot takers −60%)
is the prior; a candle backtest cannot model queue/adverse-selection, so this
runs live in shadow before any claim.

### 3b. Why the shadow maker P&L is an upper bound

The shadow leg never rests a real order, so it is *granted* queue priority it
would otherwise have to earn. The whole fill decision is one line
(`quantfirm/kalshi/paper.py:297`):

```python
return thru >= q.count or at >= 3 * q.count
```

Four things in that rule are assumptions, not observations:

1. **The `at` branch is a pure guess.** If 3x our size prints *at* our price we
   claim a fill, but the feed never shows how much rests ahead of us at that
   level. Behind 10,000 contracts, 3x our 46 fills nothing. The multiplier was
   chosen because it sounded conservative, not because it was measured.
2. **Cancels are instant and free.** The quote is pulled on a 2c adverse fair
   move (`paper.py:253`), and in shadow that pull always wins. Adverse
   selection *is* losing that race: the informed taker hits you before the
   cancel lands, so the shadow dodges exactly the fills that hurt most.
3. **The order is a ghost.** Resting at `bid + 1c` in the real book takes the
   touch, other makers requote, the spread tightens and the per-fill margin
   compresses. We are measuring a book that never saw us.
4. **The fills are a biased sample.** We are filled when someone wanted the
   other side at that price, i.e. when they had a reason. The windows where the
   quote sits unfilled are disproportionately the ones where we were right.
   This is not a patchable bug; it is invisible in public tape data.

`scripts/kalshi_fill_audit.py` quantifies how little that costs before the edge
is gone. Deleting a fraction of the *winning* fills (keeping every loss) as an
adverse-selection proxy:

```
break-even haircut   13.3% of winning fills may be phantom before edge = 0
  haircut         P&L     hit       t
      0%     151.44   0.698    0.67
     25%     -99.29   0.635   -0.46
     50%    -456.40   0.537   -2.46
```

**13% is a very thin margin** for a model that hands itself free queue
priority. (This read 28% at n=120 on 2026-09-11; one bad hour halved it. Re-run
the audit rather than quoting a number from this file.)

**Correction — correlation does matter, in the tail.** An earlier revision of
this section argued the sample was "close to independent" because same-window
gold/silver legs agree only ~58% of the time and clustering by window did not
lower the t-stat. That unconditional rate is the wrong statistic. On 2026-09-11
23:16-23:46Z three consecutive windows went against us on **both** metals at
once: five straight NO fills, all resolving YES, -$176 peak-to-trough in about
half an hour, taking t from 1.50 to 0.67. Gold and silver decouple in quiet
tape and move as one in a trend, which is exactly when the book is wrong.

Two structural features make that tail expensive:

* **Average loss is ~2x average win** (~$24 vs ~$12), because the quote rests
  on the favorite side. The hit rate therefore has almost no slack: at n=126
  the cushion over break-even was +3.1pp.
* **The fair value assumes driftless GBM.** In a sustained directional move the
  "no continuation" prior is systematically wrong, so the desk sells the
  continuation repeatedly within the same trend rather than once.

**The trend regime repeated, and the daily stop straddles it.** The same thing
happened again on 2026-09-12 01:31-02:01Z: three consecutive windows, seven
losing fills across both books, all NO, all resolving YES — one of them gold NO
at 0.80, i.e. the model was *confident* and wrong. Cumulatively since 2026-09-11
23:00Z the maker book is -$224.50 at hit 0.353, against +$277.51 at hit 0.720
before it. Peak-to-trough is -$261.20.

The per-book daily loss stop (`_entries_allowed`, 10%) worked — maker entries
were blocked at 02:01Z — but its baseline resets at **00:00 UTC, which is
mid-session for metals**. The 23:16-23:46Z and 01:31-02:01Z drawdowns are one
regime event; the stop saw two separate days and re-armed at full size in the
middle of it. A session- or rolling-window baseline would have halted after the
first leg. This is a risk-control gap, not a strategy parameter to tune.

**The NO side has never made money.** Across the whole sample the desk's NO
fills are n=96 for **-$4.09** (hit 0.646); the YES fills are n=39 for +$57.10
(hit 0.744). NO is 71% of all fills. Whatever the headline P&L has been at any
moment, it has not come from the side the desk trades most.

**Blocker cleared (2026-09-12).** The engine now persists the public trade
tape to `state/kalshi_tape_<UTC date>.jsonl` (deduped by `trade_id`, polled
every 15s per market, recorded for every open market rather than only while a
quote rests, so the sample is not conditioned on our own participation).
`_maker_filled` can therefore be replayed offline against a real queue model —
that work is now the top open problem, not a blocked one. See
`docs/HANDOFF.md`. No tape exists until the desk runs a full session.


## 4. Backtest protocol & honesty constraints

Data: full settled-market history + per-market 1-min contract candles
(yes_bid/yes_ask OHLC) from the public API; underlying = GC=F/SI=F/HG=F
1-min bars (Yahoo), re-anchored to the settlement print at every window open
(`S_t = F_t · K/F_open`), so basis error is intra-window drift only (~1-2 bp).

* Strictly causal: vol state sees only past bars; decisions use the candle
  closing at T. **Fill model (`--fill-mode`):** `touch` is the zero-latency
  ceiling (candle opens are carry-forward quotes, so this fills at the stale
  quote — NOT conservative); `lag` is the realistic floor (fills only levels
  that survived the fill minute, at that minute's close, capped at traded
  volume). Reported with a contested/uncontested split; the uncontested
  subset is the certain-fill floor a slow taker actually gets.
* Fees: conservative cent-ceiling per order. Fill-only-at-limit and
  slippage stress variants (`--slippage-extra`).
* Train/test: split fixed BEFORE sweeping at 2026-08-27T00:00Z; parameter
  selection on train only; the chosen config evaluated ONCE on test.
* Known optimism that a 1-min grid cannot remove: sub-minute sniping
  competition is invisible; treat backtest results as an upper bound and
  gate go-live on live SHADOW results (prod-book fills, recorded live).

Findings that shaped the gates (train-split autopsy, gold): entries in the
first ~3 minutes of a window and longshot buys (price < 0.30) are reliably
negative (model-vol error and FLB, respectively); the τ 5–9 min mid-window
band carried the edge in both regimes. August (weeks 33–34) was net negative
at loose gates: the 15M books matured through August — early-sample results
underweight today's liquidity.

## 5. Results

See `research/kalshi_backtest.md` (generated) for the current numbers:
train sweep table, chosen config, single test-split evaluation, stress
variants, and live shadow-session results. Numbers in this file are not
repeated to avoid staleness.

## 6. Running it

```bash
# data refresh (public API, ~30-40 min cold, resume-safe)
python scripts/kalshi_harvest.py --gzip

# venue/feed health, credential check
python -m quantfirm.kalshi.cli status

# backtest / sweep / calibration
python -m quantfirm.kalshi.cli backtest --data data/kalshi --split test
python -m quantfirm.kalshi.cli sweep --data data/kalshi
python -m quantfirm.kalshi.cli calibrate --data data/kalshi

# live paper session (shadow vs prod book; demo orders too if creds present)
python -m quantfirm.kalshi.cli paper --minutes 60 --log-decisions
```

## 7. Demo-env credentials (the one manual step)

The first demo API key cannot be created programmatically (web UI only,
behind WAF + device fingerprinting — automating that is out of bounds).
One-time setup:
1. Sign up at https://demo.kalshi.co/sign-up (mock info is allowed on demo).
2. Deposit mock funds (test card `4000 0566 5566 5556`, any future expiry).
3. Profile settings → API keys → create; download the private key PEM once.
4. `export KALSHI_DEMO_KEY_ID=...` and
   `KALSHI_DEMO_PRIVATE_KEY_PATH=/path/to/key.pem` (or put the PEM in
   `KALSHI_DEMO_PRIVATE_KEY`). `.gitignore` already excludes `*.pem`.
Then `python -m quantfirm.kalshi.cli paper` places real IOC orders on demo
alongside the shadow record. Until then the engine runs shadow-only.

## 8. Risk & promotion

This desk follows the firm ladder: PAPER (now) → CANARY → PRODUCTION only
via referee sign-off (docs/FIRM.md). Go-live additionally requires: ≥ 2 weeks
of live shadow P&L consistent with backtest at matched gates, demo plumbing
green (orders, cancels, settlement accounting), and the Pyth/`pyth_value`
WS latency question answered. Real-money Kalshi needs KYC + ACH funding and
is explicitly out of scope for this branch.
