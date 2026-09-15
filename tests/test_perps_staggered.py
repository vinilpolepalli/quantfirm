"""Backtester tests for a universe whose members list at different times.

No network. Two kinds of test live here:

  * synthetic panels with a hand-built listing calendar, where every number the
    engine should produce can be written down in closed form — an asset that
    lists halfway, an asset that stops quoting, and per-asset trading costs;
  * a REGRESSION lock on the four-asset research universe read from
    ``data/perps/*.csv.gz`` (files on disk, no fetch). The staggered universe
    and the per-asset cost vector must both be inert there, because every
    published number on this desk was produced on btc/eth/gold/silver and would
    otherwise become incomparable. Those tests skip, not fail, when the data
    directory is not present.
"""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantfirm.perps import backtest as B  # noqa: E402
from quantfirm.perps import data as D  # noqa: E402
from quantfirm.perps.specs import TAKER_T0  # noqa: E402

# funding and interest off, so every move in equity is price or cost and can be
# checked against arithmetic done by hand
NOFRILLS = dict(funding="none", interest_apy=0.0, rebalance_band=0.0)


def bars(index, close) -> pd.DataFrame:
    """OHLCV whose open is the previous close and whose high/low straddle both."""
    close = np.asarray(close, dtype=float)
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": np.ones(len(close))}, index=index)


def ramp(n, start=100.0, step=0.5) -> np.ndarray:
    """A price that moves every day, so a mispriced fill or a phantom mark shows."""
    return start + step * np.arange(n)


def targets(index, weights: dict, assets) -> pd.DataFrame:
    t = pd.DataFrame(0.0, index=index, columns=list(assets))
    for a, w in weights.items():
        t[a] = w
    return t


class TestLatelisting(unittest.TestCase):
    """An asset contributes nothing before its first bar."""

    def setUp(self):
        self.idx = pd.date_range("2020-01-01", periods=200, freq="D", tz="UTC")
        self.listed = 120                     # eth's first native bar
        self.panel = {
            "btc": bars(self.idx, ramp(200, 100.0, 0.7)),
            # a first price far from anything btc does, so a back-filled leading
            # price could not hide inside the noise
            "eth": bars(self.idx[self.listed:], ramp(80, 4000.0, -9.0)),
        }
        self.cfg = B.BacktestConfig(rebalance_every=1, min_assets=1, **NOFRILLS)

    def test_starts_at_the_first_listing_not_the_last(self):
        r = B.run(self.panel, targets(self.idx, {"btc": 0.4, "eth": 0.4}, self.panel), self.cfg)
        self.assertEqual(r["start"], str(self.idx[0].date()))
        self.assertEqual(r["n_days"], 200)
        self.assertEqual(r["n_assets"], 2)
        # min_assets=2 waits for eth, which is the OLD behaviour, on request
        r2 = B.run(self.panel, targets(self.idx, {"btc": 0.4, "eth": 0.4}, self.panel),
                   B.BacktestConfig(rebalance_every=1, min_assets=2, **NOFRILLS))
        self.assertEqual(r2["start"], str(self.idx[self.listed].date()))
        self.assertEqual(r2["n_days"], 200 - self.listed)

    def test_pre_listing_book_is_identical_to_the_one_asset_book(self):
        """Before eth lists, the two-asset book IS the btc book, to the bit."""
        wide = B.run(self.panel, targets(self.idx, {"btc": 0.4, "eth": 0.4}, self.panel), self.cfg)
        narrow = B.run({"btc": self.panel["btc"]}, targets(self.idx, {"btc": 0.4}, ["btc"]), self.cfg)
        pre = slice(0, self.listed)
        self.assertTrue(np.array_equal(wide["_series"]["equity"].to_numpy()[pre],
                                       narrow["_series"]["equity"].to_numpy()[pre]))
        # eth books nothing at all before it lists: no weight, no P&L, no fee
        w, pnl = wide["_series"]["weights"]["eth"], wide["_series"]["pnl_asset"]["eth"]
        self.assertTrue((w.iloc[pre] == 0).all())
        self.assertTrue((pnl.iloc[pre] == 0).all())
        self.assertFalse(wide["_series"]["available"]["eth"].iloc[pre].any())
        # and once it lists it does trade, so the equality above is a real test
        self.assertTrue((wide["_series"]["weights"]["eth"].iloc[self.listed + 2:] > 0).all())
        self.assertGreater((wide["_series"]["fees"].iloc[self.listed:] > 0).sum(), 0)

    def test_listing_day_creates_no_equity(self):
        """The bar an asset appears on moves equity by exactly the held book's P&L."""
        wide = B.run(self.panel, targets(self.idx, {"btc": 0.4, "eth": 0.4}, self.panel), self.cfg)
        narrow = B.run({"btc": self.panel["btc"]}, targets(self.idx, {"btc": 0.4}, ["btc"]), self.cfg)
        t = self.listed
        self.assertEqual(wide["_series"]["returns"].iloc[t], narrow["_series"]["returns"].iloc[t])
        self.assertEqual(wide["_series"]["pnl_asset"]["eth"].iloc[t], 0.0)

    def test_unlisted_asset_cannot_liquidate_the_book(self):
        """A back-filled price is never a position, so it can never be a wick."""
        panel = {k: v.copy() for k, v in self.panel.items()}
        # eth's first bar prints 95% below its back-filled level: if the engine
        # ever held a pre-listing unit count, this is a liquidation
        d = panel["eth"].copy()
        d.iloc[0, d.columns.get_loc("low")] = d["close"].iloc[0] * 0.05
        panel["eth"] = d
        cfg = B.BacktestConfig(rebalance_every=1, min_assets=1, max_gross=3.0, max_asset=3.0,
                               min_liq_distance=0.0, **NOFRILLS)
        r = B.run(panel, targets(self.idx, {"btc": 1.0, "eth": 1.0}, panel), cfg)
        self.assertEqual(r["n_liquidations"], 0)


class TestDelistingGap(unittest.TestCase):
    """A position in an asset that stops quoting is closed once, at the last print."""

    def setUp(self):
        self.idx = pd.date_range("2021-01-01", periods=200, freq="D", tz="UTC")
        self.last = 99          # eth's last native bar
        self.back = 160         # and the day it comes back, 3x higher
        eth_idx = self.idx[:self.last + 1].append(self.idx[self.back:])
        eth_px = np.concatenate([ramp(self.last + 1, 2000.0, 3.0),
                                 ramp(len(self.idx) - self.back, 7000.0, 5.0)])
        self.panel = {"btc": bars(self.idx, ramp(200, 100.0, 0.4)),
                      "eth": bars(eth_idx, eth_px)}
        # one entry at t=1 and nothing else on the calendar, so any later fee is
        # the forced exit and nothing else
        self.cfg = B.BacktestConfig(rebalance_every=10_000, min_assets=1, **NOFRILLS)
        self.w = 0.4
        self.r = B.run(self.panel, targets(self.idx, {"eth": self.w}, self.panel), self.cfg)
        self.gone = self.last + 1 + self.cfg.max_stale_days   # first day the mask is False

    def test_mask_turns_off_max_stale_days_after_the_last_bar(self):
        av = self.r["_series"]["available"]["eth"]
        self.assertTrue(av.iloc[self.gone - 1])
        self.assertFalse(av.iloc[self.gone])
        self.assertFalse(av.iloc[self.gone:self.back].any())
        self.assertTrue(av.iloc[self.back])

    def test_closed_once_at_the_last_real_price_paying_the_cost_once(self):
        fees = self.r["_series"]["fees"]
        # exactly two fee events: the entry and the forced exit
        self.assertEqual(list(np.flatnonzero(fees.to_numpy() > 0)), [1, self.gone])
        units = self.w / self.panel["eth"]["open"].iloc[1]      # entry at t=1 on equity 1.0
        last_close = self.panel["eth"]["close"].iloc[self.last]
        side = TAKER_T0.side_cost("eth")
        self.assertAlmostEqual(fees.iloc[self.gone], units * last_close * side, places=12)
        # the exit price is the last REAL close, not the stale open of that bar
        self.assertNotAlmostEqual(self.panel["eth"]["open"].iloc[self.last], last_close, places=6)
        # the exit is real turnover, booked on the notional actually closed
        self.assertAlmostEqual(self.r["_series"]["turnover"].iloc[self.gone],
                               units * last_close / self.r["_series"]["equity"].iloc[self.gone - 1],
                               places=12)
        self.assertEqual(list(np.flatnonzero(self.r["_series"]["turnover"].to_numpy() > 0)),
                         [1, self.gone])
        # and it stays closed: no weight, no P&L, no further cost
        w = self.r["_series"]["weights"]["eth"]
        self.assertTrue((w.iloc[self.gone:] == 0).all())
        self.assertTrue((self.r["_series"]["pnl_asset"]["eth"].iloc[self.gone:] == 0).all())
        self.assertTrue((fees.iloc[self.gone + 1:] == 0).all())

    def test_equity_is_continuous_across_the_exit_and_the_relisting(self):
        eq = self.r["_series"]["equity"]
        fee = self.r["_series"]["fees"].iloc[self.gone]
        # the exit day moves equity by the exit cost and nothing else
        self.assertAlmostEqual(eq.iloc[self.gone], eq.iloc[self.gone - 1] - fee, places=12)
        # the asset returns 3x higher and the book does not book one cent of it
        self.assertAlmostEqual(eq.iloc[self.back], eq.iloc[self.back - 1], places=12)
        self.assertAlmostEqual(self.r["_series"]["returns"].iloc[self.back], 0.0, places=12)
        self.assertGreater(self.panel["eth"]["close"].iloc[-1],
                           2 * self.panel["eth"]["close"].iloc[self.last])

    def test_a_rebalancing_book_re_enters_only_after_the_asset_comes_back(self):
        cfg = B.BacktestConfig(rebalance_every=1, min_assets=1, **NOFRILLS)
        r = B.run(self.panel, targets(self.idx, {"eth": self.w}, self.panel), cfg)
        w = r["_series"]["weights"]["eth"]
        self.assertTrue((w.iloc[self.gone:self.back + 1] == 0).all())
        self.assertGreater(w.iloc[self.back + 2], 0.0)
        self.assertTrue((r["_series"]["fees"].iloc[self.gone + 1:self.back + 1] == 0).all())


class TestPerAssetCosts(unittest.TestCase):
    """fees are a per-asset vector: LINK's 9.7 bps is not BTC's 0.2."""

    def setUp(self):
        self.idx = pd.date_range("2022-01-01", periods=120, freq="D", tz="UTC")
        px = ramp(120, 100.0, 0.3)
        self.panel = {"btc": bars(self.idx, px), "link": bars(self.idx, px)}
        self.cfg = B.BacktestConfig(rebalance_every=10_000, min_assets=1, **NOFRILLS)

    def test_the_wide_market_is_charged_its_own_spread(self):
        fb = B.run(self.panel, targets(self.idx, {"btc": 0.5}, self.panel),
                   self.cfg)["_series"]["fees"].iloc[1]
        fl = B.run(self.panel, targets(self.idx, {"link": 0.5}, self.panel),
                   self.cfg)["_series"]["fees"].iloc[1]
        self.assertAlmostEqual(fb, 0.5 * TAKER_T0.side_cost("btc"), places=12)
        self.assertAlmostEqual(fl, 0.5 * TAKER_T0.side_cost("link"), places=12)
        # btc quotes inside the flat modelling spread, so it pays exactly what it
        # always paid; link quotes outside it and pays more
        self.assertAlmostEqual(TAKER_T0.side_cost("btc"), TAKER_T0.per_side, places=15)
        self.assertAlmostEqual(fl / fb, TAKER_T0.side_cost("link") / TAKER_T0.per_side, places=9)
        self.assertGreater(fl, fb * 1.4)

    def test_a_mixed_book_pays_the_sum_of_its_own_legs(self):
        f = B.run(self.panel, targets(self.idx, {"btc": 0.25, "link": 0.25}, self.panel),
                  self.cfg)["_series"]["fees"].iloc[1]
        self.assertAlmostEqual(f, 0.25 * (TAKER_T0.side_cost("btc") + TAKER_T0.side_cost("link")),
                               places=12)
        # a flat per-side model would have charged the BTC number on both legs
        self.assertGreater(f, 0.5 * TAKER_T0.per_side)


# ------------------------------------------------------------------ regression
DATA_OK = all(os.path.exists(os.path.join(D.DATA_DIR, f"{a}_1d.csv.gz"))
              for a in ("btc", "eth", "gold", "silver"))


@unittest.skipUnless(DATA_OK, "data/perps daily bars not present")
class TestFourAssetRegression(unittest.TestCase):
    """The published four-asset numbers, reproduced from local files.

    The staggered universe and the per-asset cost vector are both inert on
    btc/eth/gold/silver: all four quote every day of the window (metals gaps are
    at most 5 days, inside the 7-day staleness tolerance) and all four quote
    inside the flat modelling half-spread. If one of these fails, a published
    result has silently moved and the cause must be found, not accepted.
    """

    @classmethod
    def setUpClass(cls):
        cls.panel = D.load_panel(("btc", "eth", "gold", "silver"))
        cls.idx = D.align(cls.panel).index

    def test_availability_is_all_true_over_the_published_window(self):
        av = D.availability(self.panel)
        win = av[(av.index >= pd.Timestamp("2018-01-01", tz="UTC"))
                 & (av.index < pd.Timestamp(D.HOLDOUT_START, tz="UTC"))]
        self.assertEqual(len(win), 2738)
        self.assertTrue(win.to_numpy().all())

    def test_fixed_weight_book_is_unchanged(self):
        """Engine-level lock: no strategy code involved, so this pins backtest.py."""
        w = pd.DataFrame({"btc": 0.5, "eth": 0.25, "gold": 0.15, "silver": 0.1}, index=self.idx)
        r = B.run(self.panel, w, B.BacktestConfig(), "2018-01-01", D.HOLDOUT_START)
        for k, v in {"net_sharpe": 0.776, "cagr": 0.3537, "max_drawdown": -0.7356,
                     "ann_turnover": 0.93, "fees_annual": 0.0014, "total_return": 8.6983,
                     "n_days": 2738, "start": "2018-01-01", "end": "2025-06-30",
                     "avg_n_available": 4.0}.items():
            self.assertEqual(r[k], v, k)

    def test_cli_backtest_numbers_are_unchanged(self):
        """`cli backtest --strategy X --split dev --start 2018-01-01`, verbatim."""
        from quantfirm.perps.strategies import REGISTRY, load_all
        load_all()
        published = {
            "trend_long_only": {"net_sharpe": 0.907, "cagr": 0.1067, "max_drawdown": -0.0943,
                                "ann_turnover": 3.76, "fees_annual": 0.0055,
                                "total_return": 1.1401, "n_days": 2738},
            "vol_target_hold": {"net_sharpe": 0.94, "cagr": 0.1545, "max_drawdown": -0.2115,
                                "ann_turnover": 1.68, "fees_annual": 0.0024,
                                "total_return": 1.9378, "n_days": 2738},
        }
        for name, want in published.items():
            r = B.run_strategy(self.panel, REGISTRY[name], {}, B.BacktestConfig(),
                               "2018-01-01", D.HOLDOUT_START)
            for k, v in want.items():
                self.assertEqual(r[k], v, f"{name}.{k}")

    def test_min_assets_recovers_the_legacy_default_window(self):
        """`start=None` used to begin when the LAST asset listed; min_assets=4 is that."""
        from quantfirm.perps.strategies import REGISTRY, load_all
        load_all()
        cfg = B.BacktestConfig(min_assets=4)
        for name, want in (("vol_target_hold", {"net_sharpe": 1.311, "cagr": 0.2146}),
                           ("buy_hold", {"net_sharpe": 1.296, "cagr": 0.6071})):
            r = B.run_strategy(self.panel, REGISTRY[name], {}, cfg, None, D.HOLDOUT_START)
            self.assertEqual(r["start"], "2016-05-18", name)
            self.assertEqual(r["n_days"], 3331, name)
            for k, v in want.items():
                self.assertEqual(r[k], v, f"{name}.{k}")


@unittest.skipUnless(DATA_OK and os.path.exists(os.path.join(D.DATA_DIR, "xrp_1d.csv.gz")),
                     "data/perps daily bars not present")
class TestRealDelisting(unittest.TestCase):
    """XRP left Coinbase for 905 days (2021-01-19 → 2023-07-13). The engine must
    hold nothing across that hole and must not book the re-listing gap."""

    def test_xrp_is_closed_for_the_whole_gap_and_books_no_jump(self):
        panel = D.load_panel(("btc", "xrp"))
        idx = D.align(panel).index
        w = pd.DataFrame({"btc": 0.3, "xrp": 0.3}, index=idx)
        r = B.run(panel, w, B.BacktestConfig(rebalance_every=7, min_assets=1, **NOFRILLS),
                  "2019-06-01", D.HOLDOUT_START)
        s = r["_series"]
        off = pd.Timestamp("2021-01-27", tz="UTC")     # 7 days after the last bar
        on = pd.Timestamp("2023-07-13", tz="UTC")
        gap = (s["weights"].index >= off) & (s["weights"].index < on)
        self.assertTrue((s["weights"]["xrp"][gap] == 0).all())
        self.assertTrue((s["pnl_asset"]["xrp"][gap] == 0).all())
        self.assertEqual(s["available"]["xrp"][gap].sum(), 0)
        # the return on the day it comes back is btc's, not a 905-day price jump
        self.assertAlmostEqual(s["pnl_asset"]["xrp"].loc[on], 0.0, places=12)
        self.assertLess(abs(float(s["returns"].loc[on])), 0.25)
        self.assertEqual(r["n_liquidations"], 0)


if __name__ == "__main__":
    unittest.main()
