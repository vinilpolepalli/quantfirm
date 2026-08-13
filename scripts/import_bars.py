"""Merge daily bars from a second vendor into the equity panel.

Why this exists
---------------
`scripts/update_equities.py` fetches from Yahoo over plain HTTP. That endpoint
answers 429 from datacenter egress — both this host and GitHub's runners — so
the panel can sit stale for days while the nightly job reports success. A stale
panel is not a cosmetic problem: `plan()` refuses to trade on one, so the desk
stops rebalancing entirely, and a holding can drift out of its band unnoticed.

The only equity-bar source reachable here is the broker's own API, via an MCP
server that answers to an agent rather than to a cron job. So the fetch and the
merge are split: a desk session pulls bars and writes them to a JSON file, and
this script does the validation and the write. That keeps the risky half — the
part that mutates the series a momentum ranking reads — in reviewed code with
guards, instead of in an agent's improvised one-liner.

Input format (a JSON object, symbol -> list of bars):

    {"AAPL": [{"date": "2026-08-06", "open": 1.0, "high": 2.0,
               "low": 0.5, "close": 1.5, "volume": 123}, ...], ...}

Raw broker responses are also accepted, and are the preferred input. Pass any
number of files holding a `get_equity_historicals` payload
(`{"data": {"results": [{"symbol":..., "bars": [...]}]}}`) and they are parsed
directly. Nothing is retyped by hand: a bar that an agent copies through its
own context is a bar that can acquire a typo, and the overlap gate below only
proves the vendor agrees on dates the panel already has, so it cannot catch a
damaged value on one of the new dates. Feed the file, not the transcript.

Why all-or-nothing
------------------
`load_panel` outer-joins symbols on the union of their dates, so importing a
subset appends rows on which every other symbol is NaN. Two things then break
at once: the cross-sectional rank sees a universe collapsed to whatever was
imported, and `plan()`'s stale-panel guard reads the new maximum date and
concludes the panel is current. A partial import is therefore worse than no
import, and the default is to refuse one (see --allow-partial).

The overlap gate
----------------
Every symbol must supply at least one date the panel already has, and those
closes must agree with the panel to within --tol. This is the check that makes
a second vendor safe to mix in:

  * it catches a different adjustment convention (split- vs dividend-adjusted
    history diverges on exactly these overlapping dates),
  * it catches a symbol whose ticker means something different at the other
    vendor, and
  * it catches transcription damage, since bars that arrive through an agent's
    context are copied by hand.

A symbol that fails the gate is skipped and reported. It is never merged, and
nothing is written for it, because a silently wrong price here would propagate
into the cross-sectional rank and out into real orders.

Usage:
    python scripts/import_bars.py raw/*.txt --check     # report only
    python scripts/import_bars.py raw/*.txt             # merge and write
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import sys

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
# Honour the same override quantfirm/equities/data.py uses. If these two ever
# disagree about where the panel lives, this script would validate one series
# and the strategy would rank another.
EQ_DIR = os.environ.get("QF_EQ_DATA_DIR", os.path.join(ROOT, "data", "equities"))
COLS = ["open", "high", "low", "close", "volume"]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_equities import sane  # noqa: E402  same corporate-action guard


def read_local(sym: str) -> pd.DataFrame:
    with gzip.open(os.path.join(EQ_DIR, f"{sym}_1d.csv.gz"), "rt") as f:
        return pd.read_csv(f, index_col=0, parse_dates=True)


def write_local(sym: str, merged: pd.DataFrame) -> None:
    buf = io.StringIO()
    merged.to_csv(buf, index_label="ts", date_format="%Y-%m-%d")
    tmp = os.path.join(EQ_DIR, f".{sym}.tmp.gz")
    with gzip.open(tmp, "wt") as f:
        f.write(buf.getvalue())
    os.replace(tmp, os.path.join(EQ_DIR, f"{sym}_1d.csv.gz"))


def load_payloads(paths: list[str]) -> dict[str, list[dict]]:
    """Read one or more input files into a single symbol -> [bars] mapping.

    Accepts both the plain {symbol: [bars]} form and a raw broker
    `get_equity_historicals` response. Later files win on a duplicate symbol.
    """
    out: dict[str, list[dict]] = {}
    for p in paths:
        with open(p) as f:
            blob = json.load(f)
        results = (blob.get("data") or {}).get("results") if isinstance(blob, dict) else None
        if results is not None:                      # raw broker response
            for res in results:
                out[res["symbol"]] = [
                    {"date": str(b["begins_at"])[:10],
                     "open": b["open_price"], "high": b["high_price"],
                     "low": b["low_price"], "close": b["close_price"],
                     "volume": b["volume"]}
                    for b in res.get("bars", [])
                    # An interpolated bar is synthesised gap-fill, not a
                    # session. Appending one invents a close the tape never
                    # printed, so drop it and let the date stay absent.
                    if not b.get("interpolated")
                ]
        elif isinstance(blob, dict):                 # plain {symbol: [bars]}
            out.update(blob)
        else:
            raise SystemExit(f"{p}: expected a JSON object")
    return out


def to_frame(bars: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    if "date" not in df.columns:
        raise ValueError("each bar needs a 'date'")
    df.index = pd.to_datetime(df["date"]).dt.normalize()
    missing = [c for c in COLS if c not in df.columns]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    return df[COLS].astype(float).sort_index()


def one(sym: str, bars: list[dict], tol: float, write: bool,
        fix_splits: bool = True) -> tuple[str, int, str, object]:
    """-> (status, rows_added, detail, resulting_end_date).

    The end date is what this symbol's series would finish on after the import,
    which is what the uniformity check in main() is built from.
    """
    try:
        local = read_local(sym)
    except FileNotFoundError:
        # Not in the universe. A batched fetch will over-collect; that is not a
        # failure, it just is not ours to write.
        return "extra", 0, "not in the panel universe, ignored", None
    except Exception as e:
        return "skip", 0, f"unreadable local file: {e}", None

    try:
        new = to_frame(bars)
    except Exception as e:
        return "skip", 0, f"bad input: {e}", None
    if new.empty:
        return "skip", 0, "no bars supplied", None

    # -- overlap gate ------------------------------------------------------
    shared = local.index.intersection(new.index)
    if len(shared) == 0:
        return "skip", 0, ("no overlapping date with the panel — cannot verify "
                           "the vendor agrees, refusing to merge unverified bars"), None
    a = local.loc[shared, "close"].astype(float)
    b = new.loc[shared, "close"].astype(float)
    rel = ((b - a) / a).abs()
    worst = rel.idxmax()
    rescaled = ""
    if float(rel.max()) > tol:
        # A split the panel never applied shows up as ONE constant ratio on
        # every shared date: the vendor adjusts its whole history, the panel
        # holds pre-split prices. A constant factor cancels out of every
        # return, so the panel's momentum was never wrong — but appending
        # post-split bars onto pre-split ones would print a fake gap on the
        # seam. Rescale the local history instead of refetching it.
        k = (a / b)
        spread = float(k.max() / k.min() - 1)
        if spread <= tol and len(shared) >= 5 and fix_splits:
            factor = float(k.median())
            local = local.copy()
            for c in ("open", "high", "low", "close"):
                local[c] = local[c].astype(float) / factor
            local["volume"] = local["volume"].astype(float) * factor
            if write:
                write_local(sym, local)
            a = local.loc[shared, "close"].astype(float)
            rel = ((b - a) / a).abs()
            rescaled = (f"rescaled local history by 1/{factor:.6g} "
                        f"(constant-ratio corporate action); ")
        else:
            hint = ("" if spread <= tol else
                    f", ratio not constant (spread {spread:.2%})")
            return "skip", 0, (
                f"overlap mismatch on {len(shared)} shared date(s): worst "
                f"{worst.date()} panel {a[worst]:.4f} vs vendor {b[worst]:.4f} "
                f"({rel.max():.2%} > tol {tol:.2%}){hint}"), None
    overlap_note = (f"{rescaled}{len(shared)} overlap date(s) agree "
                    f"(max {rel.max():.2e})")

    # -- append only what is genuinely new ---------------------------------
    last = local.index[-1]
    add = new[new.index > last]
    if add.empty:
        return "current", 0, overlap_note, last.date()

    bad = sane(sym, local, add)          # same split / future-bar guard as Yahoo
    if bad:
        return "reject", 0, f"{bad}; {overlap_note}", last.date()

    end = add.index[-1].date()
    if not write:
        return "ok", len(add), f"{overlap_note}; {len(add)} row(s) available", end

    merged = pd.concat([local, add[COLS]]).sort_index()
    merged = merged[~merged.index.duplicated(keep="first")]
    write_local(sym, merged)
    return "ok", len(add), f"{overlap_note}; appended through {end}", end


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json_paths", nargs="+",
                    help="input file(s): raw get_equity_historicals responses "
                         "or {symbol: [bars]} objects")
    ap.add_argument("--check", action="store_true",
                    help="validate and report, write nothing")
    ap.add_argument("--tol", type=float, default=0.0005,
                    help="max relative close disagreement on overlapping dates "
                         "(default 0.0005, i.e. 5bp)")
    ap.add_argument("--no-fix-splits", action="store_true",
                    help="do not rescale local history when the overlap "
                         "disagrees by one constant factor; treat it as a "
                         "mismatch and skip the symbol")
    ap.add_argument("--allow-partial", action="store_true",
                    help="write even if some panel symbols are missing or "
                         "failed. Leaves the panel ragged; see the module "
                         "docstring for why that defeats the stale guard")
    args = ap.parse_args()

    payload = load_payloads(args.json_paths)

    # Dry-run everything first. Nothing is written until the whole universe is
    # accounted for, so a failed batch cannot leave the panel half-updated.
    plan: dict[str, tuple[str, int, str, object]] = {}
    for sym in sorted(payload):
        plan[sym] = one(sym, payload[sym], args.tol, write=False,
                        fix_splits=not args.no_fix_splits)

    on_disk = {f[:-len("_1d.csv.gz")] for f in os.listdir(EQ_DIR)
               if f.endswith("_1d.csv.gz")}
    absent = sorted(on_disk - set(payload))
    failed = sorted(s for s, (st, _, _, _) in plan.items() if st in ("skip", "reject"))

    # Would this import leave every symbol finishing on the same date? A mixed
    # outcome is the trap: some symbols advance, the rest report "current"
    # because the vendor had nothing new for them, and the result is the exact
    # ragged panel this script exists to prevent. It is not enough that no
    # symbol FAILED — they must all land on the same last date.
    ends = {s: e for s, (st, _, _, e) in plan.items() if st != "extra" and e}
    end_tally: dict[object, int] = {}
    for e in ends.values():
        end_tally[e] = end_tally.get(e, 0) + 1
    ragged = len(end_tally) > 1
    if ragged:
        newest = max(end_tally)
        behind = sorted(s for s, e in ends.items() if e != newest)
        print(f"\n  RAGGED: {len(behind)} symbol(s) would stay behind {newest}: "
              f"{', '.join(behind[:10])}{' …' if len(behind) > 10 else ''}")
        print("  end dates after import: "
              + ", ".join(f"{e}={n}" for e, n in sorted(end_tally.items())))

    for sym in sorted(plan):
        st, _, detail, _end = plan[sym]
        if st != "current":
            print(f"  {st:<8} {sym:<6} {detail}")
    if absent:
        print(f"\n  {len(absent)} panel symbol(s) absent from the input: "
              f"{', '.join(absent[:12])}{' …' if len(absent) > 12 else ''}")

    counts: dict[str, int] = {}
    for st, _, _, _ in plan.values():
        counts[st] = counts.get(st, 0) + 1
    would_add = sum(n for _, n, _, _ in plan.values())
    print("\n" + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
          + f", rows={would_add}")

    incomplete = bool(absent or failed or ragged)
    if args.check:
        print("(--check, nothing written)")
        return sys.exit(1 if incomplete else 0)
    if incomplete and not args.allow_partial:
        sys.exit(
            f"\nREFUSING to write: {len(absent)} symbol(s) missing from the "
            f"input, {len(failed)} failed validation"
            f"{', and the result would be ragged' if ragged else ''}.\n"
            "A partial import appends rows the rest of the universe does not "
            "have, which collapses the cross-sectional rank AND makes plan()'s "
            "stale-panel guard read the panel as current. Supply every symbol, "
            "or pass --allow-partial if you have a specific reason.\n")

    written = 0
    for sym in sorted(payload):
        if plan[sym][0] != "ok":
            continue
        _, n, _detail, _end = one(sym, payload[sym], args.tol, write=True,
                                  fix_splits=not args.no_fix_splits)
        written += n
    print(f"wrote {written} row(s) across "
          f"{sum(1 for s in plan.values() if s[0] == 'ok')} symbol(s)")
    sys.exit(1 if incomplete else 0)


if __name__ == "__main__":
    main()
