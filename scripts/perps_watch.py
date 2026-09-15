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
# What this watch has ALREADY told the owner. Without it every run re-reports the
# same standing fact forever, and a weekly email that always says the same thing
# stops being read long before the week it finally says something new.
MARK = os.path.join(STATE, "perps_watch_mark.json")

# docs/KALSHI_PERPS.md section 9: what would change the verdict. Breadth in crypto
# was measured and does not help, so the diversifier worth waiting for is a perp
# that is NOT crypto.
EXPECTED = {
    "incumbent": {"ann_return": 0.098, "ann_vol": 0.080},
    "candidate": {"ann_return": 0.152, "ann_vol": 0.090},
    "growth":    {"ann_return": 0.220, "ann_vol": 0.128},
}


def load_mark() -> dict:
    try:
        with open(MARK) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_mark(mark: dict) -> None:
    os.makedirs(STATE, exist_ok=True)
    tmp = MARK + ".tmp"
    with open(tmp, "w") as f:
        json.dump(mark, f, indent=1, sort_keys=True)
    os.replace(tmp, MARK)


MIN_FUNDING_INTERVALS = 30      # ten days; below this a "rate" is two observations and a slope


def funding_reading(asset: str, n: int = 90) -> dict | None:
    """Deadband status of the last ``n`` funding intervals, or None if there is no history."""
    from quantfirm.perps import data as D
    f = D.load_kalshi_funding(asset)
    if f is None or not len(f):
        return None
    return summarise_funding(f, n)


def summarise_funding(f, n: int = 90) -> dict:
    """The arithmetic of a reading, split out from the disk read so it can be tested."""
    recent = f.tail(n)
    live = recent[recent.abs() >= 1e-12]
    med = float(np.median(live)) if len(live) else 0.0
    mean = float(recent.mean())
    # Three eight-hour intervals a day; a long pays this fraction of notional when positive.
    # The headline annualisation is the MEAN over every interval, zeros included, because a
    # holder sits through the zeros too: that is what holding actually costs. Annualising the
    # median of the non-zero ones instead answers a different and much narrower question
    # ("what does an interval cost WHEN it charges"), and on a market that is quiet most of
    # the time it overstates the cost of holding by the reciprocal of the live share.
    return {
        "intervals": int(len(recent)),
        "zero_share": round(float((recent.abs() < 1e-12).mean()), 3),
        "median_nonzero": round(med, 6),
        "annualised": round(mean * 3 * 365, 4),
        "annualised_when_live": round(med * 3 * 365, 4),
    }


def funding_changed(prev: dict | None, now: dict) -> str | None:
    """Why this reading is worth an email, or None if it is last week's news."""
    if prev is None:
        if now["zero_share"] >= 0.5:
            return None          # still inside the deadband, exactly as section 2 documents
        return "funding is live: most recent intervals are OUTSIDE the deadband"
    was, is_ = prev["zero_share"], now["zero_share"]
    if (was >= 0.5) != (is_ >= 0.5):
        return ("funding went LIVE: most intervals now clear the deadband"
                if is_ < 0.5 else "funding went QUIET again: most intervals are back inside the deadband")
    if abs(is_ - was) >= 0.15:
        return f"deadband share moved {was:.0%} -> {is_:.0%}"
    if abs(now["annualised"] - prev["annualised"]) >= 0.05:
        return f"carry moved {prev['annualised']:+.1%} -> {now['annualised']:+.1%} a year"
    return None


def venue_check(mark: dict) -> list[dict]:
    """New listings, especially outside crypto, and whether funding still rounds to zero.

    Reports CHANGES, not states. A standing fact is emailed once; after that it lives in
    docs/KALSHI_PERPS.md, which is where a standing fact belongs.
    """
    out = []
    try:
        from quantfirm.perps.client import MarginClient
        from quantfirm.perps.specs import SPECS
        known = {s.ticker for s in SPECS.values()}
        markets = MarginClient("prod").markets()
    except Exception as e:                                   # offline, rate limited, changed API
        return [{"kind": "venue_unreachable", "detail": f"{type(e).__name__}: {e}"}]

    seen = set(mark.get("reported_listings") or [])
    for m in markets:
        t = m.get("ticker")
        if t in known:
            continue
        cls = (m.get("asset_class") or "").lower()
        notable = cls not in ("crypto", "")
        # A non-crypto listing keeps nagging until someone puts it in specs.py: it is the
        # one thing section 9 says would change the verdict, so being quietly forgotten
        # is the failure mode worth spending a repeated email on. Another crypto name is
        # reported once and then dropped.
        if t in seen and not notable:
            continue
        out.append({
            "kind": "new_listing",
            "ticker": t,
            "asset_class": m.get("asset_class"),
            "notable": notable,
            "repeat": t in seen,
            "detail": ("A NON-CRYPTO perp. Section 9 says this is the one thing that would "
                       "genuinely change the verdict: all twenty tradable crypto perps together "
                       "are about two and a half independent bets, so the missing diversifier "
                       "has to come from outside crypto.")
            if notable else "Another crypto name; breadth there is already measured as an illusion.",
        })
        seen.add(t)
    mark["reported_listings"] = sorted(seen)

    if len(markets) < len(known):
        out.append({"kind": "delisting",
                    "detail": f"venue lists {len(markets)} markets, specs know {len(known)}"})

    # Is the funding deadband still zeroing almost everything? Measured per traded asset,
    # because BTC cleared the deadband in 2026 while ETH did not.
    from quantfirm.perps.specs import RESEARCH_UNIVERSE
    prev_all = mark.get("funding") or {}
    now_all = dict(prev_all)
    for asset in RESEARCH_UNIVERSE:
        try:
            now = funding_reading(asset)
        except Exception:
            continue
        if now is None:
            continue
        if now["intervals"] < MIN_FUNDING_INTERVALS:
            out.append({"kind": "funding_thin", "asset": asset, **now,
                        "detail": (f"only {now['intervals']} intervals of Kalshi funding history; "
                                   f"need {MIN_FUNDING_INTERVALS} before a rate here means anything")})
            continue          # and do NOT mark it, so the real first reading still reports
        now_all[asset] = now
        why = funding_changed(prev_all.get(asset), now)
        if why:
            out.append({"kind": "funding_change", "asset": asset, "why": why, **now,
                        "detail": (f"{asset.upper()} funding: {now['zero_share']:.0%} of the last "
                                   f"{now['intervals']} intervals round to zero; the rest run at a "
                                   f"median {now['median_nonzero']:+.4%} per interval. Averaged over "
                                   f"every interval INCLUDING the zeros, which is what holding through "
                                   f"them actually costs, that is {now['annualised']:+.1%} a year "
                                   f"{'paid BY longs' if now['annualised'] > 0 else 'paid TO longs'} "
                                   f"({now['annualised_when_live']:+.1%} on the intervals that charge). "
                                   "Section 2 assumed the deadband zeroed this.")})
        else:
            out.append({"kind": "funding_stable", "asset": asset, **now})
    mark["funding"] = now_all
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
    mark = load_mark()
    findings = venue_check(mark) + drift_check()
    notable = [f for f in findings
               if f["kind"] in ("new_listing", "delisting", "funding_change",
                                "vol_drift", "venue_unreachable")]
    # Only remember a reading once it has been reported, so a run that says nothing
    # cannot silently swallow the finding the next run would have made.
    if notable and not any(f["kind"] == "venue_unreachable" for f in notable):
        save_mark(mark)
    payload = {"ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "notable": notable, "all": findings}
    if a.quiet and not notable:
        raise SystemExit(3)
    print(json.dumps(payload, indent=1))


if __name__ == "__main__":
    main()
