"""One-time go-live transition: carve the bot's bankroll out of existing
holdings with minimum spread cost.

Instead of selling $BANKROLL of crypto to cash and letting the engine buy
right back (paying the ~1.9% round trip), this computes the live strategy's
CURRENT target position and only trades the difference:

    target_qty  = target_frac * bankroll / price      (kept as coins)
    sell_qty    = bankroll/price - target_qty         (converted to cash)

then writes state/live_state.json so the engine starts with correct books.

Usage (requires RH_API_KEY / RH_PRIVATE_KEY_B64 in env):
    python scripts/seed_books.py --bankroll 250 [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from quantfirm.live.engine import build_candles, load_config  # noqa: E402
from quantfirm.live import state as st  # noqa: E402
from quantfirm.live.rh_client import RobinhoodCrypto  # noqa: E402
from quantfirm.strategies import load_all  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bankroll", type=float, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    strat = load_all()[cfg["strategy"]]
    df = build_candles(cfg["data_symbol"])
    target_frac = float(strat(df, **cfg.get("params", {})).iloc[-1])
    target_frac = max(0.0, min(1.0, target_frac))

    client = RobinhoodCrypto()
    quote = client.best_bid_ask(cfg["venue_symbol"])
    mid = float(quote["price"])
    bid = float(quote["bid_inclusive_of_sell_spread"])

    bankroll_qty = args.bankroll / mid
    target_qty = round(target_frac * args.bankroll / mid, 8)
    sell_qty = round(bankroll_qty - target_qty, 8)

    plan = {
        "bar": df.index[-1].isoformat(),
        "mid": mid,
        "target_frac": target_frac,
        "bankroll_usd": args.bankroll,
        "keep_as_position_qty": target_qty,
        "sell_qty": sell_qty,
        "sell_notional_usd": round(sell_qty * bid, 2),
    }
    print(json.dumps(plan, indent=2))
    if args.dry_run:
        return

    cash = 0.0
    if sell_qty * bid >= 1.0:
        order_id = RobinhoodCrypto.deterministic_order_id(
            "seed_books", cfg["venue_symbol"], "sell", plan["bar"])
        resp = client.place_market_order(cfg["venue_symbol"], "sell",
                                         f"{sell_qty:.8f}", order_id)
        cash = sell_qty * bid
        st.log_trade({"ts": st.now_iso(), "symbol": cfg["venue_symbol"],
                      "side": "sell", "qty": sell_qty, "ref_price": bid,
                      "notional_usd": round(cash, 2), "client_order_id": order_id,
                      "order_id": resp.get("id", ""), "status": resp.get("state", "")})

    state = st.load()
    state.update({
        "last_bar": plan["bar"],
        "position_qty": target_qty,
        "cash_usd": round(cash, 4),
        "peak_equity": round(target_qty * mid + cash, 4),
    })
    state.setdefault("equity_history", []).append(
        [st.now_iso(), round(target_qty * mid + cash, 4)])
    st.save(state)
    print(json.dumps({"seeded": True, "state_file": st.STATE_FILE}, indent=2))


if __name__ == "__main__":
    main()
