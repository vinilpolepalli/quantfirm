"""Offline tests for the OSS-clone paper sleeve. No network."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quantfirm.kalshi.ladder import LadderLeg
from quantfirm.kalshi.oss_paper import (
    COUNT, KILL_N, apply_settlements, empty_state,
    flb_taker_intent, open_positions, phantom_wing, refuse_live,
    select_intents, settle_position, verdict,
)
from quantfirm.kalshi.oss_paper import Intent


def _leg(**kw):
    defaults = dict(ticker="KXHIGHNY-26SEP18-B70.5", yes_ask=0.12, yes_bid=0.11,
                    yes_ask_size=8, yes_bid_size=8, volume=400, strike_type="between")
    defaults.update(kw)
    return LadderLeg(**defaults)


class TestPhantomAndIntent(unittest.TestCase):
    def test_zero_volume_is_phantom(self):
        self.assertTrue(phantom_wing(0.10, 70, 0))
        self.assertTrue(phantom_wing(0.01, 5, 400))
        self.assertFalse(phantom_wing(0.12, 8, 400))

    def test_flb_taker_prices_no_from_bid(self):
        i = flb_taker_intent(_leg(), "EV")
        self.assertIsNotNone(i)
        self.assertEqual(i.side, "no")
        self.assertAlmostEqual(i.px, 0.89)
        self.assertEqual(i.count, COUNT)
        self.assertGreater(i.fee, 0)

    def test_missing_bid_or_thin_bid_refuses(self):
        self.assertIsNone(flb_taker_intent(_leg(yes_bid=None), "EV"))
        self.assertIsNone(flb_taker_intent(_leg(yes_bid_size=0), "EV"))
        self.assertIsNone(flb_taker_intent(_leg(yes_ask=0.01, volume=500), "EV"))
        self.assertIsNone(flb_taker_intent(_leg(volume=0, yes_ask_size=70), "EV"))


class TestSettleAndKill(unittest.TestCase):
    def test_no_wins_when_yes_loses(self):
        pos = {"ticker": "T", "event": "E", "side": "no", "px": 0.90,
               "count": 1, "fee": 0.01, "family": "flb_taker", "yes_ask": 0.10}
        win = settle_position(pos, "no")
        self.assertTrue(win["won"])
        self.assertAlmostEqual(win["pnl"], 0.09)
        self.assertFalse(win["longshot_hit"])
        lose = settle_position(pos, "yes")
        self.assertTrue(lose["longshot_hit"])
        self.assertAlmostEqual(lose["pnl"], -0.91)

    def test_refuse_self_computed_result(self):
        pos = {"ticker": "T", "event": "E", "side": "no", "px": 0.90,
               "count": 1, "fee": 0.01, "family": "flb_taker", "yes_ask": 0.10}
        with self.assertRaises(ValueError):
            settle_position(pos, "cli_75")

    def test_apply_settlements_returns_cash(self):
        st = empty_state(100)
        st["cash"] = 99.09
        st["positions"] = [{
            "ticker": "T", "event": "E", "side": "no", "px": 0.90,
            "count": 1, "fee": 0.01, "family": "flb_taker", "yes_ask": 0.10,
            "cost": 0.91,
        }]
        done = apply_settlements(st, {"T": "no"})
        self.assertEqual(len(done), 1)
        self.assertEqual(st["positions"], [])
        self.assertAlmostEqual(st["cash"], 100.09)

    def test_insufficient_before_kill_n(self):
        st = empty_state()
        code, _ = verdict(st)
        self.assertEqual(code, "INSUFFICIENT")

    def test_kill_when_hit_rate_not_below_ask(self):
        st = empty_state()
        st["settled"] = [
            {"family": "flb_taker", "pnl": -0.90, "longshot_hit": True, "yes_ask": 0.10}
            for _ in range(3)
        ] + [
            {"family": "flb_taker", "pnl": 0.08, "longshot_hit": False, "yes_ask": 0.10}
            for _ in range(KILL_N - 3)
        ]
        code, why = verdict(st)
        self.assertEqual(code, "NO")
        self.assertIn("not overpriced", why)

    def test_kill_when_pnl_red_even_if_hit_rate_looks_cheap(self):
        # 1 hit / 20 at 18¢ ask = 5% < 18%, but fees+hit still lose.
        st = empty_state()
        st["settled"] = [
            {"family": "flb_taker", "pnl": -0.83, "longshot_hit": True, "yes_ask": 0.18}
        ] + [
            {"family": "flb_taker", "pnl": 0.02, "longshot_hit": False, "yes_ask": 0.18}
            for _ in range(KILL_N - 1)
        ]
        code, why = verdict(st)
        self.assertEqual(code, "NO")
        self.assertIn("no edge", why)

    def test_ruin_brake(self):
        st = empty_state(257)
        st["cash"] = 100
        code, _ = verdict(st)
        self.assertEqual(code, "NO")


class TestSelectAndOpen(unittest.TestCase):
    def test_caps_and_open_debit_cash(self):
        st = empty_state(257)
        intents = [
            Intent("A", "E1", "no", 0.89, 1, 0.01, 0.11, 0.11, 400, "flb"),
            Intent("B", "E1", "no", 0.88, 1, 0.01, 0.12, 0.12, 400, "flb"),
            Intent("C", "E1", "no", 0.87, 1, 0.01, 0.13, 0.13, 400, "flb"),
            Intent("D", "E1", "no", 0.86, 1, 0.01, 0.14, 0.14, 400, "flb"),
        ]
        take, skip = select_intents(intents, st, 257)
        self.assertEqual(len(take), 3)  # MAX_PER_EVENT
        self.assertTrue(any(s["reason"] == "max_per_event" for s in skip))
        open_positions(st, take, opened="t0")
        self.assertEqual(len(st["positions"]), 3)
        self.assertLess(st["cash"], 257)

    def test_killed_sleeve_takes_nothing(self):
        st = empty_state()
        st["killed"] = True
        i = Intent("A", "E", "no", 0.89, 1, 0.01, 0.11, 0.11, 400, "flb")
        take, skip = select_intents([i], st, 257)
        self.assertEqual(take, [])
        self.assertEqual(skip[0]["reason"], "sleeve_killed")


class TestRefuseLive(unittest.TestCase):
    def test_refuse_live_exits(self):
        with self.assertRaises(SystemExit):
            refuse_live(True)
        refuse_live(False)

    def test_script_has_no_order_call(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        paths = (
            os.path.join(root, "scripts", "kalshi_oss_paper.py"),
            os.path.join(root, "quantfirm", "kalshi", "oss_paper.py"),
        )
        src = ""
        for p in paths:
            with open(p) as f:
                src += f.read()
        self.assertNotIn("create_order", src)
        self.assertNotIn("/portfolio/events/orders", src)


if __name__ == "__main__":
    unittest.main()
