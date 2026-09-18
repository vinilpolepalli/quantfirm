"""The $257 screen must refuse inherited run-rates and refuse a catalog dump.

No network: the live Kalshi pull is not what this file is for. The contract
is the arithmetic a session uses to decide whether to move money or register
another hundred trials.
"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import perps_alloc_257 as A  # noqa: E402


def _tick(t, earned, total, interval_h=1.0):
    return {"t": t, "earned": earned, "total": total, "held": 5, "interval_h": interval_h}


class TestWallClock(unittest.TestCase):
    def test_last_day_is_the_sum_not_an_annualised_rate(self):
        now = dt.datetime(2026, 9, 18, 12, 0, tzinfo=dt.timezone.utc)
        hist = [
            _tick("2026-09-17T12:00:00+00:00", 10.0, 50.0),   # exactly 24h ago, included
            _tick("2026-09-17T18:00:00+00:00", 1.0, 51.0),
            _tick("2026-09-18T12:00:00+00:00", 2.0, 53.0),
        ]
        w = A.wall_clock_window(hist, 24, now)
        self.assertEqual(w["earned_usd"], 13.0)
        self.assertEqual(w["wall_usd_per_day"], 13.0)
        self.assertEqual(w["n_ticks"], 3)

    def test_gappy_capped_intervals_make_the_gate_rate_none(self):
        # Three ticks in 24h, each claiming interval_h=1, is an 3h span.
        # The paper gate refuses a window whose capped span is under half.
        now = dt.datetime(2026, 9, 18, 12, 0, tzinfo=dt.timezone.utc)
        hist = [
            _tick("2026-09-17T18:00:00+00:00", 0.3, 1.0),
            _tick("2026-09-18T00:00:00+00:00", 0.3, 1.3),
            _tick("2026-09-18T12:00:00+00:00", 0.3, 1.6),
        ]
        w = A.wall_clock_window(hist, 24, now)
        self.assertEqual(w["capped_interval_h"], 3.0)
        self.assertIsNone(w["gate_usd_per_day"])
        self.assertAlmostEqual(w["wall_usd_per_day"], 0.9)

    def test_unreadable_rows_are_skipped_not_fatal(self):
        now = dt.datetime(2026, 9, 18, 12, 0, tzinfo=dt.timezone.utc)
        hist = [{"t": "nope", "earned": 99}, _tick("2026-09-18T11:00:00+00:00", 1.0, 1.0)]
        w = A.wall_clock_window(hist, 6, now)
        self.assertEqual(w["n_ticks"], 1)
        self.assertEqual(w["earned_usd"], 1.0)


class TestIncentiveScreen(unittest.TestCase):
    def test_since_inception_is_flagged_as_the_overread(self):
        st = {
            "started": "2026-09-16T12:00:00+00:00",
            "accrued": 50.0,
            "ticks": 10,
            "capital": 257.0,
            "verdict": "INSUFFICIENT",
            "verdict_reason": "43h of data, need 48h",
            "history": [
                _tick("2026-09-16T12:00:00+00:00", 40.0, 40.0),
                _tick("2026-09-18T12:00:00+00:00", 1.0, 50.0),
            ],
        }
        got = A.incentive_screen(st)
        self.assertGreater(got["since_inception_usd_per_day"], 20)
        self.assertLess(got["windows"]["24h"]["wall_usd_per_day"], 5)
        self.assertIn("over-read", got["note"])
        self.assertAlmostEqual(got["board_identity_usd_per_day"],
                               A.BOARD_PAID_PER_DAY / A.BOARD_RESTING * 257.0, places=3)


class TestPerpsScale(unittest.TestCase):
    def test_cagr_scales_dollars_not_the_ratio(self):
        with open(os.path.join(ROOT, "research", "kalshi_perps", "granularity.json")) as fh:
            gran = json.load(fh)
        row = A.perps_row(gran, "trend_long_only@0.12", 257.0)
        self.assertAlmostEqual(row["expected_usd_per_year"], 0.1016 * 257.0, places=2)
        self.assertLess(row["expected_usd_per_day"], 0.10)
        self.assertGreater(row["typical_dd_usd"], 20)


class TestVerdict(unittest.TestCase):
    def test_every_action_is_no(self):
        with open(os.path.join(ROOT, "state", "kalshi_incentive_paper.json")) as fh:
            st = json.load(fh)
        inc = A.incentive_screen(st)
        v = A.verdict(inc, {"copper_us500_wti_listed": False}, None)
        self.assertEqual(v["move_the_257_to_perps"], "NO")
        self.assertEqual(v["dump_internet_strats_into_the_registry"], "NO")
        self.assertEqual(v["restart_the_halted_perps_desk"], "NO")
        self.assertEqual(v["register_a_funding_overlay_today"], "NO")

    def test_catalog_is_already_killed_families_not_a_todo_list(self):
        self.assertGreaterEqual(len(A.ALREADY_KILLED), 8)
        joined = " ".join(x[1].lower() for x in A.ALREADY_KILLED)
        for family in ("basis_crowding", "funding", "intraday", "trend"):
            self.assertIn(family, joined)

    def test_script_writes_json_offline(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "alloc.json")
            old = sys.argv
            try:
                sys.argv = ["perps_alloc_257.py", "--out", out]
                self.assertEqual(A.main(), 0)
            finally:
                sys.argv = old
            with open(out) as fh:
                payload = json.load(fh)
            self.assertEqual(payload["verdict"]["move_the_257_to_perps"], "NO")
            self.assertFalse(payload["live"])
            self.assertEqual(payload["capital_usd"], 257.0)


if __name__ == "__main__":
    unittest.main()
