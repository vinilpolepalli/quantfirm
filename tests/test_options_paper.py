"""Tests for the v2 options paper desk engine. Run: python3 tests/test_options_paper.py

Tests install their own sleeve table so they stay independent of whatever the
production SLEEVES config happens to be.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantfirm.options import paper

# captured before any _install_sleeves() call so tests can assert on the real config
PROD_SLEEVES = {k: dict(v) for k, v in paper.SLEEVES.items()}

ASOF = "2026-09-01T19:47:00Z"
FRESH = "2026-09-01T19:46:00Z"

CREDIT_SLEEVE = {
    "fat": {"enabled": True, "kind": "credit_spread", "tag": "FAT",
            "underlyings": ["QQQ"], "sides": ["put"], "width": 5.0,
            "delta_band": (0.25, 0.45), "target_delta": 0.35, "dte_band": (1, 10),
            "qty": 1, "min_credit_frac": 0.10, "min_oi": 100,
            "max_legspread_frac": 1.5, "max_open": 3,
            "profit_frac": 0.20, "stop_mult": None, "dte_exit": None},
}
DEBIT_SLEEVE = {
    "lotto": {"enabled": True, "kind": "long_option", "tag": "LOT",
              "underlyings": ["QQQ"], "sides": ["call", "put"],
              "delta_band": (0.15, 0.40), "target_delta": 0.25, "dte_band": (1, 10),
              "min_oi": 100, "max_legspread_frac": 1.5, "ticket_usd": 60.0,
              "max_open": 3, "profit_mult": 1.0, "stop_frac": None, "dte_exit": None},
}


def c(strike, bid, ask, delta, kind="put", expiry="2026-09-04", oi=5000, sym="QQQ",
      updated=FRESH):
    return {"underlying": sym, "strike": float(strike), "type": kind,
            "expiry": expiry, "bid": bid, "ask": ask, "delta": delta,
            "iv": 0.20, "oi": oi, "updated_at": updated}


def snap(contracts, spot=766.0, asof=ASOF, settle=None, mom=0.01):
    return {"asof": asof,
            "underlyings": {"QQQ": {"last": spot, "momentum": mom}},
            "contracts": contracts, "settle_prices": settle or {}}


# put credit spread: short 760P (0.35d) / long 755P.  mid: -2.00 + 1.00 = -1.00
def credit_chain(short=(1.98, 2.02), long_=(0.98, 1.02), updated=FRESH):
    return {"s760": c(760, short[0], short[1], -0.35, updated=updated),
            "l755": c(755, long_[0], long_[1], -0.22, updated=updated)}


def test_credit_open():
    paper._install_sleeves(CREDIT_SLEEVE)
    st = paper.new_state("2026-09-01", "2026-09-09")
    paper.tick(st, snap(credit_chain()), "2026-09-01")
    op = [p for p in st["positions"] if p["status"] == "open"]
    assert len(op) == 1, op
    p = op[0]
    # net_mid -1.00, legspread 0.08 -> paid_open = -1.00 + 0.30*0.08 = -0.976 -> -0.98
    assert p["paid_open"] == -0.98, p["paid_open"]
    assert p["max_loss"] == 402.0, p["max_loss"]        # (5.00 - 0.98) * 100
    assert abs(st["cash"] - (500.0 + 98.0 - 0.08)) < 1e-6, st["cash"]
    assert abs(st["equity"] - (st["cash"] - 98.0)) < 1e-6, st["equity"]
    print("  credit open ok: paid", p["paid_open"], "risk", p["max_loss"],
          "equity", st["equity"])
    return st


def test_credit_profit_target(st):
    # spread decays to mid -0.15; target is 20% of the 0.98 credit = -0.196
    chain = {"s760": c(760, 0.28, 0.32, -0.08), "l755": c(755, 0.13, 0.17, -0.04)}
    paper.tick(st, snap(chain), "2026-09-02")
    cl = [p for p in st["positions"] if p["status"] == "closed"]
    assert len(cl) == 1 and cl[0]["exit_reason"] == "profit_target", cl
    # received = -0.15 - 0.30*0.08 = -0.174 -> -0.17; pnl = (-0.17 + 0.98)*100 - fees
    assert cl[0]["exit_price"] == -0.17, cl[0]["exit_price"]
    assert abs(cl[0]["realized_pnl"] - (81.0 - 0.16)) < 1e-6, cl[0]["realized_pnl"]
    print("  credit profit-take ok: P&L", cl[0]["realized_pnl"])


def test_expiry_settlement_itm():
    """The path v1 never had: a credit spread that expires with the short ITM."""
    paper._install_sleeves(CREDIT_SLEEVE)
    st = paper.new_state("2026-09-01", "2026-09-09")
    paper.tick(st, snap(credit_chain()), "2026-09-01")
    p = st["positions"][0]
    entry = p["paid_open"]

    # jump past expiry with SPY at 757 -> short 760P is 3.00 ITM, long 755P worthless
    st2 = paper.tick(st, snap({}, spot=757.0, asof="2026-09-08T19:47:00Z",
                              settle={"QQQ|2026-09-04": 757.0}), "2026-09-08")
    cl = [q for q in st2["positions"] if q["status"] == "closed"][0]
    assert cl["exit_reason"] == "expired", cl["exit_reason"]
    assert cl["exit_price"] == -3.00, cl["exit_price"]        # -max(0,760-757) + 0
    # pnl = (-3.00 - (-0.98)) * 100 - 0.08 = -202.08
    assert abs(cl["realized_pnl"] - (-202.08)) < 1e-6, cl["realized_pnl"]
    assert abs(st2["equity"] - (500.0 - 202.08)) < 1e-6, st2["equity"]
    print("  expiry ITM ok: settled", cl["exit_price"], "P&L", cl["realized_pnl"],
          "equity", st2["equity"], "(entry was", entry, ")")


def test_expiry_settlement_max_loss_capped():
    """Deep ITM must lose the width, never more — bounded-loss invariant."""
    paper._install_sleeves(CREDIT_SLEEVE)
    st = paper.new_state("2026-09-01", "2026-09-09")
    paper.tick(st, snap(credit_chain()), "2026-09-01")
    p = st["positions"][0]
    st2 = paper.tick(st, snap({}, spot=600.0, asof="2026-09-08T19:47:00Z",
                              settle={"QQQ|2026-09-04": 600.0}), "2026-09-08")
    cl = [q for q in st2["positions"] if q["status"] == "closed"][0]
    assert cl["exit_price"] == -5.00, cl["exit_price"]        # capped at the width
    assert abs(cl["realized_pnl"] + p["max_loss"]) < 0.2, (cl["realized_pnl"], p["max_loss"])
    print("  expiry crash ok: loss capped at width, P&L", cl["realized_pnl"],
          "vs stated max_loss", -p["max_loss"])


def test_expiry_worthless():
    paper._install_sleeves(CREDIT_SLEEVE)
    st = paper.new_state("2026-09-01", "2026-09-09")
    paper.tick(st, snap(credit_chain()), "2026-09-01")
    st2 = paper.tick(st, snap({}, spot=800.0, asof="2026-09-08T19:47:00Z",
                              settle={"QQQ|2026-09-04": 800.0}), "2026-09-08")
    cl = [q for q in st2["positions"] if q["status"] == "closed"][0]
    assert cl["exit_price"] == 0.0 and cl["realized_pnl"] > 97, cl
    print("  expiry worthless ok: kept full credit, P&L", cl["realized_pnl"])


def test_expiry_missing_settle_price():
    paper._install_sleeves(CREDIT_SLEEVE)
    st = paper.new_state("2026-09-01", "2026-09-09")
    paper.tick(st, snap(credit_chain()), "2026-09-01")
    st2 = paper.tick(st, snap({}, asof="2026-09-08T19:47:00Z"), "2026-09-08")
    assert [q for q in st2["positions"] if q["status"] == "open"], "should still be open"
    assert any("no settle price" in i for i in st2["incidents"]), st2["incidents"]
    print("  missing settle price ok: held + incident logged")


def test_expiry_day_sellout():
    paper._install_sleeves(CREDIT_SLEEVE)
    st = paper.new_state("2026-09-01", "2026-09-09")
    paper.tick(st, snap(credit_chain()), "2026-09-01")
    chain = credit_chain(short=(0.48, 0.52), long_=(0.08, 0.12),
                         updated="2026-09-04T19:46:00Z")
    st2 = paper.tick(st, snap(chain, asof="2026-09-04T19:47:00Z"), "2026-09-04")
    cl = [q for q in st2["positions"] if q["status"] == "closed"][0]
    assert cl["exit_reason"] == "expiry_day_sellout", cl["exit_reason"]
    print("  expiry-day sellout ok at", cl["exit_price"])


def test_long_option():
    paper._install_sleeves(DEBIT_SLEEVE)
    st = paper.new_state("2026-09-01", "2026-09-09")
    # momentum positive -> calls. 770C mid 0.60, spread 0.04 -> paid 0.612 -> 0.61
    chain = {"c770": c(770, 0.58, 0.62, 0.25, kind="call")}
    paper.tick(st, snap(chain), "2026-09-01")
    p = [q for q in st["positions"] if q["status"] == "open"][0]
    assert p["structure"] == "long_call" and p["paid_open"] == 0.61, p
    assert p["qty"] == 1, p["qty"]                       # 60 // 61 -> 0 -> clamped 1
    assert p["max_loss"] == 61.0, p["max_loss"]
    assert abs(st["cash"] - (500.0 - 61.0 - 0.04)) < 1e-6, st["cash"]

    # doubles -> profit_mult 1.0 fires
    chain2 = {"c770": c(770, 1.28, 1.32, 0.45, kind="call",
                        updated="2026-09-02T19:46:00Z")}
    paper.tick(st, snap(chain2, asof="2026-09-02T19:47:00Z"), "2026-09-02")
    cl = [q for q in st["positions"] if q["status"] == "closed"][0]
    assert cl["exit_reason"] == "profit_target", cl["exit_reason"]
    assert cl["realized_pnl"] > 60, cl["realized_pnl"]
    print("  long option ok: paid", p["paid_open"], "-> P&L", cl["realized_pnl"])


def test_long_option_expires_worthless():
    paper._install_sleeves(DEBIT_SLEEVE)
    st = paper.new_state("2026-09-01", "2026-09-09")
    paper.tick(st, snap({"c770": c(770, 0.58, 0.62, 0.25, kind="call")}), "2026-09-01")
    p = st["positions"][0]
    st2 = paper.tick(st, snap({}, spot=740.0, asof="2026-09-08T19:47:00Z",
                              settle={"QQQ|2026-09-04": 740.0}), "2026-09-08")
    cl = [q for q in st2["positions"] if q["status"] == "closed"][0]
    assert cl["exit_price"] == 0.0, cl["exit_price"]
    assert abs(cl["realized_pnl"] + p["max_loss"]) < 0.1, cl["realized_pnl"]
    print("  long option expiry ok: total loss of premium", cl["realized_pnl"])


def test_risk_cap_and_ladder():
    paper._install_sleeves(CREDIT_SLEEVE)
    st = paper.new_state("2026-09-01", "2026-09-09")
    # two spreads at ~$402 risk each: the second must be refused by the 100% cap
    paper.tick(st, snap(credit_chain()), "2026-09-01")
    chain2 = dict(credit_chain(updated="2026-09-02T19:46:00Z"),
                  **{"s759": c(759, 1.95, 1.99, -0.34, updated="2026-09-02T19:46:00Z"),
                     "l754": c(754, 0.95, 0.99, -0.21, updated="2026-09-02T19:46:00Z")})
    paper.tick(st, snap(chain2, asof="2026-09-02T19:47:00Z"), "2026-09-02")
    assert len([p for p in st["positions"] if p["status"] == "open"]) == 1
    assert any("exceeds" in e for e in st["last_report"]["events"]), st["last_report"]["events"]
    print("  risk cap ok: second entry refused")

    # crush equity below the 20% flatten line
    st["cash"] = 50.0
    st3 = paper.tick(st, snap(credit_chain(updated="2026-09-03T19:46:00Z"),
                              asof="2026-09-03T19:47:00Z"), "2026-09-03")
    assert st3["halted"] and not [p for p in st3["positions"] if p["status"] == "open"]
    assert any("flatten" in (p.get("exit_reason") or "") for p in st3["positions"])
    print("  ladder ok: halted + flattened at equity", st3["equity"])


def test_gates():
    paper._install_sleeves(CREDIT_SLEEVE)
    # stale quotes
    st = paper.new_state("2026-09-01", "2026-09-09")
    paper.tick(st, snap(credit_chain(updated="2026-09-01T17:00:00Z")), "2026-09-01")
    assert not st["positions"], "stale quotes must block entry"
    # thin OI
    st2 = paper.new_state("2026-09-01", "2026-09-09")
    thin = credit_chain(); thin["s760"]["oi"] = 5
    paper.tick(st2, snap(thin), "2026-09-01")
    assert not st2["positions"], "thin OI must block entry"
    # credit below floor (10% of $5 width = $0.50); mid here is only -0.20
    st3 = paper.new_state("2026-09-01", "2026-09-09")
    paper.tick(st3, snap(credit_chain(short=(1.18, 1.22), long_=(0.98, 1.02))),
               "2026-09-01")
    assert not st3["positions"], "sub-floor credit must block entry"
    print("  gates ok: staleness, OI, credit floor all block")


def test_spy_is_banned():
    """Owner instruction 2026-09-01: SPY must never be selected, even if a
    config edit puts it back in a sleeve's underlyings."""
    paper._install_sleeves({"fat": dict(CREDIT_SLEEVE["fat"], underlyings=["SPY"])})
    st = paper.new_state("2026-09-01", "2026-09-09")
    spy_chain = {"s760": c(760, 1.98, 2.02, -0.35, sym="SPY"),
                 "l755": c(755, 0.98, 1.02, -0.22, sym="SPY")}
    spy_snap = {"asof": ASOF, "underlyings": {"SPY": {"last": 766.0, "momentum": 0.01}},
                "contracts": spy_chain, "settle_prices": {}}
    paper.tick(st, spy_snap, "2026-09-01")
    assert not st["positions"], "SPY was traded despite the ban"
    # same chain on a permitted symbol still trades, proving the gate is symbol-specific
    paper._install_sleeves(CREDIT_SLEEVE)
    st2 = paper.new_state("2026-09-01", "2026-09-09")
    paper.tick(st2, snap(credit_chain()), "2026-09-01")
    assert st2["positions"], "control case should still open on QQQ"
    assert "SPY" in paper.BANNED_UNDERLYINGS
    print("  SPY ban ok: config re-adding SPY still opens nothing")


def test_legacy_positions_keep_v1_exits():
    """Migrated v1 positions must retain their profit/stop/time exits; an
    unknown sleeve name silently gives them none."""
    assert "legacy" in PROD_SLEEVES, "legacy exit rules missing"
    cfg = PROD_SLEEVES["legacy"]
    assert cfg["enabled"] is False and cfg["profit_frac"] == 0.50
    assert cfg["stop_mult"] == 2.5 and cfg["dte_exit"] == 21
    # a legacy credit position at 50% decay must trigger the profit target
    p = {"paid_open": -0.12, "mark": -0.06}
    assert paper._hit_profit(p, cfg), "legacy profit target did not fire"
    p = {"paid_open": -0.12, "mark": -0.30}
    assert paper._hit_stop(p, cfg), "legacy stop did not fire"
    for name, sl in PROD_SLEEVES.items():
        assert "SPY" not in sl.get("underlyings", []), f"{name} still lists SPY"
    print("  legacy exits ok: 50% profit / 2.5x stop / 21 DTE restored; "
          "no shipped sleeve lists SPY")


def test_reports():
    paper._install_sleeves(CREDIT_SLEEVE)
    st = paper.new_state("2026-09-01", "2026-09-09")
    paper.tick(st, snap(credit_chain()), "2026-09-01")
    d = paper.render_daily(st["last_report"])
    w = paper.render_weekly(st, "2026-09-04")
    assert "HIGH-RISK MANDATE" in d and "OPENED" in d and "capital at risk" in d
    assert "cost meter" in w and "equity curve" in w
    print("  reports render ok")


def test_half_strikes_render_exactly():
    """A 232.5 strike must never print as 232 — that is a different contract."""
    assert paper._strike(232.5) == "232.5"
    assert paper._strike(714.0) == "714"
    assert paper._strike(447.5) == "447.5"
    pos = {"underlying": "NVDA", "qty": 1,
           "legs": [{"strike": 232.5, "expiry": "2026-09-04", "type": "call",
                     "side": "long", "ratio": 1}]}
    assert "232.5C" in paper._desc(pos)
    print("  half-strike rendering ok")


if __name__ == "__main__":
    print("test_options_paper (v2):")
    st = test_credit_open()
    test_credit_profit_target(st)
    test_expiry_settlement_itm()
    test_expiry_settlement_max_loss_capped()
    test_expiry_worthless()
    test_expiry_missing_settle_price()
    test_expiry_day_sellout()
    test_long_option()
    test_long_option_expires_worthless()
    test_risk_cap_and_ladder()
    test_gates()
    test_spy_is_banned()
    test_legacy_positions_keep_v1_exits()
    test_reports()
    test_half_strikes_render_exactly()
    print("ALL OK")
