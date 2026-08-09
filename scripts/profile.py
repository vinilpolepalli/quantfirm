"""Risk-profile selection for the equity desk.

A profile is a *pre-measured* preset: strategy, strategy params, and risk-block
values, together with the walk-forward numbers that preset actually produced.
The measured block is the point. Anyone can invent a knob called "aggressive";
what makes this safe to hand to a new owner is that each setting has been run
through the same evaluation as the incumbent and carries its real numbers, so
the choice is made against evidence rather than an adjective.

    python scripts/profile.py list                 # the ladder + measured numbers
    python scripts/profile.py show aggressive
    python scripts/profile.py current
    python scripts/profile.py apply aggressive     # writes config/equity_live.json

Applying a profile to a funded book is a real trading decision: changing
top_n changes the target portfolio, so the next plan will rebalance into it.
`apply` refuses on a live book unless --i-understand-this-rebalances is passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PROFILES = os.path.join(ROOT, "config", "profiles.json")
LIVE = os.path.join(ROOT, "config", "equity_live.json")
STATE = os.path.join(ROOT, "state", "equity_state.json")


def _load(path: str, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        if default is not None:
            return default
        sys.exit(f"missing {path}")


def _profiles() -> dict:
    return _load(PROFILES)


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:+.1f}%"


def _wrap(text: str, indent: str = "     ", width: int = 78) -> str:
    import textwrap
    return "\n".join(textwrap.fill(p, width=width, initial_indent=indent,
                                   subsequent_indent=indent)
                     for p in text.split("\n") if p.strip())


def _fmt_measured(m: dict) -> str:
    if not m:
        return "not measured"
    lo, hi = (m.get("max_drawdown_range") or [None, None])
    rng = f" (range {lo * 100:.1f}%..{hi * 100:.1f}%)" if lo is not None else ""
    # Headline the haircut Sharpe where the policy demands one — quoting the raw
    # number for a survivorship-biased universe overstates the evidence.
    hc = m.get("sharpe_haircut")
    sr = (f"Sharpe {hc:.2f} after survivorship haircut "
          f"({m.get('oos_sharpe', 0):.2f} raw)" if hc
          else f"Sharpe {m.get('oos_sharpe', 0):.2f}")
    return (f"drawdown {m.get('max_drawdown', 0) * 100:.1f}%{rng}\n"
            f"CAGR {m.get('cagr', 0) * 100:.1f}%   {sr}   "
            f"worst fold {m.get('worst_fold', 0):.2f}\n"
            f"holdout: {m.get('holdout', 'not measured')}")


def cmd_list(_args) -> None:
    doc = _profiles()
    meta = doc.get("measured_on", {})
    print(f"\n  Risk profiles — quantfirm {doc.get('version', '?')}\n")
    print(_wrap(meta.get("method", ""), "  "))
    print()
    print(_wrap("CAVEAT: " + meta.get("caveat", ""), "  "))
    print(f"\n  {'-' * 74}\n  READ THIS BEFORE CHOOSING\n")
    for line in doc.get("disclosure", []):
        print(_wrap("- " + line, "  "))
    print(f"  {'-' * 74}\n")

    cur = _current_name()
    for name, p in doc["profiles"].items():
        mark = "*" if name == cur else " "
        print(f" {mark} {name.upper():<14} {p.get('headline', '')}")
        print(f"     strategy: {p.get('strategy')}")
        for line in _fmt_measured(p.get("measured", {})).split("\n"):
            print(f"     {line}")
        print()
        print(_wrap(p.get("honest_note", "")))
        if p.get("not_for"):
            print(_wrap("Not for: " + p["not_for"]))
        print()
    if cur:
        print("  (* = currently applied)\n")
    print("  Apply with:  python scripts/profile.py apply <name>\n")


def cmd_show(args) -> None:
    doc = _profiles()
    p = doc["profiles"].get(args.name)
    if not p:
        sys.exit(f"unknown profile '{args.name}' — choices: "
                 f"{', '.join(doc['profiles'])}")
    print(json.dumps(p, indent=2))


def _current_name() -> str | None:
    live = _load(LIVE, {})
    return live.get("risk_profile")


def cmd_current(_args) -> None:
    live = _load(LIVE, {})
    name = live.get("risk_profile")
    print(json.dumps({
        "risk_profile": name or "(none recorded — config predates profiles)",
        "strategy": live.get("strategy"),
        "top_n": live.get("params", {}).get("top_n"),
        "gate_mode": live.get("params", {}).get("gate_mode"),
        "kill_drawdown": live.get("risk", {}).get("kill_drawdown"),
        "max_single_name_frac": live.get("risk", {}).get("max_single_name_frac"),
        "in_strategy_defense": _defense(live),
    }, indent=2))


def _defense(live: dict) -> str:
    """What actually protects the book, as opposed to what the params imply."""
    if live.get("strategy") != "xsec_refined":
        return "strategy-native (see profiles.json)"
    if live.get("params", {}).get("gate_mode", "none") != "none":
        return "SPY-SMA book gate (fires; abs_filter does not)"
    return ("none — abs_filter and the defensive sleeve never fire at these "
            "params; the kill switch is the only risk control")


def _book_is_live() -> tuple[bool, str]:
    live = _load(LIVE, {})
    st = _load(STATE, {})
    if not live.get("enabled"):
        return False, "config disabled"
    pos = st.get("positions") or {}
    if not pos:
        return False, "no open positions"
    return True, f"{len(pos)} open position(s): {', '.join(sorted(pos))}"


def cmd_apply(args) -> None:
    doc = _profiles()
    p = doc["profiles"].get(args.name)
    if not p:
        sys.exit(f"unknown profile '{args.name}' — choices: "
                 f"{', '.join(doc['profiles'])}")

    live_book, why = _book_is_live()
    if live_book and not args.i_understand_this_rebalances:
        sys.exit(
            f"REFUSING: the book is live ({why}).\n"
            f"Switching to '{args.name}' changes the target portfolio, so the "
            f"next plan will sell and re-buy to reach it — at real cost, on a "
            f"real book.\nRe-run with --i-understand-this-rebalances to proceed.")

    live = _load(LIVE)
    before = {"strategy": live.get("strategy"),
              "params": dict(live.get("params", {})),
              "risk": dict(live.get("risk", {})),
              "risk_profile": live.get("risk_profile")}

    # Replace wholesale, never merge. Merging leaves keys from the previous
    # profile behind, so switching aggressive -> conservative -> aggressive
    # lands on a config that matches no measured row and whose published
    # numbers therefore describe a portfolio nobody ever backtested.
    live["strategy"] = p["strategy"]
    live["params"] = dict(p.get("params", {}))
    live["risk"] = dict(p.get("risk", {}))
    live["risk_profile"] = args.name
    live["risk_profile_applied_at"] = datetime.now(timezone.utc).isoformat()

    tmp = LIVE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(live, f, indent=2)
        f.write("\n")
    os.replace(tmp, LIVE)

    # Assert the write round-trips to the profile. A silent divergence here
    # means the live book is running something the published numbers do not
    # describe, which is the whole failure this feature exists to avoid.
    back = _load(LIVE)
    for field, want in (("strategy", p["strategy"]),
                        ("params", dict(p.get("params", {}))),
                        ("risk", dict(p.get("risk", {})))):
        if back.get(field) != want:
            sys.exit(f"ABORT: {field} did not round-trip to profile "
                     f"'{args.name}'. Config may be inconsistent — inspect "
                     f"{LIVE} before trading.")

    # A profile switch is a mandate change; the books should carry it so the
    # daily report can explain a rebalance that the strategy did not ask for.
    if os.path.exists(STATE):
        st = _load(STATE)
        st.setdefault("incidents", []).append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "risk_profile_change",
            "detail": (f"risk profile {before.get('risk_profile') or 'unset'} "
                       f"-> {args.name}; strategy {before['strategy']} -> "
                       f"{live['strategy']}; top_n "
                       f"{before['params'].get('top_n')} -> "
                       f"{live['params'].get('top_n')}; kill_drawdown "
                       f"{before['risk'].get('kill_drawdown')} -> "
                       f"{live['risk'].get('kill_drawdown')}"),
        })
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f, indent=2)
        os.replace(tmp, STATE)

    print(json.dumps({
        "applied": args.name,
        "strategy": live["strategy"],
        "params_changed": {k: v for k, v in p.get("params", {}).items()
                           if before["params"].get(k) != v},
        "risk_changed": {k: v for k, v in p.get("risk", {}).items()
                         if before["risk"].get(k) != v},
        "measured": p.get("measured"),
        "next": "python scripts/equity_rebalance.py plan",
    }, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("show"); s.add_argument("name")
    sub.add_parser("current")
    a = sub.add_parser("apply")
    a.add_argument("name")
    a.add_argument("--i-understand-this-rebalances", action="store_true",
                   dest="i_understand_this_rebalances")
    args = ap.parse_args()
    {"list": cmd_list, "show": cmd_show, "current": cmd_current,
     "apply": cmd_apply}[args.cmd](args)


if __name__ == "__main__":
    main()
