"""Guards on the panel-freshness check.

This check is the only thing standing between a data outage and a green CI run.
It went unnoticed for four sessions once already, so its failure modes get
tests rather than trust.
"""
from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EQ = os.path.join(ROOT, "data", "equities")
SCRIPT = os.path.join(ROOT, "scripts", "check_panel_fresh.py")
SYMS = ["AAPL", "MSFT", "NVDA", "WDC"]


def _sandbox(tmp, truncate_to=None, ragged_keep=None):
    """A small copy of the panel, optionally truncated.

    truncate_to  -- cut every symbol at this date
    ragged_keep  -- cut every symbol EXCEPT these, leaving the panel ragged
    """
    for s in SYMS:
        src = os.path.join(EQ, f"{s}_1d.csv.gz")
        dst = os.path.join(tmp, f"{s}_1d.csv.gz")
        shutil.copy(src, dst)
        cut = truncate_to
        if ragged_keep is not None:
            cut = None if s in ragged_keep else truncate_to
        if cut is None:
            continue
        with gzip.open(dst, "rt") as f:
            d = pd.read_csv(f, index_col=0, parse_dates=True)
        d = d[d.index <= pd.Timestamp(cut)]
        with gzip.open(dst, "wt") as f:
            d.to_csv(f, index_label="ts", date_format="%Y-%m-%d")
    return tmp


def _run(tmp, *args):
    env = dict(os.environ, QF_EQ_DATA_DIR=tmp)
    return subprocess.run([sys.executable, SCRIPT, *args],
                          capture_output=True, text=True, cwd=ROOT, env=env)


def _last_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# There is deliberately NO test asserting the committed panel is current.
#
# The desk imports a session's bar during the FOLLOWING session, so between any
# close and the next desk run the panel is legitimately one session behind. A
# test on the real panel would therefore go red every night on wall-clock time
# rather than on anything about the code, and a suite that fails for reasons
# unrelated to the change under test stops being read. Panel currency is an
# operational signal: it belongs to the desk cycle and to plan()'s stale-panel
# guard, which refuses to trade rather than acting on an old view.


def test_stale_panel_fails():
    with tempfile.TemporaryDirectory() as tmp:
        _sandbox(tmp, truncate_to="2020-01-02")
        r = _run(tmp)
        assert r.returncode == 1, "a five-year-old panel must fail the check"
        assert "did not advance" in r.stdout


def test_ragged_panel_fails_even_though_newest_date_looks_current():
    """The dangerous case: load_panel outer-joins on the union of dates, so one
    refreshed symbol makes the newest date look current while the rest of the
    universe is NaN on it. The staleness check alone would pass."""
    with tempfile.TemporaryDirectory() as tmp:
        _sandbox(tmp, truncate_to="2020-01-02", ragged_keep={"WDC"})
        r = _run(tmp)
        assert r.returncode == 1, "a ragged panel must fail even when new"
        assert "behind the newest date" in r.stdout
        assert "AAPL" in r.stdout


def test_warn_mode_never_fails():
    with tempfile.TemporaryDirectory() as tmp:
        _sandbox(tmp, truncate_to="2020-01-02")
        r = _run(tmp, "--warn")
        assert r.returncode == 0, "--warn must report without failing"
        assert "did not advance" in r.stdout


def test_shares_its_staleness_definition_with_the_trading_guard():
    """CI and plan() must not drift apart: if CI is green the desk must be able
    to trade, and if the desk refuses CI must be red."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import check_panel_fresh
    from equity_rebalance import missing_sessions
    assert check_panel_fresh.missing_sessions is missing_sessions


def _bars(sym, dates, price=100.0):
    return [{"date": d, "open": price, "high": price, "low": price,
             "close": price, "volume": 1} for d in dates]


def test_import_refuses_an_import_that_would_leave_the_panel_ragged(tmp_path):
    """The trap that is NOT a failure of any single symbol: some advance, the
    rest report 'current' because the vendor had nothing new for them, and the
    panel ends up ragged. Seen live when the broker had published real daily
    bars for 6 of 227 symbols and synthesized gap-fill for the other 221."""
    import gzip
    import json as _json

    src = os.path.join(EQ, "AAPL_1d.csv.gz")
    with gzip.open(src, "rt") as f:
        real = pd.read_csv(f, index_col=0, parse_dates=True)
    last = real.index[-1]
    nxt = (last + timedelta(days=1)).date().isoformat()

    panel = tmp_path / "panel"
    panel.mkdir()
    for s in ("AAA", "BBB"):
        with gzip.open(panel / f"{s}_1d.csv.gz", "wt") as f:
            real.tail(30).to_csv(f, index_label="ts", date_format="%Y-%m-%d")

    shared = [d.date().isoformat() for d in real.index[-3:]]
    closes = [float(c) for c in real["close"].iloc[-3:]]
    payload = {
        # AAA gets a genuinely new session, BBB does not
        "AAA": [{"date": d, "open": c, "high": c, "low": c, "close": c,
                 "volume": 1} for d, c in zip(shared, closes)]
               + [{"date": nxt, "open": closes[-1], "high": closes[-1],
                   "low": closes[-1], "close": closes[-1], "volume": 1}],
        "BBB": [{"date": d, "open": c, "high": c, "low": c, "close": c,
                 "volume": 1} for d, c in zip(shared, closes)],
    }
    blob = tmp_path / "bars.json"
    blob.write_text(_json.dumps(payload))

    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "import_bars.py"),
         str(blob)],
        capture_output=True, text=True, cwd=ROOT,
        env=dict(os.environ, QF_EQ_DATA_DIR=str(panel)))
    assert r.returncode == 1, "a ragged result must refuse to write"
    assert "RAGGED" in r.stdout
    with gzip.open(panel / "AAA_1d.csv.gz", "rt") as f:
        after = pd.read_csv(f, index_col=0, parse_dates=True)
    assert after.index[-1] == last, "nothing may be written when refusing"
