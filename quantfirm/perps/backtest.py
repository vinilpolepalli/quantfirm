"""Portfolio backtester for Kalshi perps on daily bars.

What it books, per day, in this order:
  1. execute the rebalance decided at YESTERDAY's close at TODAY's open
     (fees = |Δnotional| × cost.per_side; never the signal bar's close)
  2. mark contracts from yesterday's close to today's close
  3. funding on today's notional (sum of the day's intervals; longs pay when
     positive), from the chosen scenario
  4. interest on unencumbered collateral (equity − initial margin in use)
  5. liquidation check on today's intraday extremes: every position marked
     at its worst point at once; if equity ≤ maintenance the book is closed
     at that point minus a penalty. Conservative on purpose.

Positions are held as CONTRACT counts between rebalances, so weights drift
with price and turnover only happens when the target moves more than the
band on a rebalance day. Targets are capped by the venue's maintenance rates
(liquidation distance) and by the risk policy before they are traded.

Assets that list late (the staggered universe)
----------------------------------------------
Kalshi lists 23 perps whose price proxies begin anywhere between 2000 (GC=F)
and 2026 (HYPE), and one of them — XRP — stopped printing on Coinbase for 905
days in the middle. The book therefore runs on a universe whose membership
CHANGES with time:

  * an asset contributes only while ``data.availability`` says it printed a
    native bar within ``cfg.max_stale_days``. Before its first bar, and inside
    a delisting gap, its target is forced to zero, it books no P&L, pays no
    fee and no funding, and it cannot trigger a liquidation — its unit count
    is zero on every one of those days, so every term it appears in is zero;
  * the simulation starts at the first date ``cfg.min_assets`` of them are
    available (default 1) instead of the date the LAST one lists. That is the
    whole point: requiring all of them starts a sixteen-asset backtest in 2023;
  * a position in an asset that stops quoting is CLOSED, once, at its last
    real print, paying the normal per-side cost — never silently dropped. The
    forced exit ignores the rebalance calendar: a delisting does not wait for
    the weekly check;
  * an asset appearing neither creates nor destroys equity. It arrives holding
    zero contracts and can only be entered by a later rebalance, at a real open.

Trading costs are PER ASSET: ``cost.side_cost(asset)`` = fee + max(the flat
modelling half-spread, the half-spread measured on that market). btc/eth/gold/
silver all quote inside the flat 2.5 bps, so they pay exactly what they always
paid; a cross-sectional book that trades LINK is charged LINK's 9.7 bps.

Both changes are inert on a universe that is fully listed over the window and
quotes inside the flat spread — which is exactly the four-asset research
universe, whose published numbers this file must (and does) still reproduce.

ONE behaviour that is NOT inert, and must be read before quoting an old number:
``run(..., start=None)`` used to begin at the date the LAST asset listed; it now
begins at the date ``cfg.min_assets`` assets are available. On btc/eth/gold/
silver that moves the default first bar from 2016-05-18 (eth) to 2000-08-30
(GC=F), i.e. it prepends fifteen years of a metals-only book. Every window with
an explicit ``start`` — which is every published research number the desk quotes,
and everything walk_forward scores on a fold — is unaffected. To reproduce a
start=None four-asset run exactly, pass ``min_assets=4`` (the count of the
universe) or the start date itself. ``avg_n_available`` in the output says how
many names were really in the book, so a prologue like that cannot hide.

Walk-forward here FITS parameters: on each fold the grid point with the best
in-sample Sharpe (data strictly before the fold, minus an embargo) is chosen
and scored on the fold only. A run without a grid is a fixed-parameter fold
report and is labelled as such — the firm has been burned by calling those
'out of sample' before (CHANGELOG 0.1.1).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from ..metrics import cagr, deflated_sharpe, max_drawdown, sharpe
from .data import (HOLDOUT_START, align, availability, daily_funding, load_funding_proxy,
                   load_kalshi_funding)
from .specs import APPROVAL_COST, COLLATERAL_APY, SPECS, CostModel
from .strategies import cap_weights, resolve_band, UNKNOWN_MAINT_RATE

DAYS = 365


@dataclass(frozen=True)
class BacktestConfig:
    cost: CostModel = APPROVAL_COST
    funding: str = "kalshi"          # none | kalshi | proxy | proxy_raw
    interest_apy: float = COLLATERAL_APY
    rebalance_band: float | str = 0.03   # trade when |target − held| > band
    #   0.03 sits below the four-asset 0.05 weight step, so one step trades.
    #   On a wide universe the step shrinks (strategies.resolve_step: 0.05×4/n,
    #   so 0.01 at twenty names) and a fixed 0.03 band means ONE STEP NEVER
    #   TRADES: the book holds whichever two or three names clear 3% and the
    #   other seventeen are never held on any day. Pass "auto" for a band that
    #   scales with the step (0.6 × the step at that universe size), which is
    #   exactly 0.03 at four names and so leaves the narrow path untouched.
    rebalance_every: int = 7         # check the band every N days (weekly, a priori)
    max_gross: float = 1.5
    max_asset: float = 0.75
    min_liq_distance: float = 0.35
    liq_penalty: float = 0.02        # of notional closed by force
    ladder_soft: float | None = None # drawdown from peak that halves sizing (None = off)
    ladder_kill: float | None = None # drawdown that flattens for good (None = off)
    bankroll_usd: float | None = None  # when set, trade WHOLE contracts for this bankroll (granularity)
    # --- staggered universe (see "Assets that list late" in the module docstring)
    min_assets: int | None = None    # start once this many assets are AVAILABLE; None = all of them
    #   None reproduces the pre-breadth rule (begin where every asset has a
    #   price) and therefore every published fixed-window number. A wide
    #   universe wants an explicit small number, otherwise the run begins at
    #   the LAST listing — 2026-02 if hype is in the book. Defaulting this to 1
    #   silently moved a four-asset start=None run from 2016-05 to 2000-08 and
    #   changed every control in the tournament.
    max_stale_days: int = 7          # available = printed a native bar within this many days (metals weekends)


def funding_table(panel: dict[str, pd.DataFrame], index: pd.DatetimeIndex, mode: str) -> pd.DataFrame:
    """Daily funding fraction of notional per asset (positive → longs pay)."""
    cols = {}
    for a in panel:
        if mode == "none":
            s = None
        elif mode == "kalshi":
            s = load_kalshi_funding(a)
        elif mode in ("proxy", "proxy_raw"):
            s = load_funding_proxy(a)
        else:
            raise ValueError(mode)
        cols[a] = daily_funding(s, index, apply_kalshi_rule=(mode != "proxy_raw"),
                                asset_class=SPECS[a].asset_class if a in SPECS else "crypto")
    return pd.DataFrame(cols, index=index).fillna(0.0)


def live_mask(panel: dict[str, pd.DataFrame], assets: list[str], index: pd.DatetimeIndex,
              cfg: BacktestConfig = BacktestConfig()) -> pd.DataFrame:
    """Availability of ``assets`` on ``index`` — the tradability mask the book uses.

    Thin wrapper on ``data.availability`` so the backtester, its tests and any
    caller that wants to see the same universe read one definition.
    """
    a = availability({x: panel[x] for x in assets}, cfg.max_stale_days, index=index)
    return a.reindex(index=index, columns=assets).fillna(False).astype(bool)


def _first_live_row(avail: pd.DataFrame, min_assets: int) -> int:
    """Position of the first row where at least ``min_assets`` assets quote.

    Everything from that row on is kept, gaps included: dropping a thin day out
    of the middle would splice two prices together and book a jump that never
    happened. A day below the threshold simply has fewer names to hold.
    """
    need = max(int(min_assets), 1)          # 0 assets is not a book; 1 is the floor
    ok = np.flatnonzero(avail.to_numpy().sum(axis=1) >= need)
    if not len(ok):
        raise ValueError(f"no date has {need} of {list(avail.columns)} available at once")
    return int(ok[0])


def _prices(frame: pd.DataFrame, idx: pd.DatetimeIndex) -> np.ndarray:
    """Price matrix on ``idx`` with no NaN left in it.

    ``align`` forward-fills, so the only holes are BEFORE an asset's first bar.
    Those rows are back-filled (and a column that never prints inside the window
    is set to 1.0) purely so the arithmetic stays finite: the unit count of an
    unavailable asset is zero on every one of those days, so the number that
    lands here is multiplied by zero and can never reach the equity path.
    """
    return frame.loc[idx].bfill().ffill().fillna(1.0).to_numpy()


def run(panel: dict[str, pd.DataFrame], targets: pd.DataFrame, cfg: BacktestConfig = BacktestConfig(),
        start: str | None = None, end: str | None = None) -> dict:
    """Simulate ``targets`` (signed notional weights decided at each close)."""
    closes = align(panel)
    assets = [a for a in targets.columns if a in closes.columns]
    if not assets:
        raise ValueError("no asset in targets has prices in the panel")
    # membership is a mask, not a price: an asset is in the book only while it
    # actually prints bars (before its listing, and inside a delisting gap, the
    # ffilled price in `closes` is a flat line that must not be traded).
    avail = live_mask(panel, assets, closes.index, cfg)
    # start when `min_assets` of them quote — NOT when the last one lists
    need = len(assets) if cfg.min_assets is None else cfg.min_assets
    idx = closes.index[_first_live_row(avail, need):]
    if start:
        idx = idx[idx >= pd.Timestamp(start, tz="UTC")]
    if end:
        idx = idx[idx < pd.Timestamp(end, tz="UTC")]
    if len(idx) < 3:
        raise ValueError("not enough bars")
    A = avail.loc[idx].to_numpy()
    # `avail` tolerates max_stale_days of silence so a metals holiday does not
    # flatten the book. That tolerance must not extend to OPENING a position: on
    # the first days of xrp's 2021 Coinbase blackout the engine would otherwise
    # buy 42% of equity in a market that printed no bar anywhere, at a
    # forward-filled price, pay both sides of the spread and re-test
    # liquidation against a stale intraday low. `fresh` is a native bar today;
    # exposure may be held or cut without one, never increased.
    # Crypto only. A metals market that does not print on a US holiday is still
    # tradable at the next session and its ffilled bar is a fair mark, so the
    # rule would block a legitimate weekly rebalance; a 24/7 crypto market with
    # no bar has no feed. Applied to metals this moves vol_target_hold from
    # 1.311 to 1.308 for no gain in realism.
    fresh = pd.DataFrame(
        {a: (panel[a]["close"].reindex(idx).notna()
             if SPECS.get(a) is not None and SPECS[a].asset_class == "crypto"
             else pd.Series(True, index=idx))
         for a in assets}, index=idx
    ).reindex(columns=assets).fillna(False).to_numpy()
    C = _prices(closes[assets], idx)
    O = _prices(pd.concat({a: panel[a]["open"] for a in assets}, axis=1).reindex(closes.index).ffill(), idx)
    H = _prices(pd.concat({a: panel[a]["high"] for a in assets}, axis=1).reindex(closes.index).ffill(), idx)
    L = _prices(pd.concat({a: panel[a]["low"] for a in assets}, axis=1).reindex(closes.index).ffill(), idx)
    # a metals holiday: the ffilled bar has open=high=low=close of the last session — no false liquidation
    # an asset that is not quoting carries no target, and the caps then see the
    # book that will actually be held rather than one padded with dead names
    W = cap_weights(targets.reindex(closes.index).ffill().fillna(0.0).loc[idx, assets].where(avail.loc[idx], 0.0),
                    cfg.max_gross, cfg.max_asset, cfg.min_liq_distance).to_numpy()
    F = funding_table({a: panel[a] for a in assets}, idx, cfg.funding).loc[idx, assets].to_numpy()
    maint = np.array([SPECS[a].maint_rate if a in SPECS else UNKNOWN_MAINT_RATE for a in assets])
    im = maint * 1.3
    # units of the PROXY asset per contract — not contract_size, which counts the
    # contract's own underlying (kSHIB is a thousand SHIB; see PerpSpec)
    csize = np.array([SPECS[a].proxy_units_per_contract if a in SPECS else 0.0 for a in assets])
    # per-asset cost per side: fee + max(flat modelling spread, that market's
    # measured half-spread). A book trading LINK at 9.7 bps is not charged BTC's
    # 0.2. When every asset costs the same the scalar form is kept, so a
    # uniform-cost universe is arithmetically identical to the pre-breadth engine.
    band = resolve_band(cfg.rebalance_band, len(assets))
    side = np.array([cfg.cost.side_cost(a) for a in assets])
    flat_side = float(side[0]) if bool(np.all(side == side[0])) else None

    def _fee(d_notional: np.ndarray) -> float:
        return float(d_notional.sum() * flat_side) if flat_side is not None else float(d_notional @ side)

    n, k = C.shape

    equity = np.ones(n)
    units = np.zeros(k)             # contracts in "1 unit = $1 of price" terms: notional = units × price
    held_w = np.zeros((n, k))
    fees = np.zeros(n)
    fund = np.zeros(n)
    intr = np.zeros(n)
    turnover = np.zeros(n)
    liq = np.zeros(n, dtype=bool)
    pnl_asset = np.zeros((n, k))
    pending = None                  # target weights decided at yesterday's close
    peak = 1.0
    killed = False
    killed_pending = False          # a flatten order is never deferred to the weekly check
    fee_frac = np.zeros(n)
    fund_frac = np.zeros(n)
    intr_frac = np.zeros(n)
    E = 1.0
    pending = W[0]                  # the decision at the first close executes at the next open
    for t in range(1, n):
        E_prev = E
        # 0. an asset that stopped quoting leaves the book TODAY, at its last real
        #    print (the ffilled close has not moved since that bar), paying the
        #    normal cost once. A delisting does not wait for the weekly check.
        gone = (~A[t]) & (units != 0)
        if gone.any():
            d_gone = np.where(gone, np.abs(units) * C[t], 0.0)
            f_gone = _fee(d_gone)
            turnover[t] += d_gone.sum() / E
            fees[t] += f_gone
            fee_frac[t] += f_gone / E
            E -= f_gone
            units = np.where(gone, 0.0, units)
        # 1. execute yesterday's decision at today's open
        if pending is not None and (killed_pending or (not killed and (t - 1) % cfg.rebalance_every == 0)):
            scale = 1.0
            if cfg.ladder_soft is not None and E / peak - 1 <= -cfg.ladder_soft:
                scale = 0.5
            # yesterday's decision cannot be executed in a market that is not
            # quoting today, and must never re-open what step 0 just closed
            tgt = np.where(A[t], pending * scale, 0.0)
            cur_w = units * O[t] / E
            # no bar today → hold or reduce, never add
            stale = ~fresh[t]
            if stale.any():
                keep_sign = np.sign(tgt) == np.sign(cur_w)
                capped = np.where(keep_sign, np.sign(tgt) * np.minimum(np.abs(tgt), np.abs(cur_w)), 0.0)
                tgt = np.where(stale & (np.abs(tgt) > np.abs(cur_w)), capped, tgt)
            trade = np.abs(tgt - cur_w) > band
            if trade.any():
                new_units = np.where(trade, tgt * E / O[t], units)
                if cfg.bankroll_usd:
                    # whole contracts: notional per contract = contract_size × price (proxy price is
                    # the asset's USD price, so a BTC contract is 0.0001 × price). units are in
                    # equity-normalised "$1 of price" terms: units × price = notional / equity₀.
                    per_contract = csize * O[t]                      # $ per contract
                    n_c = np.floor(np.abs(tgt) * E * cfg.bankroll_usd / np.where(per_contract > 0, per_contract, np.inf))
                    quant = np.sign(tgt) * n_c * per_contract / (cfg.bankroll_usd * O[t])
                    new_units = np.where(trade, quant, units)
                d_notional = np.abs(new_units - units) * O[t]
                f = _fee(d_notional)
                turnover[t] += d_notional.sum() / E
                fees[t] += f
                fee_frac[t] += f / E
                E -= f
                units = new_units
            pending = None
            killed_pending = False
        # 2. mark to today's close
        pa = units * (C[t] - C[t - 1])
        # 5. liquidation check on intraday extremes (before booking the close)
        adverse = np.where(units > 0, L[t], np.where(units < 0, H[t], C[t]))
        eq_worst = E + (units * (adverse - C[t - 1])).sum()
        mreq_worst = (np.abs(units) * adverse * maint).sum()
        if (units != 0).any() and eq_worst <= mreq_worst:
            liq[t] = True
            notional = (np.abs(units) * adverse).sum()
            E = max(eq_worst - notional * cfg.liq_penalty, 0.0)
            pnl_asset[t] = units * (adverse - C[t - 1])
            units = np.zeros(k)
            pa = np.zeros(k)
        else:
            E += pa.sum()
            pnl_asset[t] = pa
            # 3. funding on today's notional; 4. interest on free collateral
            notional = units * C[t]
            fund[t] = -(notional * F[t]).sum()
            im_used = (np.abs(notional) * im).sum()
            intr[t] = max(E - im_used, 0.0) * cfg.interest_apy / DAYS
            fund_frac[t] = fund[t] / E
            intr_frac[t] = intr[t] / E
            E += fund[t] + intr[t]
        if E <= 0:
            E = 0.0
            equity[t:] = 0.0
            held_w[t:] = 0.0
            break
        equity[t] = E
        held_w[t] = units * C[t] / E
        peak = max(peak, E)
        # drawdown kill: flatten at tomorrow's open, never re-enter
        if cfg.ladder_kill is not None and E / peak - 1 <= -cfg.ladder_kill and not killed:
            killed = True
            pending = np.zeros(k)
            killed_pending = True
        elif not killed:
            pending = W[t]
        elif killed and (units != 0).any():
            pending = np.zeros(k)
            killed_pending = True
    ret = pd.Series(equity, index=idx).pct_change().fillna(0.0)
    eq = pd.Series(equity, index=idx)
    years = max(len(idx) / DAYS, 1e-9)
    gross = pd.DataFrame(held_w, index=idx, columns=assets).abs().sum(axis=1)
    # Sharpe on EXCESS return over the collateral yield: a book that never
    # trades earns the 3.25% and must score zero, not infinity.
    excess = ret - cfg.interest_apy / DAYS
    excess.iloc[0] = 0.0
    sr = sharpe(excess, DAYS) if float(ret.std(ddof=1)) > 1e-5 else None
    out = {
        "net_sharpe": None if sr is None else round(sr, 3),
        "sharpe_total": None if sr is None else round(sharpe(ret, DAYS), 3),
        "cagr": round(cagr(eq / eq.iloc[0], DAYS), 4),
        "max_drawdown": round(max_drawdown(eq), 4),
        "total_return": round(float(eq.iloc[-1] / eq.iloc[0] - 1), 4),
        "ann_turnover": round(float(turnover.sum() / years), 2),
        "fees_annual": round(float(fee_frac.sum() / years), 4),
        "funding_annual": round(float(fund_frac.sum() / years), 4),
        "interest_annual": round(float(intr_frac.sum() / years), 4),
        "avg_gross_leverage": round(float(gross.mean()), 3),
        "max_gross_leverage": round(float(gross.max()), 3),
        "n_liquidations": int(liq.sum()),
        "n_days": int(len(idx)),
        "years": round(years, 2),
        "start": str(idx[0].date()), "end": str(idx[-1].date()),
        # breadth evidence, carried by every published row: a book whose universe
        # is 14 names but whose average is 2.3 was mostly a two-asset book, and a
        # reader should not have to re-derive that from the dates.
        "n_assets": int(k),
        "avg_n_available": round(float(A.sum(axis=1).mean()), 2),
        # availability is not composition. A 20-name universe whose band never
        # fires quotes 15 names and HOLDS two; the number that catches a wide
        # book collapsing to a narrow one is this one, not the one above.
        "avg_n_held": round(float((held_w != 0).sum(axis=1).mean()), 2),
        "min_assets": int(need),
        "cost_model": cfg.cost.name, "funding_mode": cfg.funding,
        "killed": bool(killed),
        "worst_day": round(float(ret.min()), 4),
        "pct_positive_months": _pct_positive(ret, "M"),
        "pct_positive_quarters": _pct_positive(ret, "Q"),
    }
    out["_series"] = {"returns": ret, "excess": excess, "equity": eq,
                      "available": avail.loc[idx],
                      "n_available": avail.loc[idx].sum(axis=1),
                      "weights": pd.DataFrame(held_w, index=idx, columns=assets),
                      "pnl_asset": pd.DataFrame(pnl_asset, index=idx, columns=assets),
                      "fees": pd.Series(fees, index=idx), "funding": pd.Series(fund, index=idx),
                      "interest": pd.Series(intr, index=idx),
                      "turnover": pd.Series(turnover, index=idx)}
    return out


def _pct_positive(ret: pd.Series, freq: str) -> float:
    rule = {"M": "ME", "Q": "QE"}[freq]
    g = (1 + ret).resample(rule).prod() - 1
    g = g[g != 0]
    return round(float((g > 0).mean()), 3) if len(g) else 0.0


def public(res: dict) -> dict:
    return {k: v for k, v in res.items() if not k.startswith("_")}


# -------------------------------------------------------------- evaluation
def run_strategy(panel, strategy, params: dict, cfg: BacktestConfig, start=None, end=None) -> dict:
    targets = strategy(panel, **params)
    return run(panel, targets, cfg, start, end)


def _grid_points(grid: dict) -> list[dict]:
    if not grid:
        return [{}]
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*[grid[k] for k in keys])]


def walk_forward(panel, strategy, params: dict, cfg: BacktestConfig, grid: dict | None = None,
                 n_folds: int = 6, warmup_days: int = 730, embargo_days: int = 7,
                 dev_end: str = HOLDOUT_START, dev_start: str | None = None) -> dict:
    """Fold-by-fold evaluation on the DEV window.

    With ``grid``: for each fold pick the grid point maximising IS Sharpe on
    [dev_start, fold_start − embargo), then score the fold. Without: fixed
    params, labelled fixed_params=True (NOT out of sample).
    """
    closes = align(panel)
    idx = closes.index
    # folds cannot start before the universe exists: same min_assets gate run()
    # applies. With the default min_assets=1 this is a no-op (every row of the
    # aligned index is some asset's own native bar), so fold edges are unchanged.
    need = len(closes.columns) if cfg.min_assets is None else cfg.min_assets
    idx = idx[_first_live_row(live_mask(panel, list(closes.columns), idx, cfg), need):]
    idx = idx[idx < pd.Timestamp(dev_end, tz="UTC")]
    if dev_start:
        idx = idx[idx >= pd.Timestamp(dev_start, tz="UTC")]
    if len(idx) <= warmup_days + n_folds * 30:
        raise ValueError("dev window too short for the requested folds")
    edges = np.linspace(warmup_days, len(idx), n_folds + 1, dtype=int)
    points = _grid_points(grid or {})
    # precompute full-history targets per grid point ONCE (signals are causal, so
    # a target on day t is the same whatever the run window)
    target_cache = {}
    for i, gp in enumerate(points):
        target_cache[i] = strategy(panel, **{**params, **gp})
    folds = []
    oos = []
    oos_x = []
    is_sr, oos_sr = [], []
    for f in range(n_folds):
        lo, hi = edges[f], edges[f + 1]
        f_start, f_end = idx[lo], idx[hi - 1] + pd.Timedelta(days=1)
        pick, pick_sr = 0, -np.inf
        if grid:
            is_end = f_start - pd.Timedelta(days=embargo_days)
            for i in range(len(points)):
                r = run(panel, target_cache[i], cfg, start=str(idx[0].date()), end=str(is_end.date()))
                sr = r["net_sharpe"] if r["net_sharpe"] is not None else -np.inf
                # ties → fewer trades
                if sr > pick_sr + 1e-9 or (abs(sr - pick_sr) <= 1e-9 and
                                           r["ann_turnover"] < folds_turn(folds, pick, target_cache, panel, cfg, idx, is_end)):
                    pick, pick_sr = i, sr
        r = run(panel, target_cache[pick], cfg, start=str(f_start.date()), end=str(f_end.date()))
        is_sr.append(pick_sr if grid else float("nan"))
        oos_sr.append(r["net_sharpe"] if r["net_sharpe"] is not None else 0.0)
        oos.append(r["_series"]["returns"])
        oos_x.append(r["_series"]["excess"])
        folds.append({"fold": f, "start": str(f_start.date()), "end": str(idx[hi - 1].date()),
                      "params": {**params, **points[pick]}, "is_sharpe": None if not grid else round(pick_sr, 3),
                      "oos_sharpe": r["net_sharpe"], "oos_return": r["total_return"],
                      "max_drawdown": r["max_drawdown"], "turnover": r["ann_turnover"],
                      "n_liquidations": r["n_liquidations"]})
    all_oos = pd.concat(oos)
    all_x = pd.concat(oos_x)
    eq = (1 + all_oos).cumprod()
    med_is = float(np.nanmedian(is_sr)) if grid else float("nan")
    med_oos = float(np.median(oos_sr))
    return {
        "strategy": getattr(strategy, "strategy_name", str(strategy)),
        "fixed_params": not bool(grid),
        "n_folds": len(folds),
        "oos_sharpe_median": round(med_oos, 3),
        "oos_sharpe_concat": round(sharpe(all_x, DAYS), 3) if float(all_x.std(ddof=1)) > 1e-5 else 0.0,
        "oos_sharpe_total": round(sharpe(all_oos, DAYS), 3) if float(all_oos.std(ddof=1)) > 1e-5 else 0.0,
        "oos_cagr": round(cagr(eq, DAYS), 4),
        "oos_max_drawdown": round(max_drawdown(eq), 4),
        "folds_positive": int(sum(1 for f in folds if f["oos_return"] > 0)),
        "wfe": round(med_oos / med_is, 3) if grid and med_is > 0 else None,
        "n_trials_this_call": len(points) * (len(folds) if grid else 1),
        "folds": folds,
        "cost_model": cfg.cost.name, "funding_mode": cfg.funding,
        "_oos_returns": all_oos,
        "_oos_excess": all_x,
    }


def folds_turn(folds, pick, cache, panel, cfg, idx, is_end) -> float:
    """Turnover of the current pick on the IS window (tie-break helper)."""
    try:
        return run(panel, cache[pick], cfg, start=str(idx[0].date()), end=str(is_end.date()))["ann_turnover"]
    except Exception:  # noqa: BLE001
        return float("inf")


def cscv_pbo(returns: pd.DataFrame, n_blocks: int = 8) -> dict:
    """Probability of Backtest Overfitting via combinatorially symmetric
    cross-validation (Bailey, Borwein, Lopez de Prado, Zhu 2017).

    ``returns``: T × N daily returns of every registered trial. Split T into
    ``n_blocks`` blocks; for every half/half combination pick the best trial
    in-sample by Sharpe and record the relative rank of its out-of-sample
    Sharpe. PBO = share of combinations where that rank is below median.
    """
    R = returns.fillna(0.0).to_numpy()
    T, N = R.shape
    if N < 2 or T < n_blocks * 10:
        return {"pbo": None, "n_trials": N, "reason": "too few trials or bars"}
    blocks = np.array_split(np.arange(T), n_blocks)
    logits = []
    is_best, oos_best = [], []
    half = n_blocks // 2
    for combo in itertools.combinations(range(n_blocks), half):
        is_idx = np.concatenate([blocks[i] for i in combo])
        oos_idx = np.concatenate([blocks[i] for i in range(n_blocks) if i not in combo])
        def sr(block):
            m = block.mean(axis=0)
            s = block.std(axis=0, ddof=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                out = np.where(s > 0, m / s, 0.0)
            return out
        sr_is = sr(R[is_idx])
        sr_oos = sr(R[oos_idx])
        b = int(np.argmax(sr_is))
        rank = (sr_oos < sr_oos[b]).sum() / (N - 1) if N > 1 else 0.5
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(rank / (1 - rank)))
        is_best.append(sr_is[b])
        oos_best.append(sr_oos[b])
    logits = np.array(logits)
    slope = float(np.polyfit(is_best, oos_best, 1)[0]) if len(is_best) > 2 else float("nan")
    return {"pbo": round(float((logits < 0).mean()), 3), "n_trials": N, "n_combos": len(logits),
            "degradation_slope": round(slope, 3),
            "mean_oos_sr_of_is_best_daily": round(float(np.mean(oos_best)), 4)}


def dsr(returns: pd.Series, n_trials: int, trial_sr_std: float | None = None) -> dict:
    """Deflated Sharpe for a daily return stream against ``n_trials`` tries."""
    r = returns.dropna()
    if len(r) < 30 or r.std(ddof=1) == 0:
        return {"dsr": 0.0, "sr_daily": 0.0}
    sr_d = float(r.mean() / r.std(ddof=1))
    sk = float(r.skew())
    ku = float(r.kurt() + 3.0)
    p = deflated_sharpe(sr_d, n_trials=max(n_trials, 1), n_obs=len(r), skew=sk, kurt=ku,
                        trial_sr_std=trial_sr_std)
    return {"dsr": round(p, 4), "sr_daily": round(sr_d, 4), "sr_annual": round(sr_d * math.sqrt(DAYS), 3),
            "skew": round(sk, 3), "kurtosis": round(ku, 3), "n_obs": len(r), "n_trials": n_trials}


def stress(panel, strategy, params: dict, cfg: BacktestConfig, start=None, end=None) -> dict:
    """Same strategy under the three cost scenarios and two funding regimes."""
    from .specs import SCENARIOS
    out = {}
    targets = strategy(panel, **params)
    for c in SCENARIOS:
        for fm in ("kalshi", "proxy"):
            r = run(panel, targets, replace(cfg, cost=c, funding=fm), start, end)
            out[f"{c.name}/{fm}"] = {k: r[k] for k in ("net_sharpe", "cagr", "max_drawdown", "fees_annual",
                                                        "funding_annual", "n_liquidations")}
    return out
