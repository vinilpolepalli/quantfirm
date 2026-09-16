"""Unit tests for the Kalshi 15M metals desk (no network)."""
import csv
import json
import math
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

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


class TestSupervisorScript(unittest.TestCase):
    """Guards against two supervisor bugs that cost a weekend of churn."""

    @property
    def script(self):
        """Executable lines only -- the comments explaining these bugs quote
        the buggy snippets verbatim, which would match the assertions."""
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "scripts", "kalshi_paper_loop.sh")
        with open(path) as f:
            return "\n".join(ln for ln in f
                             if not ln.lstrip().startswith("#"))

    def test_market_guard_does_not_fail_open(self):
        """`grep -c` prints 0 AND exits 1, so `|| echo 0` yields "0\n0",
        the integer test errors, and the no-market guard FAILS OPEN. That
        spawned an engine into a closed market every ~5 min all weekend."""
        self.assertNotIn("|| echo 0", self.script,
                         "`grep -c ... || echo 0` appends a second zero and "
                         "makes the market guard fail open")
        self.assertIn("|| open_count=0", self.script)

    def test_watchdog_kills_the_engine_not_just_the_wrapper(self):
        """SIGKILL is never forwarded, so `kill -9 <timeout pid>` orphans the
        python child. 70 orphans accumulated on 2026-09-12, all polling the
        API and writing the same state files."""
        self.assertIn("pkill -KILL -f 'quantfirm[.]kalshi[.]cli paper'",
                      self.script,
                      "watchdog must reap the engine itself, not only the "
                      "`timeout` wrapper it was launched under")


class TestTapePersistence(unittest.TestCase):
    """The tape is the prerequisite for any defensible maker fill model."""

    def _engine(self, tmp, client, poll=15):
        from quantfirm.kalshi.paper import PaperEngine
        eng = PaperEngine.__new__(PaperEngine)   # __init__ opens network feeds
        eng.tape_path = os.path.join(tmp, "tape")
        eng.tape_poll_s = poll
        eng._tape_last, eng._tape_seen, eng.prod = {}, {}, client
        return eng

    class _Client:
        """Returns overlapping windows, newest first, like the real API."""
        def __init__(self): self.calls = 0
        def get_trades(self, ticker, limit=100):
            self.calls += 1
            return [{"trade_id": f"t{i}", "yes_price_dollars": "0.55",
                     "count_fp": "10", "taker_side": "yes",
                     "created_time": "2026-09-12T11:00:00Z"}
                    for i in range(5 - self.calls, 10 - self.calls)]

    def test_dedupes_overlapping_polls(self):
        import json
        import glob
        with tempfile.TemporaryDirectory() as tmp:
            c = self._Client()
            eng = self._engine(tmp, c)
            eng._persist_tape("T", 1000)
            eng._persist_tape("T", 1020)
            rows = [json.loads(l)
                    for f in glob.glob(os.path.join(tmp, "*")) for l in open(f)]
            ids = [r["trade_id"] for r in rows]
            self.assertEqual(len(ids), len(set(ids)),
                             "overlapping polls must not duplicate prints")

    def test_throttles_polling(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self._Client()
            eng = self._engine(tmp, c, poll=15)
            eng._persist_tape("T", 1000)
            eng._persist_tape("T", 1005)   # inside the throttle window
            self.assertEqual(c.calls, 1, "tape poll must respect tape_poll_s")

    def test_disabled_when_no_path(self):
        c = self._Client()
        eng = self._engine("/nonexistent", c)
        eng.tape_path = None
        eng._persist_tape("T", 1000)
        self.assertEqual(c.calls, 0, "no tape_path must mean no API call")

    def test_survives_api_failure(self):
        class Boom:
            def get_trades(self, *a, **k): raise RuntimeError("503")
        with tempfile.TemporaryDirectory() as tmp:
            eng = self._engine(tmp, Boom())
            eng._persist_tape("T", 1000)   # must not raise into the tick loop


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestPassiveEdgeClustering(unittest.TestCase):
    """Pins the fix in docs/KALSHI.md 3d. The per-print statistic said the
    underdog maker earned t=+23.3; clustered by market the same rows gave
    t=+0.38. If someone 'simplifies' per_market back into a flat mean over
    prints, the desk starts believing a fake edge again."""

    @staticmethod
    def _mod():
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "scripts", "kalshi_passive_edge.py")
        spec = importlib.util.spec_from_file_location("kpe", path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_market_clustering_beats_pseudo_replication(self):
        m = self._mod()
        # Two markets. Every print inside a market shares its settlement, so
        # there are TWO independent observations, not 400.
        recs = []
        for tkr, pnl in (("A", 0.04), ("B", -0.02)):
            for _ in range(200):
                recs.append({"pnl": pnl, "c": 10.0, "tkr": tkr})
        n, mu, t = m.per_market(recs)
        self.assertEqual(n, 2, "must count markets, not prints")
        self.assertAlmostEqual(mu, 0.01, places=9)
        # 200x more 'observations' would inflate t by ~sqrt(200).
        self.assertLess(abs(t), abs(m.per_print_t(recs)) / 5)

    def test_per_market_is_equal_weight_not_volume_weight(self):
        m = self._mod()
        # One huge market must not be able to outvote many small ones: its
        # settlement is still a single draw.
        recs = [{"pnl": -0.5, "c": 100000.0, "tkr": "BIG"}]
        recs += [{"pnl": 0.1, "c": 1.0, "tkr": f"S{i}"} for i in range(20)]
        n, mu, _ = m.per_market(recs)
        self.assertEqual(n, 21)
        self.assertGreater(mu, 0.0, "volume weighting would make this negative")

    def test_taker_semantics_verifier_flags_contradiction(self):
        m = self._mod()
        # A tape whose prints land on the wrong side of the book must report
        # CONTRADICTED -- every sign in the analysis depends on this mapping.
        with tempfile.TemporaryDirectory() as d:
            dec = os.path.join(d, "dec.jsonl")
            with open(dec, "w") as f:
                for i in range(50):
                    f.write(json.dumps({"ticker": "T", "ts": 1000 + i,
                                        "bid": 0.40, "ask": 0.60}) + "\n")
            tape = []
            for i in range(50):
                ts = datetime.fromtimestamp(1000 + i, timezone.utc).isoformat().replace("+00:00", "Z")
                tape.append({"ticker": "T", "created_time": ts,
                             "yes_price_dollars": "0.4000",   # the BID
                             "taker_outcome_side": "yes"})     # claims a lift
            orig, m.DECISIONS = m.DECISIONS, dec
            try:
                out = m.verify_taker_semantics(tape)
            finally:
                m.DECISIONS = orig
        self.assertIn("CONTRADICTED", out)


class TestDailyStopFromTradeLog(unittest.TestCase):
    """Pins the 2026-09-14 halt. The stop used to read state['cash'], which two
    concurrent engines corrupt via last-writer-wins saves; a real -9.38% day
    read as -10.08% against a baseline captured from the drifted cash, and the
    maker leg was blocked for hours by a stop that should not have fired."""

    @staticmethod
    def _engine(tmp, rows, bankroll0=500.0, frac=0.1):
        from quantfirm.kalshi.paper import PaperEngine, PaperState
        log = os.path.join(tmp, "trades.csv")
        cols = ["settled_at", "adapter", "ticker", "metal", "side", "count",
                "fill_price", "fee", "fair_at_entry", "result", "pnl", "tag",
                "cash_after"]
        with open(log, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})
        e = PaperEngine.__new__(PaperEngine)
        e.log_path = log
        e.params = Params(daily_stop_frac=frac)
        e.state = PaperState(os.path.join(tmp, "state.json"), bankroll0)
        return e

    def _today(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def test_stop_ignores_corrupted_cash(self):
        # The exact numbers from the incident: book really started the day at
        # 557.51 and lost 52.29 (-9.38%). Cash had drifted 38.96 low.
        rows = [{"settled_at": "2026-09-10", "adapter": "maker", "pnl": "57.51"},
                {"settled_at": self._today(), "adapter": "maker", "pnl": "-52.29"}]
        with tempfile.TemporaryDirectory() as d:
            e = self._engine(d, rows)
            e.state.d["cash"]["maker"] = 466.26        # the drifted figure
            e.state.d["day_stop"] = {"date": self._today(),
                                     "start": {"maker": 518.55}}  # stale baseline
            self.assertTrue(e._entries_allowed()["maker"],
                            "-9.38% must not trip a 10% stop, whatever cash says")

    def test_stop_still_fires_on_a_real_breach(self):
        rows = [{"settled_at": "2026-09-10", "adapter": "maker", "pnl": "57.51"},
                {"settled_at": self._today(), "adapter": "maker", "pnl": "-60.00"}]
        with tempfile.TemporaryDirectory() as d:
            e = self._engine(d, rows)
            e.state.d["cash"]["maker"] = 900.0   # flattering cash must not rescue it
            self.assertFalse(e._entries_allowed()["maker"],
                             "-10.8% must trip a 10% stop")

    def test_books_are_independent(self):
        rows = [{"settled_at": self._today(), "adapter": "maker", "pnl": "-80"},
                {"settled_at": self._today(), "adapter": "shadow", "pnl": "+20"}]
        with tempfile.TemporaryDirectory() as d:
            a = self._engine(d, rows)._entries_allowed()
        self.assertFalse(a["maker"])
        self.assertTrue(a["shadow"])

    def test_no_history_allows_entries(self):
        with tempfile.TemporaryDirectory() as d:
            e = self._engine(d, [])
            os.remove(e.log_path)
            self.assertEqual(e._entries_allowed(), {"shadow": True, "maker": True})

    def test_derived_not_persisted(self):
        """Two engines must agree on the gate without sharing a baseline."""
        rows = [{"settled_at": self._today(), "adapter": "maker", "pnl": "-60"}]
        with tempfile.TemporaryDirectory() as d:
            a = self._engine(d, rows)
            b = self._engine(d, rows)
            b.state.d["cash"]["maker"] = 1000.0     # b's state raced ahead
            self.assertEqual(a._entries_allowed()["maker"],
                             b._entries_allowed()["maker"])


class TestOpenPositionsSurviveConcurrentSave(unittest.TestCase):
    """Pins the 2026-09-15 position loss. Two engines run at once and each holds
    the whole state in memory; a wholesale rewrite deleted the other engine's
    open positions. The foreground engine filled gold NO 35 @0.79 and silver NO
    32 @0.81 on KX*15M-26SEP150715, exited before the close, and the background
    engine's next save erased both -- neither settled, neither was logged."""

    @staticmethod
    def _pos(**kw):
        from quantfirm.kalshi.paper import PaperPosition
        base = dict(ticker="KXGOLD15M-X", metal="gold", side="no", count=35,
                    fill_price=0.79, fee=0.0, fair=0.16, entry_ts=1, close_ts=2,
                    adapter="maker", tag="maker")
        base.update(kw)
        return PaperPosition(**base)

    def test_second_engine_does_not_erase_the_first(self):
        from quantfirm.kalshi.paper import PaperState
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            a = PaperState(path)                       # foreground engine
            a.open = [self._pos(), self._pos(ticker="KXSILVER15M-X",
                                             metal="silver", count=32,
                                             fill_price=0.81)]
            a.save()
            b = PaperState(path)                       # background engine
            self.assertEqual(len(b.open), 2)
            b.open = [self._pos(ticker="KXSILVER15M-Y", count=53,
                                fill_price=0.52)]      # only its own position
            b.save()
            after = PaperState(path)
            tickers = sorted(p.ticker for p in after.open)
            self.assertEqual(len(after.open), 3,
                             "a concurrent save must not drop the other engine's fills")
            self.assertIn("KXGOLD15M-X", tickers)
            self.assertIn("KXSILVER15M-X", tickers)

    def test_settled_positions_are_not_resurrected(self):
        from quantfirm.kalshi.paper import PaperState
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            a = PaperState(path)
            a.open = [self._pos()]
            a.save()
            b = PaperState(path)
            b.open = []                                # b settled it
            b.save(settled_keys={PaperState._pos_key(asdict_compat(self._pos()))})
            self.assertEqual(PaperState(path).open, [],
                             "a settled position must not come back via the union")

    def test_identical_positions_do_not_duplicate(self):
        from quantfirm.kalshi.paper import PaperState
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            a = PaperState(path)
            a.open = [self._pos()]
            a.save()
            b = PaperState(path)
            b.open = [self._pos()]                     # same fill, both engines
            b.save()
            self.assertEqual(len(PaperState(path).open), 1)


class TestSingleEngineLock(unittest.TestCase):
    """Two engines against one state file double-enter the same market.

    The union-on-save fix stopped them DELETING each other's positions; it
    cannot stop them OPENING the same view twice, because each engine's
    "am I already in this ticker" guard reads its own in-memory state.open.
    On 2026-09-16 that put 170 shadow contracts and 151 maker contracts into
    one 15-min gold market -- about double the intended Kelly stake on each
    book -- because the hourly check-in ran a foreground engine alongside the
    supervisor's. The lock makes the second engine refuse to start."""

    def test_second_engine_is_refused_while_lock_held(self):
        from quantfirm.kalshi.cli import _engine_lock
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "engine.lock")
            first = _engine_lock(path)
            self.assertIsNotNone(first, "the first engine must get the lock")
            self.assertIsNone(_engine_lock(path),
                              "a second engine must be refused, not queued")
            first.close()
            second = _engine_lock(path)
            self.assertIsNotNone(second,
                                 "the lock must free when the holder exits")
            second.close()


class TestClusteredTStat(unittest.TestCase):
    """One 15-minute market settles once. Every fill inside it resolves on
    that single draw, so counting fills as independent observations inflates
    t by ~sqrt(fills/market). Same trap as the passive-edge study (t=+23.3
    per print vs t=+0.38 per market)."""

    @staticmethod
    def _rows(pairs):
        return [{"adapter": "maker", "ticker": t, "pnl": str(v)}
                for t, v in pairs]

    def test_duplicate_fills_in_one_market_do_not_inflate_t(self):
        from quantfirm.kalshi.bookstats import book_stats
        # 6 markets, each won twice by the same amount: replicating every fill
        # must not change the market-level evidence at all.
        base = [(f"M{i}", 10.0 if i % 3 else -12.0) for i in range(6)]
        single = book_stats(self._rows(base), "maker")
        doubled = book_stats(self._rows([(t, v) for t, v in base
                                         for _ in (0, 1)]), "maker")
        self.assertEqual(doubled["n"], 2 * single["n"])
        self.assertEqual(doubled["n_markets"], single["n_markets"])
        self.assertAlmostEqual(doubled["t"], single["t"], places=6)
        self.assertGreater(abs(doubled["t_naive"]), abs(single["t_naive"]),
                           "the per-fill t is the inflated one, kept visible")

    def test_n_and_hit_stay_at_fill_level(self):
        from quantfirm.kalshi.bookstats import book_stats
        s = book_stats(self._rows([("A", 5.0), ("A", 5.0), ("B", -1.0)]),
                       "maker")
        self.assertEqual((s["n"], s["n_markets"]), (3, 2))
        self.assertAlmostEqual(s["hit"], 2 / 3, places=3)   # stored rounded
        # A's two winning fills net into ONE market observation of +10
        self.assertAlmostEqual(s["pnl"], 9.0)

    def test_empty_book_is_none(self):
        from quantfirm.kalshi.bookstats import book_stats
        self.assertIsNone(book_stats(self._rows([]), "maker"))
        self.assertIsNone(book_stats(self._rows([("A", 1.0)]), "shadow"))


class TestCashRebuiltFromTradeLog(unittest.TestCase):
    """`cash` is the one field concurrent saves cannot merge, so it drifted --
    by the 2026-09-16 fix it read ~65% richer than the log, and Kelly sizes on
    it. Rebuilding from the append-only log on every construction re-converges
    it each restart."""

    def _log(self, d, rows):
        path = os.path.join(d, "trades.csv")
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["adapter", "ticker", "pnl"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return path

    def test_drifted_cash_is_overwritten_by_the_log(self):
        from quantfirm.kalshi.paper import PaperState
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "state.json")
            with open(sp, "w") as f:
                json.dump({"bankroll0": 500.0,
                           "cash": {"shadow": 9999.0, "demo": 500.0,
                                    "maker": 9999.0},
                           "open": []}, f)
            lp = self._log(d, [{"adapter": "maker", "ticker": "A", "pnl": "10.5"},
                               {"adapter": "maker", "ticker": "B", "pnl": "-4.0"},
                               {"adapter": "shadow", "ticker": "A", "pnl": "2.0"}])
            st = PaperState(sp, log_path=lp)
            self.assertAlmostEqual(st.d["cash"]["maker"], 506.5)
            self.assertAlmostEqual(st.d["cash"]["shadow"], 502.0)

    def test_open_position_cost_stays_debited(self):
        from quantfirm.kalshi.paper import PaperState, PaperPosition
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "state.json")
            pos = dict(ticker="T", metal="gold", side="yes", count=10,
                       fill_price=0.40, fee=0.17, fair=0.5, entry_ts=0,
                       close_ts=1, adapter="maker")
            with open(sp, "w") as f:
                json.dump({"bankroll0": 500.0, "cash": {"maker": 1.0},
                           "open": [pos]}, f)
            lp = self._log(d, [])
            st = PaperState(sp, log_path=lp)
            # 500 - (10 * 0.40 + 0.17): an unsettled position's cost is still out
            self.assertAlmostEqual(st.d["cash"]["maker"], 495.83)

    def test_no_log_path_leaves_cash_alone(self):
        from quantfirm.kalshi.paper import PaperState
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "state.json")
            with open(sp, "w") as f:
                json.dump({"bankroll0": 500.0, "cash": {"maker": 123.0},
                           "open": []}, f)
            self.assertAlmostEqual(PaperState(sp).d["cash"]["maker"], 123.0)


def asdict_compat(p):
    from dataclasses import asdict
    return asdict(p)
