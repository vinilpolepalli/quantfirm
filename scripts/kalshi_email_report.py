#!/usr/bin/env python3
"""Compose the 4-hourly desk email body. Prints plain text to stdout.

Deliberately leads with the verdict, not the money. This desk's P&L has been
misleading at every stage, so an email that opens with a dollar figure would
be actively misleading at a glance -- and a glance is all an email gets.
"""
from __future__ import annotations

import csv, glob, json, math, os, sys, collections
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state")


def books():
    p = os.path.join(STATE, "kalshi_paper_trades.csv")
    rows = list(csv.DictReader(open(p))) if os.path.exists(p) else []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = {}
    for b in ("maker", "shadow"):
        rs = [r for r in rows if r.get("adapter") == b]
        if not rs:
            continue
        pnl = [float(r["pnl"]) for r in rs]
        w = [x for x in pnl if x > 0]; l = [-x for x in pnl if x <= 0]
        aw = sum(w)/len(w) if w else 0.0; al = sum(l)/len(l) if l else 0.0
        n = len(pnl); mu = sum(pnl)/n
        sd = math.sqrt(sum((x-mu)**2 for x in pnl)/(n-1)) if n > 1 else 0.0
        out[b] = dict(n=n, life=sum(pnl), hit=len(w)/n,
                      be=(al/(aw+al) if aw+al else 0.0),
                      t=(mu/(sd/math.sqrt(n)) if sd > 0 else 0.0),
                      today=sum(float(r["pnl"]) for r in rs
                                if (r.get("settled_at") or "")[:10] == today))
    return out


def tape():
    tick, n = set(), 0
    for f in sorted(glob.glob(os.path.join(STATE, "kalshi_tape_*.jsonl"))):
        for line in open(f):
            try:
                tick.add(json.loads(line)["ticker"]); n += 1
            except Exception:
                pass
    return n, len(tick)


def main() -> int:
    bk = books()
    prints, markets = tape()
    try:
        hist = json.load(open(os.path.join(STATE, "kalshi_checkin_mark.json"))).get("t_history") or []
    except Exception:
        hist = []
    mk, sh = bk.get("maker", {}), bk.get("shadow", {})
    now = datetime.now(timezone.utc)
    L = []
    L.append(f"Kalshi 15m metals desk — {now:%Y-%m-%d %H:%M} UTC")
    L.append("")
    L.append("VERDICT: no demonstrated edge. The discriminating statistic is the")
    L.append(f"t-stat, not the P&L. Maker book t = {mk.get('t',0):+.2f} against a bar of 3.0.")
    L.append("The queue-free tape measurement across 134 clustered markets reads")
    L.append("+1.01c/contract, t=1.55 — weaker than the t=1.98 it showed at half")
    L.append("the sample, with the favourite/underdog split flipping sign. Noise.")
    L.append("")
    L.append("PAPER BOOKS ($500 each, no real money)")
    for key, label in (("maker", "maker"), ("shadow", "shadow taker")):
        b = bk.get(key)
        if not b:
            continue
        slack = b["hit"] - b["be"]
        L.append(f"  {label:<13} n={b['n']:<4} lifetime {b['life']:+8.2f}   today {b['today']:+8.2f}")
        L.append(f"  {'':<13} hit {b['hit']:.3f} vs break-even {b['be']:.3f}  (slack {slack:+.3f})   t={b['t']:+.2f}")
    L.append("")
    if hist:
        L.append("t trajectory (recent check-ins): " + " ".join(f"{v:+.2f}" for v in hist[-10:]))
        L.append("")
    L.append(f"EVIDENCE: {prints:,} trade prints across {markets} distinct 15-minute markets.")
    L.append("Engine duty cycle ~10-20% — the desk is NOT running continuously, so")
    L.append("fills per week cannot be extrapolated from a good hour. Metals trade")
    L.append("24h on weekdays and close Fri 21:00Z to Sun 22:00Z.")
    L.append("")
    # The Vercel page exists but has never deployed -- the free-tier creation
    # cap rejected it, and that domain serves from main where the file is not.
    # The artifact build is the URL that actually resolves.
    L.append("Live dashboard: https://claude.ai/artifact/3KKbjgeKEBveR88KqS6Dbr")
    L.append("")
    L.append("A green stretch is not evidence: P(week > 0) exceeds 76% even under a")
    L.append("no-edge null. Four times this desk's own instrumentation produced a")
    L.append("spectacular number that evaporated under scrutiny.")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
