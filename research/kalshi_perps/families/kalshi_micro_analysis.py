"""Kalshi perps: native intraday microstructure effect-size study (EXPLORATORY).

Family: kalshi_micro. Nothing here is promotable: Kalshi's perps have ~3.5
months of history (crypto since 2026-06-03, gold/silver since 2026-09-10), so
this file is a plain effect-size study against the venue's costs, NOT a
walk-forward. It does not touch the tournament machinery or the trial
registry.

Questions (numbers printed by ``python -m research.kalshi_perps.families.kalshi_micro_analysis``
or ``python research/kalshi_perps/families/kalshi_micro_analysis.py``):

 1. Kalshi-Binance hourly basis (BTC, ETH): mean, std, autocorrelation,
    half-life; a causal basis mean-reversion rule (enter |basis| > k bps,
    exit when the basis crosses 0) with realised bid/ask execution, 12 bps
    taker per side, Kalshi + Binance funding accrued while holding.
 2. Returns in the hour before / after Kalshi's 04/12/20 UTC funding
    timestamps vs other hours, by sign of the funding rate, plus a causal
    pre-funding rule (signal = basis one hour before the timestamp) and a
    causal post-funding rule (signal = the rate just paid).
 3. Hour-of-day / day-of-week seasonality of return, |return|, notional
    volume and quoted spread for BTC/ETH (and volume/spread for gold/silver).
 4. Lead/lag vs Binance: cross-correlations of hourly returns at +-1h, and
    which venue closes the basis (r_{t+1} regressed on basis_t).
 5. Quoted bid-ask spread (ask_close - bid_close, bps of mid) by contract by
    month for all 20 perps: median, notional-volume-weighted mean, share of
    hours above 10 bps.
 6. Two more Kalshi-native predictors (hourly return reversal, OI change).

Conventions
-----------
* Kalshi 60-minute candles are stamped with the candle END (``end_ts``); the
  Binance 1h bar stamped T opens at T, so it is relabelled T+1h before
  joining (verified: return correlation 0.9985 at that alignment, ~0 at the
  others).
* Price = mid of bid_close / ask_close (last-trade closes are stale in thin
  hours). BTC contract = 0.0001 BTC (x1e4), ETH = 0.001 ETH (x1e3).
* A quote is valid if bid > 0, ask > 0, ask >= bid and spread < 2% (< 50%
  for the alt spread table, which only drops garbage rows).
* Thursday candles ending 08:00 and 09:00 UTC fall in the 03:00-05:00 ET
  maintenance window (no orders, marks frozen): excluded from returns,
  basis and trading. Returns are only formed across exactly-1h steps.
* Costs: 12 bps taker per side (tier 0). Simulations execute at the
  observed bid/ask so the spread is paid exactly; seasonality effects are
  compared with 24 bps + the median spread.
* Causality: a signal computed from candle T is acted on at the closing
  quote of candle T (which equals the opening quote of candle T+1 in this
  feed), and a strictly one-hour-later variant is also reported.
* Standard errors: plain s/sqrt(n) for hourly returns and per-trade PnL
  (non-overlapping trades); Newey-West (24 lags) for the basis level.
"""
from __future__ import annotations

import glob
import math
import os
import sys
import time

import numpy as np
import pandas as pd

HIST = os.environ.get(
    "KALSHI_HIST_DIR",
    "/tmp/claude-0/-home-user-quantfirm/f5ea6dde-167d-56ef-a709-62035093f0dc/scratchpad/hist")
CACHE = os.environ.get("KALSHI_MICRO_CACHE", os.path.join(os.path.dirname(HIST.rstrip("/")), "kalshi_micro_cache"))
TAKER_BPS = 12.0
ROUND_TRIP_FEES = 2 * TAKER_BPS
FUNDING_HOURS_UTC = (4, 12, 20)          # Kalshi crypto funding: 00/08/16 ET = 04/12/20 UTC (EDT)
BINANCE_FUNDING_HOURS_UTC = (0, 8, 16)
MAINT_WEEKDAY, MAINT_END_HOURS = 3, (8, 9)   # Thu 03:00-05:00 ET = 07:00-09:00 UTC
MULT = {"KXBTCPERP": 1e4, "KXETHPERP": 1e3}
BIN = {"KXBTCPERP": "BTCUSDT", "KXETHPERP": "ETHUSDT"}
H1 = pd.Timedelta(hours=1)


# ----------------------------------------------------------------- helpers
def fmt(x, d=2):
    return "nan" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}"


def mean_se(x: pd.Series | np.ndarray):
    x = pd.Series(x).dropna()
    n = len(x)
    if n < 2:
        return (float(x.mean()) if n else float("nan"), float("nan"), n)
    return float(x.mean()), float(x.std(ddof=1) / math.sqrt(n)), n


def nw_se(x: pd.Series, lags: int = 24) -> float:
    """Newey-West SE of the sample mean."""
    x = pd.Series(x).dropna().values
    n = len(x)
    e = x - x.mean()
    s = np.dot(e, e) / n
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        s += 2 * w * np.dot(e[L:], e[:-L]) / n
    return math.sqrt(max(s, 0) / n)


def ols(y, X, names):
    """OLS with intercept; returns list of (name, coef, se, t). HC0 SEs."""
    d = pd.concat([pd.Series(y, name="y"), pd.DataFrame(X)], axis=1).dropna()
    yy = d["y"].values
    XX = np.column_stack([np.ones(len(d)), d.drop(columns="y").values])
    beta, *_ = np.linalg.lstsq(XX, yy, rcond=None)
    res = yy - XX @ beta
    XtX_inv = np.linalg.inv(XX.T @ XX)
    meat = (XX * res[:, None] ** 2).T @ XX
    cov = XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.diag(cov))
    out = [("const", beta[0], se[0], beta[0] / se[0])]
    for i, nm in enumerate(names, 1):
        out.append((nm, beta[i], se[i], beta[i] / se[i]))
    return out, len(d)


def print_ols(title, rows, n):
    print(f"  {title} (n={n})")
    for nm, b, s, t in rows:
        print(f"    {nm:>14s}: coef {b:+.4f}  se {s:.4f}  t {t:+.2f}")


# -------------------------------------------------------------------- data
def load_kalshi(ticker: str, max_spread_bps: float = 200.0) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(HIST, f"kalshi_60m_{ticker}.csv"), parse_dates=["ts"])
    df = df.set_index("ts").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    bid, ask = df["bid_close"], df["ask_close"]
    mid = (bid + ask) / 2
    spread = (ask - bid) / mid * 1e4
    valid = (bid > 0) & (ask > 0) & (ask >= bid) & (spread < max_spread_bps)
    idx = df.index
    maint = (idx.weekday == MAINT_WEEKDAY) & np.isin(idx.hour, MAINT_END_HOURS)
    out = pd.DataFrame({
        "bid": bid, "ask": ask, "mid": mid.where(valid), "spread_bps": spread.where(valid),
        "close": df["close"], "volume_usd": df["volume_usd"], "oi_usd": df["oi_usd"],
        "valid": valid, "maint": maint,
    })
    prev_ok = pd.Series(idx, index=idx).diff() == H1
    lm = np.log(out["mid"])
    ret = (lm - lm.shift(1)) * 1e4
    out["ret"] = ret.where(prev_ok & ~out["maint"] & ~out["maint"].shift(1, fill_value=False))
    return out


def load_binance(sym: str) -> pd.DataFrame:
    b = pd.read_csv(os.path.join(HIST, f"binance_um_1h_{sym}.csv"), parse_dates=["ts"]).set_index("ts").sort_index()
    b.index = b.index + H1                      # open-stamped -> end-stamped
    prem = pd.read_csv(os.path.join(HIST, f"binance_premium_1h_{sym}.csv"), parse_dates=["ts"]).set_index("ts").sort_index()
    prem.index = prem.index + H1
    f = pd.read_csv(os.path.join(HIST, f"binance_funding_{sym}.csv"))
    f["ts"] = pd.to_datetime(f["ts"], utc=True, format="ISO8601").dt.floor("h")
    fund = f.set_index("ts")["last_funding_rate"].astype(float)
    fund = fund[~fund.index.duplicated(keep="last")]
    out = pd.DataFrame({"B": b["close"].astype(float), "prem_bps": prem["close"].astype(float) * 1e4})
    out["bfund"] = fund.reindex(out.index).fillna(0.0)
    lb = np.log(out["B"])
    out["ret_b"] = ((lb - lb.shift(1)) * 1e4).where(pd.Series(out.index, index=out.index).diff() == H1)
    return out


def load_funding(ticker: str) -> pd.DataFrame:
    """Kalshi funding history (rate per interval, mark price); cached in the scratchpad."""
    os.makedirs(CACHE, exist_ok=True)
    fp = os.path.join(CACHE, f"kalshi_funding_{ticker}.csv")
    if os.path.exists(fp):
        df = pd.read_csv(fp, parse_dates=["ts"])
    else:
        repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        if repo not in sys.path:
            sys.path.insert(0, repo)
        from quantfirm.perps.client import MarginClient
        time.sleep(0.6)                       # be gentle: <= 2 req/s across the run
        rows = MarginClient("prod").funding_history(ticker)
        df = pd.DataFrame({"ts": pd.to_datetime([r["funding_time"] for r in rows], utc=True),
                           "rate": [float(r["funding_rate"]) for r in rows],
                           "mark": [float(r["mark_price"]) for r in rows]})
        df.to_csv(fp, index=False)
    return df.drop_duplicates("ts").set_index("ts").sort_index()


def joint(ticker: str):
    k = load_kalshi(ticker)
    b = load_binance(BIN[ticker])
    j = k.join(b, how="inner")
    j["basis"] = (np.log(j["mid"] * MULT[ticker]) - np.log(j["B"])) * 1e4
    j.loc[j["maint"], "basis"] = np.nan
    j["basis_spot"] = j["basis"] + j["prem_bps"]      # Kalshi vs Binance spot-implied index
    fund = load_funding(ticker)
    j["kfund"] = fund["rate"].reindex(j.index).fillna(0.0)
    j["tradeable"] = j["valid"] & ~j["maint"]
    return j, fund


# ------------------------------------------------------------ 1. the basis
def basis_stats(name: str, s: pd.Series):
    s = s.dropna()
    ac = {L: s.autocorr(L) for L in (1, 2, 3, 6, 12, 24)}
    rho = ac[1]
    hl = math.log(0.5) / math.log(rho) if 0 < rho < 1 else float("nan")
    rows, n = ols(s.shift(-1).values, {"b": s.values}, ["b"])
    rho_reg, rho_se = rows[1][1], rows[1][2]
    hl_lo = math.log(0.5) / math.log(min(rho_reg + 2 * rho_se, 0.999))
    hl_hi = math.log(0.5) / math.log(max(rho_reg - 2 * rho_se, 1e-3))
    print(f"  {name}: n={len(s)} mean {s.mean():+.2f} bps (NW se {nw_se(s):.2f}), std {s.std():.2f}, "
          f"median {s.median():+.2f}, p5/p95 {s.quantile(.05):+.2f}/{s.quantile(.95):+.2f}, "
          f"share |b|>5: {(s.abs() > 5).mean():.3f}, |b|>10: {(s.abs() > 10).mean():.4f}")
    print(f"    autocorr lags 1/2/3/6/12/24: " + " ".join(f"{ac[L]:.3f}" for L in (1, 2, 3, 6, 12, 24))
          + f"; AR(1) rho {rho_reg:.3f} (se {rho_se:.3f}) -> half-life {hl:.2f} h (2se band {min(hl_lo, hl_hi):.2f}-{max(hl_lo, hl_hi):.2f} h)")


def simulate_basis(j: pd.DataFrame, k: float, sig_col: str = "basis", max_hold: int = 72,
                   exec_lag: int = 0, demean_hours: int | None = None) -> pd.DataFrame:
    """Causal one-position-at-a-time basis reversion. Signal at row i; enter at
    the quotes of row i+exec_lag; exit at the first later row where the
    signal has crossed zero (or max_hold, or the sample end)."""
    d = j.copy()
    sig = d[sig_col]
    if demean_hours:
        sig = sig - sig.shift(1).rolling(demean_hours, min_periods=demean_hours // 2).mean()
    sig = sig.values
    bid, ask, B = d["bid"].values, d["ask"].values, d["B"].values
    kf, bf, ok = d["kfund"].values, d["bfund"].values, d["tradeable"].values
    n = len(d)
    trades = []
    i = 0
    while i < n - exec_lag - 1:
        s = sig[i]
        if not ok[i] or not np.isfinite(s) or abs(s) <= k:
            i += 1
            continue
        e = i + exec_lag
        if not ok[e] or not np.isfinite(sig[e]):
            i += 1
            continue
        side = -1 if s > 0 else 1                    # Kalshi rich -> short Kalshi
        pk = bid[e] if side == -1 else ask[e]
        pb = B[e]
        fund_k = fund_b = 0.0
        x = None
        for jdx in range(e + 1, n):
            fund_k -= side * kf[jdx] * 1e4           # long Kalshi pays a positive rate
            fund_b -= (-side) * bf[jdx] * 1e4        # hedge leg is the opposite side on Binance
            crossed = np.isfinite(sig[jdx]) and ((side == -1 and sig[jdx] <= 0) or (side == 1 and sig[jdx] >= 0))
            if ok[jdx] and (crossed or jdx - e >= max_hold or jdx == n - 1):
                x = jdx
                break
        if x is None:
            break
        qk = ask[x] if side == -1 else bid[x]
        leg_k = side * math.log(qk / pk) * 1e4
        leg_b = -side * math.log(B[x] / pb) * 1e4
        capture = side * ((d["basis"].values[x]) - (d["basis"].values[e]))
        trades.append({"entry": d.index[e], "hold_h": x - e, "side": side, "sig_entry": s,
                       "capture_mid": capture, "leg_k": leg_k, "leg_b": leg_b,
                       "fund_k": fund_k, "fund_b": fund_b,
                       "spread_paid": capture - (leg_k + leg_b),
                       "gross_hedged": leg_k + leg_b + fund_k + fund_b,
                       "net_hedged": leg_k + leg_b + fund_k + fund_b - ROUND_TRIP_FEES,
                       "gross_kalshi_only": leg_k + fund_k,
                       "net_kalshi_only": leg_k + fund_k - ROUND_TRIP_FEES})
        i = x + 1
    return pd.DataFrame(trades)


def report_sim(label: str, tr: pd.DataFrame, months: float):
    if tr.empty:
        print(f"  {label}: no trades")
        return
    m, se, n = mean_se(tr["net_hedged"])
    mg, seg, _ = mean_se(tr["gross_hedged"])
    mc, sec, _ = mean_se(tr["capture_mid"])
    mk, sek, _ = mean_se(tr["net_kalshi_only"])
    print(f"  {label}: trades {n} ({n / months:.1f}/month), mean hold {tr['hold_h'].mean():.1f} h, "
          f"hit(net_hedged>0) {(tr['net_hedged'] > 0).mean():.2f}")
    print(f"      mid capture {mc:+.2f} (se {sec:.2f}) | spread paid {tr['spread_paid'].mean():.2f} | "
          f"funding K {tr['fund_k'].mean():+.2f} B {tr['fund_b'].mean():+.2f} | gross hedged {mg:+.2f} (se {seg:.2f}) | "
          f"NET hedged after 24 bps fees {m:+.2f} (se {se:.2f}) | net Kalshi-leg-only {mk:+.2f} (se {sek:.2f}); "
          f"total net hedged {tr['net_hedged'].sum():+.1f} bps")


def section_basis(ticker: str, j: pd.DataFrame):
    print(f"\n=== 1. BASIS Kalshi {ticker} vs Binance {BIN[ticker]} (bps, mid vs perp close) ===")
    s = j["basis"]
    print(f"  window {j.index.min()} -> {j.index.max()}; hours with valid basis {s.notna().sum()}")
    basis_stats("full sample", s)
    basis_stats("from 2026-07-01", s[s.index >= "2026-07-01"])
    basis_stats("vs Binance spot-implied (basis + Binance premium index)", j["basis_spot"])
    print("  by month: mean / std / n")
    g = s.groupby(s.index.strftime("%Y-%m"))
    for p, x in g:
        x = x.dropna()
        if len(x) > 10:
            print(f"    {p}: {x.mean():+.2f} / {x.std():.2f} / {len(x)}")
    months = s.notna().sum() / (24 * 30.4)
    print(f"  -- mean-reversion rule, signal = raw basis vs 0, exit when basis crosses 0, max hold 72h --")
    for k in (2, 3, 4, 5, 6, 8, 10):
        report_sim(f"k={k}", simulate_basis(j, k), months)
    print(f"  -- signal = basis minus trailing-168h mean (causal), exit when the demeaned basis crosses 0 --")
    for k in (2, 3, 4, 5, 6, 8):
        report_sim(f"k={k}", simulate_basis(j, k, demean_hours=168), months)
    print(f"  -- strictly one hour later execution (signal at T, trade at T+1h quotes), demeaned --")
    for k in (3, 5, 8):
        report_sim(f"k={k}", simulate_basis(j, k, demean_hours=168, exec_lag=1), months)
    print(f"  -- signal = Kalshi vs Binance spot-implied (basis_spot) vs 0 --")
    for k in (3, 5, 8):
        report_sim(f"k={k}", simulate_basis(j, k, sig_col="basis_spot"), months)


# -------------------------------------------------------- 2. funding hours
def section_funding(ticker: str, j: pd.DataFrame, k_all: pd.DataFrame, fund: pd.DataFrame):
    print(f"\n=== 2. FUNDING-TIME BEHAVIOUR {ticker} (Kalshi mid returns, bps; funding at 04/12/20 UTC) ===")
    r = k_all["ret"]
    hr = r.index.hour
    cls = np.where(np.isin(hr, FUNDING_HOURS_UTC), "pre (hour ending at funding)",
                   np.where(np.isin(hr, [h + 1 for h in FUNDING_HOURS_UTC]), "post (hour after funding)", "other"))
    for c in ("pre (hour ending at funding)", "post (hour after funding)", "other"):
        m, se, n = mean_se(r[cls == c])
        a, _, _ = mean_se(r[cls == c].abs())
        print(f"  {c:>30s}: mean {m:+.2f} (se {se:.2f}) n={n}; mean |ret| {a:.1f}")
    rate = fund["rate"]
    print(f"  funding rate: n={len(rate)}, mean {rate.mean() * 1e4:+.3f} bps/8h, share >0 {(rate > 0).mean():.3f}, "
          f"=0 {(rate == 0).mean():.3f}, <0 {(rate < 0).mean():.3f}; mean |rate| when nonzero {rate[rate != 0].abs().mean() * 1e4:.2f} bps")
    # pre hour: candle ending at F, joined to the rate paid at F; post hour: candle ending F+1h, rate paid at F
    pre = pd.DataFrame({"ret": r[np.isin(hr, FUNDING_HOURS_UTC)]})
    pre["rate"] = rate.reindex(pre.index)
    post = pd.DataFrame({"ret": r[np.isin(hr, [h + 1 for h in FUNDING_HOURS_UTC])]})
    post["rate"] = rate.reindex(post.index - H1).values
    for label, d in (("pre", pre), ("post", post)):
        d = d.dropna()
        for cond, nm in ((d["rate"] > 0, "rate>0"), (d["rate"] == 0, "rate=0"), (d["rate"] < 0, "rate<0")):
            m, se, n = mean_se(d.loc[cond, "ret"])
            print(f"    {label:>4s} hour | {nm}: mean {m:+.2f} (se {se:.2f}) n={n}")
    # basis around the funding timestamp (hours relative to F)
    b = j["basis"].dropna()
    rel = ((b.index.hour - 4) % 8)          # 0 = at funding (04,12,20), 7 = one hour before
    rel = np.where(rel == 0, 0, rel - 8)    # -7..-1, 0
    print("  mean basis by hour relative to funding (0 = candle ending at the timestamp):")
    print("    " + "  ".join(f"{h:+d}h:{b[rel == h].mean():+.2f}" for h in (-3, -2, -1, 0)) +
          "  | +1h..+4h: " + "  ".join(f"{b[rel == h].mean():+.2f}" for h in (-7, -6, -5, -4)))
    # does the basis one hour before predict the sign of the rate?
    bb = j["basis"].reindex(rate.index - H1)
    ok = bb.notna().values & (rate.values != 0)
    if ok.sum():
        agree = (np.sign(bb.values[ok]) == np.sign(rate.values[ok])).mean()
        print(f"  sign(basis at F-1h) == sign(rate at F) on nonzero rates: {agree:.2f} of {ok.sum()}; "
              f"corr(basis F-1h, rate) {np.corrcoef(bb.values[ok], rate.values[ok])[0, 1]:.3f}")
    # causal pre-funding rule: at F-1h, if basis > x short Kalshi (sell bid, buy ask at F); if < -x long.
    print("  causal pre-funding rule: position over the hour into funding, sign = -sign(basis at F-1h), |basis|>x")
    q = j.copy()
    detail = None
    for x in (0.0, 2.0, 4.0):
        rows = []
        for F in rate.index:
            t0 = F - H1
            if t0 not in q.index or F not in q.index:
                continue
            a, e = q.loc[t0], q.loc[F]
            if not (a["tradeable"] and e["tradeable"] and np.isfinite(a["basis"])) or abs(a["basis"]) <= x:
                continue
            side = -1 if a["basis"] > 0 else 1
            pk = a["bid"] if side == -1 else a["ask"]
            qk = e["ask"] if side == -1 else e["bid"]
            gross_mid = side * math.log(e["mid"] / a["mid"]) * 1e4
            gross = side * math.log(qk / pk) * 1e4 - side * e["kfund"] * 1e4   # holds through F -> pays/receives
            rows.append((gross_mid, gross, gross - ROUND_TRIP_FEES, side, side * math.log(e["B"] / a["B"]) * 1e4, F))
        if rows:
            arr = np.array([r[:5] for r in rows], dtype=float)
            m0, s0, n = mean_se(arr[:, 0]); m1, s1, _ = mean_se(arr[:, 1]); m2, s2, _ = mean_se(arr[:, 2])
            print(f"    |basis|>{x:.0f}: n={n}, mid-to-mid {m0:+.2f} (se {s0:.2f}), after spread+funding {m1:+.2f} (se {s1:.2f}), net of 24 bps fees {m2:+.2f} (se {s2:.2f})")
            if x == 0.0:
                detail = pd.DataFrame(rows, columns=["mid", "gross", "net", "side", "mid_binance", "F"]).set_index("F")
    if detail is not None:
        print("    diagnostics for |basis|>0 (is the pre-funding hour special, or is it noise?):")
        for sd, nm in ((1, "long entries (Kalshi cheap at F-1h)"), (-1, "short entries (Kalshi rich at F-1h)")):
            m, se, n = mean_se(detail.loc[detail["side"] == sd, "mid"])
            print(f"      {nm}: n={n}, mid-to-mid {m:+.2f} (se {se:.2f})")
        m, se, n = mean_se(detail["mid_binance"])
        print(f"      same sign applied to the Binance return over that hour: {m:+.2f} (se {se:.2f}) n={n}")
        for p, x in detail.groupby(detail.index.strftime("%Y-%m")):
            m, se, n = mean_se(x["mid"])
            print(f"      month {p}: n={n}, mid-to-mid {m:+.2f} (se {se:.2f})")
        for h, nm in ((4, "04 UTC"), (12, "12 UTC"), (20, "20 UTC")):
            x = detail[detail.index.hour == h]
            m, se, n = mean_se(x["mid"])
            print(f"      timestamp {nm}: n={n}, mid-to-mid {m:+.2f} (se {se:.2f})")
        # control: the same rule (-sign(basis_t) x r_{t+1}) applied in every other hour of the day
        ctrl = (-np.sign(q["basis"]) * q["ret"].shift(-1)).where(q["tradeable"] & q["tradeable"].shift(-1, fill_value=False))
        nxt_hour = (q.index + H1).hour
        is_pre = np.isin(nxt_hour, FUNDING_HOURS_UTC)
        is_post = np.isin(nxt_hour, [h + 1 for h in FUNDING_HOURS_UTC])
        for mask, nm in ((~is_pre & ~is_post, "all other hours"), (is_post, "post-funding hour"), (is_pre, "pre-funding hour (same as rule)")):
            m, se, n = mean_se(ctrl[mask])
            print(f"      control, -sign(basis_t) x r_(t+1) in {nm}: {m:+.2f} (se {se:.2f}) n={n}")
    print("  causal post-funding rule: at F (rate just published), sign = +1 if rate>0 else -1 if rate<0, hold one hour")
    rows = []
    for F in rate.index:
        t1 = F + H1
        if F not in q.index or t1 not in q.index or rate[F] == 0:
            continue
        a, e = q.loc[F], q.loc[t1]
        if not (a["tradeable"] and e["tradeable"]):
            continue
        side = 1 if rate[F] > 0 else -1
        pk = a["ask"] if side == 1 else a["bid"]
        qk = e["bid"] if side == 1 else e["ask"]
        rows.append((side * math.log(e["mid"] / a["mid"]) * 1e4, side * math.log(qk / pk) * 1e4))
    if rows:
        arr = np.array(rows)
        m0, s0, n = mean_se(arr[:, 0]); m1, s1, _ = mean_se(arr[:, 1])
        print(f"    n={n}, mid-to-mid {m0:+.2f} (se {s0:.2f}), after spread {m1:+.2f} (se {s1:.2f}), net of fees {m1 - ROUND_TRIP_FEES:+.2f}")
    rows = []
    for F in rate.index:
        t1 = F + H1
        if F not in q.index or t1 not in q.index or rate[F] == 0:
            continue
        a, e = q.loc[F], q.loc[t1]
        if not (a["tradeable"] and e["tradeable"]):
            continue
        side = -1 if rate[F] > 0 else 1
        rows.append(side * math.log(e["mid"] / a["mid"]) * 1e4)
    if rows:
        m0, s0, n = mean_se(rows)
        print(f"    (contrarian: fade the rate sign) mid-to-mid {m0:+.2f} (se {s0:.2f}) n={n}")


# ------------------------------------------------------------ 3. seasonality
def section_seasonality(ticker: str, k: pd.DataFrame, returns: bool = True):
    print(f"\n=== 3. SEASONALITY {ticker} (UTC; candle end hour) ===")
    d = k.copy()
    d["hour"] = d.index.hour
    d["dow"] = d.index.day_name().str[:3]
    d["absret"] = d["ret"].abs()
    if returns:
        g = d.groupby("hour")
        tab = pd.DataFrame({"ret": g["ret"].mean(), "se": g["ret"].std() / np.sqrt(g["ret"].count()),
                            "absret": g["absret"].mean(), "vol_usd_k": g["volume_usd"].mean() / 1e3,
                            "spread_med": g["spread_bps"].median(), "n": g["ret"].count()})
        tab["t"] = tab["ret"] / tab["se"]
        print("  hour-of-day: mean ret (se) | mean|ret| | mean $vol k | median spread bps | n")
        for h, row in tab.iterrows():
            print(f"    {h:02d}: {row['ret']:+6.2f} ({row['se']:.2f}) t{row['t']:+5.2f} | {row['absret']:5.1f} | "
                  f"{row['vol_usd_k']:8.0f} | {row['spread_med']:.2f} | {int(row['n'])}")
        print(f"  hours with |t|>2: {(tab['t'].abs() > 2).sum()} of 24 (expect ~1 by chance); max |t| {tab['t'].abs().max():.2f} "
              f"at hour {int(tab['t'].abs().idxmax()):02d} (mean {tab['ret'][tab['t'].abs().idxmax()]:+.2f} bps)")
        # sessions
        sess = {"Asia 00-08": range(1, 9), "Europe 08-14": range(9, 15), "US 14-22": range(15, 23), "late US 22-00": (23, 0)}
        print("  session sums of hourly means (bps per session), se:")
        for nm, hrs in sess.items():
            x = d[d["hour"].isin(list(hrs))]
            daily = x["ret"].groupby(x.index.floor("D")).sum(min_count=1).dropna()
            m, se, n = mean_se(daily)
            print(f"    {nm:>14s}: {m:+.2f} (se {se:.2f}) n_days={n}; median spread {x['spread_bps'].median():.2f}; mean $vol/h {x['volume_usd'].mean() / 1e3:.0f}k")
        g = d.groupby("dow")
        order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        print("  day-of-week: mean ret (se) | mean|ret| | mean $vol k | median spread | n")
        for dn in order:
            if dn in g.groups:
                x = d[d["dow"] == dn]
                m, se, n = mean_se(x["ret"])
                print(f"    {dn}: {m:+6.2f} ({se:.2f}) | {x['absret'].mean():5.1f} | {x['volume_usd'].mean() / 1e3:8.0f} | {x['spread_bps'].median():.2f} | {n}")
        wk = d[d.index.weekday < 5]; we = d[d.index.weekday >= 5]
        print(f"  weekend vs weekday: mean|ret| {we['absret'].mean():.1f} vs {wk['absret'].mean():.1f}; $vol/h {we['volume_usd'].mean() / 1e3:.0f}k vs {wk['volume_usd'].mean() / 1e3:.0f}k; "
              f"median spread {we['spread_bps'].median():.2f} vs {wk['spread_bps'].median():.2f}")
    else:
        print(f"  n={len(d)} hourly rows only ({d.index.min()} -> {d.index.max()}): volume/spread only, returns not meaningful")
        g = d.groupby("hour")
        print("  hour-of-day: mean $vol k | median spread bps | mean|ret| | n")
        for h, x in g:
            print(f"    {h:02d}: {x['volume_usd'].mean() / 1e3:7.0f} | {x['spread_bps'].median():.2f} | {x['absret'].mean():5.1f} | {len(x)}")
        wk = d[d.index.weekday < 5]; we = d[d.index.weekday >= 5]
        print(f"  weekend vs weekday: $vol/h {we['volume_usd'].mean() / 1e3:.0f}k vs {wk['volume_usd'].mean() / 1e3:.0f}k; median spread {we['spread_bps'].median():.2f} vs {wk['spread_bps'].median():.2f}; "
              f"mean|ret| {we['absret'].mean():.1f} vs {wk['absret'].mean():.1f} (n {len(we)} / {len(wk)})")
        # weekend gap: last Friday quote -> first Monday quote is not in sample; report Fri 21:00 -> Sun 22:00 move
        fri = d[(d.index.weekday == 4) & (d.index.hour == 21)]
        sun = d[(d.index.weekday == 6) & (d.index.hour == 22)]
        if len(fri) and len(sun):
            print(f"  Fri 21:00 UTC mid {fri['mid'].iloc[0]:.4f} -> Sun 22:00 UTC mid {sun['mid'].iloc[0]:.4f}: {math.log(sun['mid'].iloc[0] / fri['mid'].iloc[0]) * 1e4:+.1f} bps over the closed-reference weekend")


# -------------------------------------------------------------- 4. lead/lag
def section_leadlag(ticker: str, j: pd.DataFrame):
    print(f"\n=== 4. LEAD/LAG {ticker} vs Binance (hourly log returns, bps) ===")
    d = j[["ret", "ret_b", "basis", "close", "mid"]].copy()
    lc = np.log(d["close"] * MULT[ticker])
    d["ret_close"] = ((lc - lc.shift(1)) * 1e4).where(d["ret"].notna())
    rk, rb, rc = d["ret"], d["ret_b"], d["ret_close"]
    print("  corr(Kalshi_t, Binance_{t+j}) j=-2..+2 (j<0: Binance leads):  " +
          "  ".join(f"j={jj:+d}:{rk.corr(rb.shift(-jj)):.4f}" for jj in (-2, -1, 0, 1, 2)))
    print("  same with Kalshi LAST-TRADE close returns:                     " +
          "  ".join(f"j={jj:+d}:{rc.corr(rb.shift(-jj)):.4f}" for jj in (-2, -1, 0, 1, 2)))
    n = pd.concat([rk, rb], axis=1).dropna().shape[0]
    print(f"  n={n}; 2-sigma band for a null correlation ~ +-{2 / math.sqrt(n):.4f}")
    rows, nn = ols(rk.shift(-1), {"ret_b_t": rb, "basis_t": d["basis"], "ret_k_t": rk}, ["ret_b_t", "basis_t", "ret_k_t"])
    print_ols("Kalshi r_{t+1} on Binance r_t, basis_t, Kalshi r_t", rows, nn)
    rows, nn = ols(rb.shift(-1), {"ret_k_t": rk, "basis_t": d["basis"], "ret_b_t": rb}, ["ret_k_t", "basis_t", "ret_b_t"])
    print_ols("Binance r_{t+1} on Kalshi r_t, basis_t, Binance r_t", rows, nn)
    sd = d["basis"].std()
    print(f"  (basis std {sd:.2f} bps: a 1-sd rich Kalshi predicts the next-hour Kalshi move by coef x {sd:.2f})")
    print(f"  own autocorr of hourly returns: Kalshi mid {rk.autocorr(1):+.4f}, Kalshi last-trade {rc.autocorr(1):+.4f}, Binance {rb.autocorr(1):+.4f}")


# --------------------------------------------------------------- 5. spreads
def section_spreads():
    print("\n=== 5. QUOTED SPREAD (ask_close - bid_close, bps of mid) BY CONTRACT BY MONTH ===")
    files = sorted(glob.glob(os.path.join(HIST, "kalshi_60m_*.csv")))
    rows = []
    for fp in files:
        t = os.path.basename(fp)[len("kalshi_60m_"):-4]
        k = load_kalshi(t, max_spread_bps=5000.0)
        k = k[k["valid"] & ~k["maint"]]
        rec = {"ticker": t, "n": len(k), "all_med": k["spread_bps"].median(),
               "all_vw": np.average(k["spread_bps"], weights=k["volume_usd"].clip(lower=1.0)),
               "share>10": (k["spread_bps"] > 10).mean(), "vol_usd_per_day_k": k["volume_usd"].sum() / max((k.index.max() - k.index.min()).total_seconds() / 86400, 1) / 1e3}
        for p, x in k.groupby(k.index.strftime("%Y-%m")):
            rec[f"{p}_med"] = x["spread_bps"].median()
            rec[f"{p}_vw"] = np.average(x["spread_bps"], weights=x["volume_usd"].clip(lower=1.0))
        rows.append(rec)
    tab = pd.DataFrame(rows).set_index("ticker")
    months = sorted(c[:-4] for c in tab.columns if c.endswith("_med") and c != "all_med")
    hdr = "  ticker        " + " ".join(f"{m}: med/vw " for m in months) + "| all med / vw | share>10bps | $vol/day k | n"
    print(hdr)
    for t, r in tab.sort_values("vol_usd_per_day_k", ascending=False).iterrows():
        cells = " ".join(f"{fmt(r.get(m + '_med'))}/{fmt(r.get(m + '_vw'))}".rjust(15) for m in months)
        print(f"  {t:<13s} {cells} | {r['all_med']:.2f} / {r['all_vw']:.2f} | {r['share>10']:.2f} | {r['vol_usd_per_day_k']:8.0f} | {int(r['n'])}")
    print("  (med = time-median of hourly closing quotes; vw = notional-volume-weighted mean; the desk pays ~half of these per side)")


# ---------------------------------------------------- 6. other native ideas
def section_other(ticker: str, k: pd.DataFrame):
    print(f"\n=== 6. OTHER KALSHI-NATIVE PREDICTORS {ticker} (next-hour mid return, bps) ===")
    d = k.copy()
    d["doi"] = (d["oi_usd"] - d["oi_usd"].shift(1)) / d["oi_usd"].shift(1).replace(0, np.nan) * 100   # % OI change
    d["volz"] = (np.log1p(d["volume_usd"]) - np.log1p(d["volume_usd"]).rolling(168).mean()) / np.log1p(d["volume_usd"]).rolling(168).std()
    d["y"] = d["ret"].shift(-1)
    rows, n = ols(d["y"], {"ret_t": d["ret"], "doi_pct_t": d["doi"], "ret_x_volz": d["ret"] * d["volz"], "spread_t": d["spread_bps"]},
                  ["ret_t", "doi_pct_t", "ret_x_volz", "spread_t"])
    print_ols("r_{t+1} on r_t, %dOI_t, r_t*volz_t, spread_t", rows, n)
    # simple reversal rule: after a |ret| > 50 bps hour, fade it for one hour (executed at bid/ask)
    for thr in (30, 60, 100):
        sel = d[(d["ret"].abs() > thr) & d["valid"] & ~d["maint"]]
        nxt = d["ret"].shift(-1).reindex(sel.index)
        nxt_spread = d["spread_bps"].shift(-1).reindex(sel.index)
        pnl = -np.sign(sel["ret"]) * nxt - (sel["spread_bps"] + nxt_spread) / 2
        m, se, n = mean_se(pnl)
        m0, s0, _ = mean_se(-np.sign(sel["ret"]) * nxt)
        print(f"  fade hours with |ret|>{thr}: n={n}, mid-to-mid {m0:+.2f} (se {s0:.2f}), after spread {m:+.2f} (se {se:.2f}), net of 24 bps {m - ROUND_TRIP_FEES:+.2f}")


# ------------------------------------------------------------------- main
def main():
    pd.set_option("display.width", 200)
    print(f"data dir {HIST}; taker {TAKER_BPS} bps/side; maintenance Thu candles ending {MAINT_END_HOURS} UTC excluded")
    for ticker in ("KXBTCPERP", "KXETHPERP"):
        j, fund = joint(ticker)
        k_all = load_kalshi(ticker)
        print(f"\n##### {ticker}: Kalshi rows {len(k_all)} ({k_all.index.min()} -> {k_all.index.max()}), valid quotes {k_all['valid'].sum()}, "
              f"maintenance rows {k_all['maint'].sum()}, hourly returns {k_all['ret'].notna().sum()}; joint with Binance {len(j)}")
        r = k_all["ret"].dropna()
        print(f"  hourly mid return: mean {r.mean():+.2f} bps, std {r.std():.1f} bps, mean |ret| {r.abs().mean():.1f} bps; median spread {k_all['spread_bps'].median():.2f} bps "
              f"(round trip = 24 bps fees + ~{k_all['spread_bps'].median():.2f} bps spread)")
        section_basis(ticker, j)
        section_funding(ticker, j, k_all, fund)
        section_seasonality(ticker, k_all, returns=True)
        section_leadlag(ticker, j)
        section_other(ticker, k_all)
    for ticker in ("KXGOLDPERP", "KXSILVERPERP"):
        k_all = load_kalshi(ticker)
        r = k_all["ret"].dropna()
        print(f"\n##### {ticker}: rows {len(k_all)}, hourly returns {len(r)}, mean|ret| {r.abs().mean():.1f} bps, std {r.std():.1f}, median spread {k_all['spread_bps'].median():.2f} bps")
        section_seasonality(ticker, k_all, returns=False)
    section_spreads()


if __name__ == "__main__":
    sys.exit(main())
