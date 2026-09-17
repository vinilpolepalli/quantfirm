"""Unit tests for the Kalshi LIP book. No network."""
import datetime as dt
import importlib.util
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    path = os.path.join(REPO, rel)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

from quantfirm.kalshi.halt import incentive_kill_tripped
from quantfirm.kalshi.incentive import (
    MIN_AGE_HOURS, MIN_HOURS_LEFT, SELECTION, better_depth, discounted_score,
    eligible_program, order_qualifies, plan_market, qualifying_slice,
    rate_per_hour, reference_price, score_side, share_for_size, touch_reference,
)


NOW = dt.datetime(2026, 9, 17, 20, 0, tzinfo=dt.timezone.utc)


def _prog(**over):
    p = dict(
        market_ticker="KXTEST-1",
        incentive_type="liquidity",
        start_date="2026-09-16T08:00:00Z",
        end_date="2026-09-23T08:00:00Z",
        period_reward=2000000,
        target_size_fp="1000.00",
        discount_factor_bps=5000,
    )
    p.update(over)
    return p


class TestScoring(unittest.TestCase):
    def test_reference_is_t5_walk_not_touch(self):
        book = [(0.25, 50), (0.02, 200), (0.01, 1000)]
        # T=1000, T/5=200. 50 at 25c + 200 at 2c reaches 250, so ref is 0.02
        self.assertEqual(reference_price(book, 1000), 0.02)
        self.assertEqual(touch_reference(book), 0.25)

    def test_thin_book_has_no_reference(self):
        self.assertIsNone(reference_price([(0.50, 10)], 1000))

    def test_qualifying_slice_stops_at_target(self):
        book = [(0.10, 400), (0.02, 400), (0.01, 5000)]
        q = qualifying_slice(book, 1000)
        self.assertEqual(q, [(0.10, 400), (0.02, 400), (0.01, 200)])
        self.assertIsNone(qualifying_slice([(0.01, 200)], 1000))

    def test_gray_dot_deeper_than_target_does_not_qualify(self):
        book = [(0.50, 1000), (0.01, 5000)]
        self.assertTrue(order_qualifies(0.50, book, 1000))
        self.assertFalse(order_qualifies(0.01, book, 1000))
        self.assertEqual(better_depth(book, 0.01), 1000)

    def test_quote_at_t5_ref_always_qualifies(self):
        book = [(0.25, 50), (0.02, 200), (0.01, 1000)]
        ref = reference_price(book, 1000)
        self.assertTrue(order_qualifies(ref, book, 1000))

    def test_discount_steep_at_half(self):
        book = [(0.05, 100), (0.02, 100)]
        # 3 ticks below at df=0.5 => 0.125x
        self.assertAlmostEqual(discounted_score(book, 0.05, 0.5), 100 + 12.5)

    def test_qualifying_score_ignores_junk_beyond_target(self):
        book = [(0.02, 1000), (0.01, 20000)]
        side = score_side(book, 1000, 1.0)  # df=1, junk would count fully
        self.assertEqual(side["qual_score"], 1000)
        self.assertEqual(side["full_score"], 21000)
        self.assertFalse(side["excluded"])

    def test_share_is_per_side(self):
        self.assertAlmostEqual(share_for_size(100, 100, 100), 0.5)

    def test_rate_zero_when_book_under_target(self):
        m = dict(unit=0.04, target=1000, yes_depth=10, no_depth=10,
                 yes_score=100, no_score=100, reward_per_hour=1.0)
        rate, size, share, excluded = rate_per_hour(m, 8)  # 200 contracts, still under 1000
        self.assertTrue(excluded)
        self.assertEqual(rate, 0.0)
        self.assertEqual(size, 200.0)

    def test_plan_rejects_sub_dollar_payout(self):
        m = dict(
            unit=0.99, target=1000, yes_depth=5000, no_depth=5000,
            yes_score=4000, no_score=4000, reward=10.0, left_h=48, duration_h=168,
            yes_ref=0.50, no_ref=0.49,
            yes_book=[(0.50, 5000)], no_book=[(0.49, 5000)],
        )
        self.assertIsNone(plan_market(m, 20))  # ~20 contracts, tiny share

    def test_plan_accepts_clearing_minimum(self):
        m = dict(
            unit=0.04, target=1000, yes_depth=2000, no_depth=2000,
            yes_score=200, no_score=200, reward=200.0, left_h=100, duration_h=168,
            yes_ref=0.02, no_ref=0.02,
            yes_book=[(0.02, 2000)], no_book=[(0.02, 2000)],
        )
        pl = plan_market(m, 40)
        self.assertIsNotNone(pl)
        self.assertEqual(pl["size"], 1000)
        self.assertGreaterEqual(pl["expected"], 1.0)


class TestSelection(unittest.TestCase):
    def test_fresh_program_rejected(self):
        p = _prog(start_date="2026-09-17T19:00:00Z")  # 1h old
        self.assertFalse(eligible_program(p, NOW, MIN_HOURS_LEFT, MIN_AGE_HOURS))

    def test_short_program_rejected(self):
        p = _prog(end_date="2026-09-18T08:00:00Z")  # 12h left
        self.assertFalse(eligible_program(p, NOW, MIN_HOURS_LEFT, MIN_AGE_HOURS))

    def test_aged_long_program_accepted(self):
        self.assertTrue(eligible_program(_prog(), NOW, MIN_HOURS_LEFT, MIN_AGE_HOURS))

    def test_volume_program_rejected(self):
        self.assertFalse(eligible_program(_prog(incentive_type="volume"), NOW))


class TestHalt(unittest.TestCase):
    def test_incentive_switch_is_its_own_file(self):
        from quantfirm.kalshi import halt
        self.assertTrue(halt.INCENTIVE_KILL_SWITCH.endswith("KILL_SWITCH_INCENTIVE"))
        self.assertNotEqual(halt.INCENTIVE_KILL_SWITCH, halt.KILL_SWITCH)
        src = inspect.getsource(incentive_kill_tripped)
        self.assertIn("INCENTIVE_KILL_SWITCH", src)

    def test_quote_does_not_read_metals_switch(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "scripts", "kalshi_incentive_quote.py")
        with open(path) as fh:
            src = fh.read()
        self.assertIn("incentive_kill_tripped", src)
        self.assertNotIn("kill_switch_tripped()", src)
        self.assertIn("KILL_SWITCH_INCENTIVE", src)

    def test_workflow_stays_canary_sized(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".github", "workflows", "kalshi_incentive.yml")
        with open(path) as fh:
            src = fh.read()
        self.assertIn("--capital 40", src)
        self.assertIn("--markets 2", src)
        self.assertIn("--min-age-hours 12", src)


class TestPaperCarryAndClock(unittest.TestCase):
    def test_age_survives_a_tick(self):
        paper = _load("kalshi_incentive_paper", "scripts/kalshi_incentive_paper.py")
        src = inspect.getsource(paper)
        self.assertIn('pos.get("age_h_at_open")', src)
        self.assertIn('rec["age_h_at_open"] = pos["age_h_at_open"]', src)
        self.assertIn('pos.get("opened")', src)

    def test_verdict_uses_selection_clock(self):
        paper = _load("kalshi_incentive_paper", "scripts/kalshi_incentive_paper.py")
        now = NOW
        st = {
            "started": "2026-09-16T16:16:07+00:00",
            "selection": SELECTION,
            "selection_since": now.isoformat(),
            "capital": 257,
            "history": [{"t": now.isoformat(), "earned": 0.0, "interval_h": 0.0}],
        }
        code, why = paper.verdict(st, now)
        self.assertEqual(code, "INSUFFICIENT")
        self.assertIn("aged12_qualifying", why)

    def test_interval_cap(self):
        paper = _load("kalshi_incentive_paper", "scripts/kalshi_incentive_paper.py")
        self.assertEqual(paper.MAX_INTERVAL_H, 1.0)


class TestQuoteGate(unittest.TestCase):
    def test_five_gates_still_required(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "scripts", "kalshi_incentive_quote.py")
        with open(path) as fh:
            src = fh.read()
        self.assertIn("args.live and env_live and armed and not killed and client.can_trade", src)
        self.assertIn("INCENTIVE_LIVE", src)


if __name__ == "__main__":
    unittest.main()
