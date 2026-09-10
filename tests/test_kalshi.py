"""Unit tests for the Kalshi 15M metals desk (no network)."""
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantfirm.kalshi.fair import (VolEstimator, fair_yes, kelly_fraction,
                                   norm_cdf, taker_fee)
from quantfirm.kalshi.strategy import Params, decide


class TestFair(unittest.TestCase):
    def test_norm_cdf(self):
        self.assertAlmostEqual(norm_cdf(0), 0.5)
        self.assertAlmostEqual(norm_cdf(1.96), 0.975, places=3)

    def test_fair_at_strike_is_half(self):
        self.assertAlmostEqual(fair_yes(100.0, 100.0, 0.001, 10), 0.5)

    def test_fair_above_strike(self):
        p = fair_yes(100.10, 100.0, 0.0001, 10)  # +10bp, sigma*sqrt(tau)~3.2bp
        self.assertGreater(p, 0.99)

    def test_fair_at_expiry_is_indicator(self):
        self.assertEqual(fair_yes(100.01, 100.0, 0.001, 0), 1.0)
        self.assertEqual(fair_yes(99.99, 100.0, 0.001, 0), 0.0)

    def test_taker_fee_worked_examples(self):
        # 10 lots at 50c: 0.07*10*0.25 = 0.175 -> ceil to cent 0.18
        self.assertAlmostEqual(taker_fee(10, 0.50), 0.18)
        # 20 lots at 50c: 0.35 exactly
        self.assertAlmostEqual(taker_fee(20, 0.50), 0.35)
        # wings are cheap: 10 lots at 90c: 0.07*10*0.09 = 0.063 -> 0.07
        self.assertAlmostEqual(taker_fee(10, 0.90), 0.07)

    def test_kelly(self):
        self.assertAlmostEqual(kelly_fraction(0.60, 0.50), 0.2)
        self.assertEqual(kelly_fraction(0.40, 0.50), 0.0)

    def test_vol_estimator_converges(self):
        v = VolEstimator(halflife_min=10, diurnal=False, seed_sigma=0.01)
        for i in range(500):
            v.update(1000000 + 60 * i, 0.0002 if i % 2 else -0.0002)
        self.assertAlmostEqual(v.sigma_1m(0), 0.0002, places=5)


class TestStrategy(unittest.TestCase):
    def base_kwargs(self, **over):
        kw = dict(ticker="T", ts=1000000, s=100.2, k=100.0, sigma_1m=0.0005,
                  close_ts=1000000 + 600, yes_bid=0.60, yes_ask=0.62,
                  bankroll=500.0, open_positions=0,
                  params=Params(macro_blackout_et=()))
        kw.update(over)
        return kw

    def test_enters_yes_when_cheap(self):
        # fair ~ N(ln(1.002)/(0.0005*sqrt(10))) ~ N(1.26) ~ 0.897
        it = decide(**self.base_kwargs())
        self.assertIsNotNone(it)
        self.assertEqual(it.side, "yes")
        self.assertGreater(it.edge, 0.05)

    def test_no_entry_when_fair(self):
        it = decide(**self.base_kwargs(yes_bid=0.88, yes_ask=0.90))
        self.assertIsNone(it)

    def test_enters_no_when_rich(self):
        it = decide(**self.base_kwargs(s=99.8, yes_bid=0.40, yes_ask=0.42))
        self.assertIsNotNone(it)
        self.assertEqual(it.side, "no")

    def test_tau_gates(self):
        self.assertIsNone(decide(**self.base_kwargs(close_ts=1000000 + 60)))
        self.assertIsNone(decide(**self.base_kwargs(close_ts=1000000 + 850)))

    def test_spread_gate(self):
        self.assertIsNone(decide(**self.base_kwargs(yes_bid=0.40, yes_ask=0.62)))

    def test_concurrency_gate(self):
        self.assertIsNone(decide(**self.base_kwargs(open_positions=2)))

    def test_price_bounds(self):
        self.assertIsNone(decide(**self.base_kwargs(
            s=100.5, yes_bid=0.93, yes_ask=0.94)))

    def test_blackout(self):
        p = Params()  # default blackouts on
        # 2026-09-10 12:30:00 UTC == 8:30 ET
        ts = 1789043400
        self.assertTrue(p.blackout(ts))
        self.assertFalse(p.blackout(ts + 3600))

    def test_sizing_respects_bankroll_cap(self):
        it = decide(**self.base_kwargs())
        self.assertLessEqual(it.count * it.limit_price, 0.05 * 500.0 + 1.0)


class TestBacktestCausality(unittest.TestCase):
    def _mini_data(self, tmp, gap_away=False):
        """One market, quotes cheap at decision minute; next candle either
        holds the price or gaps away."""
        import json
        o, c = 1755086400, 1755087300  # 15-min window
        m = {"ticker": "KXGOLD15M-X", "open_time": "2025-08-13T12:00:00Z",
             "close_time": "2025-08-13T12:15:00Z", "floor_strike": 100.0,
             "result": "yes", "expiration_value": "100.30", "status": "settled"}
        # rewrite times to match o/c
        from datetime import datetime, timezone
        m["open_time"] = datetime.fromtimestamp(o, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        m["close_time"] = datetime.fromtimestamp(c, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(os.path.join(tmp, "markets_KXGOLD15M.jsonl"), "w") as f:
            f.write(json.dumps(m) + "\n")
        rows = ["market_ticker,end_period_ts,yes_bid_open,yes_bid_high,yes_bid_low,yes_bid_close,"
                "yes_ask_open,yes_ask_high,yes_ask_low,yes_ask_close,"
                "price_open,price_high,price_low,price_close,volume,open_interest"]
        for i in range(1, 16):
            ts = o + 60 * i
            if i < 5:  # pre-jump: s == K exactly, fair = 0.5, market agrees
                bid, ask, ask_open = 0.48, 0.52, 0.52
            else:      # post-jump: fair ~1.0 but market only at 0.55/0.60
                bid, ask = 0.55, 0.60
                ask_open = 0.95 if (gap_away and i >= 6) else 0.60
            rows.append(f"KXGOLD15M-X,{ts},{bid},{bid},{bid},{bid},"
                        f"{ask_open},{ask},{ask},{ask},0.58,0.58,0.58,0.58,100,100")
        with open(os.path.join(tmp, "candles_KXGOLD15M.csv"), "w") as f:
            f.write("\n".join(rows))
        # underlying: flat then jumps +25bp at minute 4 (bar close ts = o+240)
        import pandas as pd
        idx, px = [], []
        for i in range(-600, 16):  # long history to warm the vol EWMA
            ts = o + 60 * i
            idx.append(pd.Timestamp(ts - 60, unit="s", tz="UTC"))
            if i >= 4:
                px.append(100.25)          # the jump
            elif i >= 0:
                px.append(100.0)           # window start: flat, s == K
            else:
                px.append(100.0 * (1 + (0.0001 if i % 3 == 0 else -0.0001)))
        pd.DataFrame({"close": px}, index=idx).to_csv(
            os.path.join(tmp, "yf_gold_1m.csv"))

    def test_fill_and_settle(self):
        from quantfirm.kalshi.backtest import Backtest
        with tempfile.TemporaryDirectory() as tmp:
            self._mini_data(tmp)
            bt = Backtest(tmp, bankroll=500.0)
            m = bt.run(Params(theta=0.03, macro_blackout_et=(), diurnal=False))
            self.assertEqual(m["n_trades"], 1)
            t = m["trades"][0]
            self.assertEqual(t.side, "yes")
            self.assertGreater(t.pnl, 0)  # bought ~0.60, settled yes

    def test_gap_away_means_no_fill(self):
        from quantfirm.kalshi.backtest import Backtest
        with tempfile.TemporaryDirectory() as tmp:
            self._mini_data(tmp, gap_away=True)
            bt = Backtest(tmp, bankroll=500.0)
            m = bt.run(Params(theta=0.03, macro_blackout_et=(), diurnal=False))
            self.assertEqual(m["n_trades"], 0)
            self.assertGreaterEqual(m["skipped"].get("gapped_away", 0), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
