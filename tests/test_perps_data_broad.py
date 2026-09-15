"""The breadth data layer: 23 listed perps, staggered listings, delisting gaps.

Kalshi lists 23 perps and their proxies do not share a start date — BTC has
4,076 daily bars, HYPE has 223 — and one of them (XRP) has a 905-day hole in
the middle where Coinbase had delisted it. `align()` forward-fills, so inside
that hole the price frame shows a flat line that a vol-targeted or
minimum-variance book would read as a zero-risk asset and load up on. These
tests pin the mask that stops that: `availability()` must be False wherever
the only thing `align()` has to show is a stale carry-forward.

No network: the module's HTTP session is disabled for the whole file, so a
fetcher that slips into a code path under test fails loudly instead of
silently hitting Coinbase.
"""
import gzip
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantfirm.perps import data as D  # noqa: E402

_NET = None


def setUpModule():
    """Hard-fail any HTTP the tests provoke. requests routes get/post through
    Session.request, so one patch closes the whole door."""
    global _NET
    _NET = mock.patch.object(
        D._S, "request",
        side_effect=AssertionError("network call in tests/test_perps_data_broad.py"))
    _NET.start()


def tearDownModule():
    if _NET is not None:
        _NET.stop()


def bars(dates, price=100.0) -> pd.DataFrame:
    """Native OHLCV on exactly ``dates`` — no filling, no reindexing."""
    idx = pd.DatetimeIndex(pd.to_datetime(dates, utc=True)).normalize()
    close = np.asarray(price, dtype=float) * np.ones(len(idx)) if np.isscalar(price) \
        else np.asarray(price, dtype=float)
    return pd.DataFrame({"open": close, "high": close, "low": close,
                         "close": close, "volume": np.ones(len(idx))}, index=idx)


def daily(start, end):
    return pd.date_range(start, end, freq="D", tz="UTC")


class TestAvailabilityGap(unittest.TestCase):
    """A synthetic delisting: 'live' prints every day, 'gappy' goes dark."""

    def setUp(self):
        self.live = daily("2020-01-01", "2020-06-30")
        # dark from 2020-03-02 through 2020-04-30 inclusive (60 missing days),
        # trading again on 2020-05-01 at a very different price.
        before = daily("2020-01-01", "2020-03-01")
        after = daily("2020-05-01", "2020-06-30")
        self.gap_start = pd.Timestamp("2020-03-02", tz="UTC")
        self.gap_end = pd.Timestamp("2020-04-30", tz="UTC")
        self.last_native = pd.Timestamp("2020-03-01", tz="UTC")
        self.resume = pd.Timestamp("2020-05-01", tz="UTC")
        self.panel = {
            "live": bars(self.live),
            "gappy": pd.concat([bars(before, 10.0), bars(after, 30.0)]),
        }

    def test_false_inside_the_gap_and_true_after_it(self):
        av = D.availability(self.panel, max_stale_days=7)
        deep = pd.Timestamp("2020-04-01", tz="UTC")           # middle of the hole
        self.assertFalse(bool(av.loc[deep, "gappy"]))
        self.assertTrue(bool(av.loc[deep, "live"]))            # the gap is per asset
        self.assertTrue(bool(av.loc[self.resume, "gappy"]))    # the day it prints again
        self.assertTrue(bool(av.loc[self.last_native, "gappy"]))  # the day before it went dark
        # everything from 8 days after the last native bar to the day before it
        # resumes is unavailable, with no True islands in between
        window = daily(self.last_native + pd.Timedelta(days=8), self.resume - pd.Timedelta(days=1))
        self.assertFalse(av.loc[window, "gappy"].any())

    def test_the_gap_is_exactly_where_align_is_lying(self):
        """The property that motivates the mask: wherever availability is False
        inside the sample, align() is showing a forward-filled price."""
        closes = D.align(self.panel)
        av = D.availability(self.panel, max_stale_days=0)
        native = closes.index.isin(self.panel["gappy"].index)
        stale = ~native & (closes.index >= self.panel["gappy"].index[0])
        # align() carries the last real close across the whole hole ...
        self.assertTrue((closes.loc[stale, "gappy"] == 10.0).all())
        self.assertEqual(closes["gappy"].loc[stale].pct_change().dropna().abs().max(), 0.0)
        # ... and the mask is False on exactly those days.
        self.assertFalse(av.loc[stale, "gappy"].any())
        self.assertTrue(av.loc[native, "gappy"].all())

    def test_false_before_the_first_bar(self):
        av = D.availability(self.panel, max_stale_days=7)
        # 'gappy' and 'live' start together here, so add a late lister
        panel = dict(self.panel, late=bars(daily("2020-06-01", "2020-06-30")))
        av = D.availability(panel, max_stale_days=7)
        self.assertFalse(av.loc[:pd.Timestamp("2020-05-31", tz="UTC"), "late"].any())
        self.assertTrue(av.loc[pd.Timestamp("2020-06-01", tz="UTC"), "late"])
        self.assertEqual(int(av["late"].sum()), 30)

    def test_stale_tolerance_is_the_documented_number(self):
        """max_stale_days=n keeps an asset available for exactly n days past its
        last native bar — the knob that lets a metals weekend through."""
        for n in (0, 1, 3, 7, 14):
            av = D.availability(self.panel, max_stale_days=n)
            gap_days = int(av.loc[self.gap_start:self.gap_end, "gappy"].sum())
            self.assertEqual(gap_days, n, f"max_stale_days={n}")
        with self.assertRaises(ValueError):
            D.availability(self.panel, max_stale_days=-1)

    def test_weekday_only_asset_stays_available_at_the_default(self):
        """Metals print Mon–Fri; a 2-day weekend (or a 4-day holiday) is the
        contract's calendar, not an outage, so the default must not flag it."""
        wd = pd.date_range("2020-01-01", "2020-06-30", freq="B", tz="UTC")
        panel = {"crypto": bars(daily("2020-01-01", "2020-06-30")), "metal": bars(wd)}
        av = D.availability(panel, max_stale_days=7)
        self.assertTrue(av["metal"].all())
        # and at zero tolerance the weekends correctly read as no-bar days
        av0 = D.availability(panel, max_stale_days=0)
        self.assertEqual(int(av0["metal"].sum()), len(wd))

    def test_shape_columns_and_index_match_align(self):
        av = D.availability(self.panel)
        closes = D.align(self.panel)
        self.assertEqual(list(av.columns), list(self.panel))
        pd.testing.assert_index_equal(av.index, closes.index)
        self.assertTrue((av.dtypes == bool).all())

    def test_index_override_scores_on_the_callers_frame(self):
        idx = daily("2020-03-20", "2020-03-31")
        av = D.availability(self.panel, index=idx)
        pd.testing.assert_index_equal(av.index, idx)
        self.assertFalse(av["gappy"].any())
        self.assertTrue(av["live"].all())


class TestFirstBarAgainstFiles(unittest.TestCase):
    """first_bar / last_bar / listing_table read the file, not a cache."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(D, "DATA_DIR", self.tmp.name)
        p.start()
        self.addCleanup(p.stop)
        self.dates = list(daily("2021-04-05", "2021-04-09")) + list(daily("2021-05-01", "2021-05-03"))
        self._write("widget", bars(pd.DatetimeIndex(self.dates)))

    def _write(self, asset, df):
        out = df.reset_index().rename(columns={"index": "ts"})
        out.columns = ["ts", "open", "high", "low", "close", "volume"]
        with gzip.open(os.path.join(self.tmp.name, f"{asset}_1d.csv.gz"), "wt") as f:
            out.to_csv(f, index=False)

    def test_first_and_last_bar_match_the_file(self):
        self.assertEqual(D.first_bar("widget"), pd.Timestamp("2021-04-05", tz="UTC"))
        self.assertEqual(D.last_bar("widget"), pd.Timestamp("2021-05-03", tz="UTC"))
        # and match what load_daily reports, which is the file itself
        d = D.load_daily("widget")
        self.assertEqual(D.first_bar("widget"), d.index[0])
        self.assertEqual(D.last_bar("widget"), d.index[-1])
        self.assertEqual(len(d), len(self.dates))

    def test_listing_table_reports_rows_and_the_longest_gap(self):
        t = D.listing_table(["widget"])
        row = t.loc["widget"]
        self.assertEqual(row["n_rows"], len(self.dates))
        self.assertEqual(row["first_bar"], pd.Timestamp("2021-04-05", tz="UTC"))
        self.assertEqual(row["last_bar"], pd.Timestamp("2021-05-03", tz="UTC"))
        self.assertEqual(row["max_gap_days"], 22.0)   # 2021-04-09 → 2021-05-01

    def test_missing_asset_raises_with_a_usable_message(self):
        with self.assertRaises(FileNotFoundError) as e:
            D.first_bar("nosuchthing")
        self.assertIn("nosuchthing", str(e.exception))
        with self.assertRaises(FileNotFoundError):
            D.load_panel(["widget", "nosuchthing"])
        self.assertEqual(list(D.load_panel(["widget", "nosuchthing"], skip_missing=True)),
                         ["widget"])

    def test_alias_resolves_to_the_venue_ticker_name(self):
        """KXKSHIBPERP's contract is 1000 SHIB; the file is kshib, but a caller
        who types 'shib' must not get a FileNotFoundError."""
        self._write("kshib", bars(daily("2021-09-09", "2021-09-20")))
        self.assertEqual(D.resolve_asset("shib"), "kshib")
        self.assertEqual(D.first_bar("shib"), D.first_bar("kshib"))
        self.assertEqual(len(D.load_daily("shib")), len(D.load_daily("kshib")))


class TestUniverseWiring(unittest.TestCase):
    def test_every_listed_perp_has_a_proxy(self):
        self.assertEqual(len(D.proxy_assets()), 23)
        self.assertEqual(len(set(D.proxy_assets())), 23)
        self.assertEqual(len(D.COINBASE_PRODUCTS), 21)
        self.assertEqual(set(D.YAHOO), {"gold", "silver"})
        # every Coinbase product is a distinct USD spot pair
        prods = list(D.COINBASE_PRODUCTS.values())
        self.assertEqual(len(set(prods)), len(prods))
        self.assertTrue(all(p.endswith("-USD") for p in prods))
        # start hints cover every product, and none predates Coinbase
        self.assertEqual(set(D.COINBASE_START), set(D.COINBASE_PRODUCTS))
        self.assertTrue(all(pd.Timestamp(v) >= pd.Timestamp("2015-01-01")
                            for v in D.COINBASE_START.values()))
        # funding stress symbols, where they exist, are Binance USDT perps
        self.assertTrue(set(D.BINANCE_FUNDING) <= set(D.COINBASE_PRODUCTS))
        self.assertTrue(all(s.endswith("USDT") for s in D.BINANCE_FUNDING.values()))

    def test_update_all_fetches_new_products_with_their_start_hint(self):
        """Wiring check, no network: update_all must route each asset to its
        mapped product and pass the probed start date."""
        seen = []

        def fake_coinbase(product, start="2015-01-01"):
            seen.append((product, start))
            return pd.DataFrame({"ts": daily("2023-05-18", "2023-05-20"),
                                 "open": 1.0, "high": 1.0, "low": 1.0,
                                 "close": 1.0, "volume": 1.0})

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(D, "fetch_coinbase_daily", side_effect=fake_coinbase), \
             mock.patch.object(D, "DATA_DIR", tmp.name):
            meta = D.update_all(assets=("sui", "hype"), kalshi=False, funding=False, log=lambda *a: None)
        self.assertEqual(seen, [("SUI-USD", D.COINBASE_START["sui"]),
                                ("HYPE-USD", D.COINBASE_START["hype"])])
        self.assertIn("sui_1d", meta["files"])
        self.assertIn("hype_1d", meta["files"])
        self.assertTrue(os.path.exists(os.path.join(tmp.name, "sui_1d.csv.gz")))

    def test_update_all_skips_the_kalshi_leg_for_assets_with_no_spec(self):
        """An asset can have a proxy before specs.py has a PerpSpec for it;
        that must not raise, and must not invent a ticker."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(D, "fetch_coinbase_daily",
                               return_value=pd.DataFrame({"ts": daily("2024-01-01", "2024-01-03"),
                                                          "open": 1.0, "high": 1.0, "low": 1.0,
                                                          "close": 1.0, "volume": 1.0})), \
             mock.patch.object(D, "fetch_kalshi_funding") as kf, \
             mock.patch.object(D, "SPECS", {}), \
             mock.patch.object(D, "DATA_DIR", tmp.name):
            D.update_all(assets=("vvv",), kalshi=True, funding=False, log=lambda *a: None)
        kf.assert_not_called()

    def test_update_all_all_keyword_covers_every_proxy(self):
        with mock.patch.object(D, "fetch_coinbase_daily",
                               return_value=pd.DataFrame(columns=["ts"])) as cb, \
             mock.patch.object(D, "fetch_yahoo_daily",
                               return_value=pd.DataFrame(columns=["ts"])) as yh, \
             mock.patch.object(D, "_write_csv") as w, \
             mock.patch("builtins.open", mock.mock_open()):
            D.update_all(assets="all", kalshi=False, funding=False, log=lambda *a: None)
        self.assertEqual(cb.call_count, 21)
        self.assertEqual(yh.call_count, 2)
        w.assert_not_called()   # empty frames write nothing


@unittest.skipUnless(os.path.isdir(D.DATA_DIR), "no cached perps data")
class TestShippedFiles(unittest.TestCase):
    """Guards on the files actually in data/perps — cheap, and they are the
    evidence a breadth campaign cites."""

    def test_every_listed_perp_has_a_file_with_the_shared_schema(self):
        cols = ["open", "high", "low", "close", "volume"]
        missing = [a for a in D.proxy_assets()
                   if not os.path.exists(os.path.join(D.DATA_DIR, f"{a}_1d.csv.gz"))]
        self.assertEqual(missing, [], f"no daily proxy for {missing}")
        for a in D.proxy_assets():
            d = D.load_daily(a)
            self.assertEqual(list(d.columns), cols, a)
            self.assertTrue(d.index.is_monotonic_increasing, a)
            self.assertTrue(d.index.is_unique, a)
            self.assertEqual(str(d.index.tz), "UTC", a)
            self.assertTrue((d["close"] > 0).all(), a)
            self.assertGreater(len(d), 200, a)

    def test_xrp_delisting_reads_as_not_tradable(self):
        """The real case the mask exists for: Coinbase delisted XRP on
        2021-01-19 (SEC suit) and relisted it 2023-07-13. align() carries the
        old close across the hole and then prints a +170% 'return' on the
        relist; availability() must be False for the whole stretch."""
        panel = D.load_panel(("btc", "xrp"))
        av = D.availability(panel, max_stale_days=7)
        closes = D.align(panel)
        dark = pd.Timestamp("2022-01-01", tz="UTC")
        self.assertFalse(bool(av.loc[dark, "xrp"]))
        self.assertTrue(bool(av.loc[dark, "btc"]))
        self.assertTrue(bool(av.loc[pd.Timestamp("2023-07-13", tz="UTC"), "xrp"]))
        # the artifact the mask suppresses is huge, so this is not a nicety
        relist = pd.Timestamp("2023-07-13", tz="UTC")
        self.assertGreater(closes["xrp"].pct_change().loc[relist], 1.0)
        # a strategy that requires the asset to have been tradable on BOTH ends
        # of the return never sees that move: the prior day is masked out.
        tradable_return = closes["xrp"].pct_change().where(av["xrp"] & av["xrp"].shift(1))
        self.assertTrue(pd.isna(tradable_return.loc[relist]))
        # and no |return| above 100% survives the mask anywhere in the sample
        self.assertLess(tradable_return.abs().max(), 1.0)

    def test_first_bars_are_staggered_so_breadth_is_time_varying(self):
        """If every asset started on the same day there would be no reason for
        an availability API at all."""
        firsts = {a: D.first_bar(a) for a in D.proxy_assets()}
        self.assertGreater(len(set(firsts.values())), 15)
        self.assertLess(firsts["btc"], firsts["hype"])
        panel = D.load_panel(D.proxy_assets())
        breadth = D.availability(panel, max_stale_days=7).sum(axis=1)
        self.assertEqual(int(breadth.iloc[-1]), 23)          # all 23 quoting today
        self.assertLess(int(breadth.loc["2016-01-04"]), 6)   # only metals + btc back then
        # breadth is not monotonic: XRP's delisting takes one back out again
        self.assertFalse(breadth.is_monotonic_increasing)


if __name__ == "__main__":
    unittest.main()
