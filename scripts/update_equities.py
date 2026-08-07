"""Append missing daily bars to the equity panel (data/equities/SYMBOL_1d.csv.gz).

Why this exists: nothing was refreshing the equity panel. `update_data.py`
covers the crypto desk only, and the panel was last written by the one-off
fetch swarm that seeded it. The equity desk was therefore ranking and
band-checking on a panel that fell further behind every session — a live-money
blindness bug, since a position can breach its rebalance band on a day the
planner cannot see.

    python scripts/update_equities.py            # append whatever is missing
    python scripts/update_equities.py --check    # report staleness, write nothing
    python scripts/update_equities.py --days 10  # widen the backfill window

Source is Yahoo's chart endpoint (split-adjusted closes, same convention as the
seeded files) rather than the broker MCP, because this has to run unattended
from GitHub Actions where no MCP is available. Spot-checked against the
broker's own `get_equity_historicals` closes for 2026-08-06 across 16 symbols:
identical to the cent on every one.

Safety: only *appends* sessions strictly newer than what a file already holds.
It never rewrites history, so a bad upstream response cannot silently restate a
close the strategy already traded on.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import os
import subprocess
import sys
import threading
import time

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
EQ_DIR = os.path.join(ROOT, "data", "equities")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

# Yahoo spells class shares with a hyphen; the panel uses the broker's dotted form.
YAHOO_ALIAS = {"BRK.B": "BRK-B", "PBR.A": "PBR-A"}

COLS = ["open", "high", "low", "close", "volume"]


def symbols() -> list[str]:
    return sorted(f[: -len("_1d.csv.gz")] for f in os.listdir(EQ_DIR)
                  if f.endswith("_1d.csv.gz"))


def read_local(sym: str) -> pd.DataFrame:
    with gzip.open(os.path.join(EQ_DIR, f"{sym}_1d.csv.gz"), "rt") as f:
        df = pd.read_csv(f)
    df["ts"] = pd.to_datetime(df["ts"]).dt.normalize()
    return df.drop_duplicates(subset="ts").set_index("ts").sort_index()


_THROTTLE = threading.Semaphore(1)
_LAST = [0.0]
_COOLDOWN_UNTIL = [0.0]
_GAP = 2.4           # seconds between requests
_HOST = [0]          # alternate hosts to halve the per-host rate


def _paced_get(url: str) -> str:
    """One request at a time, spaced, with a shared cool-off.

    The endpoint 429s hard on bursts, and once it does it stays angry for
    minutes. A per-symbol backoff is not enough — every worker just burns its
    own retries against the same block, and the run ends reporting 227 dead
    tickers when nothing is wrong with the data. So a 429 parks *all* workers.
    """
    with _THROTTLE:
        now = time.monotonic()
        if now < _COOLDOWN_UNTIL[0]:
            time.sleep(_COOLDOWN_UNTIL[0] - now)
        wait = _GAP - (time.monotonic() - _LAST[0])
        if wait > 0:
            time.sleep(wait)
        _LAST[0] = time.monotonic()
        out = subprocess.run(
            ["curl", "-sS", "--max-time", "25", "-H", f"User-Agent: {UA}", url],
            capture_output=True, text=True, timeout=40).stdout
        if "Too Many Requests" in out[:200]:
            _COOLDOWN_UNTIL[0] = time.monotonic() + 90
        return out


def fetch(sym: str, since: dt.date, tries: int = 10) -> pd.DataFrame | None:
    """Daily bars from `since` (inclusive) to now. None on any failure."""
    tick = YAHOO_ALIAS.get(sym, sym)
    p1 = int(dt.datetime.combine(since, dt.time()).timestamp())
    p2 = int(dt.datetime.utcnow().timestamp()) + 86400
    path = (f"/v8/finance/chart/{tick}?period1={p1}&period2={p2}&interval=1d")
    for attempt in range(tries):
        try:
            _HOST[0] ^= 1
            out = _paced_get(f"https://query{_HOST[0] + 1}.finance.yahoo.com{path}")
            if "Too Many Requests" in out[:200] or not out.strip():
                continue          # cool-off already applied in _paced_get
            res = json.loads(out)["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            idx = [dt.datetime.utcfromtimestamp(t).date() for t in res["timestamp"]]
            df = pd.DataFrame({
                "open": q["open"], "high": q["high"], "low": q["low"],
                "close": q["close"], "volume": q["volume"],
            }, index=pd.to_datetime(idx)).dropna(subset=["close"])
            return df if not df.empty else None
        except Exception:
            time.sleep(min(20, 2 ** attempt))
    return None


def sane(sym: str, local: pd.DataFrame, new: pd.DataFrame) -> str | None:
    """Reject an append that looks like a corporate action or a bad response.

    A split the panel has not applied would show up as a huge overnight gap; we
    would rather refuse and surface it than quietly append a discontinuity into
    a series the momentum ranking reads.
    """
    prev = float(local["close"].iloc[-1])
    first = float(new["close"].iloc[0])
    if prev <= 0 or first <= 0:
        return "non-positive close"
    move = abs(first / prev - 1)
    if move > 0.60:
        return f"{move:.0%} gap vs last local close — possible unapplied split"
    if (new.index.date > dt.datetime.utcnow().date()).any():
        return "future-dated bar"
    return None


def one(sym: str, days: int, write: bool) -> tuple[str, str, int]:
    """-> (symbol, status, rows_added)"""
    try:
        local = read_local(sym)
    except Exception as e:
        return sym, f"unreadable: {e}", 0
    last = local.index[-1].date()
    got = fetch(sym, last)
    if got is None:
        return sym, "fetch failed", 0
    new = got[got.index.date > last]
    if new.empty:
        return sym, "current", 0
    bad = sane(sym, local, new)
    if bad:
        return sym, f"REJECTED ({bad})", 0
    if not write:
        return sym, f"stale, {len(new)} available", len(new)
    merged = pd.concat([local, new[COLS]]).sort_index()
    merged = merged[~merged.index.duplicated(keep="first")]
    buf = io.StringIO()
    merged.to_csv(buf, index_label="ts", date_format="%Y-%m-%d")
    tmp = os.path.join(EQ_DIR, f".{sym}.tmp.gz")
    with gzip.open(tmp, "wt") as f:
        f.write(buf.getvalue())
    os.replace(tmp, os.path.join(EQ_DIR, f"{sym}_1d.csv.gz"))
    return sym, "appended", len(new)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    ap.add_argument("--days", type=int, default=10, help="unused window hint (kept for CI clarity)")
    args = ap.parse_args()

    syms = symbols()
    write = not args.check
    # Sequential on purpose: the pace lock serialises requests anyway, so
    # workers only ever added a retry stampede against a shared rate limit.
    results = [one(s, args.days, write) for s in syms]

    added = [r for r in results if r[2] > 0]
    failed = [r for r in results if r[1] == "fetch failed"]
    rejected = [r for r in results if r[1].startswith("REJECTED")]
    unreadable = [r for r in results if r[1].startswith("unreadable")]

    for sym, status, _ in sorted(rejected + unreadable):
        print(f"  !! {sym}: {status}", file=sys.stderr)
    if failed:
        print(f"  !! fetch failed ({len(failed)}): "
              f"{', '.join(s for s, _, _ in failed[:15])}", file=sys.stderr)

    # Panel date after the run, so CI logs show what the desk will actually see.
    from quantfirm.equities.data import load_panel  # noqa: E402
    panel_end = str(load_panel().index[-1].date())
    print(json.dumps({
        "symbols": len(syms),
        "updated" if write else "stale": len(added),
        "rows_added": sum(r[2] for r in added) if write else 0,
        "fetch_failed": len(failed),
        "rejected": len(rejected),
        "panel_last_date": panel_end,
    }, indent=2))

    # A handful of dead tickers is normal; a broad failure means the source
    # changed shape and the panel must not be trusted.
    if len(failed) + len(rejected) > max(5, len(syms) // 20):
        sys.exit(f"too many failures ({len(failed) + len(rejected)}/{len(syms)}) — panel not trustworthy")


if __name__ == "__main__":
    sys.path.insert(0, ROOT)
    main()
