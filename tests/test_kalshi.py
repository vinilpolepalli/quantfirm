"""Unit tests for the Kalshi 15M metals desk (no network)."""
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantfirm.kalshi.fair import (VolEstimator, fair_yes, implied_sigma_1m,
                                   kelly_fraction, norm_cdf, taker_fee)
from quantfirm.kalshi.strategies import (favorite_blind, late_lock, registry)
from quantfirm.kalshi.strategy import Params, decide
from quantfirm.kalshi.universe import BANKROLL, SERIES


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

    def test_implied_sigma_inverts_fair(self):
        s, k, sig, tau = 100.20, 100.0, 0.0008, 8.0
        p = fair_yes(s, k, sig, tau)
        inv = implied_sigma_1m(s, k, p, tau)
        self.assertIsNotNone(inv)
        self.assertAlmostEqual(inv, sig, places=5)

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

    def test_decide_ignores_extra_kwargs(self):
        it = decide(**self.base_kwargs(), f_now=100.2, f_open=100.0,
                    open_ts=999940, metal="gold")
        self.assertIsNotNone(it)


class TestNewStrategies(unittest.TestCase):
    def _kw(self, **over):
        kw = dict(ticker="T", ts=1000000, s=100.4, k=100.0, sigma_1m=0.0004,
                  close_ts=1000000 + 180, yes_bid=0.90, yes_ask=0.92,
                  bankroll=BANKROLL, open_positions=0,
                  params=Params(macro_blackout_et=(), tau_min_s=90,
                                tau_max_s=360, price_min=0.50, price_max=0.96,
                                theta=0.03, min_count=5, max_stake_frac=0.08),
                  recent_volume=200.0)
        kw.update(over)
        return kw

    def test_late_lock_buys_certain_yes(self):
        it = late_lock(**self._kw())
        self.assertIsNotNone(it)
        self.assertEqual(it.side, "yes")
        self.assertGreaterEqual(it.count, 5)

    def test_late_lock_skips_coin_flip(self):
        it = late_lock(**self._kw(s=100.0, yes_bid=0.49, yes_ask=0.51))
        self.assertIsNone(it)

    def test_favorite_blind_takes_rich_side(self):
        p = Params(macro_blackout_et=(), tau_min_s=180, tau_max_s=720,
                   price_min=0.72, price_max=0.94, min_count=5,
                   max_stake_frac=0.08)
        it = favorite_blind(
            ticker="T", ts=1000000, s=100.0, k=100.0, sigma_1m=0.001,
            close_ts=1000000 + 400, yes_bid=0.80, yes_ask=0.82,
            bankroll=BANKROLL, open_positions=0, params=p, recent_volume=200)
        self.assertIsNotNone(it)
        self.assertEqual(it.side, "yes")

    def test_registry_has_controls_and_candidates(self):
        names = {s.name for s in registry()}
        for n in ("ctrl_always_yes", "oracle_lag", "late_lock",
                  "favorite_blind", "open_fade"):
            self.assertIn(n, names)

    def test_universe_covers_wti(self):
        self.assertIn("KXWTI15M", SERIES)
        self.assertEqual(SERIES["KXWTI15M"], "wti")

    def test_favorite_div_is_registered(self):
        names = {s.name for s in registry()}
        self.assertIn("favorite_div", names)


class TestDiversifyAndHalt(unittest.TestCase):
    def test_corr_allows_metal_and_energy(self):
        from quantfirm.kalshi.halt import blocked_by_corr
        from types import SimpleNamespace
        open_ = [SimpleNamespace(metal="gold", side="yes")]
        self.assertTrue(blocked_by_corr("silver", "yes", open_))
        self.assertFalse(blocked_by_corr("silver", "no", open_))
        self.assertFalse(blocked_by_corr("wti", "yes", open_))
        self.assertFalse(blocked_by_corr("copper", "yes", open_))
        open_.append(SimpleNamespace(metal="wti", side="no"))
        self.assertTrue(blocked_by_corr("natgas", "no", open_))
        self.assertFalse(blocked_by_corr("natgas", "yes", open_))

    def test_langgraph_desk_compiles(self):
        from quantfirm.kalshi.agent import build_desk
        from quantfirm.kalshi.paper import PaperEngine
        from quantfirm.kalshi.strategy import Params
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            eng = PaperEngine(
                params=Params(macro_blackout_et=()),
                state_path=os.path.join(tmp, "s.json"),
                log_path=os.path.join(tmp, "t.csv"),
                metals=("gold",),
                use_demo=False, maker=False)
            g = build_desk(eng, live=False)
            self.assertTrue(callable(g.invoke))


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


class TestMakerFillRealism(unittest.TestCase):
    """Guards against the fill artifacts that invalidated both backtests."""

    def test_fill_requires_a_real_print_not_a_quote_touch(self):
        """A maker fill must be evidenced by a TRADE at our level.

        Regression: the fill test used to read the bid/ask range. Since we
        post at best_bid+1c, `bid_low <= our_price` is true by construction,
        so every quote filled instantly and the backtest printed a bogus
        +944%/t=11. Quote range must not create fills.
        """
        from quantfirm.kalshi.maker import MakerBacktest, MakerParams
        p = MakerParams(fill_mode="through", count=10, queue_ahead_mult=3.0)
        # bid/ask straddle our price, but NO trade printed at or below it
        candle = {"bid_low": 0.50, "bid_close": 0.59, "ask_high": 0.62,
                  "px_low": 0.61, "px_high": 0.64, "volume": 5000.0}
        filled, _ = MakerBacktest._test_fill(candle, "yes", 0.60, 0.0, p)
        self.assertFalse(filled, "quote-range touch must not fill a maker order")
        # now a seller actually prints through our level
        candle["px_low"] = 0.58
        filled, _ = MakerBacktest._test_fill(candle, "yes", 0.60, 0.0, p)
        self.assertTrue(filled, "a real print through our level should fill")

    def test_no_fill_without_volume(self):
        from quantfirm.kalshi.maker import MakerBacktest, MakerParams
        p = MakerParams(fill_mode="through", count=10)
        candle = {"px_low": 0.10, "px_high": 0.90, "volume": 0.0}
        filled, _ = MakerBacktest._test_fill(candle, "yes", 0.60, 0.0, p)
        self.assertFalse(filled)

    def test_no_side_uses_ask_side_prints(self):
        from quantfirm.kalshi.maker import MakerBacktest, MakerParams
        p = MakerParams(fill_mode="through", count=10)
        # long NO at 0.60 == resting a YES ask at 0.40; needs a BUY print >0.40
        candle = {"px_low": 0.30, "px_high": 0.35, "volume": 1000.0}
        filled, _ = MakerBacktest._test_fill(candle, "no", 0.60, 0.0, p)
        self.assertFalse(filled)
        candle["px_high"] = 0.45
        filled, _ = MakerBacktest._test_fill(candle, "no", 0.60, 0.0, p)
        self.assertTrue(filled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
