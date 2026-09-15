# Perps research campaign — protocol for designer agents

You are one designer in a swarm. Your job is to give ONE strategy family its
best honest shot under the firm's gauntlet, then report exactly what the
tools printed. The referee (the parent session) runs the joint tournament,
the overfitting tests and the single holdout opening. Nobody promotes their
own work.

## Non-negotiable rules

1. **DEV only.** Never pass `--split holdout` or `--i-am-the-judge`, never
   read data after 2025-07-01 in your own code, never call
   `cli holdout`. The CLI refuses; do not work around it.
2. **Register before you run.** Write your hypothesis, mechanism, external
   evidence and a grid of at most 6 configurations into your family module's
   docstring and `TRIALS` dict BEFORE the first backtest. Every CLI run is
   appended to `research/kalshi_perps/trial_registry.jsonl` and raises the
   deflated-Sharpe bar for everyone. If you tune after seeing results, that
   is a new trial: add it to `TRIALS`, say so in your report. Do not delete
   registry rows.
3. **One file.** Your code lives in `quantfirm/perps/families/<family>.py`
   and your report in `research/kalshi_perps/families/<family>.md`. Do not
   edit any other file in the repo. Do not commit or push.
4. **Causal by construction.** Rolling windows and shifts only; row t may use
   data ≤ t. Aux series are aligned by UTC date: a value stamped day t is
   known at the close of day t at the earliest — shift it by one day before
   using it as a signal for the weight decided at close t (the backtester
   executes at t+1's open, so a same-day value would be look-ahead for
   series published after the close; when in doubt, shift by 1).
5. **Costs are the venue's.** Taker tier 0 (12 bps + 2.5 bps half-spread),
   weekly rebalance check, 3% band, Kalshi funding (≈0) as base, Binance
   funding through Kalshi's deadband as stress, 3.25% on idle collateral.
   Do not change `BacktestConfig` defaults except `rebalance_every` if your
   hypothesis is about cadence (then say so).
6. **Report the numbers the tools printed.** No rounding up, no dropping the
   bad fold. A family that fails is a useful result; write it up the same way.

## What you have

```python
from quantfirm.perps import data as D
panel = D.load_panel(("btc", "eth", "gold", "silver"))      # daily OHLCV, 2015/2016→ (gold/silver 2000→)
panel6 = D.load_panel(("btc", "eth", "gold", "silver", "sol", "xrp"))  # sol from 2021-06, xrp from 2019-02 (gaps)
D.load_aux("dvol_btc")     # Deribit DVOL implied-vol index, daily OHLC, 2021-03-24→ (columns open/high/low/close, in vol points)
D.load_aux("dvol_eth")
D.load_aux("macro")        # vix, dxy, us10y (yield %), tip (ETF close), 2010→ (NaN on non-trading days: ffill)
D.load_aux("premium_btc")  # Binance USDT-perp premium index vs spot, daily OHLC, 2020→ (fraction; 0.0005 = 5 bps)
D.load_aux("premium_eth")
D.load_funding_proxy("btc")   # Binance 8h funding rates, Series, 2020→
D.load_kalshi_funding("btc")  # Kalshi's own, 2026-06→
```
Scratchpad extras (read-only, not in the repo):
`/tmp/claude-0/-home-user-quantfirm/f5ea6dde-167d-56ef-a709-62035093f0dc/scratchpad/hist/`
has Binance 1h bars and 1h premium for BTC/ETH (2020→), Hyperliquid/OKX
funding, and Kalshi 60-minute candles for all 20 perps (June 2026→,
`kalshi_60m_<TICKER>.csv` with bid/ask/price OHLC, volume, OI).

Strategy interface (`quantfirm/perps/strategies.py`):
```python
from ..strategies import register, vol_target, align, asset_vol, cap_weights
from ..data import align, load_aux

@register("my_family")
def my_family(panel, target_vol: float = 0.12, some_param: int = 60, **kw):
    closes = align(panel)                 # wide close frame, ffilled over metals holidays
    sig = ...                             # DataFrame in [-1, 1], same index/columns as closes, causal
    return vol_target(sig, panel, target_vol, **kw)   # equal-risk sizing, ex-ante vol scaling, venue caps

TRIALS = {"my_family": {"params": {"target_vol": 0.12}, "grid": {"some_param": [40, 60, 90]}}}
```
`vol_target` scales a fully-long reference book to `target_vol`, so a weak
signal gives a smaller book, never a levered one. Long-only means clip the
signal at 0 before `vol_target`. Return weights are signed notional /
equity per asset; the backtester holds contracts between weekly checks.

## How to evaluate (run from the repo root)

```bash
python -m quantfirm.perps.cli walkforward --strategy my_family --params '{"target_vol": 0.12}' \
    --grid '{"some_param": [40, 60, 90]}' --note "family=my_family v1"
python -m quantfirm.perps.cli backtest --strategy my_family --split dev --start 2018-01-01 --yearly --stress \
    --params '{"target_vol": 0.12, "some_param": 60}' --note "family=my_family v1"
python -m quantfirm.perps.cli robust --strategy my_family --params '{"target_vol": 0.12, "some_param": 60}' --n-boot 500 --n-null 60
python -m unittest tests.test_perps -q    # the causality test covers every registered strategy — it must stay green
```
The walk-forward selects your grid point in-sample per fold and scores it
out of sample; the concatenated OOS Sharpe (`oos_sharpe_concat`, excess over
the collateral yield) is the number that matters. The benchmark to beat is
`vol_target_hold` at the same vol target: **OOS Sharpe 1.13, OOS CAGR
18.2%, OOS max DD −18.4%, 6/6 folds** (2018→2025-06). The current incumbent,
`trend_long_only`, scores 0.80 / 9.8% / −12.5% / 6/6.

Gates a family must pass to be promoted: beats the benchmark OOS Sharpe;
≥4/6 folds positive; OOS max DD ≤ 25%; zero liquidations; positive total
return under the stress scenario; deflated Sharpe ≥ 0.95 against the whole
registry; CSCV PBO ≤ 0.10 across all registered configurations.

## Report format (`research/kalshi_perps/families/<family>.md`)

1. Hypothesis and mechanism (2–5 sentences) and the external evidence you
   relied on (with URLs or paper names).
2. Data used and how you made it causal.
3. The registered grid, verbatim.
4. Walk-forward table: per fold params / IS SR / OOS SR / OOS return / DD /
   turnover; then oos_sharpe_concat, oos_cagr, oos_max_drawdown, folds
   positive, WFE.
5. Dev-window fixed run with `--yearly --stress`: by-year returns and the six
   stress cells.
6. `robust` output: bootstrap Sharpe p5/p50/p95, perturbation min/median,
   timing-null percentile, regime split, Sharpe-difference vs benchmark
   (`p_a_gt_b`).
7. Verdict in one line: PASS candidates / FAIL with the failed gates.
8. What you would try next and why you did NOT run it (it would be another
   trial).
Keep it under 900 words. Numbers exactly as printed.
