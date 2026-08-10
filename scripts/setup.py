"""First-run setup for a freshly cloned firm.

Walks a new owner through the two decisions that cannot be inherited from
whoever cloned the repo: which brokerage account the desk trades, and how much
risk it is allowed to take.

    python scripts/setup.py                    # interactive
    python scripts/setup.py --profile balanced # non-interactive (CI/agents)
    python scripts/setup.py --check            # report readiness, change nothing

Deliberately does NOT enable trading. Setup ends with the book still disabled
and a printed checklist; flipping `enabled` is a separate, deliberate act after
the account is funded and the books are seeded.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIVE = os.path.join(ROOT, "config", "equity_live.json")
PROFILES = os.path.join(ROOT, "config", "profiles.json")
LOCAL_ACCT = os.path.join(ROOT, "config", "account.local.json")
STATE = os.path.join(ROOT, "state", "equity_state.json")

B, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"


def _load(p, d=None):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return d if d is not None else {}


def _tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def show_ladder() -> dict:
    doc = _load(PROFILES)
    meta = doc.get("measured_on", {})
    print(f"\n{B}Choose a risk profile{RESET}")
    print(f"{DIM}Measured on {meta.get('split')} ({meta.get('window')}), "
          f"{meta.get('folds')}-fold walk-forward, "
          f"{meta.get('cost_bps_per_side')}bps/side.{RESET}")
    print(f"{DIM}{meta.get('caveat', '')}{RESET}\n")
    names = list(doc["profiles"])
    for i, name in enumerate(names, 1):
        p = doc["profiles"][name]
        m = p.get("measured", {})
        print(f"  {B}{i}. {name}{RESET} — {p.get('headline', '')}")
        print(f"     strategy {p.get('strategy')}   "
              f"CAGR {m.get('cagr', 0) * 100:.1f}%   "
              f"worst drawdown {m.get('max_drawdown', 0) * 100:.1f}%   "
              f"Sharpe {m.get('oos_sharpe', 0):.2f}")
        print(f"     {p.get('honest_note', '')}\n")
    return doc


def pick(doc: dict, preset: str | None) -> str:
    names = list(doc["profiles"])
    if preset:
        if preset not in names:
            sys.exit(f"unknown profile '{preset}' — choices: {', '.join(names)}")
        return preset
    if not _tty():
        sys.exit("not a terminal — pass --profile <name> to choose "
                 f"non-interactively ({', '.join(names)})")
    default = "balanced" if "balanced" in names else names[0]
    while True:
        ans = input(f"Profile [1-{len(names)} or name, default {default}]: ").strip()
        if not ans:
            return default
        if ans in names:
            return ans
        if ans.isdigit() and 1 <= int(ans) <= len(names):
            return names[int(ans) - 1]
        print(f"  pick one of: {', '.join(names)}")


def account_status() -> tuple[bool, str]:
    env = os.environ.get("QF_EQUITY_ACCOUNT", "").strip()
    if env.isdigit():
        return True, "QF_EQUITY_ACCOUNT environment variable"
    v = str(_load(LOCAL_ACCT).get("account_number", "")).strip()
    if v.isdigit():
        return True, "config/account.local.json (gitignored)"
    return False, "not set"


def cmd_check() -> int:
    live = _load(LIVE)
    st = _load(STATE)
    ok_acct, how = account_status()
    rows = [
        ("risk profile", live.get("risk_profile") or "NOT SET", bool(live.get("risk_profile"))),
        ("strategy", live.get("strategy", "?"), bool(live.get("strategy"))),
        ("account", how, ok_acct),
        ("books initialized", str(bool(st.get("initialized"))), bool(st.get("initialized"))),
        ("trading enabled", str(bool(live.get("enabled"))), True),
    ]
    risk = live.get("risk", {})
    deployable = float(risk.get("bankroll_usd", 0) or 0) * float(risk.get("max_growth_mult", 1) or 1)
    hist = st.get("equity_history") or []
    equity = float(hist[-1][1]) if hist else 0.0
    if equity and deployable and equity > deployable:
        rows.append(("capital deployable",
                     f"${deployable:,.0f} cap vs ${equity:,.0f} funded — "
                     f"${equity - deployable:,.0f} would sit idle", False))
    if not live.get("enabled") and not st.get("positions"):
        pass
    elif st.get("positions") and not os.environ.get("QF_EQUITY_ACCOUNT") \
            and not str(_load(LOCAL_ACCT).get("account_number", "")).isdigit():
        rows.append(("book provenance",
                     "positions present but no account configured — these may be "
                     "the previous owner's; see --clear-books", False))
    print(f"\n{B}Readiness{RESET}")
    for k, v, good in rows:
        print(f"  [{'x' if good else ' '}] {k:<20} {v}")
    print()
    return 0 if all(g for _, _, g in rows) else 1


def set_bankroll(value: float | None) -> None:
    """Capital is not part of a risk profile, but getting it wrong is a risk.

    Deployment is capped at bankroll_usd * max_growth_mult while drawdown is
    measured on total equity, so a cloner who funds $10k and inherits the
    previous owner's $250 bankroll would leave ~87% of it idle AND make the
    kill switch unreachable — the traded sleeve cannot lose enough of the whole
    account to trip it. So ask.
    """
    live = _load(LIVE)
    cur = float(live.get("risk", {}).get("bankroll_usd", 0) or 0)
    if value is None:
        if not _tty():
            print(f"\n  bankroll_usd left at ${cur:,.2f} "
                  f"(pass --bankroll to change it non-interactively)")
            return
        print(f"\n{B}Starting capital{RESET}")
        print(f"{DIM}  Deployment is capped at bankroll x max_growth_mult "
              f"(currently {live.get('risk', {}).get('max_growth_mult', 5)}x). "
              f"Set this to what you are actually funding.{RESET}")
        raw = input(f"  Bankroll in USD [default {cur:,.0f}]: ").strip()
        if not raw:
            return
        try:
            value = float(raw.replace("$", "").replace(",", ""))
        except ValueError:
            print("  not a number — leaving unchanged")
            return
    if value <= 0:
        print("  bankroll must be positive — leaving unchanged")
        return
    live.setdefault("risk", {})["bankroll_usd"] = round(float(value), 2)
    tmp = LIVE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(live, f, indent=2)
        f.write("\n")
    os.replace(tmp, LIVE)
    print(f"  bankroll_usd set to ${value:,.2f}")


INHERITED_MSG = """
REFUSING: this clone still holds the previous owner's book.

  positions : {pos}
  cash      : ${cash:,.2f}
  marks     : {marks}
  trading   : {enabled}

Those are not your positions. If a desk cycle fires against your account with
this state loaded, the planner believes it owns six things you do not own and
plans against a book that is not yours.

  python scripts/setup.py --clear-books --profile <name>   # fresh start (usual)
  python scripts/setup.py --keep-books   --profile <name>  # this really is my book
"""


def inherited_books() -> dict | None:
    """A fresh clone carries the upstream owner's positions, because the books
    are committed. Detect that rather than trusting anyone to read the README."""
    st = _load(STATE)
    pos = st.get("positions") or {}
    hist = st.get("equity_history") or []
    if not pos and not hist:
        return None
    return {"pos": ", ".join(sorted(pos)) or "none",
            "cash": float(st.get("settled_cash", 0) or 0),
            "marks": len(hist),
            "enabled": "ENABLED" if _load(LIVE).get("enabled") else "disabled"}


def clear_books() -> None:
    """Erase owner data and disarm. Deliberately leaves config/profiles.json,
    the code and the docs alone — this resets the firm's books, not the firm."""
    import glob
    removed = []
    for pat in ("state/*.json", "state/*.csv", "state/KILL_SWITCH*",
                "dashboard/reports/*.html", "dashboard/reports/*.pdf"):
        for f in glob.glob(os.path.join(ROOT, pat)):
            os.remove(f)
            removed.append(os.path.relpath(f, ROOT))
    live = _load(LIVE)
    live["enabled"] = False
    live.pop("risk_profile_applied_at", None)
    tmp = LIVE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(live, f, indent=2)
        f.write("\n")
    os.replace(tmp, LIVE)
    print(f"  cleared {len(removed)} file(s) of the previous owner's data")
    print("  trading disabled — re-enable deliberately once your books are seeded")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", help="skip the prompt and use this profile")
    ap.add_argument("--check", action="store_true", help="report readiness only")
    ap.add_argument("--bankroll", type=float,
                    help="starting capital in USD (skips the prompt)")
    ap.add_argument("--clear-books", action="store_true", dest="clear_books",
                    help="erase the previous owner's positions, trade log and "
                         "reports, and disable trading (do this on a fresh clone)")
    ap.add_argument("--keep-books", action="store_true", dest="keep_books",
                    help="this book is mine — skip the inherited-books check")
    args = ap.parse_args()

    if args.check:
        sys.exit(cmd_check())

    if args.clear_books:
        clear_books()
    elif not args.keep_books:
        inh = inherited_books()
        if inh:
            sys.exit(INHERITED_MSG.format(**inh))

    print(f"\n{B}quantfirm setup{RESET}")
    print(f"{DIM}Two decisions the previous owner's config cannot make for you.{RESET}")

    doc = show_ladder()
    name = pick(doc, args.profile)

    # Never auto-acknowledge the live-book guard. This is a first-run tool; if
    # there are open positions then this is not a first run, and switching
    # profile would sell and re-buy a funded book. An earlier version passed
    # --i-understand-this-rebalances automatically whenever positions existed,
    # which silently defeated the one guard that exists to prevent exactly
    # that — it changed a live book to `aggressive` during testing.
    if _load(STATE).get("positions"):
        sys.exit(
            "\nREFUSING: this book already holds positions, so this is not a "
            "first run.\nChanging profile now would rebalance a funded book. "
            "If you mean it, say so explicitly:\n"
            f"    python scripts/profile.py apply {name} "
            "--i-understand-this-rebalances\n")

    cmd = [sys.executable, os.path.join(ROOT, "scripts", "profile.py"), "apply", name]
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(r.returncode)

    set_bankroll(args.bankroll)

    ok_acct, how = account_status()
    print(f"\n{B}Next{RESET}")
    n = 1
    if not ok_acct:
        print(f"  {n}. Point the desk at your brokerage account. It is never stored")
        print(f"     in the repo:")
        print(f"       export QF_EQUITY_ACCOUNT=<your account number>")
        print(f"     or write config/account.local.json (gitignored):")
        print(f'       {{"account_number": "<your account number>"}}'); n += 1
    else:
        print(f"  ✓  account resolves from {how}")
    print(f"  {n}. Fund the account, then seed the books:"); n += 1
    print(f"       python scripts/equity_rebalance.py record --init-cash <amount>")
    print(f"  {n}. Refresh the price panel:"); n += 1
    print(f"       python scripts/update_equities.py")
    print(f"  {n}. Flip \"enabled\": true in config/equity_live.json when you mean it.")
    print(f"\n  Re-check any time:  python scripts/setup.py --check\n")


if __name__ == "__main__":
    main()
