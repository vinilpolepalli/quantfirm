"""Paper copy-trade accounting. No network."""
from __future__ import annotations

import unittest

from quantfirm.kalshi.copytrade import (
    TRIALS,
    Bucket,
    Candle,
    KMarket,
    coalesce,
    date_token_from_slug,
    first_candle,
    is_prior_sport,
    map_trade,
    names_match,
    simulate,
    taker_fee,
    top_scores,
    weights_from_scores,
)


def _mkt(ticker, event, subtitle, result="yes", close=2_000, mult=1.0):
    return KMarket(ticker, event, event.split("-")[0], subtitle, result, close, mult)


CHELSEA = [
    _mkt("KXEPLGAME-26SEP18BRECFC-BRE", "KXEPLGAME-26SEP18BRECFC", "Brentford", "yes"),
    _mkt("KXEPLGAME-26SEP18BRECFC-CFC", "KXEPLGAME-26SEP18BRECFC", "Chelsea", "no"),
    _mkt("KXEPLGAME-26SEP18BRECFC-TIE", "KXEPLGAME-26SEP18BRECFC", "Tie", "no"),
]


def _gamma_chelsea():
    return {
        "title": "Brentford FC vs. Chelsea FC",
        "slug": "epl-bre-che-2026-09-18",
        "markets": [
            {
                "slug": "epl-bre-che-2026-09-18-che",
                "sportsMarketType": "moneyline",
                "groupItemTitle": "Chelsea FC",
                "question": "Will Chelsea FC win on 2026-09-18?",
                "outcomes": '["Yes", "No"]',
            },
            {
                "slug": "epl-bre-che-2026-09-18-draw",
                "sportsMarketType": "moneyline",
                "groupItemTitle": "Draw (Brentford FC vs. Chelsea FC)",
                "question": "Will Brentford FC vs. Chelsea FC end in a draw?",
                "outcomes": ["Yes", "No"],
            },
            {
                "slug": "epl-bre-che-2026-09-18-spread-home-1pt5",
                "sportsMarketType": "spreads",
                "groupItemTitle": "Spread -1.5",
                "question": "Spread",
                "outcomes": ["Yes", "No"],
            },
        ],
    }


def _trade(**kw):
    base = {
        "proxyWallet": "0xabc",
        "side": "BUY",
        "size": 100,
        "price": 0.40,
        "timestamp": 1_000,
        "slug": "epl-bre-che-2026-09-18-che",
        "eventSlug": "epl-bre-che-2026-09-18",
        "outcome": "No",
    }
    base.update(kw)
    return base


class TestMap(unittest.TestCase):
    def test_date_token_is_english_month(self):
        self.assertEqual(date_token_from_slug("epl-bre-che-2026-09-18"), "26SEP18")

    def test_no_on_chelsea_is_chelsea_no_not_brentford(self):
        hit = map_trade(_trade(), _gamma_chelsea(), CHELSEA)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.ticker, "KXEPLGAME-26SEP18BRECFC-CFC")
        self.assertEqual(hit.kalshi_side, "no")
        self.assertEqual(hit.action, "buy")

    def test_draw_yes_maps_to_tie(self):
        hit = map_trade(
            _trade(slug="epl-bre-che-2026-09-18-draw", outcome="Yes", price=0.28),
            _gamma_chelsea(), CHELSEA)
        self.assertEqual(hit.ticker, "KXEPLGAME-26SEP18BRECFC-TIE")
        self.assertEqual(hit.kalshi_side, "yes")

    def test_spread_is_not_copied(self):
        hit = map_trade(
            _trade(slug="epl-bre-che-2026-09-18-spread-home-1pt5"),
            _gamma_chelsea(), CHELSEA)
        self.assertIsNone(hit)

    def test_h2h_outcome_is_yes_on_that_name(self):
        markets = [
            _mkt("KXNFLGAME-26SEP20GBNYJ-GB", "KXNFLGAME-26SEP20GBNYJ", "GB Packers"),
            _mkt("KXNFLGAME-26SEP20GBNYJ-NYJ", "KXNFLGAME-26SEP20GBNYJ", "NY Jets", "no"),
        ]
        event = {
            "title": "Packers vs. Jets",
            "slug": "nfl-gb-nyj-2026-09-20",
            "markets": [{
                "slug": "nfl-gb-nyj-2026-09-20",
                "sportsMarketType": "moneyline",
                "groupItemTitle": None,
                "question": "Packers vs. Jets",
                "outcomes": ["Packers", "Jets"],
            }],
        }
        hit = map_trade(
            _trade(slug="nfl-gb-nyj-2026-09-20", eventSlug="nfl-gb-nyj-2026-09-20",
                    outcome="Jets", price=0.33),
            event, markets)
        self.assertEqual(hit.ticker, "KXNFLGAME-26SEP20GBNYJ-NYJ")
        self.assertEqual(hit.kalshi_side, "yes")

    def test_two_events_same_day_do_not_cross(self):
        markets = CHELSEA + [
            _mkt("KXEPLGAME-26SEP18MCISUN-MCI", "KXEPLGAME-26SEP18MCISUN", "Manchester City"),
            _mkt("KXEPLGAME-26SEP18MCISUN-SUN", "KXEPLGAME-26SEP18MCISUN", "Sunderland"),
        ]
        hit = map_trade(_trade(outcome="Yes", slug="epl-bre-che-2026-09-18-che"),
                        _gamma_chelsea(), markets)
        self.assertEqual(hit.ticker, "KXEPLGAME-26SEP18BRECFC-CFC")
        self.assertEqual(hit.kalshi_side, "yes")

    def test_names(self):
        self.assertTrue(names_match("Chelsea FC", "Chelsea"))
        self.assertTrue(names_match("Rayo Vallecano de Madrid", "Rayo Vallecano"))
        self.assertFalse(names_match("Manchester United", "Manchester City"))


class TestSelect(unittest.TestCase):
    def test_prior_sport_filter(self):
        self.assertTrue(is_prior_sport("Will Chelsea FC win on 2026-09-18?"))
        self.assertTrue(is_prior_sport("Packers vs. Jets"))
        self.assertFalse(is_prior_sport("Bitcoin Up or Down - August 14"))
        self.assertFalse(is_prior_sport("Spread: Panthers (-2.5)"))
        self.assertFalse(is_prior_sport("Will the highest temperature in Madrid be 34°C"))

    def test_weights(self):
        scores = top_scores({"a": 30, "b": 10, "c": -5, "d": None, "e": 5}, k=2)
        self.assertEqual(set(scores), {"a", "b"})
        w = weights_from_scores(scores, "pnl")
        self.assertAlmostEqual(w["a"], 0.75)
        self.assertAlmostEqual(sum(weights_from_scores(scores, "equal").values()), 1.0)

    def test_trials_are_frozen_and_decision_is_first(self):
        self.assertEqual(TRIALS[0]["name"], "honest_pnl_equal")
        self.assertFalse(TRIALS[0]["biased"])
        self.assertTrue(any(t["name"] == "fade_pnl_equal" and t["fade"] for t in TRIALS))
        self.assertTrue(any(t["biased"] for t in TRIALS))


class TestFillTiming(unittest.TestCase):
    def test_uses_the_candle_after_the_lag_not_the_signal_bar(self):
        candles = [
            Candle(130, 0.40, 0.40, 0.42, 0.41, volume=10),
            Candle(170, 0.50, 0.50, 0.55, 0.52, volume=10),
        ]
        # signal bucket end 100, lag 60 → need end >= 160
        hit = first_candle(candles, 160, close_ts=None, grace_s=300, max_spread=0.15)
        self.assertEqual(hit.end_ts, 170)
        missed = first_candle(candles, 171, close_ts=None, grace_s=10, max_spread=0.15)
        self.assertIsNone(missed)

    def test_dead_book_does_not_fill(self):
        candles = [Candle(200, 0.0, 0.0, 1.0, 1.0, volume=0)]
        self.assertIsNone(first_candle(candles, 100, None, 300, 0.15))


def _candle(end, bid, ask):
    return Candle(end, bid, bid, ask, ask, volume=100)


def _affordable_qty(cash, px, mult=1.0):
    qty = int(cash / px)
    while qty > 0 and qty * px + taker_fee(qty, px, mult) > cash + 1e-9:
        qty -= 1
    return qty


class TestSimulate(unittest.TestCase):
    def _bucket(self, **kw):
        base = dict(wallet="0xabc", ts_end=1_000, ticker="T", kalshi_side="yes",
                    action="buy", size=1_000, poly_notional=400, fee_multiplier=1.0,
                    close_ts=5_000, result="yes")
        base.update(kw)
        return Bucket(**base)

    def test_fee_examples(self):
        self.assertAlmostEqual(taker_fee(10, 0.50), 0.18)
        self.assertAlmostEqual(taker_fee(20, 0.50), 0.35)
        self.assertAlmostEqual(taker_fee(20, 0.50, multiplier=0.5), 0.18)

    def test_win_settlement_pnl_matches_cash(self):
        # one leader, full sleeve, name cap 100% so the math is visible
        b = self._bucket()
        candles = {"T": [_candle(1_070, 0.40, 0.42)]}
        metas = {"T": (5_000, "yes", 1.0)}
        rep = simulate([b], candles, metas, {"0xabc": 1.0}, bankroll=100,
                       max_name_frac=1.0, max_ticker_frac=1.0, lag_s=60)
        qty = _affordable_qty(100, 0.42)
        fee = taker_fee(qty, 0.42)
        expect = qty * 1.0 - qty * 0.42 - fee
        self.assertEqual(rep["n_fills"], 1)
        self.assertEqual(rep["n_open"], 0)
        self.assertAlmostEqual(rep["pnl_mtm"], round(expect, 4), places=2)
        self.assertAlmostEqual(rep["pnl_settled"], round(expect, 4), places=2)
        self.assertGreater(rep["pnl_mtm"], 0)

    def test_loss_settlement(self):
        b = self._bucket(result="no")
        candles = {"T": [_candle(1_070, 0.40, 0.42)]}
        metas = {"T": (5_000, "no", 1.0)}
        rep = simulate([b], candles, metas, {"0xabc": 1.0}, bankroll=100,
                       max_name_frac=1.0, max_ticker_frac=1.0)
        self.assertLess(rep["pnl_mtm"], 0)
        qty = _affordable_qty(100, 0.42)
        fee = taker_fee(qty, 0.42)
        self.assertAlmostEqual(rep["pnl_mtm"], round(-(qty * 0.42 + fee), 4), places=2)

    def test_does_not_fill_on_the_signal_candle(self):
        b = self._bucket()
        # only a candle before the lag; nothing to lift
        candles = {"T": [_candle(1_000, 0.40, 0.42)]}
        metas = {"T": (5_000, "yes", 1.0)}
        rep = simulate([b], candles, metas, {"0xabc": 1.0}, bankroll=100,
                       max_name_frac=1.0, max_ticker_frac=1.0, lag_s=60)
        self.assertEqual(rep["n_fills"], 0)
        self.assertEqual(rep["pnl_mtm"], 0)

    def test_price_gate_blocks_a_chase(self):
        b = self._bucket(poly_notional=400)  # vwap 0.40
        candles = {"T": [_candle(1_070, 0.50, 0.55)]}
        metas = {"T": (5_000, "yes", 1.0)}
        rep = simulate([b], candles, metas, {"0xabc": 1.0}, bankroll=100,
                       max_name_frac=1.0, max_ticker_frac=1.0, price_gate=0.03)
        self.assertEqual(rep["n_fills"], 0)
        self.assertGreaterEqual(rep["skips"].get("price_gate", 0), 1)

    def test_follow_plus_fade_cannot_both_win_a_settlement(self):
        b = self._bucket()
        candles = {"T": [_candle(1_070, 0.40, 0.50)]}
        metas = {"T": (5_000, "yes", 1.0)}
        kw = dict(bankroll=100, max_name_frac=1.0, max_ticker_frac=1.0)
        follow = simulate([b], candles, metas, {"0xabc": 1.0}, fade=False, **kw)
        fade = simulate([b], candles, metas, {"0xabc": 1.0}, fade=True, **kw)
        self.assertLess(follow["pnl_mtm"] + fade["pnl_mtm"], 0)

    def test_sell_exits_before_settlement(self):
        buy = self._bucket(ts_end=1_000, result="no")
        sell = self._bucket(ts_end=2_000, action="sell", size=1_000, poly_notional=500,
                            result="no")
        candles = {"T": [_candle(1_070, 0.40, 0.42), _candle(2_070, 0.60, 0.62)]}
        metas = {"T": (5_000, "no", 1.0)}
        rep = simulate([buy, sell], candles, metas, {"0xabc": 1.0}, bankroll=100,
                       max_name_frac=1.0, max_ticker_frac=1.0)
        self.assertEqual(rep["n_open"], 0)
        self.assertGreater(rep["pnl_mtm"], 0)
        self.assertEqual(rep["n_fills"], 2)

    def test_coalesce_waits_until_bucket_end(self):
        from quantfirm.kalshi.copytrade import MappedTrade
        t1 = MappedTrade("0xabc", 1_010, "T", "yes", "buy", 10, 0.4, 1, 9_000, None)
        t2 = MappedTrade("0xabc", 1_100, "T", "yes", "buy", 10, 0.5, 1, 9_000, None)
        opp = MappedTrade("0xabc", 1_050, "T", "yes", "sell", 4, 0.4, 1, 9_000, None)
        buckets = coalesce([t1, t2, opp], bucket_s=300)
        self.assertEqual(len(buckets), 2)
        buy = next(b for b in buckets if b.action == "buy")
        self.assertEqual(buy.ts_end, 1_200)
        self.assertEqual(buy.size, 20)
        self.assertAlmostEqual(buy.poly_vwap, 0.45)


class TestNoLivePath(unittest.TestCase):
    def test_sources_do_not_place_orders(self):
        import inspect
        import quantfirm.kalshi.copytrade as ct
        src = inspect.getsource(ct)
        self.assertNotIn("create_order", src)
        self.assertNotIn("/portfolio/events/orders", src)


if __name__ == "__main__":
    unittest.main()
