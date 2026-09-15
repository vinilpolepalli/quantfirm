"""Sizing on a wide Kalshi perps universe — and proof the four-asset book is untouched.

``quantfirm.perps.strategies.vol_target`` was written for btc/eth/gold/silver,
four assets that all have complete history over the researched window. Kalshi
lists 23 perps, 20 of them tradable, whose price proxies begin anywhere between
2000 (Yahoo metals) and 2026 (hype), and one of which stopped quoting for 905
days mid-history (xrp, delisted from Coinbase 2021-01-19 → 2023-07-13 over the
SEC suit). This file covers the three things that breaks, plus the regression
that matters more than any of them.

Everything here runs on synthetic panels: no network, no data files.

THE REGRESSION IS THE POINT. ``TestFourAssetRegression`` carries a verbatim
copy of the pre-change sizer and asserts the live one reproduces it to the bit
on a four-asset panel. Every published number on this desk — the first
tournament, the ten-family campaign, the one holdout opening — was produced by
that arithmetic, so if this class ever fails, the numbers in
``docs/KALSHI_PERPS.md`` and ``research/kalshi_perps/`` stopped describing the
code and one of the two has to be withdrawn.
"""
import os
import sys
import unittest
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantfirm.perps import strategies as S  # noqa: E402
from quantfirm.perps.specs import (BREADTH_UNIVERSE, RESEARCH_UNIVERSE, SPECS,  # noqa: E402
                                   max_weight_for_distance)

# The 16 tradable markets with enough proxy history to be worth a synthetic
# breadth test: BREADTH_UNIVERSE (14) plus the two later listers.
WIDE = BREADTH_UNIVERSE + ("near", "sui")


# --------------------------------------------------------------- panel maker
def make_panel(assets=RESEARCH_UNIVERSE, n=900, seed=0, start="2019-01-01",
               listing=None, gaps=None, beta=0.75):
    """Random-walk daily OHLCV per asset, metals dropped on weekends.

    Crypto names load on a common factor (``beta``) and metals barely do, so a
    16-name panel has the roughly 0.45 average pairwise correlation a real one
    does. Independent names would make a wide book look four times more
    diversified than Kalshi's board is and would quietly hide the weight-step
    problem this file exists to catch.

    ``listing``: {asset: n_bars_to_skip_at_the_front} — the asset's proxy does
    not exist before that, exactly like sol (2021-06) against btc (2015-07).
    ``gaps``: {asset: (start_i, end_i)} — bars removed mid-history, the
    delisting case that ``align()`` hides behind a forward fill.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    vols = {"btc": 0.04, "eth": 0.05, "gold": 0.01, "silver": 0.018}
    factor = rng.normal(0.0002, 0.03, n)
    panel = {}
    for i, a in enumerate(assets):
        vol = vols.get(a, 0.03 + 0.004 * (i % 5))
        b = 0.15 if (a in SPECS and SPECS[a].asset_class == "metals") else beta
        r = b * (vol / 0.03) * factor + np.sqrt(max(1 - b * b, 0.05)) * rng.normal(0, vol, n)
        close = 100 * np.exp(np.cumsum(r))
        open_ = np.roll(close, 1)
        open_[0] = close[0]
        high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
        low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
        df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                           "volume": rng.uniform(1e3, 1e4, n)}, index=idx)
        if a in SPECS and SPECS[a].asset_class == "metals":
            df = df[df.index.dayofweek < 5]
        if listing and a in listing:
            df = df.iloc[listing[a]:]
        if gaps and a in gaps:
            lo, hi = gaps[a]
            keep = ~((df.index >= idx[lo]) & (df.index < idx[hi]))
            df = df[keep]
        panel[a] = df
    return panel


# ------------------------------------------------- the frozen legacy sizer
# Copied verbatim from quantfirm/perps/strategies.py as it stood before the
# breadth work (portfolio_vol + vol_target, defaults included). Do not "fix"
# anything in here: its only job is to be what the published numbers were made
# with. cap_weights and asset_vol are called through the live module because
# neither changed behaviour (cap_weights' only edit is the fallback maintenance
# rate for an asset with no PerpSpec, which no listed market uses).
def legacy_portfolio_vol(weights, returns, window=60):
    cols = list(weights.columns)
    R = returns[cols].fillna(0.0).to_numpy()
    W = weights[cols].fillna(0.0).to_numpy()
    n = len(W)
    out = np.full(n, np.nan)
    for t in range(window, n):
        block = R[t - window + 1:t + 1]
        cov = np.cov(block, rowvar=False)
        if np.ndim(cov) == 0:
            cov = np.array([[cov]])
        w = W[t]
        out[t] = np.sqrt(max(float(w @ cov @ w), 0.0) * 365)
    return pd.Series(out, index=weights.index)


def legacy_vol_target(signal, panel, target_vol, vol_window=60, cov_window=120,
                      max_gross=1.5, max_asset=0.75, min_liq_distance=0.35,
                      max_scale=3.0, step=0.05):
    closes = S.align(panel)
    rets = closes.pct_change()
    vol = S.asset_vol(panel, vol_window)
    n = len(signal.columns)
    ref = (1.0 / vol) / n
    pv_ref = legacy_portfolio_vol(ref, rets, cov_window)
    k = (target_vol / pv_ref).clip(upper=max_scale)
    raw = signal.div(vol).div(n).fillna(0.0)
    w = raw.mul(k, axis=0).fillna(0.0)
    if step and step > 0:
        w = (w / step).round() * step
    return S.cap_weights(w, max_gross, max_asset, min_liq_distance)


class TestFourAssetRegression(unittest.TestCase):
    """The four-asset book must be byte-identical to the pre-change code."""

    def setUp(self):
        self.panel = make_panel(RESEARCH_UNIVERSE, n=900, seed=0)
        self.closes = S.align(self.panel)

    def test_vol_target_matches_the_frozen_legacy_sizer(self):
        sig = pd.DataFrame(1.0, index=self.closes.index, columns=self.closes.columns)
        for tv in (0.08, 0.12, 0.18):
            new = S.vol_target(sig, self.panel, tv)
            old = legacy_vol_target(sig, self.panel, tv)
            self.assertTrue(new.index.equals(old.index) and new.columns.equals(old.columns))
            self.assertEqual(float((new - old).abs().to_numpy().max()), 0.0,
                             f"vol_target drifted from the published arithmetic at {tv}")
            self.assertEqual(new.to_numpy().tobytes(), old.to_numpy().tobytes())

    def test_registered_strategies_match_the_frozen_legacy_sizer(self):
        """trend_long_only and vol_target_hold, the incumbent and the benchmark."""
        for name in ("trend_long_only", "vol_target_hold"):
            fn = S.REGISTRY[name]
            new = fn(self.panel)
            with mock.patch.object(S, "vol_target", legacy_vol_target):
                old = S.REGISTRY[name](self.panel)
            self.assertEqual(float((new - old).abs().to_numpy().max()), 0.0,
                             f"{name} no longer reproduces its published weights")

    def test_mixed_and_long_short_signals_also_match(self):
        rng = np.random.default_rng(11)
        sig = pd.DataFrame(rng.choice([-1.0, 0.0, 0.5, 1.0],
                                      size=(len(self.closes), len(self.closes.columns))),
                           index=self.closes.index, columns=self.closes.columns)
        new = S.vol_target(sig, self.panel, 0.12)
        old = legacy_vol_target(sig, self.panel, 0.12)
        self.assertEqual(float((new - old).abs().to_numpy().max()), 0.0)

    def test_portfolio_vol_default_is_the_legacy_estimator(self):
        rets = self.closes.pct_change()
        ref = (1.0 / S.asset_vol(self.panel, 60)) / 4
        a = S.portfolio_vol(ref, rets, 120)
        b = legacy_portfolio_vol(ref, rets, 120)
        pd.testing.assert_series_equal(a, b)

    def test_step_auto_is_exactly_the_old_step_at_four_assets(self):
        self.assertEqual(S.resolve_step("auto", len(RESEARCH_UNIVERSE)), 0.05)
        self.assertEqual(S.resolve_step(0.05, 16), 0.05)
        with self.assertRaises(ValueError):
            S.resolve_step("small", 4)


# ------------------------------- 1. covariance with incomplete history
class TestCovarianceIncompleteHistory(unittest.TestCase):
    def test_pairwise_matches_pandas_where_defined(self):
        """The estimator is ordinary pairwise-complete covariance, not a guess."""
        rng = np.random.default_rng(3)
        blk = rng.normal(0, 0.02, (120, 5))
        blk[:70, 3] = np.nan        # 50 usable observations
        blk[:110, 4] = np.nan       # 10 usable observations
        cov, ok = S._pairwise_cov(blk, 30)
        ref = pd.DataFrame(blk).cov(min_periods=30).to_numpy()
        m = np.isfinite(ref)
        self.assertLess(float(np.abs(cov[m] - ref[m]).max()), 1e-15)
        self.assertTrue(np.array_equal(ok, np.array([True, True, True, True, False])))
        self.assertEqual(float(np.abs(cov[~ok]).sum()), 0.0)   # the short name is zeroed out

    def test_no_rows_are_dropped_for_the_complete_assets(self):
        """A young asset must not cost the old ones their history.

        Complete-case deletion would estimate every pair on the 50 rows the
        young asset shares; pairwise keeps the full 120 for the pairs that have
        it, so those entries equal the plain np.cov of the complete block.
        """
        rng = np.random.default_rng(5)
        blk = rng.normal(0, 0.02, (120, 3))
        full = np.cov(blk, rowvar=False)
        blk[:70, 2] = np.nan
        cov, ok = S._pairwise_cov(blk, 30)
        self.assertLess(float(np.abs(cov[:2, :2] - full[:2, :2]).max()), 1e-15)
        # and complete-case deletion would NOT have given that
        cc = np.cov(blk[70:], rowvar=False)
        self.assertGreater(float(np.abs(cc[:2, :2] - full[:2, :2]).max()), 0.0)

    def test_zero_filling_understates_a_young_asset(self):
        """Why the legacy estimator is wrong here, stated as a number."""
        rng = np.random.default_rng(7)
        idx = pd.date_range("2020-01-01", periods=200, freq="D", tz="UTC")
        rets = pd.DataFrame(rng.normal(0, 0.03, (200, 2)), index=idx, columns=["btc", "sol"])
        rets.loc[rets.index < idx[140], "sol"] = np.nan      # sol lists on day 140
        w = pd.DataFrame(1.0, index=idx, columns=["btc", "sol"])
        legacy = legacy_portfolio_vol(w, rets, 120).iloc[-1]
        pairwise = S.portfolio_vol(w, rets, 120, min_obs=40).iloc[-1]
        self.assertGreater(pairwise, legacy * 1.1,
                           "zero-filled gaps should make the book look far calmer than it is")

    def test_asset_with_too_little_history_is_excluded_not_sized(self):
        """The rule: below min_obs an asset is OUT of the book that day."""
        panel = make_panel(("btc", "eth", "gold", "silver", "sol"), n=600, seed=1,
                           listing={"sol": 400})
        closes = S.align(panel)
        sig = pd.DataFrame(1.0, index=closes.index, columns=closes.columns)
        w = S.vol_target(sig, panel, 0.12, cov_window=120, cov_min_obs=60, step=0.0)
        first_bar = panel["sol"].index[0]
        rets = closes.pct_change().where(S.tradable(panel))
        usable = S.usable_history(rets, 120, 60)["sol"]
        # nothing before the rule is satisfied, something after
        self.assertEqual(float(w.loc[~usable, "sol"].abs().max()), 0.0)
        self.assertGreater(float(w.loc[usable, "sol"].abs().max()), 0.0)
        self.assertGreater(usable[usable].index[0], first_bar)
        # the other four are sized throughout — the young name costs them nothing
        for a in ("btc", "eth", "gold", "silver"):
            self.assertGreater(float(w.loc[usable, a].abs().min()), 0.0)

    def test_singular_and_non_psd_blocks_do_not_blow_up(self):
        """Three names with inconsistent overlaps: corr(A,B)=+1, corr(B,C)=+1,
        A and C never overlap at all. The pairwise matrix is not PSD and its
        quadratic form goes negative; the estimator must still return a finite
        positive vol (the diagonal fallback), never 0 (which would divide into
        an infinitely levered book)."""
        n, win = 121, 120
        idx = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC")
        rng = np.random.default_rng(13)
        x = rng.normal(0, 0.02, n)
        R = pd.DataFrame(np.nan, index=idx, columns=["a", "b", "c"])
        R.iloc[1:61, 0] = x[1:61]      # a: first half only
        R.iloc[1:121, 1] = x[1:121]    # b: all of it
        R.iloc[61:121, 2] = x[61:121]  # c: second half only
        cov, ok = S._pairwise_cov(R.to_numpy(dtype=float)[1:], 30)
        w = np.array([1.0, -1.0, 1.0])
        self.assertLess(float(w @ cov @ w), 0.0)               # genuinely not PSD
        self.assertEqual(float(cov[0, 2]), 0.0)                # a and c never overlap
        W = pd.DataFrame([[1.0, -1.0, 1.0]] * n, index=idx, columns=["a", "b", "c"])
        pv = S.portfolio_vol(W, R, win, min_obs=30).iloc[-1]
        self.assertTrue(np.isfinite(pv))
        self.assertGreater(pv, 0.0)

    def test_min_obs_must_be_at_least_two(self):
        idx = pd.date_range("2021-01-01", periods=130, freq="D", tz="UTC")
        R = pd.DataFrame(0.01, index=idx, columns=["btc"])
        W = pd.DataFrame(1.0, index=idx, columns=["btc"])
        with self.assertRaises(ValueError):
            S.portfolio_vol(W, R, 120, min_obs=1)

    def test_pairwise_equals_legacy_when_nothing_is_missing(self):
        """The two estimators are the same estimator on a complete panel — the
        difference is entirely about what to do with holes."""
        panel = make_panel(RESEARCH_UNIVERSE, n=500, seed=2)
        closes = S.align(panel)
        rets = closes.pct_change().iloc[1:]      # drop the one genuinely-NaN row
        ref = ((1.0 / S.asset_vol(panel, 60)) / 4).reindex(rets.index).bfill()
        a = S.portfolio_vol(ref, rets, 120, min_obs=60).iloc[200:]
        b = S.portfolio_vol(ref, rets, 120).iloc[200:]
        self.assertLess(float((a - b).abs().max()), 1e-12)


# ------------------------------------- 2. weight caps on a wide universe
class TestWideUniverseCaps(unittest.TestCase):
    def setUp(self):
        self.panel = make_panel(WIDE, n=700, seed=4)
        self.closes = S.align(self.panel)
        self.sig = pd.DataFrame(1.0, index=self.closes.index, columns=self.closes.columns)

    def test_both_caps_hold_on_sixteen_assets(self):
        self.assertEqual(len(self.closes.columns), 16)
        w = S.breadth_vol_target(self.sig, self.panel, 0.40, max_gross=1.5, max_asset=0.75)
        self.assertLessEqual(float(w.abs().sum(axis=1).max()), 1.5 + 1e-9)
        for a in w.columns:
            m = SPECS[a].maint_rate
            self.assertLessEqual(float(w[a].max()),
                                 min(0.75, max_weight_for_distance(0.35, m)) + 1e-9)
            self.assertGreaterEqual(float(w[a].min()),
                                    -min(0.75, max_weight_for_distance(0.35, m, True)) - 1e-9)

    def test_gross_is_the_binding_cap_when_the_universe_is_wide(self):
        """With 16 equal-risk names no single name is near its own cap; the
        gross rescale is what sets the size. That is the shape the campaign
        needs, and it is why max_asset alone is not a risk control here."""
        w = S.breadth_vol_target(self.sig, self.panel, 0.80, max_gross=1.5, max_asset=0.75)
        gross = w.abs().sum(axis=1)
        binding = gross[gross > 1.5 - 1e-9]
        self.assertGreater(len(binding), 50, "expected the gross cap to bind often")
        self.assertLess(float(w.loc[binding.index].abs().max().max()), 0.75,
                        "no single name should have reached the per-asset cap")

    def test_liquidation_cap_is_per_asset_not_one_number(self):
        """A thin alt at 0.59 maintenance can carry far less weight per dollar
        than gold at 0.066. Raise max_asset above every distance cap so the
        distance cap is the one doing the work, then read it off."""
        cols = ["gold", "btc", "eth", "kshib", "vvv", "wld"]
        idx = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
        raw = pd.DataFrame(10.0, index=idx, columns=cols)
        capped = S.cap_weights(raw, max_gross=1e6, max_asset=10.0, min_liq_distance=0.35)
        got = {a: float(capped[a].iloc[0]) for a in cols}
        for a in cols:
            self.assertAlmostEqual(got[a], max_weight_for_distance(0.35, SPECS[a].maint_rate),
                                   places=12)
        # strictly ordered by maintenance rate: the thinner the alt, the smaller the cap
        order = sorted(cols, key=lambda a: SPECS[a].maint_rate)
        self.assertEqual([a for a in sorted(cols, key=lambda a: -got[a])], order)
        self.assertGreater(got["gold"], got["btc"])
        self.assertGreater(got["btc"], got["wld"])
        # and shorts are capped tighter than longs on the same name
        short = S.cap_weights(-raw, max_gross=1e6, max_asset=10.0, min_liq_distance=0.35)
        for a in cols:
            self.assertLess(abs(float(short[a].iloc[0])), got[a])

    def test_unknown_asset_gets_the_tightest_maintenance_rate(self):
        idx = pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC")
        raw = pd.DataFrame(10.0, index=idx, columns=["mystery"])
        capped = S.cap_weights(raw, max_gross=1e6, max_asset=10.0, min_liq_distance=0.35)
        self.assertAlmostEqual(float(capped["mystery"].iloc[0]),
                               max_weight_for_distance(0.35, S.UNKNOWN_MAINT_RATE), places=12)
        self.assertEqual(S.UNKNOWN_MAINT_RATE, max(s.maint_rate for s in SPECS.values()))

    def test_the_four_asset_weight_step_empties_a_sixteen_asset_book(self):
        """The reason step has to scale: 5% of equity is a third of a four-name
        weight and four times a sixteen-name one, so the old step rounds most
        of a wide book to zero and the 'breadth' strategy silently becomes a
        two-name strategy."""
        coarse = S.vol_target(self.sig, self.panel, 0.12, step=0.05)
        fine = S.vol_target(self.sig, self.panel, 0.12, step="auto")
        held_coarse = (coarse.abs() > 0).sum(axis=1).iloc[300:].mean()
        held_fine = (fine.abs() > 0).sum(axis=1).iloc[300:].mean()
        self.assertLess(held_coarse, 4.0)      # measured 2.00 of 16 names
        self.assertGreater(held_fine, 15.0)    # measured 16.00 of 16
        # and the book the coarse step keeps is a third of the size it meant to hold
        self.assertLess(float(coarse.abs().sum(axis=1).iloc[300:].mean()),
                        0.5 * float(fine.abs().sum(axis=1).iloc[300:].mean()))
        self.assertAlmostEqual(S.resolve_step("auto", 16), 0.0125, places=12)

    def test_wide_book_is_not_levered_past_the_cap_by_the_scale_clip(self):
        w = S.breadth_vol_target(self.sig, self.panel, 0.12)
        self.assertLessEqual(float(w.abs().sum(axis=1).max()), 1.5 + 1e-9)
        self.assertGreater(float(w.abs().sum(axis=1).iloc[300:].mean()), 0.0)


# ---------------------------------------- 3. availability-aware helpers
class TestAvailabilityHelpers(unittest.TestCase):
    def setUp(self):
        # sol lists 300 bars in; xrp goes dark for 200 bars (the Coinbase case)
        self.panel = make_panel(("btc", "gold", "sol", "xrp"), n=800, seed=6,
                                listing={"sol": 300}, gaps={"xrp": (400, 600)})
        self.closes = S.align(self.panel)

    def test_tradable_marks_listing_gaps_and_keeps_metals_weekends(self):
        av = S.tradable(self.panel)
        self.assertTrue(av.index.equals(self.closes.index))
        sol_first = self.panel["sol"].index[0]
        self.assertFalse(bool(av.loc[av.index[0], "sol"]))
        self.assertFalse(bool(av.loc[sol_first - pd.Timedelta(days=1), "sol"]))
        self.assertTrue(bool(av.loc[sol_first, "sol"]))
        # inside the xrp blackout, past the staleness tolerance
        gap_lo = self.closes.index[400] + pd.Timedelta(days=30)
        self.assertFalse(bool(av.loc[gap_lo, "xrp"]))
        self.assertTrue(bool(av.loc[self.closes.index[399], "xrp"]))
        # gold does not trade on weekends and must stay available anyway
        sat = [d for d in av.index[400:460] if d.dayofweek == 5]
        self.assertTrue(all(bool(av.loc[d, "gold"]) for d in sat))
        self.assertTrue(av.dtypes.eq(bool).all())

    def test_tradable_honours_an_explicit_index(self):
        idx = self.closes.index[::7]
        av = S.tradable(self.panel, index=idx)
        self.assertTrue(av.index.equals(idx))

    def test_gate_signal_zeroes_exactly_the_untradable_cells(self):
        sig = pd.DataFrame(1.0, index=self.closes.index, columns=self.closes.columns)
        av = S.tradable(self.panel)
        gated = S.gate_signal(sig, self.panel)
        self.assertTrue(((gated == 0.0) == ~av).all().all())
        self.assertTrue(((gated == 1.0) == av).all().all())
        # a mask can be passed in instead of a panel; a panel-less call needs one
        self.assertTrue(gated.equals(S.gate_signal(sig, mask=av)))
        with self.assertRaises(ValueError):
            S.gate_signal(sig)

    def test_gate_signal_zeroes_a_column_the_mask_does_not_cover(self):
        sig = pd.DataFrame(1.0, index=self.closes.index,
                           columns=list(self.closes.columns) + ["ghost"])
        gated = S.gate_signal(sig, self.panel)
        self.assertEqual(float(gated["ghost"].abs().max()), 0.0)

    def test_a_dead_asset_takes_no_weight_and_is_not_priced(self):
        """Inside the blackout the aligned xrp column is a flat forward fill:
        every return in it is an exact zero that never happened. Blind, the
        sizer holds a seventh of the book in a market it could not enter, exit
        or mark, and prices the whole book off a covariance partly made of
        those zeros. With the mask it holds none of it."""
        gap = self.closes.index[(self.closes.index > self.closes.index[430])
                                & (self.closes.index < self.closes.index[590])]
        rets = self.closes.pct_change()
        self.assertEqual(int((rets.loc[gap, "xrp"] != 0).sum()), 0,
                         "the blackout should be an unbroken run of fabricated zeros")

        sig = pd.DataFrame(1.0, index=self.closes.index, columns=self.closes.columns)
        blind = S.vol_target(sig, self.panel, 0.12, step=0.0)
        seeing = S.breadth_vol_target(sig, self.panel, 0.12, step=0.0)
        share = (blind.loc[gap, "xrp"] / blind.loc[gap].abs().sum(axis=1)).mean()
        self.assertGreater(float(share), 0.10)          # measured 13.7% of gross
        self.assertEqual(float(seeing.loc[gap, "xrp"].abs().max()), 0.0)
        # the live names keep their weights; only the dead leg is removed
        for a in ("btc", "gold"):
            self.assertGreater(float(seeing.loc[gap, a].mean()), 0.0)
        # and xrp comes back when the feed does
        back = self.closes.index[self.closes.index > self.panel["xrp"].index[-1]
                                 - pd.Timedelta(days=1)]
        self.assertGreater(float(seeing.loc[back, "xrp"].abs().max()), 0.0)

    def test_the_resumption_bar_is_not_booked_as_one_days_return(self):
        """The day a delisted market reappears, the forward-filled close jumps
        by the whole blackout. That bar is not a return and must not reach the
        covariance."""
        av = S.tradable(self.panel)
        usable = av & av.shift(1).fillna(False)
        resume = self.closes.index[self.closes.index > self.closes.index[590]]
        first_back = av.loc[resume, "xrp"].idxmax()
        self.assertTrue(bool(av.loc[first_back, "xrp"]))
        self.assertFalse(bool(usable.loc[first_back, "xrp"]))
        jump = abs(self.closes["xrp"].pct_change().loc[first_back])
        self.assertGreater(jump, 0.0)

    def test_breadth_vol_target_is_causal(self):
        """Appending future bars must not change past target weights."""
        cut = self.closes.index[600]
        trunc = {a: d[d.index <= cut] for a, d in self.panel.items()}
        sig_full = pd.DataFrame(1.0, index=self.closes.index, columns=self.closes.columns)
        full = S.breadth_vol_target(sig_full, self.panel, 0.12)
        tc = S.align(trunc)
        part = S.breadth_vol_target(pd.DataFrame(1.0, index=tc.index, columns=tc.columns),
                                    trunc, 0.12)
        common = part.index[(part.index >= self.closes.index[300]) & (part.index < cut)]
        self.assertGreater(len(common), 100)
        self.assertLess(float((full.loc[common] - part.loc[common]).abs().max().max()), 1e-12)

    def test_breadth_defaults_are_the_documented_ones(self):
        self.assertEqual(S.BREADTH_SIZING, {"cov_min_obs": 60, "step": "auto"})
        self.assertEqual(S.DEFAULT_MAX_STALE_DAYS, 7)


if __name__ == "__main__":
    unittest.main()
