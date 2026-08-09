"""Upgrade a running clone of this firm to a newer version.

Why this is not just `git pull`: the books are committed. state/,
config/equity_live.json and dashboard/reports/ are all tracked, so a clone that
has been trading has diverged on exactly the paths upstream also changes. A
plain pull conflicts, and the tempting resolution — take theirs — would merge
the upstream owner's positions into your ledger. For a live trading system that
is a corrupted book, not a merge conflict.

So this splits the repo in two and treats the halves differently:

  SYSTEM  code, docs, workflows, profiles   -> taken from upstream wholesale
  OWNER   books, live config, reports, keys -> never overwritten, only migrated

    python scripts/upgrade.py --check     # what would change, touch nothing
    python scripts/upgrade.py             # do it (backs up owner data first)
    python scripts/upgrade.py --to 0.1.1  # stop at a specific version

Adding a future version means appending one entry to MIGRATIONS. Each entry
gets the owner's config and state, mutates them in place, and returns the
human-readable notes to print.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, "VERSION")
LIVE = os.path.join(ROOT, "config", "equity_live.json")
STATE = os.path.join(ROOT, "state", "equity_state.json")
KILL = os.path.join(ROOT, "state", "KILL_SWITCH_EQ")

UPSTREAM_DEFAULT = "https://github.com/vinilpolepalli/quantfirm.git"

# Paths that belong to the software. Taken from upstream verbatim.
SYSTEM_PATHS = [
    "scripts", "quantfirm", "tests", "docs", ".github", "requirements.txt",
    "README.md", "CHANGELOG.md", "VERSION", "config/profiles.json",
    "dashboard/index.html", "dashboard/fonts", "dashboard/vercel.json",
    ".gitignore",
]

# Paths that belong to whoever runs this clone. Never taken from upstream.
OWNER_PATHS = [
    "state", "config/equity_live.json", "config/live.json",
    "config/account.local.json", "dashboard/reports",
]

B, DIM, RED, RESET = "\033[1m", "\033[2m", "\033[31m", "\033[0m"


def sh(*args, check=True, cwd=ROOT) -> str:
    r = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def vtuple(v: str) -> tuple:
    return tuple(int(x) for x in v.strip().split(".") if x.isdigit())


def current_version() -> str:
    # A clone from before VERSION existed is 0.1.0 by definition.
    try:
        with open(VERSION_FILE) as f:
            return f.read().strip() or "0.1.0"
    except FileNotFoundError:
        return "0.1.0"


# --------------------------------------------------------------------------
# migrations
# --------------------------------------------------------------------------

def _m_0_1_1(cfg: dict, state: dict) -> list[str]:
    """0.1.0 -> 0.1.1: risk profiles, cost basis, stale-panel guard."""
    notes = []

    # Label the existing configuration against the shipped ladder rather than
    # forcing anyone onto a profile. A clone that tuned its own params keeps
    # them and is marked "custom" — silently rewriting someone's live strategy
    # during an upgrade would be the worst possible behaviour here.
    if "risk_profile" not in cfg:
        profiles = load(os.path.join(ROOT, "config", "profiles.json")).get("profiles", {})
        match = None
        for name, p in profiles.items():
            if (cfg.get("strategy") == p.get("strategy")
                    and cfg.get("params", {}) == p.get("params", {})):
                match = name
                break
        cfg["risk_profile"] = match or "custom"
        notes.append(
            f"tagged your configuration as risk_profile='{cfg['risk_profile']}'"
            + ("" if match else
               " — it matches no shipped profile, so it was left exactly as-is."
               " `python scripts/profile.py list` shows the presets if you want one"))

    # Cost basis: P&L must be measured against contributed capital, not a
    # hardcoded 250. Seed it from the owner's own bankroll.
    if "cost_basis" not in state and state:
        basis = float(cfg.get("risk", {}).get("bankroll_usd", 250.0))
        state["cost_basis"] = basis
        notes.append(f"set state cost_basis=${basis:,.2f} from your bankroll "
                     f"(add later deposits with `equity_rebalance.py reconcile-cash`)")

    notes.append(
        "BEHAVIOUR CHANGE: the planner now refuses to trade on a stale price "
        "panel. Run `python scripts/update_equities.py` before the next desk "
        "cycle or it will (correctly) decline to place orders")
    notes.append(
        "BEHAVIOUR CHANGE: a tripped kill switch is no longer cleared by "
        "deleting state/KILL_SWITCH_EQ — use `equity_rebalance.py resume "
        "--i-accept`, which also rebases the drawdown peak")
    return notes


MIGRATIONS = [("0.1.1", _m_0_1_1)]


# --------------------------------------------------------------------------

def upstream_ref(remote_url: str, branch: str) -> str:
    remotes = sh("git", "remote").splitlines()
    if "upstream" in remotes:
        sh("git", "remote", "set-url", "upstream", remote_url)
    else:
        sh("git", "remote", "add", "upstream", remote_url)
    sh("git", "fetch", "--quiet", "upstream", branch)
    return f"upstream/{branch}"


def dirty_system_paths() -> list[str]:
    out = sh("git", "status", "--porcelain")
    dirty = []
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        # This script excepts itself. On a clone predating it the documented
        # bootstrap is `git checkout upstream/main -- scripts/upgrade.py`,
        # which leaves it staged — so without this the upgrade refuses to run
        # on exactly the clones that most need it. Harmless either way: it is
        # about to be replaced from upstream anyway.
        if path == "scripts/upgrade.py":
            continue
        if any(path == p or path.startswith(p.rstrip("/") + "/") for p in SYSTEM_PATHS):
            dirty.append(path)
    return dirty


def backup_owner_data() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(ROOT, ".upgrade-backup", stamp)
    os.makedirs(dest, exist_ok=True)
    for rel in OWNER_PATHS:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            continue
        dst = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, dst)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    ap.add_argument("--to", help="stop at this version instead of the newest")
    ap.add_argument("--remote", default=UPSTREAM_DEFAULT)
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()

    cur = current_version()
    print(f"\n{B}quantfirm upgrade{RESET}")
    print(f"  installed: {cur}")

    try:
        ref = upstream_ref(args.remote, args.branch)
    except RuntimeError as e:
        sys.exit(f"\ncannot reach upstream ({args.remote}):\n  {e}\n"
                 f"If you downloaded a zip rather than cloning, re-clone or add "
                 f"the remote by hand.")

    latest = sh("git", "show", f"{ref}:VERSION", check=False).strip() or "0.1.0"
    target = args.to or latest
    print(f"  upstream : {latest}   target: {target}")

    if vtuple(target) <= vtuple(cur):
        print(f"\n  Already at {cur}; nothing to do.\n")
        return

    steps = [(v, fn) for v, fn in MIGRATIONS
             if vtuple(cur) < vtuple(v) <= vtuple(target)]
    print(f"  migrations to run: {', '.join(v for v, _ in steps) or 'none'}")

    changed = sh("git", "diff", "--name-only", f"HEAD..{ref}").splitlines()
    sys_changed = [p for p in changed
                   if any(p == s or p.startswith(s.rstrip('/') + '/') for s in SYSTEM_PATHS)]
    owner_upstream = [p for p in changed
                      if any(p == o or p.startswith(o.rstrip('/') + '/') for o in OWNER_PATHS)]

    print(f"\n{B}Will update{RESET} ({len(sys_changed)} system files)")
    for p in sys_changed[:15]:
        print(f"    {p}")
    if len(sys_changed) > 15:
        print(f"    … and {len(sys_changed) - 15} more")
    print(f"\n{B}Will NOT touch{RESET} — your data, though upstream changed "
          f"{len(owner_upstream)} of these")
    for p in OWNER_PATHS:
        print(f"    {p}")

    if args.check:
        print(f"\n  {DIM}--check: nothing was modified.{RESET}\n")
        return

    dirty = dirty_system_paths()
    if dirty:
        sys.exit(f"\n{RED}REFUSING{RESET}: you have local edits to system files:\n"
                 + "\n".join(f"    {d}" for d in dirty[:10])
                 + "\n  Commit or stash them first — the upgrade would discard them.")

    if os.path.exists(KILL):
        sys.exit(f"\n{RED}REFUSING{RESET}: the kill switch is tripped. Resolve the "
                 f"halt first (`equity_rebalance.py resume --i-accept`), so an "
                 f"upgrade is never tangled up with an incident.")
    if load(STATE).get("pending_order"):
        sys.exit(f"\n{RED}REFUSING{RESET}: state records a pending order. Let the "
                 f"desk reconcile it before upgrading.")

    backup = backup_owner_data()
    print(f"\n  backed up your books to {os.path.relpath(backup, ROOT)}")

    for path in SYSTEM_PATHS:
        subprocess.run(["git", "checkout", ref, "--", path],
                       cwd=ROOT, capture_output=True, text=True)
    print(f"  pulled system files from {ref}")

    cfg, state = load(LIVE), load(STATE)
    all_notes = []
    for v, fn in steps:
        notes = fn(cfg, state)
        all_notes += [(v, n) for n in notes]
    if cfg:
        save(LIVE, cfg)
    if state:
        save(STATE, state)
    with open(VERSION_FILE, "w") as f:
        f.write(target + "\n")

    print(f"\n{B}Migrated to {target}{RESET}")
    for v, n in all_notes:
        flag = f"{RED}!{RESET}" if n.startswith("BEHAVIOUR CHANGE") else "·"
        print(f"  {flag} [{v}] {n}")

    print(f"\n{B}Verify before the next desk cycle{RESET}")
    print("    python -m pytest tests -q")
    print("    python scripts/setup.py --check")
    print("    python scripts/update_equities.py")
    print(f"\n  Your books were not modified except for the migrations listed "
          f"above.\n  Backup: {os.path.relpath(backup, ROOT)}\n")


if __name__ == "__main__":
    main()
