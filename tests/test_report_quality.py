"""Guards on the nightly report gate.

state/research_report.json is what the risk-committee agent reads on a
kill-switch event. It sat unchanged for five days while the workflow reported
success, so the ways it can be quietly wrong get tests.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "check_report.py")
REPORT = os.path.join(ROOT, "state", "research_report.json")


@pytest.fixture
def good():
    with open(REPORT) as f:
        return json.load(f)


def _run_with(report: dict | str | None):
    """Run the checker against a temporary copy of the repo's state/ dir."""
    with tempfile.TemporaryDirectory() as tmp:
        for sub in ("state", "config", "data", "scripts", "quantfirm"):
            src = os.path.join(ROOT, sub)
            if os.path.isdir(src):
                # data/ is large; only the one candle file the checker dates
                if sub == "data":
                    os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
                    shutil.copy(os.path.join(src, "BTCUSDT_1h.csv.gz"),
                                os.path.join(tmp, "data", "BTCUSDT_1h.csv.gz"))
                    continue
                shutil.copytree(src, os.path.join(tmp, sub),
                                ignore=shutil.ignore_patterns("__pycache__"))
        path = os.path.join(tmp, "state", "research_report.json")
        if report is None:
            os.remove(path)
        elif isinstance(report, str):
            open(path, "w").write(report)
        else:
            json.dump(report, open(path, "w"))
        # Invoke the SANDBOXED copy: check_report.py resolves its paths from
        # __file__, so running the repo's own script would read the real
        # state/ no matter what cwd says.
        return subprocess.run(
            [sys.executable, os.path.join(tmp, "scripts", "check_report.py")],
            capture_output=True, text=True, cwd=tmp)


def test_the_committed_report_is_usable():
    """If this fails, the nightly is shipping something the risk committee
    should not be reading — which is the whole point of the gate."""
    r = subprocess.run([sys.executable, SCRIPT], capture_output=True,
                       text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


def test_rejects_a_report_about_a_different_strategy(good):
    bad = dict(good, strategy="not_the_watched_one")
    r = _run_with(bad)
    assert r.returncode == 1
    assert "on watch" in r.stdout


def test_rejects_a_walk_forward_with_no_folds(good):
    r = _run_with(dict(good, fold_sharpes=[]))
    assert r.returncode == 1
    assert "no folds" in r.stdout


def test_rejects_non_finite_metrics(good):
    r = _run_with(json.dumps(dict(good, oos_sharpe=float("nan"))))
    assert r.returncode == 1
    assert "finite" in r.stdout


def test_rejects_a_missing_field(good):
    bad = {k: v for k, v in good.items() if k != "max_drawdown"}
    r = _run_with(bad)
    assert r.returncode == 1
    assert "max_drawdown" in r.stdout


def test_rejects_an_unreadable_report():
    r = _run_with("{not json")
    assert r.returncode == 1
    assert "unreadable" in r.stdout


def test_warn_mode_never_fails(good):
    r = subprocess.run([sys.executable, SCRIPT, "--warn",
                        "--max-data-age-hours", "0"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, "--warn must report without failing"
