"""Tests for the options paper desk tick engine. Run: python tests/test_options_paper.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantfirm.options import paper


def q(asof, contracts, spy=766.0):
    return {"asof": asof, "underlying": {"symbol": "SPY", "last": spy},
            "contracts": contracts}


def contract(strike, bid, ask, delta, oi=5000, expiry="2026-09-30",
             updated="2026-08-26T19:45:00Z"):
    return {"strike": strike, "type": "put", "expiry": expiry, "bid": bid,
            "ask": ask, "delta": delta, "iv": 0.14, "oi": oi,
            "updated_at": updated}


def fresh_chain(short_bid=0.98, short_ask=1.02, long_bid=0.78, long_ask=0.82,
                updated="2026-08-26T19:45:00Z"):
    # short 736P mid 1.00, long 735P mid 0.80 -> net mid 0.20, legspread 0.08
    return {
        "id-736": contract(736.0, short_bid, short_ask, -0.18, updated=updated),
        "id-735": contract(735.0, long_bid, long_ask, -0.155, updated=updated),
        "id-734": contract(734.0, 0.60, 0.64, -0.13, updated=updated),
    }


def test_open_position():
    st = paper.new_state("2026-08-26", "2026-09-09")
    paper.tick(st, q("2026-08-26T19:46:00Z", fresh_chain()), "2026-08-26")
    opens = [p for p in st["positions"] if p["status"] == "open"]
    assert len(opens) == 1, opens
    p = opens[0]
    assert p["short"]["strike"] == 736.0 and p["long"]["strike"] == 735.0
    # net mid 0.20, legspread 0.08 -> credit 0.20 - 0.30*0.08 = 0.176 -> 0.18
    assert abs(p["entry_credit"] - 0.18) < 1e-9, p["entry_credit"]
    assert abs(st["cash"] - (500.0 + 18.0 - 0.08)) < 1e-6, st["cash"]
    # equity = cash - mark liability (mark = credit at open)
    assert abs(st["equity"] - (st["cash"] - 18.0)) < 1e-6
    assert p["profit_target"] == 0.09 and abs(p["stop_level"] - 0.45) < 1e-9
    print("  open ok: credit", p["entry_credit"], "equity", st["equity"])
    return st


def test_run_limits(st):
    # next day: mark unchanged; second entry allowed (different short strike
    # is not required — but held short id is excluded, picks next best 735/734)
    paper.tick(st, q("2026-08-27T19:46:00Z",
                     fresh_chain(updated="2026-08-27T19:45:00Z")), "2026-08-27")
    opens = [p for p in st["positions"] if p["status"] == "open"]
    assert len(opens) == 2, [p["id"] for p in opens]
    assert opens[1]["short"]["strike"] == 735.0  # held 736 excluded
    print("  second entry ok:", opens[1]["id"], opens[1]["short"]["strike"])


def test_profit_take(st):
    # crush the marks: short mid 0.06, long mid 0.02 -> net 0.04 <= target 0.09
    chain = {
        "id-736": contract(736.0, 0.05, 0.07, -0.05, updated="2026-08-28T19:45:00Z"),
        "id-735": contract(735.0, 0.01, 0.03, -0.04, updated="2026-08-28T19:45:00Z"),
        "id-734": contract(734.0, 0.01, 0.02, -0.03, updated="2026-08-28T19:45:00Z"),
    }
    cash_before = st["cash"]
    paper.tick(st, q("2026-08-28T19:46:00Z", chain), "2026-08-28")
    closed = [p for p in st["positions"] if p["status"] == "closed"]
    assert len(closed) == 2, len(closed)
    p = closed[0]
    # exit: net mid 0.04, legspread 0.04 -> debit 0.04 + 0.30*0.04 = 0.052 -> 0.05
    assert abs(p["exit_debit"] - 0.05) < 1e-9, p["exit_debit"]
    expect_pnl = (p["entry_credit"] - 0.05) * 100 - 0.08 - 0.08
    assert abs(p["realized_pnl"] - round(expect_pnl, 2)) < 1e-6
    assert st["cash"] < cash_before  # paid debits
    print("  profit take ok: P&L", p["realized_pnl"], "equity", st["equity"])


def test_gates():
    st = paper.new_state("2026-08-26", "2026-09-09")
    # credit floor: net mid 0.10 < 0.12 -> no entry (734 removed so the
    # engine cannot fall through to a 735/734 spread)
    chain = fresh_chain(short_bid=0.88, short_ask=0.92)
    del chain["id-734"]
    paper.tick(st, q("2026-08-26T19:46:00Z", chain), "2026-08-26")
    assert not st["positions"], st["positions"]
    # stale quotes -> no entry
    st2 = paper.new_state("2026-08-26", "2026-09-09")
    paper.tick(st2, q("2026-08-26T19:46:00Z",
                      fresh_chain(updated="2026-08-26T17:00:00Z")), "2026-08-26")
    assert not st2["positions"]
    # low OI -> no entry
    st3 = paper.new_state("2026-08-26", "2026-09-09")
    chain = fresh_chain()
    del chain["id-734"]
    chain["id-736"]["oi"] = 10
    paper.tick(st3, q("2026-08-26T19:46:00Z", chain), "2026-08-26")
    assert not st3["positions"]
    print("  gates ok: credit floor, staleness, OI all block entry")


def test_time_exit():
    st = paper.new_state("2026-08-26", "2026-09-09")
    paper.tick(st, q("2026-08-26T19:46:00Z", fresh_chain()), "2026-08-26")
    # jump to 21 DTE (expiry 2026-09-30 -> 2026-09-09)
    chain = fresh_chain(updated="2026-09-09T19:45:00Z")
    paper.tick(st, q("2026-09-09T19:46:00Z", chain), "2026-09-09")
    closed = [p for p in st["positions"] if p["status"] == "closed"]
    assert closed and closed[0]["exit_reason"] == "time_exit", closed
    print("  time exit ok at dte", closed[0]["dte"])


def test_reports():
    st = paper.new_state("2026-08-26", "2026-09-09")
    paper.tick(st, q("2026-08-26T19:46:00Z", fresh_chain()), "2026-08-26")
    daily = paper.render_daily(st["last_report"])
    weekly = paper.render_weekly(st, "2026-08-28")
    assert "day 1" in daily and "OPENED" in daily
    assert "weekly report" in weekly and "cost meter" in weekly
    print("  reports render ok")


if __name__ == "__main__":
    print("test_options_paper:")
    st = test_open_position()
    test_run_limits(st)
    test_profit_take(st)
    test_gates()
    test_time_exit()
    test_reports()
    print("ALL OK")
