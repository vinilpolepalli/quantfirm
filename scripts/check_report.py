"""Fail if the nightly research report is not a usable artifact.

state/research_report.json is what the risk-committee agent reads when the
equity kill switch trips (docs/RUNBOOK.md). A report that is stale, truncated,
or describing a different strategy than the one on watch is worse than no
report, because it will be read as current.

The report went five days without updating while the workflow reported success:
the equity-panel fetch step ahead of it consumed the job's whole timeout budget
under a rate-limited upstream, the job was cancelled before its commit step, and
nothing said so. This is the check that would have caught it.

What "good" means here:

  * it parses, has the fields the risk committee reads, and none of them are
    NaN or infinite;
  * it describes the strategy config/live.json actually has on watch, so a
    config change cannot silently leave a report about something else behind;
  * it covers at least as many bars as the committed version — the report is a
    function of the data, so a shrinking bar count means the refresh regressed;
  * the underlying candles are recent, which is the difference between "the
    revalidation ran" and "the revalidation ran on fresh data".

    python scripts/check_report.py            # exit 1 if the report is unusable
    python scripts/check_report.py --warn     # report, always exit 0
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
REPORT = os.path.join(ROOT, "state", "research_report.json")
LIVE = os.path.join(ROOT, "config", "live.json")
CANDLES = os.path.join(ROOT, "data", "BTCUSDT_1h.csv.gz")

REQUIRED = ["cagr", "max_drawdown", "oos_sharpe", "n_bars", "fold_sharpes",
            "strategy", "symbol", "split"]


def committed_n_bars() -> int | None:
    """n_bars from the version in HEAD, or None if unavailable."""
    try:
        out = subprocess.run(
            ["git", "show", "HEAD:state/research_report.json"],
            capture_output=True, text=True, cwd=ROOT, check=True).stdout
        return int(json.loads(out).get("n_bars", 0))
    except Exception:
        return None


def candle_age_hours() -> float | None:
    try:
        with gzip.open(CANDLES, "rt") as f:
            d = pd.read_csv(f, index_col=0, parse_dates=True)
        last = d.index[-1]
        if last.tzinfo is None:
            last = last.tz_localize("UTC")
        return (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--warn", action="store_true", help="report but always exit 0")
    ap.add_argument("--max-data-age-hours", type=float, default=48.0,
                    help="how stale the underlying candles may be (default 48)")
    args = ap.parse_args()

    problems: list[str] = []

    try:
        with open(REPORT) as f:
            rep = json.load(f)
    except Exception as e:
        print(f"FAIL: report unreadable: {e}")
        return 0 if args.warn else 1

    missing = [k for k in REQUIRED if k not in rep]
    if missing:
        problems.append(f"missing field(s): {', '.join(missing)}")

    for k in ("cagr", "max_drawdown", "oos_sharpe"):
        v = rep.get(k)
        if isinstance(v, (int, float)) and not math.isfinite(float(v)):
            problems.append(f"{k} is {v}, not a finite number")
    folds = rep.get("fold_sharpes") or []
    if not folds:
        problems.append("fold_sharpes is empty — walk-forward produced no folds")

    try:
        with open(LIVE) as f:
            want = json.load(f).get("strategy")
        if want and rep.get("strategy") != want:
            problems.append(
                f"report is about '{rep.get('strategy')}' but config/live.json "
                f"has '{want}' on watch")
    except Exception as e:
        problems.append(f"could not read config/live.json to cross-check: {e}")

    prev = committed_n_bars()
    now_bars = int(rep.get("n_bars", 0) or 0)
    if prev is not None and now_bars < prev:
        problems.append(
            f"n_bars went backwards: {prev} committed -> {now_bars} now, so the "
            f"data refresh regressed rather than advanced")

    age = candle_age_hours()
    if age is None:
        problems.append("could not read data/BTCUSDT_1h.csv.gz to date the candles")
    elif age > args.max_data_age_hours:
        problems.append(
            f"underlying candles are {age:.1f}h old (limit {args.max_data_age_hours:.0f}h) "
            f"— the revalidation ran, but not on fresh data")

    print(f"report: {rep.get('strategy')} / {rep.get('symbol')} / "
          f"split={rep.get('split')}, {now_bars} bars, "
          f"oos_sharpe={rep.get('oos_sharpe')}, {len(folds)} fold(s)")
    if age is not None:
        print(f"candles: {age:.1f}h old")
    if prev is not None:
        print(f"n_bars: {prev} committed -> {now_bars} now ({now_bars - prev:+d})")

    if not problems:
        print("OK: the nightly report is current, complete and about the watched strategy")
        return 0

    print("\nFAIL: the nightly report is not usable.")
    for p in problems:
        print(f"  - {p}")
    print("\nThe risk committee reads this file on a kill-switch event "
          "(docs/RUNBOOK.md). A stale or mismatched report will be read as "
          "current, so this fails the run rather than shipping it.")
    return 0 if args.warn else 1


if __name__ == "__main__":
    sys.exit(main())
