"""Fail if the equity panel is not current.

The nightly job used to report success while refreshing nothing. Its fetch step
is `continue-on-error` on purpose — a flaky upstream should not take the crypto
revalidation down with it — but the effect was that four consecutive runs went
green while `data/equities` sat five sessions behind and the desk quietly
stopped trading. A silently skipped data refresh looked exactly like a working
one.

So the fetch stays non-fatal and this runs at the END of the job instead, after
everything that can still succeed has succeeded and committed. The run then
goes red on the one thing that actually matters: whether the panel advanced.

Staleness is deliberately NOT redefined here. It imports `missing_sessions`
from the rebalancer, so CI and `plan()`'s trading guard cannot drift apart —
if this passes, the desk can trade, and if it fails, the desk would refuse.

It also checks that every symbol ends on the same date. A ragged panel is the
more dangerous failure: `load_panel` outer-joins on the union of dates, so a
partial refresh makes the newest date look current to the staleness check while
most of the universe is NaN on it.

    python scripts/check_panel_fresh.py          # exit 1 if stale or ragged
    python scripts/check_panel_fresh.py --warn   # report, always exit 0
"""

from __future__ import annotations

import argparse
import collections
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from equity_rebalance import missing_sessions  # noqa: E402  one definition of stale
from quantfirm.equities.data import available_symbols, load_symbol  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--warn", action="store_true",
                    help="report but always exit 0")
    args = ap.parse_args()

    ends: dict[str, date] = {}
    for sym in available_symbols():
        try:
            ends[sym] = load_symbol(sym).index[-1].date()
        except Exception as e:                       # unreadable is also not fresh
            print(f"  {sym}: unreadable ({e})")
            ends[sym] = date.min

    if not ends:
        print("FAIL: no symbols in the panel at all")
        return 0 if args.warn else 1

    tally = collections.Counter(ends.values())
    newest = max(tally)
    missing = missing_sessions(newest, date.today())
    ragged = [s for s, d in ends.items() if d != newest]

    print(f"panel: {len(ends)} symbols, newest last date {newest}")
    if len(tally) > 1:
        print("  end dates: " + ", ".join(f"{d}={n}" for d, n in sorted(tally.items())))

    problems = []
    if missing:
        problems.append(
            f"panel ends {newest}, missing {len(missing)} completed "
            f"session(s): {', '.join(missing)}")
    if ragged:
        shown = ", ".join(f"{s} ({ends[s]})" for s in sorted(ragged)[:10])
        problems.append(
            f"{len(ragged)} symbol(s) behind the newest date: {shown}"
            f"{' …' if len(ragged) > 10 else ''}")

    if not problems:
        print("OK: panel is current and every symbol ends on the same date")
        return 0

    print("\nFAIL: the equity panel did not advance.")
    for p in problems:
        print(f"  - {p}")
    print("\nThe desk's stale-panel guard will refuse to trade in this state, "
          "so it holds rather than acting on an old view — but it will not "
          "rebalance, and a holding can drift out of its band unnoticed.\n"
          "Refresh with scripts/update_equities.py, or import broker bars with "
          "scripts/import_bars.py.")
    return 0 if args.warn else 1


if __name__ == "__main__":
    sys.exit(main())
