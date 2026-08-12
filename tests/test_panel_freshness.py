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


def test_current_panel_passes():
    """The real committed panel should be current; if it is not, CI should be
    telling us so, and this test failing is that message."""
    r = _run(EQ)
    assert r.returncode == 0, r.stdout + r.stderr


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
