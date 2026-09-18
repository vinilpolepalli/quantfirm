"""The $257 screen after the incentive kill: perps economics, no LIP, no go-live.

No network. The live Kalshi pull is not what this file is for.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import perps_alloc_257 as A  # noqa: E402


class TestPerpsScale(unittest.TestCase):
    def test_cagr_scales_dollars_not_the_ratio(self):
        with open(os.path.join(ROOT, "research", "kalshi_perps", "granularity.json")) as fh:
            gran = json.load(fh)
        row = A.perps_row(gran, "trend_long_only@0.12", 257.0)
        self.assertAlmostEqual(row["expected_usd_per_year"], 0.1016 * 257.0, places=2)
        self.assertLess(row["expected_usd_per_day"], 0.10)
        self.assertGreater(row["typical_dd_usd"], 20)


class TestNoIncentiveSurface(unittest.TestCase):
    def test_script_has_no_lip_state_path(self):
        self.assertFalse(hasattr(A, "INCENTIVE_STATE"))
        self.assertFalse(hasattr(A, "incentive_screen"))
        with open(A.__file__) as fh:
            src = fh.read()
        self.assertNotIn("kalshi_incentive", src)
        self.assertNotIn("INCENTIVE_LIVE", src)

    def test_catalog_is_already_killed_families_not_a_todo_list(self):
        self.assertGreaterEqual(len(A.ALREADY_KILLED), 8)
        joined = " ".join(x[1].lower() for x in A.ALREADY_KILLED)
        for family in ("basis_crowding", "funding", "intraday", "trend"):
            self.assertIn(family, joined)


class TestVerdict(unittest.TestCase):
    def test_dead_lip_owner_transfer_no_go_live(self):
        v = A.verdict({"copper_us500_wti_listed": False}, None)
        self.assertEqual(v["incentive_desk"], "DEAD")
        self.assertEqual(v["owner_transfers_257_to_perps"], "YES_AFTER_PAPER")
        self.assertEqual(v["agent_moves_money"], "NO")
        self.assertEqual(v["lift_kill_switch_for_paper"], "YES")
        self.assertEqual(v["set_live_true"], "NO")
        self.assertEqual(v["dump_internet_strats_into_the_registry"], "NO")
        self.assertEqual(v["register_a_funding_overlay_today"], "NO")

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
            self.assertEqual(payload["verdict"]["incentive_desk"], "DEAD")
            self.assertEqual(payload["verdict"]["lift_kill_switch_for_paper"], "YES")
            self.assertEqual(payload["verdict"]["set_live_true"], "NO")
            self.assertFalse(payload["live"])
            self.assertEqual(payload["capital_usd"], 257.0)
            self.assertNotIn("incentive", payload)
            self.assertFalse(payload["plumbing"]["kill_switch_perps"])
            self.assertIn("PAPER", payload["plumbing"]["perps_status"])
            self.assertIn("live=false", payload["plumbing"]["perps_status"])


class TestPrune(unittest.TestCase):
    def test_incentive_paths_are_gone(self):
        gone = (
            ".github/workflows/kalshi_incentive.yml",
            "scripts/kalshi_incentive_paper.py",
            "scripts/kalshi_incentive_quote.py",
            "scripts/kalshi_incentive_scan.py",
            "scripts/kalshi_incentive_stress.py",
            "docs/KALSHI_INCENTIVE.md",
            "research/kalshi_incentives.md",
            "state/kalshi_incentive_paper.json",
            "state/INCENTIVE_LIVE",
        )
        for rel in gone:
            self.assertFalse(os.path.exists(os.path.join(ROOT, rel)), rel)


if __name__ == "__main__":
    unittest.main()
