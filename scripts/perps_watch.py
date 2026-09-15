#!/usr/bin/env python3
"""Weekly watch for the perps desk: what would change the verdict, and is paper drifting?

This is deliberately NOT a strategy generator. The trial registry is append-only
and every configuration anyone tests raises the deflated-Sharpe bar for every
future idea: at 80 configurations a candidate already needs an out-of-sample
Sharpe near 1.4 to clear it. A routine that ground out new trials each week
would make the desk PROGRESSIVELY LESS able to validate anything, which is the
opposite of research. So this watches for the four things that would actually
change the answer, and checks whether the paper books are behaving like the
backtest said they would.

    python scripts/perps_watch.py            # findings as JSON
    python scripts/perps_watch.py --quiet    # exit 3 when there is nothing to say
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:          # runnable as `python scripts/perps_watch.py` from anywhere
    sys.path.insert(0, ROOT)
STATE = os.path.join(ROOT, "state")

# docs/KALSHI_PERPS.md section 9: what would change the verdict. Breadth in crypto
# was measured and does not help, so the diversifier worth waiting for is a perp
# that is NOT crypto.
EXPECTED = {
    "incumbent": {"ann_return": 0.098, "ann_vol": 0.080},
    "candidate": {"ann_return": 0.152, "ann_vol": 0.090},
    "growth":    {"ann_return": 0.220, "ann_vol": 0.128},
}


def venue_check() -> list[dict]:
    """New listings, especially outside crypto, and whether funding still rounds to zero."""
    out = []
    try:
        from quantfirm.perps.client import MarginClient
        from quantfirm.perps.specs import SPECS
        known = {s.ticker for s in SPECS.values()}
        markets = MarginClient("prod").markets()
    except Exception as e:                                   # offline, rate limited, changed API
        return [{"kind": "venue_unreachable", "detail": f"{type(e).__name__}: {e}"}]

    new = [m for m in markets if m.get("ticker") not in known]
    for m in new:
        cls = (m.get("asset_class") or "").lower()
        out.append({
            "kind": "new_listing",
            "ticker": m.get("ticker"),
            "asset_class": m.get("asset_class"),
            "notable": cls not in ("crypto", ""),
            "detail": ("A NON-CRYPTO perp. Section 9 says this is the one thing that would "
                       "genuinely change the verdict: all twenty tradable crypto perps together "
                       "are about two and a half independent bets, so the missing diversifier "
                       "has to come from outside crypto.")
            if cls not in ("crypto", "") else "Another crypto name; breadth there is already measured as an illusion.",
        })
    if len(markets) != len(known) and not new:
        out.append({"kind": "delisting", "detail": f"venue lists {len(markets)} markets, specs know {len(known)}"})

    # is the funding deadband still zeroing almost everything?
    try:
        from quantfirm.perps import data as D
        f = D.load_kalshi_funding("btc")
        if f is not None and len(f):
            recent = f.tail(90)
            zero_share = float((recent.abs() < 1e-12).mean())
            if zero_share < 0.5:
                out.append({"kind": "funding_live", "zero_share": round(zero_share, 3),
                            "detail": ("BTC funding is now non-zero on more than half of recent "
                                       "intervals. The desk's whole carry analysis assumed the "
                                       "deadband zeroes it; re-read section 2.")})
    except Exception:
        pass
    return out


def drift_check() -> list[dict]:
    """Is each paper book behaving like its backtest, or has it come loose?"""
    out = []
    hist_path = os.path.join(STATE, "perps_report_history.jsonl")
    if not os.path.exists(hist_path):
        return out
    rows = []
    with open(hist_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if len(rows) < 14:            # two weeks is the floor for saying anything at all
        return [{"kind": "too_early",
                 "detail": f"{len(rows)} snapshots so far; drift needs at least 14 to mean anything"}]

    first, last = rows[0], rows[-1]
    days = max(1, (dt.datetime.fromisoformat(last["ts"]) - dt.datetime.fromisoformat(first["ts"])).days)
    for name, exp in EXPECTED.items():
        eq = [(r["books"].get(name) or {}).get("equity") for r in rows]
        eq = [x for x in eq if isinstance(x, (int, float))]
        if len(eq) < 14:
            continue
        rets = np.diff(np.log(eq))
        realised_vol = float(np.std(rets) * np.sqrt(365))
        realised_ret = float((eq[-1] / eq[0] - 1) * 365 / days)
        # volatility converges far faster than return, so it is the honest early check
        ratio = realised_vol / exp["ann_vol"] if exp["ann_vol"] else float("nan")
        if ratio > 1.75 or ratio < 0.4:
            out.append({"kind": "vol_drift", "book": name,
                        "realised_vol": round(realised_vol, 4), "expected_vol": exp["ann_vol"],
                        "detail": (f"{name} is running at {ratio:.1f}x its expected volatility over "
                                   f"{days} days. Return over a window this short means nothing, but "
                                   f"volatility this far off usually means a sizing or data problem, "
                                   f"not a market one.")})
        out.append({"kind": "tracking", "book": name, "days": days,
                    "realised_ann_return": round(realised_ret, 4),
                    "realised_ann_vol": round(realised_vol, 4),
                    "expected_ann_return": exp["ann_return"], "expected_ann_vol": exp["ann_vol"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="exit 3 when there is nothing worth saying")
    a = ap.parse_args()
    findings = venue_check() + drift_check()
    notable = [f for f in findings
               if f["kind"] in ("new_listing", "delisting", "funding_live", "vol_drift", "venue_unreachable")]
    payload = {"ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "notable": notable, "all": findings}
    if a.quiet and not notable:
        raise SystemExit(3)
    print(json.dumps(payload, indent=1))


if __name__ == "__main__":
    main()
