#!/usr/bin/env python3
"""CLI for the options paper desk. PAPER ONLY — never places real orders.

Run by the daily execution agent (see docs/OPTIONS_PAPER.md for the runbook):

    python scripts/options_paper.py init --start 2026-08-26 --end 2026-09-09
    python scripts/options_paper.py tick --quotes state/options_quotes/2026-08-26.json
    python scripts/options_paper.py tick --quotes ... --no-entry     # plumbing check
    python scripts/options_paper.py report --weekly --date 2026-08-28
    python scripts/options_paper.py status

The tick reads/writes state/options_paper_state.json, gzips the quotes file it
consumed into state/options_quotes/, and writes the daily report to
state/options_reports/daily-<date>.txt (weekly-<date>.txt for --weekly).
The report path is printed on the last line of stdout for the agent to email.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quantfirm.options import paper  # noqa: E402

STATE = ROOT / "state" / "options_paper_state.json"
QUOTES_DIR = ROOT / "state" / "options_quotes"
REPORTS_DIR = ROOT / "state" / "options_reports"


def _load_state() -> dict:
    if not STATE.exists():
        sys.exit("no paper state; run `init` first")
    return json.loads(STATE.read_text())


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=False) + "\n")


def cmd_init(args) -> None:
    if STATE.exists() and not args.force:
        sys.exit(f"{STATE} exists; refusing to reinitialize without --force")
    state = paper.new_state(args.start, args.end)
    _save_state(state)
    print(f"paper desk initialized: ${state['bankroll_usd']:.0f}, "
          f"{args.start} -> {args.end}")


def cmd_tick(args) -> None:
    state = _load_state()
    quotes_path = Path(args.quotes)
    quotes = json.loads(quotes_path.read_text())
    today = args.date or date.today().isoformat()

    if state["history"] and state["history"][-1]["date"] == today:
        print(f"tick for {today} already recorded; no-op (run-lock)")
        print(REPORTS_DIR / f"daily-{today}.txt")
        return
    if today > state["ends"]:
        print(f"paper window ended {state['ends']}; tick refused. "
              "Compile the final report instead.")
        return

    paper.tick(state, quotes, today, allow_entry=not args.no_entry)
    _save_state(state)

    QUOTES_DIR.mkdir(parents=True, exist_ok=True)
    archived = QUOTES_DIR / f"{today}.json.gz"
    with open(quotes_path, "rb") as src, gzip.open(archived, "wb") as dst:
        shutil.copyfileobj(src, dst)

    text = paper.render_daily(state["last_report"])
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"daily-{today}.txt"
    out.write_text(text + "\n")
    print(text)
    print(out)


def cmd_report(args) -> None:
    state = _load_state()
    today = args.date or date.today().isoformat()
    if args.weekly:
        text = paper.render_weekly(state, today)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORTS_DIR / f"weekly-{today}.txt"
        out.write_text(text + "\n")
        print(text)
        print(out)
    else:
        print(paper.render_daily(state["last_report"]))


def cmd_status(args) -> None:
    state = _load_state()
    open_n = sum(1 for p in state["positions"] if p["status"] == "open")
    print(f"equity ${state['equity']:.2f} / bankroll ${state['bankroll_usd']:.0f} | "
          f"open {open_n} | halted {state.get('halted', False)} | "
          f"window {state['started']} -> {state['ends']} | "
          f"ticks {len(state['history'])}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("tick")
    p.add_argument("--quotes", required=True)
    p.add_argument("--date", default=None)
    p.add_argument("--no-entry", action="store_true",
                   help="mark and manage exits only; open nothing")
    p.set_defaults(fn=cmd_tick)

    p = sub.add_parser("report")
    p.add_argument("--weekly", action="store_true")
    p.add_argument("--date", default=None)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("status")
    p.set_defaults(fn=cmd_status)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
