"""Guards on the risk-profile machinery.

These exist because the feature's failure modes are all silent: a profile that
merges instead of replacing, or a setup path that waves through the live-book
acknowledgement, leaves a funded book running something nobody measured.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES = json.load(open(os.path.join(ROOT, "config", "profiles.json")))


def _sandbox(tmp, positions=None, enabled=True):
    """A throwaway copy of config/ + state/ so tests never touch the real book."""
    for sub in ("config", "state", "scripts", "quantfirm"):
        src = os.path.join(ROOT, sub)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(tmp, sub),
                            ignore=shutil.ignore_patterns("__pycache__"))
    live = json.load(open(os.path.join(tmp, "config", "equity_live.json")))
    live["enabled"] = enabled
    json.dump(live, open(os.path.join(tmp, "config", "equity_live.json"), "w"), indent=2)
    st_path = os.path.join(tmp, "state", "equity_state.json")
    st = json.load(open(st_path)) if os.path.exists(st_path) else {"version": 1}
    st["positions"] = positions if positions is not None else {}
    json.dump(st, open(st_path, "w"), indent=2)
    return tmp


def _run(tmp, script, *args):
    return subprocess.run([sys.executable, os.path.join(tmp, "scripts", script), *args],
                          capture_output=True, text=True, cwd=tmp)


def test_every_profile_declares_a_registered_strategy():
    from quantfirm.equities.strategies import load_all
    known = load_all()
    for name, p in PROFILES["profiles"].items():
        assert p.get("strategy") in known, f"{name}: unknown strategy {p.get('strategy')}"


def test_every_profile_carries_measured_numbers_and_a_disclosure():
    for name, p in PROFILES["profiles"].items():
        m = p.get("measured") or {}
        assert m.get("max_drawdown") is not None, f"{name}: no measured drawdown"
        assert m.get("holdout"), f"{name}: holdout status must be stated explicitly"
        assert p.get("honest_note"), f"{name}: needs an honest_note"
    assert PROFILES.get("disclosure"), "the ladder must carry a disclosure block"


def test_kill_switch_sits_outside_the_profiles_own_drawdown():
    """The crypto-tournament lesson: a halt line inside normal drawdown turns a
    routine drawdown into a permanent exit."""
    for name, p in PROFILES["profiles"].items():
        worst = min(p["measured"]["max_drawdown_range"])
        kill = p["risk"]["kill_drawdown"]
        assert kill > abs(worst), (
            f"{name}: kill_drawdown {kill} is inside its own measured worst "
            f"drawdown {worst:.1%} — it would liquidate on normal behaviour")


def test_apply_replaces_params_wholesale_and_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        _sandbox(tmp, positions={}, enabled=False)
        for name in ("balanced", "aggressive", "conservative", "balanced"):
            r = _run(tmp, "profile.py", "apply", name)
            assert r.returncode == 0, r.stderr
        live = json.load(open(os.path.join(tmp, "config", "equity_live.json")))
        want = PROFILES["profiles"]["balanced"]
        assert live["strategy"] == want["strategy"]
        assert live["params"] == want["params"], "params leaked across switches"
        assert live["risk"] == want["risk"], "risk block leaked across switches"


def test_apply_refuses_on_a_funded_book_without_acknowledgement():
    with tempfile.TemporaryDirectory() as tmp:
        _sandbox(tmp, positions={"AAPL": 1.0}, enabled=True)
        r = _run(tmp, "profile.py", "apply", "aggressive")
        assert r.returncode != 0, "must refuse to rebalance a funded book silently"
        assert "REFUSING" in r.stdout + r.stderr
        live = json.load(open(os.path.join(tmp, "config", "equity_live.json")))
        assert live["params"]["top_n"] == 6, "config must be untouched after refusal"


def test_setup_never_auto_acknowledges_the_live_book_guard():
    """Regression: setup.py used to pass --i-understand-this-rebalances
    whenever positions existed, defeating the guard it was meant to respect."""
    with tempfile.TemporaryDirectory() as tmp:
        _sandbox(tmp, positions={"AAPL": 1.0}, enabled=True)
        r = _run(tmp, "setup.py", "--profile", "aggressive")
        assert r.returncode != 0, "setup must refuse on a funded book"
        live = json.load(open(os.path.join(tmp, "config", "equity_live.json")))
        assert live["params"]["top_n"] == 6, "setup changed a funded book"
