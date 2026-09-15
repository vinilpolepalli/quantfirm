#!/usr/bin/env python3
"""Render the Kalshi 15M metals desk page from committed state.

    python3 scripts/gen_kalshi_dashboard.py            # writes dashboard/kalshi.html

Data is baked into the file, exactly like gen_dashboard.py — the host serves
it raw, there is no fetch, and it works offline. The hourly check-in regenerates
it, so the page is as fresh as the last check-in and says so.

The visual system is scripts/theme.py, shared with the firm dashboard.

This page has a job beyond reporting a number: the P&L on this desk has been
misleading at every stage (docs/HANDOFF.md §0 lists four separate times our own
instrumentation produced a spectacular result that evaporated). So the verdict
and the t-stat are rendered at the SAME weight as the money, and the money is
never shown without them.
"""
from __future__ import annotations

import collections
import csv
import glob
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state")
OUT = os.path.join(ROOT, "dashboard", "kalshi.html")


def _rows():
    p = os.path.join(STATE, "kalshi_paper_trades.csv")
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def _books(rows):
    """Per-book n, lifetime, today, hit rate and break-even hit rate."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = {}
    for book in ("maker", "shadow"):
        rs = [r for r in rows if r.get("adapter") == book]
        if not rs:
            continue
        pnl = [float(r["pnl"]) for r in rs]
        wins = [p for p in pnl if p > 0]
        losses = [-p for p in pnl if p <= 0]
        aw = sum(wins) / len(wins) if wins else 0.0
        al = sum(losses) / len(losses) if losses else 0.0
        # break-even hit rate given the realised win/loss sizes
        be = al / (aw + al) if (aw + al) > 0 else 0.0
        n = len(pnl)
        mu = sum(pnl) / n
        sd = math.sqrt(sum((x - mu) ** 2 for x in pnl) / (n - 1)) if n > 1 else 0.0
        out[book] = {
            "n": n,
            "lifetime": sum(pnl),
            "today": sum(float(r["pnl"]) for r in rs
                         if (r.get("settled_at") or "")[:10] == today),
            "hit": len(wins) / n,
            "be": be,
            "avg_win": aw,
            "avg_loss": al,
            "t": (mu / (sd / math.sqrt(n))) if sd > 0 else 0.0,
            "equity": 500.0 + sum(pnl),
        }
    return out


def _daily(rows, book):
    d = collections.defaultdict(float)
    for r in rows:
        if r.get("adapter") == book:
            d[(r.get("settled_at") or "")[:10]] += float(r["pnl"])
    run, series = 0.0, []
    for day in sorted(d):
        run += d[day]
        series.append((day, 500.0 + run))
    return series


def _tape():
    tick, prints = set(), 0
    for f in sorted(glob.glob(os.path.join(STATE, "kalshi_tape_*.jsonl"))):
        for line in open(f):
            try:
                tick.add(json.loads(line)["ticker"])
                prints += 1
            except Exception:
                pass
    return prints, len(tick)


def _t_history():
    p = os.path.join(STATE, "kalshi_checkin_mark.json")
    try:
        return json.load(open(p)).get("t_history") or []
    except Exception:
        return []


def _spark(series, w=280, h=48):
    """Equity sparkline. Flat baseline at the $500 start so a reader sees
    immediately whether the book is above or below where it began."""
    if len(series) < 2:
        return ""
    vals = [v for _, v in series]
    lo, hi = min(vals + [500.0]), max(vals + [500.0])
    span = (hi - lo) or 1.0
    step = w / (len(vals) - 1)
    pts = " ".join(f"{i * step:.1f},{h - (v - lo) / span * h:.1f}"
                   for i, v in enumerate(vals))
    base = h - (500.0 - lo) / span * h
    up = vals[-1] >= 500.0
    col = "var(--gain)" if up else "var(--loss)"
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'preserveAspectRatio="none" aria-hidden="true">'
            f'<line x1="0" y1="{base:.1f}" x2="{w}" y2="{base:.1f}" '
            f'stroke="var(--rule)" stroke-dasharray="3 3" stroke-width="1"/>'
            f'<polyline points="{pts}" fill="none" stroke="{col}" '
            f'stroke-width="1.75" stroke-linejoin="round" stroke-linecap="round"/>'
            f'</svg>')


def _t_strip(hist):
    if not hist:
        return ""
    cells = []
    for v in hist[-14:]:
        cls = "up" if v > 0 else ("down" if v < 0 else "")
        cells.append(f'<span class="tcell {cls}">{v:+.2f}</span>')
    return '<div class="tstrip">' + "".join(cells) + "</div>"


EXTRA_CSS = """
.verdict { border:1px solid var(--rule); border-left:3px solid var(--warn);
  border-radius:var(--r-md); background:var(--sunk);
  padding:var(--s4) var(--s5); margin:var(--s6) 0 0; }
.verdict h2 { font:400 17px/1.2 var(--display); margin:0 0 var(--s2);
  color:var(--ink-1); }
.verdict p { margin:0 0 var(--s3); font-size:12.5px; color:var(--ink-2);
  max-width:66ch; }
.verdict p:last-child { margin-bottom:0; }
.verdict b { color:var(--ink-1); font-weight:500; }
.spark { display:block; width:100%; height:48px; margin:var(--s3) 0 0; }
.tstrip { display:flex; flex-wrap:wrap; gap:4px; margin-top:var(--s3); }
.tcell { font:500 10.5px/1 var(--mono); padding:4px 6px; border-radius:4px;
  background:var(--sunk); color:var(--ink-3); border:1px solid var(--rule-soft); }
.tcell.up { color:var(--gain); } .tcell.down { color:var(--loss); }
.bookhead { display:flex; align-items:baseline; justify-content:space-between;
  gap:var(--s3); }
.bookhead .fig { font:700 28px/1 var(--mono); letter-spacing:-.03em; }
.bookhead .fig.up { color:var(--gain); } .bookhead .fig.down { color:var(--loss); }
.kv { display:grid; grid-template-columns:1fr auto; gap:var(--s2) var(--s4);
  font-size:12px; margin-top:var(--s4); }
.kv dt { color:var(--ink-3); } .kv dd { margin:0; color:var(--ink-1);
  font-variant-numeric:tabular-nums; }
.status { display:inline-flex; align-items:center; gap:6px; }
.status .dot { width:7px; height:7px; border-radius:999px; background:var(--ink-3); }
.status.live .dot { background:var(--gain); }
.status.down .dot { background:var(--loss); }
"""


def render() -> str:
    rows = _rows()
    books = _books(rows)
    prints, markets = _tape()
    hist = _t_history()
    now = datetime.now(timezone.utc)

    mk = books.get("maker", {})
    sh = books.get("shadow", {})
    total = mk.get("lifetime", 0.0) + sh.get("lifetime", 0.0)
    combined_equity = 1000.0 + total   # two books, $500 each

    head = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta name="robots" content="noindex, nofollow">'
            f'<meta name="color-scheme" content="light dark">'
            f'<title>quantfirm — kalshi 15m metals</title>'
            f'<style>{theme.page_css("fonts/")}{EXTRA_CSS}</style></head><body>')

    parts = [head, '<div class="wrap">']

    parts.append(
        '<header class="mast">'
        '<h1 class="name">kalshi <em>15m metals</em></h1>'
        f'<div class="meta"><span>paper · no real money</span>'
        f'<span>{now:%Y-%m-%d %H:%M} UTC</span></div>'
        '</header><div class="rule"></div>')

    parts.append(
        '<section class="hero">'
        '<div class="kicker">combined paper equity — $1,000 start</div>'
        f'<span class="fig">{theme.money(combined_equity)}</span>'
        '<div class="deltas">'
        + theme.delta_pill(total, total / 1000.0, "since inception")
        + '</div>'
        '<p class="line">Two books against live Kalshi data: a <b>maker</b> leg '
        'resting quotes and a <b>shadow taker</b> leg crossing the spread. '
        'Neither has a demonstrated edge — see below.</p>'
        '</section>')

    # the verdict sits above the books, deliberately
    all_t = mk.get("t", 0.0)
    parts.append(
        '<div class="verdict"><h2>What this number does and does not mean</h2>'
        '<p>The measurement that actually tests the strategy is not the P&amp;L, '
        f'it is the <b>t-statistic</b> — currently <b>{all_t:+.2f}</b> on the maker '
        'book against a bar of 3.0. Every public print on this venue had a real '
        'resting maker on the other side, so the tape <i>is</i> the population of '
        'achievable maker fills at perfect queue priority. Measured there across '
        '134 settled markets, clustered one observation per market: '
        '<b>+1.01¢/contract, t = 1.55</b>. At half that sample it read t = 1.98, '
        'so more data made the effect <i>weaker</i>, and the favourite/underdog '
        'split flipped sign outright. That is noise, not a small real edge.</p>'
        '<p>Four times on this desk our own instrumentation produced a spectacular '
        'number that evaporated under scrutiny (+103.7%, +944%, t=+23.3, and a '
        'concurrency bug that was silently deleting filled positions). The P&amp;L '
        'above is real bookkeeping on paper trades; it is <b>not</b> evidence of '
        'edge, and a green stretch never was — P(week &gt; 0) exceeds 76% even '
        'under a no-edge null.</p></div>')

    parts.append('<div class="grid">')
    for key, label, note in (
            ("maker", "maker book", "rests quotes, pays no Kalshi fee"),
            ("shadow", "shadow taker book", "crosses the spread, pays taker fee")):
        b = books.get(key)
        if not b:
            continue
        cls = theme.dircls(b["lifetime"])
        slack = b["hit"] - b["be"]
        parts.append(
            f'<div class="card"><div class="bookhead">'
            f'<h2 style="margin:0">{label}</h2>'
            f'<span class="fig {cls}">{theme.money(b["lifetime"], True)}</span>'
            f'</div>'
            f'<div class="kicker" style="margin-top:6px">{note}</div>'
            + _spark(_daily(rows, key)) +
            f'<dl class="kv">'
            f'<dt>settled fills</dt><dd>{b["n"]}</dd>'
            f'<dt>today</dt><dd class="{theme.dircls(b["today"])}">'
            f'{theme.money(b["today"], True)}</dd>'
            f'<dt>hit rate</dt><dd>{b["hit"]:.3f}</dd>'
            f'<dt>break-even hit rate</dt><dd>{b["be"]:.3f}</dd>'
            f'<dt>slack over break-even</dt><dd>{slack:+.3f}</dd>'
            f'<dt>avg win / avg loss</dt>'
            f'<dd>{theme.money(b["avg_win"])} / {theme.money(b["avg_loss"])}</dd>'
            f'<dt>t-stat</dt><dd>{b["t"]:+.2f}</dd>'
            f'</dl></div>')
    parts.append('</div>')

    parts.append(
        '<div class="grid"><div class="card full">'
        '<h2>t-stat trajectory <span class="n">maker book, per check-in</span></h2>'
        '<div class="kicker">needs +3.00 to clear the significance gate; '
        'it has wandered in both directions and crossed zero</div>'
        + _t_strip(hist) + '</div></div>')

    parts.append(
        '<div class="grid"><div class="card full">'
        '<h2>evidence base <span class="n">public tape</span></h2>'
        '<dl class="kv">'
        f'<dt>trade prints recorded</dt><dd>{prints:,}</dd>'
        f'<dt>distinct 15-minute markets</dt><dd>{markets}</dd>'
        f'<dt>engine duty cycle</dt><dd>~10–20%</dd>'
        f'<dt>metals trading hours</dt><dd>24h weekdays, closed Fri 21:00Z → Sun 22:00Z</dd>'
        '</dl>'
        '<p style="font-size:12px;color:var(--ink-2);margin:var(--s4) 0 0;max-width:66ch">'
        'The tape is the raw material for the queue-free measurement quoted above. '
        'The duty cycle matters: this desk is not running continuously, so fills '
        'per week cannot be extrapolated from an hour.</p>'
        '</div></div>')

    parts.append(
        f'<div class="rule thin" style="margin-top:var(--s7)"></div>'
        f'<p style="font-size:11px;color:var(--ink-3);margin-top:var(--s3)">'
        f'Regenerated by the hourly desk check-in · '
        f'<a href="index.html">the book</a> · '
        f'<a href="options.html">options</a></p>')

    parts.append('</div></body></html>')
    return "".join(parts)


def main() -> int:
    html = render()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(html)
    print(f"wrote {OUT} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
