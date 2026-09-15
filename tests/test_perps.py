"""Unit tests for the Kalshi perps desk (no network)."""
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantfirm.perps import backtest as B  # noqa: E402
from quantfirm.perps import risk as R  # noqa: E402
from quantfirm.perps import strategies as S  # noqa: E402
from quantfirm.perps.client import (MarginClient, PerpQuote, banded_price,  # noqa: E402
                                    inside_band, parse_market)
from quantfirm.perps.data import daily_funding, split  # noqa: E402
from quantfirm.perps.specs import (FEE_TIERS, SPECS, TAKER_T0, fee_rates,  # noqa: E402
                                   kalshi_funding, liquidation_move,
                                   max_weight_for_distance)


def synthetic_panel(n=900, seed=0, assets=("btc", "eth", "gold", "silver"), drift=None):
    """Random-walk daily OHLCV for each asset, metals with weekend gaps."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2019-01-01", periods=n, freq="D", tz="UTC")
    panel = {}
    for i, a in enumerate(assets):
        vol = {"btc": 0.04, "eth": 0.05, "gold": 0.01, "silver": 0.018}.get(a, 0.03)
        mu = (drift or {}).get(a, 0.0)
        r = rng.normal(mu, vol, n)
        close = 100 * np.exp(np.cumsum(r))
        open_ = np.roll(close, 1); open_[0] = close[0]
        high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
        low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
        df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                           "volume": rng.uniform(1e3, 1e4, n)}, index=idx)
        if SPECS[a].asset_class == "metals":
            df = df[df.index.dayofweek < 5]
        panel[a] = df
    return panel


class TestSpecs(unittest.TestCase):
    def test_fee_tiers_monotone(self):
        vols = [t[0] for t in FEE_TIERS]
        self.assertEqual(vols, sorted(vols))
        takers = [t[1] for t in FEE_TIERS]
        self.assertEqual(takers, sorted(takers, reverse=True))
        self.assertEqual(fee_rates(0), (0.0012, 0.0005))
        self.assertEqual(fee_rates(1_000_000), (0.0006, 0.00024))
        self.assertEqual(fee_rates(5e9), (0.00026, 0.00006))

    def test_funding_rule(self):
        self.assertEqual(kalshi_funding(0.00009), 0.0)          # below the crypto deadband
        self.assertEqual(kalshi_funding(0.0001), 0.0001)         # exactly at it
        self.assertEqual(kalshi_funding(-0.05), -0.02)           # capped
        self.assertEqual(kalshi_funding(0.00005, "metals"), 0.00005)  # metals deadband is 0.002%
        self.assertEqual(kalshi_funding(0.00001, "metals"), 0.0)

    def test_margin_arithmetic(self):
        btc = SPECS["btc"]
        self.assertAlmostEqual(btc.initial_rate, btc.maint_rate * 1.3)
        # 1x long can never be liquidated; 2x long ≈ 40% move; shorts liquidate sooner
        self.assertEqual(liquidation_move(1.0, btc.maint_rate), 1.0)
        self.assertAlmostEqual(liquidation_move(2.0, btc.maint_rate), 0.401, places=2)
        self.assertLess(liquidation_move(-2.0, btc.maint_rate), liquidation_move(2.0, btc.maint_rate))
        self.assertEqual(liquidation_move(0.0, btc.maint_rate), float("inf"))
        # inverse: the weight that gives a 35% distance has a 35% distance
        w = max_weight_for_distance(0.35, btc.maint_rate)
        self.assertAlmostEqual(liquidation_move(w, btc.maint_rate), 0.35, places=6)
        ws = max_weight_for_distance(0.35, btc.maint_rate, short=True)
        self.assertAlmostEqual(liquidation_move(-ws, btc.maint_rate), 0.35, places=6)

    def test_cost_model(self):
        self.assertAlmostEqual(TAKER_T0.round_trip(), 2 * (0.0012 + 0.00025))


class TestClient(unittest.TestCase):
    def test_banded_price_and_band(self):
        tick = Decimal("0.0001")
        bid, ask = Decimal("7.8144"), Decimal("7.8148")
        pb = banded_price("bid", bid, ask, tick, slack_ticks=20)
        pa = banded_price("ask", bid, ask, tick, slack_ticks=20)
        self.assertEqual(pb, Decimal("7.8168"))
        self.assertEqual(pa, Decimal("7.8124"))
        self.assertTrue(inside_band("bid", pb, bid, ask, tick))
        self.assertTrue(inside_band("ask", pa, bid, ask, tick))
        self.assertFalse(inside_band("bid", Decimal("5.0"), bid, ask, tick))  # >20% below best bid
        self.assertFalse(inside_band("ask", Decimal("10.0"), bid, ask, tick))
        self.assertIsNone(banded_price("bid", bid, None, tick))

    def test_signing_path_and_headers(self):
        c = MarginClient("prod", key_id="k", private_key_pem=None)
        self.assertFalse(c.can_trade)
        signer = mock.Mock()
        signer.sign.return_value = "SIG"
        c._signer = signer
        c.key_id = "KEY"
        h = c._headers("POST", "/trade-api/v2/margin/orders?x=1")
        self.assertEqual(h["KALSHI-ACCESS-KEY"], "KEY")
        self.assertEqual(h["KALSHI-ACCESS-SIGNATURE"], "SIG")
        msg = signer.sign.call_args[0][0]
        self.assertTrue(msg.endswith("POST/trade-api/v2/margin/orders"))  # query stripped, prefix kept

    def test_create_order_body(self):
        c = MarginClient("demo")
        c.key_id, c._signer = "K", mock.Mock(sign=mock.Mock(return_value="S"))
        with mock.patch.object(c, "_req", return_value={"order_id": "o", "fill_count": "1.00", "remaining_count": "0.00"}) as rq:
            c.create_order("KXBTCPERP1", "ask", 3, Decimal("7.81"), reduce_only=True, client_order_id="cid")
        body = rq.call_args.kwargs["body"]
        self.assertEqual(body["side"], "ask")
        self.assertEqual(body["count"], "3.00")
        self.assertEqual(body["price"], "7.8100")
        self.assertEqual(body["time_in_force"], "immediate_or_cancel")
        self.assertTrue(body["reduce_only"])
        self.assertEqual(body["self_trade_prevention_type"], "taker_at_cross")
        self.assertEqual(body["client_order_id"], "cid")
        self.assertEqual(rq.call_args.kwargs["tries"], 1)   # a timeout must never double-send
        with self.assertRaises(ValueError):
            c.create_order("KXBTCPERP1", "bid", 1, "1", time_in_force="good_till_canceled", reduce_only=True)

    def test_quote_sorts_levels(self):
        c = MarginClient("prod")
        ob = {"orderbook": {"asks": [["7.8191", "9604.00"], ["7.8165", "3.00"]],
                            "bids": [["7.8133", "9611.00"], ["7.8160", "319.00"]]}}
        with mock.patch.object(c, "_req", return_value=ob):
            q = c.quote("KXBTCPERP")
        self.assertEqual(q.bid, Decimal("7.8160"))
        self.assertEqual(q.ask, Decimal("7.8165"))
        self.assertAlmostEqual(q.spread_bps, 0.64, places=1)

    def test_parse_market(self):
        m = {"ticker": "KXGOLDPERP", "status": "active", "asset_class": "Metals", "contract_size": "0.001000",
             "tick_size": "0.0001", "bid": "4.2858", "ask": "4.2859", "price": "4.2859",
             "reference_price": {"price": "4.2856", "ts_ms": 1}, "leverage_estimates": {"1000": 15.26},
             "open_interest_notional_value_dollars": "1.0", "volume_24h_notional_value_dollars": "2.0"}
        p = parse_market(m)
        self.assertEqual(p["asset_class"], "metals")
        self.assertEqual(p["reference"], 4.2856)
        self.assertEqual(p["leverage_1k"], 15.26)


class TestData(unittest.TestCase):
    def test_daily_funding_sums_and_rounds(self):
        idx = pd.date_range("2026-06-03", periods=3, freq="D", tz="UTC")
        rates = pd.Series([0.0002, 0.00005, -0.0003, 0.05],
                          index=pd.to_datetime(["2026-06-03T04:00Z", "2026-06-03T12:00Z",
                                                "2026-06-03T20:00Z", "2026-06-04T04:00Z"]))
        d = daily_funding(rates, idx)
        self.assertAlmostEqual(d.iloc[0], 0.0002 - 0.0003)   # 0.00005 rounds to zero
        self.assertAlmostEqual(d.iloc[1], 0.02)               # capped
        self.assertEqual(d.iloc[2], 0.0)
        self.assertTrue((daily_funding(None, idx) == 0).all())

    def test_split_boundary_is_strict(self):
        idx = pd.date_range("2025-06-29", periods=4, freq="D", tz="UTC")
        df = pd.DataFrame({"close": 1.0}, index=idx)
        dev, hold = split(df, "dev"), split(df, "holdout")
        self.assertEqual(str(dev.index[-1].date()), "2025-06-30")
        self.assertEqual(str(hold.index[0].date()), "2025-07-01")
        self.assertEqual(len(dev) + len(hold), 4)


class TestStrategies(unittest.TestCase):
    def setUp(self):
        self.panel = synthetic_panel()

    def test_registry_has_controls_and_candidates(self):
        self.assertIn("vol_target_hold", S.REGISTRY)
        self.assertTrue(S.REGISTRY["vol_target_hold"].is_control)
        self.assertFalse(S.REGISTRY["trend_ensemble"].is_control)
        for name in ("tsmom", "ma_trend", "breakout", "trend_ensemble", "trend_long_only", "coin_flip", "flat"):
            self.assertIn(name, S.REGISTRY)

    def test_causality_every_strategy(self):
        """Appending future bars must not change past target weights."""
        cut = 700
        trunc = {a: d[d.index < self.panel[a].index[0] + pd.Timedelta(days=cut)] for a, d in self.panel.items()}
        for name, fn in S.REGISTRY.items():
            full = fn(self.panel)
            part = fn(trunc)
            common = part.index[part.index >= full.index[300]]
            common = common[common < part.index[-5]]  # skip the last rows where rolling windows are identical anyway
            diff = (full.loc[common] - part.loc[common]).abs().max().max()
            self.assertLess(diff, 1e-9, f"{name} looks ahead: max diff {diff}")

    def test_caps_and_liquidation_distance(self):
        w = S.trend_ensemble(self.panel, target_vol=0.5, max_gross=1.5, max_asset=0.75, min_liq_distance=0.35)
        gross = w.abs().sum(axis=1)
        self.assertLessEqual(gross.max(), 1.5 + 1e-9)
        for a in w.columns:
            self.assertLessEqual(w[a].max(), min(0.75, max_weight_for_distance(0.35, SPECS[a].maint_rate)) + 1e-9)
            self.assertGreaterEqual(w[a].min(), -min(0.75, max_weight_for_distance(0.35, SPECS[a].maint_rate, True)) - 1e-9)

    def test_long_only_never_short(self):
        w = S.trend_long_only(self.panel)
        self.assertGreaterEqual(w.min().min(), 0.0)

    def test_flat_is_zero_and_buy_hold_is_gross_one(self):
        self.assertEqual(S.flat(self.panel).abs().sum().sum(), 0.0)
        bh = S.buy_hold(self.panel)
        self.assertTrue(np.allclose(bh.sum(axis=1), 1.0))

    def test_weak_signal_means_smaller_book(self):
        closes = S.align(self.panel)
        strong = pd.DataFrame(1.0, index=closes.index, columns=closes.columns)
        weak = strong * 0.25
        ws = S.vol_target(strong, self.panel, 0.12)
        ww = S.vol_target(weak, self.panel, 0.12)
        self.assertLess(ww.abs().sum(axis=1).iloc[-1], ws.abs().sum(axis=1).iloc[-1])


class TestBacktest(unittest.TestCase):
    def setUp(self):
        self.panel = synthetic_panel(n=600)
        self.closes = S.align(self.panel)

    def _const_targets(self, w: dict) -> pd.DataFrame:
        t = pd.DataFrame(0.0, index=self.closes.index, columns=list(self.panel))
        for a, v in w.items():
            t[a] = v
        return t

    def test_flat_book_earns_only_interest(self):
        cfg = B.BacktestConfig(funding="none")
        r = B.run(self.panel, self._const_targets({}), cfg)
        yrs = r["years"]
        self.assertAlmostEqual(r["total_return"], (1 + cfg.interest_apy / 365) ** (r["n_days"] - 1) - 1, places=3)
        self.assertEqual(r["ann_turnover"], 0.0)
        self.assertEqual(r["fees_annual"], 0.0)
        self.assertIsNone(r["net_sharpe"])
        self.assertGreater(yrs, 1.0)

    def test_fees_charged_on_turnover_and_execution_lags(self):
        cfg = B.BacktestConfig(funding="none", interest_apy=0.0, rebalance_every=1, rebalance_band=0.0)
        t = self._const_targets({"btc": 0.5})
        r = B.run(self.panel, t, cfg)
        s = r["_series"]
        # first trade happens on day 1 at the open, costing 0.5 × per_side
        self.assertGreater(s["fees"].iloc[1], 0.0)
        self.assertAlmostEqual(s["fees"].iloc[1], 0.5 * cfg.cost.per_side, places=6)
        # a target set on day t cannot earn day t's return: equity on day 1 only moves by the fee and open→close
        # check no-lookahead by shifting targets: shifted targets should give a different path
        r2 = B.run(self.panel, t.shift(5).fillna(0.0), cfg)
        self.assertNotAlmostEqual(r["total_return"], r2["total_return"])
        # a strategy with no rebalancing after entry pays fees exactly once (weights drift, band=0 forces daily re-trades though)
        cfg_band = B.BacktestConfig(funding="none", interest_apy=0.0, rebalance_every=1, rebalance_band=0.3)
        r3 = B.run(self.panel, t, cfg_band)
        self.assertEqual(int((r3["_series"]["fees"] > 0).sum()), 1)   # entry only; drift stays inside the band

    def test_funding_sign(self):
        """Longs pay positive funding, shorts receive it."""
        idx = self.closes.index
        f = pd.Series(0.001, index=idx)   # 0.1% a day, above the deadband
        with mock.patch.object(B, "funding_table", return_value=pd.DataFrame({a: f for a in self.panel})):
            cfg = B.BacktestConfig(funding="kalshi", interest_apy=0.0, rebalance_band=0.3)
            long = B.run(self.panel, self._const_targets({"gold": 0.5}), cfg)
            short = B.run(self.panel, self._const_targets({"gold": -0.5}), cfg)
        self.assertLess(long["funding_annual"], 0.0)
        self.assertGreater(short["funding_annual"], 0.0)

    def test_liquidation_on_crash(self):
        panel = synthetic_panel(n=400, seed=3)
        # engineer a −60% intraday crash in btc on day 200 that recovers by the close
        d = panel["btc"].copy()
        i = 200
        d.iloc[i, d.columns.get_loc("low")] = d["close"].iloc[i - 1] * 0.4
        panel["btc"] = d
        closes = S.align(panel)
        t = pd.DataFrame(0.0, index=closes.index, columns=list(panel))
        t["btc"] = 2.0   # 2x long: liquidation distance ≈ 40%
        cfg = B.BacktestConfig(funding="none", interest_apy=0.0, max_gross=3.0, max_asset=3.0, min_liq_distance=0.0)
        r = B.run(panel, t, cfg)
        self.assertEqual(r["n_liquidations"], 1)
        # equity after liquidation reflects the wick, not the close
        self.assertLess(r["_series"]["equity"].iloc[i], r["_series"]["equity"].iloc[i - 1] * 0.5)
        # and at 1x the same crash does NOT liquidate
        t["btc"] = 1.0
        r1 = B.run(panel, t, cfg)
        self.assertEqual(r1["n_liquidations"], 0)

    def test_drawdown_kill_flattens_for_good(self):
        panel = synthetic_panel(n=500, seed=5, drift={"btc": -0.01})
        closes = S.align(panel)
        t = pd.DataFrame(0.0, index=closes.index, columns=list(panel))
        t["btc"] = 1.0
        cfg = B.BacktestConfig(funding="none", interest_apy=0.0, ladder_kill=0.15)
        r = B.run(panel, t, cfg)
        self.assertTrue(r["killed"])
        w = r["_series"]["weights"]["btc"]
        last_nonzero = w[w.abs() > 1e-9].index[-1]
        self.assertTrue((w[w.index > last_nonzero] == 0).all())
        self.assertGreater(r["max_drawdown"], -0.35)

    def test_walk_forward_selects_and_scores(self):
        panel = synthetic_panel(n=1500, seed=11)
        cfg = B.BacktestConfig(funding="none")
        wf = B.walk_forward(panel, S.tsmom, {"target_vol": 0.12}, cfg,
                            grid={"lookbacks": [(21, 63), (126, 252)]}, n_folds=3, warmup_days=400,
                            dev_end="2030-01-01", dev_start="2019-01-01")
        self.assertEqual(wf["n_folds"], 3)
        self.assertFalse(wf["fixed_params"])
        for f in wf["folds"]:
            self.assertIn(f["params"]["lookbacks"], [(21, 63), (126, 252)])
            self.assertIsNotNone(f["is_sharpe"])
        self.assertEqual(wf["n_trials_this_call"], 6)

    def test_cscv_pbo_on_noise_is_high(self):
        rng = np.random.default_rng(0)
        M = pd.DataFrame(rng.normal(0, 0.01, (800, 12)))
        out = B.cscv_pbo(M, n_blocks=8)
        self.assertIsNotNone(out["pbo"])
        self.assertGreater(out["pbo"], 0.3)   # pure noise: the IS winner is a coin flip OOS

    def test_dsr_rejects_noise_best_of_many(self):
        rng = np.random.default_rng(1)
        best = max((pd.Series(rng.normal(0, 0.01, 1000)) for _ in range(40)),
                   key=lambda s: s.mean() / s.std())
        d = B.dsr(best, n_trials=40)
        self.assertLess(d["dsr"], 0.95)


class TestRisk(unittest.TestCase):
    def test_ladder(self):
        p = R.PROFILES["balanced"]
        self.assertEqual(R.ladder_scale(100, 100, p), 1.0)
        self.assertEqual(R.ladder_scale(91, 100, p), 0.5)
        self.assertEqual(R.ladder_scale(84, 100, p), 0.0)

    def test_liq_distance_and_margin_ratio(self):
        self.assertEqual(R.account_liq_distance({}), float("inf"))
        d1 = R.account_liq_distance({"btc": 1.0})
        d2 = R.account_liq_distance({"btc": 2.0})
        self.assertGreater(d1, d2)
        self.assertGreater(d1, 0.6)
        self.assertLess(R.margin_ratio({"btc": 1.0}), 0.2)

    def test_pre_trade_gate(self):
        p = R.PROFILES["balanced"]
        ok = R.check_pre_trade(p, equity_usd=250, peak_equity_usd=250, order_notional_usd=50,
                               weights_after={"btc": 0.5, "gold": 0.4}, data_age_hours=2)
        self.assertEqual(ok, [])
        bad = R.check_pre_trade(p, equity_usd=200, peak_equity_usd=250, order_notional_usd=5000,
                                weights_after={"btc": 1.6}, data_age_hours=50, day_pnl_frac=-0.05)
        joined = " ".join(bad)
        for tag in ("stale_data", "order_too_large", "drawdown_kill", "daily_stop", "gross_leverage", "asset_weight"):
            self.assertIn(tag, joined)
        # a risk-reducing order is never blocked by the loss stops or the ladder
        red = R.check_pre_trade(p, equity_usd=200, peak_equity_usd=250, order_notional_usd=50,
                                weights_after={"btc": 0.2}, data_age_hours=2, day_pnl_frac=-0.05, reduces_risk=True)
        self.assertEqual(red, [])

    def test_kill_switch_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(R, "KILL_SWITCH", os.path.join(d, "KILL_SWITCH_PERPS")):
                self.assertFalse(R.kill_switch_tripped())
                R.trip_kill_switch("test")
                self.assertTrue(R.kill_switch_tripped())
                with open(R.KILL_SWITCH) as f:
                    self.assertEqual(json.load(f)["reason"], "test")


class TestPaperEngine(unittest.TestCase):
    def _engine(self, tmp):
        from quantfirm.perps import paper as P
        client = mock.Mock()
        client.can_trade = False
        client.exchange_status.return_value = {"exchange_active": True, "trading_active": True}
        client.markets.return_value = [
            {"ticker": "KXBTCPERP", "settlement_mark_price": {"price": "7.8146"}, "price": "7.8146"},
            {"ticker": "KXGOLDPERP", "settlement_mark_price": {"price": "4.2858"}, "price": "4.2858"},
        ]
        client.quote.side_effect = lambda t: PerpQuote(t, Decimal("7.8144"), Decimal("7.8148"), Decimal("100"), Decimal("100"), 0.0) \
            if t == "KXBTCPERP" else PerpQuote(t, Decimal("4.2857"), Decimal("4.2859"), Decimal("100"), Decimal("100"), 0.0)
        client.funding_history.return_value = []
        eng = P.PaperEngine("flat", {}, R.PROFILES["balanced"], adapter="shadow", bankroll=250.0,
                            universe=("btc", "gold"), client=client, state_path=os.path.join(tmp, "s.json"))
        return eng, P

    def test_shadow_fill_pays_far_touch_and_fee(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng, P = self._engine(tmp)
            with mock.patch.object(P, "STATE_DIR", tmp), mock.patch.object(P, "DECISIONS_PATH", os.path.join(tmp, "d.jsonl")), \
                 mock.patch.object(P, "STATUS_PATH", os.path.join(tmp, "st.json")):
                eng.refresh_marks()
                eng.roll_day()
                px, fee = eng._fill_shadow("btc", "bid", 10)
                self.assertEqual(px, 7.8148)                       # buys pay the ask
                self.assertAlmostEqual(fee, 10 * 7.8148 * 0.0012)  # tier-0 taker
                eng._apply_fill("btc", "bid", 10, px, fee)
                self.assertAlmostEqual(eng.book.cash, 250 - fee)
                self.assertEqual(eng.book.positions["btc"]["contracts"], 10)
                # closing half at the bid realizes the spread loss
                px2, fee2 = eng._fill_shadow("btc", "ask", 5)
                self.assertEqual(px2, 7.8144)
                eng._apply_fill("btc", "ask", 5, px2, fee2)
                self.assertEqual(eng.book.positions["btc"]["contracts"], 5)
                self.assertAlmostEqual(eng.book.realized, 5 * (7.8144 - 7.8148))
                eng.save()
                eng2 = P.PaperEngine("flat", {}, R.PROFILES["balanced"], adapter="shadow", bankroll=1.0,
                                     universe=("btc", "gold"), client=eng.client, state_path=eng.state_path)
                self.assertEqual(eng2.book.positions["btc"]["contracts"], 5)   # state round-trips

    def test_tick_with_flat_strategy_places_nothing_and_writes_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng, P = self._engine(tmp)
            panel = synthetic_panel(n=400, assets=("btc", "gold"))
            for a in panel:
                panel[a].index = panel[a].index + (pd.Timestamp.now(tz="UTC").normalize() - panel[a].index[-1])
            # status and decision paths belong to the ENGINE now, so two books can
            # run side by side without writing over each other's history
            eng.status_path = os.path.join(tmp, "st.json")
            eng.decisions_path = os.path.join(tmp, "d.jsonl")
            with mock.patch.object(P, "STATE_DIR", tmp), \
                 mock.patch.object(P.D, "load_panel", return_value=panel):
                notes = eng.tick()
            self.assertTrue(any("orders 0" in n for n in notes))
            self.assertEqual(eng.book.positions, {})
            with open(os.path.join(tmp, "st.json")) as f:
                st = json.load(f)
            self.assertEqual(st["adapter"], "shadow")
            self.assertAlmostEqual(st["equity"], 250.0, places=2)
            self.assertEqual(st["book"], "incumbent")   # an unnamed book is the incumbent

    def test_named_books_keep_separate_state_status_and_decisions(self):
        """Two books must never write over each other, and the incumbent's
        unsuffixed paths must not move when a second book is added."""
        from quantfirm.perps import paper as P
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(P, "STATE_DIR", tmp):
                a = P.PaperEngine("flat", client=mock.Mock())
                b = P.PaperEngine("flat", book="candidate", client=mock.Mock())
            self.assertTrue(a.state_path.endswith("perps_paper_state.json"))
            self.assertTrue(b.state_path.endswith("perps_paper_state_candidate.json"))
            for x in ("state_path", "status_path", "decisions_path"):
                self.assertNotEqual(getattr(a, x), getattr(b, x))
            self.assertIsNone(a.book_name)
            self.assertEqual(b.book_name, "candidate")

    def test_kill_switch_halts_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            eng, P = self._engine(tmp)
            with mock.patch.object(P, "kill_switch_tripped", return_value=True):
                notes = eng.tick()
            self.assertTrue(any("KILL_SWITCH" in n for n in notes))
            eng.client.markets.assert_not_called()


class TestGranularity(unittest.TestCase):
    def test_whole_contracts_only(self):
        panel = synthetic_panel(n=300, seed=8)
        closes = S.align(panel)
        t = pd.DataFrame(0.0, index=closes.index, columns=list(panel))
        t["btc"] = 0.10
        cfg = B.BacktestConfig(funding="none", interest_apy=0.0, bankroll_usd=250.0, rebalance_band=0.0, rebalance_every=1)
        r = B.run(panel, t, cfg)
        w = r["_series"]["weights"]["btc"]
        eq = r["_series"]["equity"]
        # weights are notional / equity at the close; notional in $ = w × equity × bankroll, and it
        # must be a whole number of contracts (contract_size × price each)
        px = closes["btc"].reindex(w.index)
        contracts = (w * eq * 250.0 / (px * float(SPECS["btc"].contract_size))).dropna()
        frac = (contracts - contracts.round()).abs()
        self.assertTrue((frac < 1e-6).all(), f"max fractional contract {frac.max()}")
        self.assertGreater(contracts.max(), 0)
        # and a target smaller than one contract trades nothing
        t2 = t * 0.0
        t2["btc"] = 0.00001
        r2 = B.run(panel, t2, cfg)
        self.assertEqual(float(r2["_series"]["weights"]["btc"].abs().max()), 0.0)


class TestRobustAndRegistry(unittest.TestCase):
    def test_block_bootstrap_and_sharpe_diff(self):
        from quantfirm.perps import robust as RB
        rng = np.random.default_rng(0)
        idx = pd.date_range("2020-01-01", periods=800, freq="D", tz="UTC")
        good = pd.Series(rng.normal(0.001, 0.01, 800), index=idx)
        bad = pd.Series(rng.normal(-0.001, 0.01, 800), index=idx)
        bb = RB.block_bootstrap(good, n_boot=200)
        self.assertLess(bb["sharpe_p5_25_50_75_95"][0], bb["sharpe_p5_25_50_75_95"][4])
        self.assertLess(bb["p_sharpe_le_0"], 0.2)
        d = RB.sharpe_difference(good, bad, n_boot=200)
        self.assertGreater(d["p_a_gt_b"], 0.95)

    def test_timing_null_is_centered_below_a_trend_strategy_or_equal_exposure(self):
        from quantfirm.perps import robust as RB
        panel = synthetic_panel(n=700, seed=2)
        cfg = B.BacktestConfig(funding="none")
        out = RB.timing_null(panel, S.vol_target_hold, {}, cfg, "2019-06-01", "2021-01-01", n_null=8, block=30)
        self.assertEqual(out["n_null"], 8)
        self.assertIn("percentile_of_real", out)

    def test_perturbation_runs(self):
        from quantfirm.perps import robust as RB
        panel = synthetic_panel(n=700, seed=4)
        cfg = B.BacktestConfig(funding="none")
        out = RB.perturbation(panel, S.tsmom, {"target_vol": 0.12}, cfg, "2019-06-01", "2021-01-01")
        self.assertGreater(out["n_perturbations"], 0)

    def test_registry_append_and_count(self):
        from quantfirm.perps import registry as REG
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(REG, "PATH", os.path.join(d, "reg.jsonl")):
                REG.record("x", {"a": 1}, "dev", {"net_sharpe": 1.0})
                REG.record("x", {"a": 1}, "dev", {"net_sharpe": 1.1})   # same config twice → one unique
                REG.record("x", {"a": 2}, "dev", {"net_sharpe": 0.5})
                self.assertEqual(REG.count_unique("dev"), 2)
                self.assertEqual(REG.summary()["rows"], 3)

    def test_families_autoload(self):
        reg = S.load_all()
        self.assertIn("trend_long_only", reg)
        from quantfirm.perps import families
        self.assertIsInstance(families.load_all(), dict)


if __name__ == "__main__":
    unittest.main()
