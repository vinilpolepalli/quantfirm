#!/usr/bin/env python3
"""Daily paper-trading report for the Kalshi perps desk, as email-ready HTML.

Reads every book's committed status file, compares against yesterday's snapshot
in ``state/perps_report_history.jsonl``, and prints a JSON object with
``subject``, ``html`` and ``text``. Nothing here trades, sends, or needs a key.

    python scripts/perps_daily_report.py            # JSON to stdout
    python scripts/perps_daily_report.py --html-only > /tmp/report.html

The HTML is inline-styled and table-based because email clients strip <style>
blocks. Markdown is deliberately NOT used: an email client renders HTML, and a
raw asterisk is not a bullet.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import html
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state")
HISTORY = os.path.join(STATE, "perps_report_history.jsonl")

GREEN, RED, MUTED, INK = "#0b7a3b", "#b3261e", "#5f6368", "#1f2328"
DASH = "\u2014"   # a literal em dash renders in HTML and in plain text; &mdash; only in HTML
BOOK_LABEL = {
    "incumbent": "trend gate, 4 assets, 12% vol target",
    "candidate": "core + 30% residual-momentum sleeve, 12% vol",
    "growth": "same blend at an 18% vol target and a 40% sleeve",
}


def load_books() -> list[dict]:
    books = []
    for path in sorted(glob.glob(os.path.join(STATE, "perps_desk_status*.json"))):
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        d["_book"] = d.get("book") or "incumbent"
        books.append(d)
    order = {"incumbent": 0, "candidate": 1, "growth": 2}
    return sorted(books, key=lambda b: (order.get(b["_book"], 9), b["_book"]))


def previous() -> dict:
    """Yesterday's snapshot per book, or {} on the first run."""
    if not os.path.exists(HISTORY):
        return {}
    rows = []
    with open(HISTORY) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows[-1].get("books", {}) if rows else {}


def append_history(books: list[dict]) -> None:
    row = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "books": {b["_book"]: {"equity": b.get("equity"), "n_positions": len(b.get("positions", [])),
                                  "gross": b.get("gross_leverage"), "fees": b.get("fees"),
                                  "assets": sorted(p["asset"] for p in b.get("positions", []))}
                     for b in books}}
    os.makedirs(STATE, exist_ok=True)
    with open(HISTORY, "a") as f:
        f.write(json.dumps(row) + "\n")


def _money(x) -> str:
    return f"${x:,.2f}" if isinstance(x, (int, float)) else DASH


def _signed(x, pct=False) -> tuple[str, str]:
    if not isinstance(x, (int, float)):
        return DASH, MUTED
    s = f"{x:+.2%}" if pct else f"{x:+,.2f}"
    return s, (GREEN if x > 0 else RED if x < 0 else MUTED)


def build(books: list[dict], prev: dict, note: str = "") -> dict:
    today = dt.datetime.now(dt.timezone.utc).strftime("%a %d %b %Y")
    total = sum(b.get("equity", 0) or 0 for b in books)
    start = sum(b.get("bankroll0", 0) or 0 for b in books)
    prev_total = sum((prev.get(b["_book"], {}) or {}).get("equity") or 0 for b in books) or None

    rows, text_rows, notes = [], [], []
    for b in books:
        name = b["_book"]
        eq, b0 = b.get("equity"), b.get("bankroll0") or 0
        p = prev.get(name, {}) or {}
        day = (eq - p["equity"]) if (isinstance(eq, (int, float)) and p.get("equity")) else None
        day_pct = (day / p["equity"]) if (day is not None and p.get("equity")) else None
        since = (eq / b0 - 1) if (isinstance(eq, (int, float)) and b0) else None
        day_s, day_c = _signed(day)
        since_s, since_c = _signed(since, pct=True)
        legs = len(b.get("positions", []))
        halted = b.get("halted") or ""
        rows.append(f"""
      <tr>
        <td style="padding:10px 12px;border-bottom:1px solid #e6e8eb;color:{INK};">
          <strong>{html.escape(name.title())}</strong><br>
          <span style="color:{MUTED};font-size:12px;">{BOOK_LABEL.get(name, '')}</span>
        </td>
        <td style="padding:10px 12px;border-bottom:1px solid #e6e8eb;text-align:right;color:{INK};">{_money(eq)}</td>
        <td style="padding:10px 12px;border-bottom:1px solid #e6e8eb;text-align:right;color:{day_c};">{day_s}</td>
        <td style="padding:10px 12px;border-bottom:1px solid #e6e8eb;text-align:right;color:{since_c};">{since_s}</td>
        <td style="padding:10px 12px;border-bottom:1px solid #e6e8eb;text-align:right;color:{INK};">{b.get('gross_leverage', DASH)}</td>
        <td style="padding:10px 12px;border-bottom:1px solid #e6e8eb;text-align:right;color:{INK};">{legs}</td>
      </tr>""")
        text_rows.append(f"  {name:<10} {_money(eq):>10}  day {day_s:>8}  since start {since_s:>8}  "
                         f"gross {b.get('gross_leverage')}  legs {legs}")
        if halted:
            notes.append(f"{name} is HALTED: {halted}")
        if b.get("kill_switch"):
            notes.append(f"{name}: kill switch is tripped")
        was = set(p.get("assets") or [])
        now = set(x["asset"] for x in b.get("positions", []))
        if was and (was ^ now):
            opened, closed = sorted(now - was), sorted(was - now)
            bits = []
            if opened:
                bits.append("opened " + ", ".join(opened))
            if closed:
                bits.append("closed " + ", ".join(closed))
            notes.append(f"{name}: " + "; ".join(bits))

    tot_day = (total - prev_total) if prev_total else None
    tot_day_s, tot_day_c = _signed(tot_day)
    tot_since_s, tot_since_c = _signed((total / start - 1) if start else None, pct=True)
    headline = (f"{_money(total)} across {len(books)} paper books, "
                f"{tot_day_s + ' today' if tot_day is not None else 'first report'}")

    banner_html = banner_text = ""
    if note:
        banner_html = (f'<tr><td style="padding:0 20px;">'
                       f'<div style="margin:14px 0 0;padding:10px 12px;background:#fff8e1;'
                       f'border:1px solid #f0d58c;border-radius:6px;color:#5c4400;font-size:13px;'
                       f'line-height:1.5;">{html.escape(note)}</div></td></tr>')
        banner_text = note + "\n\n"

    notes_html = ""
    if notes:
        items = "".join(f'<li style="margin:2px 0;">{html.escape(n)}</li>' for n in notes)
        notes_html = (f'<p style="margin:18px 0 6px;color:{INK};font-weight:600;">Changes</p>'
                      f'<ul style="margin:0;padding-left:20px;color:{INK};font-size:14px;">{items}</ul>')

    html_body = f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f6f7f9;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f7f9;padding:24px 12px;">
 <tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="max-width:640px;background:#ffffff;border:1px solid #e6e8eb;border-radius:10px;
                font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
   <tr><td style="padding:20px 20px 4px;">
     <div style="color:{MUTED};font-size:12px;letter-spacing:.06em;text-transform:uppercase;">Kalshi perps &middot; paper</div>
     <div style="color:{INK};font-size:20px;font-weight:600;margin-top:4px;">{today}</div>
     <div style="color:{tot_day_c};font-size:15px;margin-top:8px;">{headline}</div>
     <div style="color:{MUTED};font-size:13px;margin-top:2px;">Since start {tot_since_s}</div>
   </td></tr>
   {banner_html}
   <tr><td style="padding:14px 8px 0;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;border-collapse:collapse;">
     <tr style="color:{MUTED};font-size:11px;text-transform:uppercase;letter-spacing:.04em;">
       <th align="left"   style="padding:6px 12px;">Book</th>
       <th align="right"  style="padding:6px 12px;">Equity</th>
       <th align="right"  style="padding:6px 12px;">Today</th>
       <th align="right"  style="padding:6px 12px;">Since start</th>
       <th align="right"  style="padding:6px 12px;">Gross</th>
       <th align="right"  style="padding:6px 12px;">Legs</th>
     </tr>{''.join(rows)}
    </table>
   </td></tr>
   <tr><td style="padding:0 20px 8px;">{notes_html}</td></tr>
   <tr><td style="padding:8px 20px 20px;border-top:1px solid #e6e8eb;">
     <p style="margin:10px 0 0;color:{MUTED};font-size:12px;line-height:1.5;">
       Paper only. No orders are sent and no money is at risk; the desk config has
       <code style="background:#f1f3f5;padding:1px 4px;border-radius:3px;">live: false</code>.
       Each book starts from $250. The candidate and growth books blend the four-asset long book with a
       residual cross-sectional momentum sleeve; both beat the incumbent out of sample but FAIL the firm's
       deflated-Sharpe gate on a three-year window, which is why they are on paper rather than in production.
     </p>
   </td></tr>
  </table>
 </td></tr>
</table>
</body></html>"""

    text = (f"Kalshi perps paper books - {today}\n\n{banner_text}{headline}\n"
            f"Since start {tot_since_s}\n\n" + "\n".join(text_rows) +
            ("\n\nChanges\n" + "\n".join("  - " + n for n in notes) if notes else "") +
            "\n\nPaper only: no orders, no money at risk, config live=false.\n")

    sign = "+" if (tot_day or 0) >= 0 else ""
    subject = (f"Perps paper {dt.datetime.now(dt.timezone.utc):%b %d}: {_money(total)}"
               + (f" ({sign}{tot_day:.2f})" if tot_day is not None else " (first report)"))
    return {"subject": subject, "html": html_body, "text": text}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html-only", action="store_true")
    ap.add_argument("--no-record", action="store_true", help="do not append to the history file")
    ap.add_argument("--note", default="", help="banner at the top, e.g. a warning or a test-send label")
    a = ap.parse_args()
    books = load_books()
    if not books:
        raise SystemExit("no book status files in state/ - run `cli paper` first")
    out = build(books, previous(), note=a.note)
    if not a.no_record:
        append_history(books)
    print(out["html"] if a.html_only else json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
