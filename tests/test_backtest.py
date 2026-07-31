"""Money-critical invariants: no lookahead, correct cost accounting,
idempotent order ids, risk checks fire."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd

from quantfirm import backtest as bt
from quantfirm import risk
from quantfirm.costs import CostModel
from quantfirm.live.rh_client import RobinhoodCrypto


def _df(n=1000, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": close, "high": close, "low": close,
                         "close": close, "volume": 1.0}, index=idx)


def test_no_lookahead_position_lag():
    """A position that 'knows' bar t's return must not earn it: run() applies
    pos.shift(1), so perfect-foresight positions earn the NEXT bar, not this one."""
    df = _df()
    ret = df["close"].pct_change().fillna(0)
    foresight = (ret > 0).astype(float)  # cheating signal built from bar t itself
    res = bt.run(df, foresight, CostModel("free", 0.0))
    honest = bt.run(df, foresight.shift(1).fillna(0), CostModel("free", 0.0))
    # If shift(1) were missing, foresight would produce an absurd Sharpe (>20).
    assert res["net_sharpe"] < 5, "lookahead leak: foresight signal scored too well"
    assert abs(res["net_sharpe"]) != abs(honest["net_sharpe"]) or res == honest


def test_costs_charged_on_turnover():
    df = _df()
    flip = pd.Series([1.0, 0.0] * (len(df) // 2), index=df.index)
    free = bt.run(df, flip, CostModel("free", 0.0))
    costly = bt.run(df, flip, CostModel("x", 0.0093))
    assert costly["total_return"] < free["total_return"] - 0.5, "costs not biting"


def test_deterministic_order_id_stable():
    a = RobinhoodCrypto.deterministic_order_id("s", "BTC-USD", "buy", "2026-07-31T14:00:00+00:00")
    b = RobinhoodCrypto.deterministic_order_id("s", "BTC-USD", "buy", "2026-07-31T14:00:00+00:00")
    c = RobinhoodCrypto.deterministic_order_id("s", "BTC-USD", "sell", "2026-07-31T14:00:00+00:00")
    assert a == b and a != c


def test_risk_blocks():
    p = risk.RiskPolicy()
    v = risk.check_pre_trade(p, equity_usd=140, peak_equity_usd=250, order_usd=50,
                             position_after_usd=100, data_age_hours=1.0)
    assert any(x.startswith("drawdown_breach") for x in v)
    v2 = risk.check_pre_trade(p, equity_usd=250, peak_equity_usd=250, order_usd=50,
                              position_after_usd=100, data_age_hours=9.0)
    assert any(x.startswith("stale_data") for x in v2)
    v3 = risk.check_pre_trade(p, equity_usd=250, peak_equity_usd=250, order_usd=50,
                              position_after_usd=100, data_age_hours=1.0)
    assert v3 == []


def test_walk_forward_runs():
    df = _df(3000)
    from quantfirm.strategies import load_all
    strat = load_all()["ma_cross"]
    out = bt.walk_forward(df, strat, {"fast": 10, "slow": 50}, CostModel("x", 0.0093),
                          n_folds=3, warmup_bars=100)
    assert "oos_sharpe" in out and len(out["fold_sharpes"]) == 3


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
