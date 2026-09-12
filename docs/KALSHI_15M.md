# Kalshi 15-minute commodities desk — this pass

Status: **LIVE canary 24/7**, $250. `desk_book` on five commodities + BTC + ETH.

## Setup

Public market data needs **no credentials**. Real orders need a Kalshi
API key plus an explicit live switch. Keys never go in git (`.gitignore`
already covers `.env*` and `*.pem`).

### 1. Clone and install

```bash
git clone https://github.com/vinilpolepalli/quantfirm.git && cd quantfirm
pip install -r requirements.txt
python -m unittest tests.test_kalshi -q
```

### 2. Kalshi account and API key

1. Create / sign in at [kalshi.com](https://kalshi.com) (prod) or
   [demo.kalshi.co](https://demo.kalshi.co) (fake money, order plumbing only).
2. Complete KYC and fund the account if you want **prod** orders.
3. Profile → **API keys** → create. Download the private key PEM **once**.
4. Copy the example env file and fill it in:

```bash
cp .env.kalshi.example .env.kalshi
```

```
# Paper/shadow: leave everything unset. Public books are enough.

# Demo (fake money, real IOC path):
# KALSHI_DEMO_KEY_ID=your-demo-key-id
# KALSHI_DEMO_PRIVATE_KEY_PATH=/path/to/demo.pem

# Prod (real money). Live orders also need KALSHI_LIVE=1 and no
# state/KILL_SWITCH_KALSHI file.
# KALSHI_PROD_KEY_ID=your-prod-key-id
# KALSHI_PROD_PRIVATE_KEY_PATH=/path/to/prod.pem
# KALSHI_LIVE=0
```

The PEM can also be the file body in `KALSHI_PROD_PRIVATE_KEY` (newlines
or `\n` both work). Never print it. Never commit it.

Check the venue without sending orders:

```bash
python -m quantfirm.kalshi.cli status
```

`prod: ... creds=YES` means the key signed. `balance:` is your Kalshi cash.
`creds=no` is fine for paper.

### 3. Paper first (no live orders)

```bash
python -m quantfirm.kalshi.cli paper --minutes 60 --no-demo --no-maker \
  --strategy desk_book --bankroll 250 --log-decisions
```

Or the 24/7 supervisor, still paper if `KALSHI_LIVE` is unset:

```bash
./scripts/kalshi_paper_loop.sh
```

Default book: gold, silver, copper, WTI, natgas, BTC, ETH. Strategy:
`desk_book` (commodities 8% ≥60¢ until close; BTC and ETH 4% of the book
**each**, ~$9–10). Maker off. Kill switch: `touch state/KILL_SWITCH_KALSHI`.

Heartbeat / heal (does not start a second agent if the supervisor is up):

```bash
python scripts/kalshi_desk_checkin.py
python -m quantfirm.kalshi.cli heartbeat
python -m quantfirm.kalshi.cli open-count
```

Optional data harvest (public API):

```bash
python scripts/kalshi_harvest.py --gzip
```

### 4. Live canary (real money)

All of these must be true or the engine stays paper:

1. `KALSHI_PROD_KEY_ID` + PEM in the process env (or `.env.kalshi`)
2. `KALSHI_LIVE=1` in `.env.kalshi` or the environment
3. `python -m quantfirm.kalshi.cli agent ... --live` (the supervisor adds
   `--live` when `KALSHI_LIVE=1`)
4. No file at `state/KILL_SWITCH_KALSHI`

Then start **one** supervisor:

```bash
# .env.kalshi has KALSHI_LIVE=1
nohup bash scripts/kalshi_paper_loop.sh >> state/kalshi_paper_loop.log 2>&1 &
```

Confirm: heartbeat shows `"live": true` and the agent argv has
`--strategy desk_book --live`. Stop with
`touch state/KILL_SWITCH_KALSHI` (orders halt; supervisor can keep
running) or by stopping the supervisor pid in
`state/kalshi_paper_loop.pid`. Do **not** `pkill -f` the agent string —
that self-matches the heal shell.

### 5. GitHub Actions backstop (optional)

After this desk is on `main`, `.github/workflows/kalshi.yml` ticks four
times an hour. Repo → Settings → Secrets:

| Secret | Purpose |
|---|---|
| `KALSHI_PROD_KEY_ID` | prod API key id |
| `KALSHI_PROD_PRIVATE_KEY` | PEM body (one line / `\n` OK) |
| `KALSHI_LIVE` | set to `1` only if CI may send real orders |

Leave `KALSHI_LIVE` unset on Actions if a persistent host already runs the
24/7 loop — otherwise you get two live agents.

24/7 heal prompts: `docs/KALSHI_ROUTINE.md`. Venue charter / fees:
`docs/KALSHI.md`.

## What changed

The prior desk proved two things and left one open:

1. A REST-latency **taker** that chases stale quotes **loses** (lag-fill
   −15%, uncontested fills are the winner's-curse subset).
2. A candle **maker** backtest that prints huge P&L is an **artifact**
   (null mid-quoter earns more). Do not quote it.
3. A live **maker** shadow book is the only remaining structural idea,
   and even that P&L is an upper bound (free queue priority).

This pass does not retune `theta` to revive (1). It asks whether any
*other* 15-minute commodity strategy survives an honest $250 / lag-fill
tournament, and it wires the live paper engine to the settlement feed.

## Universe (verified 2026-09-12)

| Series | Asset | Settlement | Typical window volume | Live now |
|---|---|---|---|---|
| `KXGOLD15M` | Gold | Pyth `Metal.Index.GOLD/USD` | ~100k | yes |
| `KXSILVER15M` | Silver | Pyth `Metal.Index.SILVER/USD` | ~50k | yes |
| `KXWTI15M` | WTI | Pyth `Commodities.Index.PYTHOIL/USD` | ~45k | yes |
| `KXCOPPER15M` | Copper | Pyth `Commodities.Index.CU/USD` | ~17k | yes |
| `KXNATGAS15M` | Nat gas | Pyth `Commodities.Index.NATGAS/USD` | ~10k | yes |
| `KXPALLADIUM15M` / `KXPLATINUM15M` | — | Pyth metals | — | listed, dark |
| `KXINX15M` / `KXNDQ15M` | SPX / NDX | Google Finance | — | listed, dark |
| `KXBTC15M` | BTC | CF Benchmarks 60s average | ~1.8M | **live, 4%** |
| `KXETH15M` | ETH | CF Benchmarks 60s average | large | **live, 4%** |

Hours: commodity 15M books **close Sat ~04:00Z and reopen Mon ~03:15Z**.
BTC/ETH stay open. Treat the API as truth. Fees unchanged: quadratic
taker `ceil(0.07·C·P·(1−P))`, maker $0.

Default paper book: **gold, silver, copper, WTI, natgas, BTC, ETH**.
Live strategy: **`desk_book`**. Commodities are `rich_fav` — first ≥60¢
favorite (skip coin-flips <60¢ and when the taker fee is ≥15% of the win
or net payout <7¢), from window open **until close**, **8% stake**.
Crypto is half the commodity *rate* but **per name**: **4% of the book
each (~$9–10) / ≥60¢ / until close** so every real-favorite interval can
clip. BTC and ETH are independent, not a split of one 4% budget
(REST last-minute 90¢ locks lost; that is not this trade — 93¢+ still
sit out via fee-eat). Coin-flips still sit.
BTC and ETH can both be on. SOL/DOGE/XRP 15m are open on Kalshi but not
scored — stay off. Maker off. 24/7 supervisor. 8% is ~$20 at risk and
~$2.20 net on an 88¢ win. Crypto 4% is ~$10 at risk. 15–18% (`yolo_*`)
is off this loop. Numbers: `research/kalshi_crypto.md`,
`research/kalshi_iterate.md`, `research/kalshi_yolo.md`.

`spot_lock` and `offhours_lock` stay registered. Off-hours was green
on train (t=1.18) and died on test. `nuke_lock` / `longshot` stay
**off** the paper engine.

A 99¢ last-tick book cannot deliver 1% of bankroll without putting nearly
all of it at risk, so we skip those too.

Correlation slots: gold/silver share a side, WTI/natgas share a side,
copper / BTC / ETH are their own books. 24/7 wiring is in
`docs/KALSHI_ROUTINE.md`.

## Live signal

`GET /trade-api/v2/live_data/events/{event_ticker}` returns a 1-second
timeseries whose last print is in the same units as `floor_strike` /
`expiration_value`. That is the settlement-aligned S. Swissquote XAU/XAG
stays as fallback (~7 USD / 16 bp off the gold strike on 2026-09-12 —
too much basis to prefer it). Pyth Hermes `/v2/updates/price/latest`
now returns 401 without an API key.

The paper engine also persists `GET /markets/trades` to
`state/kalshi_paper_tape.jsonl` so maker fills can be replayed.

## Strategies in the tournament

See `quantfirm/kalshi/strategies.py` (parameters frozen) and
`research/kalshi_tournament.md` (the numbers). Families:

| Name | Hypothesis | Why it might survive REST latency |
|---|---|---|
| `ctrl_*` | Drift / fee-drain controls | If these win, we have no edge |
| `oracle_lag` | Prior-desk stale-quote taker | Should lose (replication) |
| `oracle_flow` | Fade uninformed book flow | Taking an overreaction, not chasing a stale ask |
| `favorite_blind` | Whelan FLB on 15M metals | Structural, no race |
| `rich_fav` / `desk_book` | ≥60¢ commodities until close; BTC and ETH 4% | Same FLB; crypto until close; fee-eat 93¢+ |
| `crypto_fav` | BTC/ETH 4% each (~$10) ≥60¢ until close | Weekend 24/7 sleeve |
| `favorite_confirmed` | FLB + GBM agrees | Same, fewer longshots |
| `late_lock` | Near-certain favorite, last 6 min | Reversal needed is large |
| `open_fade` / `open_follow` | 3-min impulse then fade/follow | Path of S, not book lag |
| `session_favorite` | Favorites in London/NY only | Tighter books, less junk |
| `iv_rich_favorite` | Book IV >> realized → buy favorite | Vol mispricing, not sniping |
| `yolo_book` | Sprint + 88–94¢ FLB + follow, 15% stake | Size-up, not a new signal |
| `longshot` / `nuke_lock` | Lottery / 35% overbet | Registered, **not** papered |

Maker remains a **live** experiment. The candle maker backtest is still
invalid; `maker-control` must stay red.

## How to run

```bash
python scripts/kalshi_harvest.py --gzip          # public API; WTI/natgas too
python -m quantfirm.kalshi.cli status
python -m quantfirm.kalshi.cli diagnostics --data data/kalshi --split train
python -m quantfirm.kalshi.cli tournament --data data/kalshi --bankroll 250
python -m quantfirm.kalshi.cli backtest --data data/kalshi --split test \
    --fill-mode lag --bankroll 250
python -m quantfirm.kalshi.cli paper --minutes 60 --no-demo --no-maker \
    --strategy desk_book --bankroll 250 --log-decisions
./scripts/kalshi_paper_loop.sh          # 24/7 supervisor, 5 commodities + BTC/ETH
python scripts/kalshi_desk_checkin.py   # heal + commit heartbeat
```

24/7 wiring is in `docs/KALSHI_ROUTINE.md`. Promotion bar is unchanged
(`docs/KALSHI.md` §8, `docs/HANDOFF.md` §5). A profitable paper hour is
not a go-live.
