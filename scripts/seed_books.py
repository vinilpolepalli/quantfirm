"""One-time go-live transition: carve the bot's bankroll out of existing
holdings with minimum spread cost, verify the credential can see its own
orders, and initialize the books.

Instead of selling $BANKROLL of crypto to cash and letting the engine buy
right back (paying the ~1.9% round trip), this computes the live strategy's
CURRENT target position and only trades the difference. Guards:
  * refuses to run on already-initialized books (unless --force)
  * quantizes to the venue's served increments, like the engine
  * books only the venue-confirmed fill, like the engine
  * sets orders_read_verified only after finding its own order (or any order
    history) via the API — the engine refuses to trade blind

Usage (requires RH_API_KEY / RH_PRIVATE_KEY_B64 in env):
    python scripts/seed_books.py --bankroll 250 [--dry-run] [--force]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, ROUND_DOWN

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from quantfirm.live.engine import build_candles, load_config, find_order, poll_terminal, book_order  # noqa: E402
from quantfirm.live import state as st  # noqa: E402
from quantfirm.live.rh_client import RobinhoodCrypto  # noqa: E402
from quantfirm.strategies import load_all  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bankroll", type=float, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="re-seed over already-initialized books (dangerous)")
    args = ap.parse_args()

    state = st.load()
    if state.get("initialized") and not args.force:
        print(json.dumps({"error": "books already initialized; use --force to override"}))
        sys.exit(1)
    if state.get("pending_order"):
        print(json.dumps({"error": "pending order in state; resolve it first"}))
        sys.exit(1)

    cfg = load_config()
    strat = load_all()[cfg["strategy"]]
    df = build_candles(cfg["data_symbol"])
    target_frac = float(strat(df, **cfg.get("params", {})).iloc[-1])
    target_frac = max(0.0, min(1.0, target_frac))

    client = RobinhoodCrypto()
    quote = client.best_bid_ask(cfg["venue_symbol"])
    mid = float(quote["price"])
    bid = float(quote["bid_inclusive_of_sell_spread"])

    pair = client.trading_pair(cfg["venue_symbol"])
    increment = Decimal(str(pair.get("asset_increment") or "0.00000001"))
    min_qty = float(pair.get("min_order_size") or 0.000001)

    bankroll_qty = args.bankroll / mid
    target_qty = float(Decimal(str(target_frac * args.bankroll / mid))
                       .quantize(increment, rounding=ROUND_DOWN))
    sell_qty = float(Decimal(str(bankroll_qty - target_qty))
                     .quantize(increment, rounding=ROUND_DOWN))

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
    if sell_qty >= min_qty and sell_qty * bid >= 1.0:
        order_id = RobinhoodCrypto.deterministic_order_id(
            "seed_books", cfg["venue_symbol"], "sell", plan["bar"])
        try:
            client.place_market_order(cfg["venue_symbol"], "sell",
                                      f"{sell_qty:.8f}", order_id)
        except Exception as e:
            if find_order(client, order_id) is None:
                print(json.dumps({"error": f"sell failed: {e}"}))
                sys.exit(1)
        order = poll_terminal(client, order_id, seconds=60)
        if not order:
            print(json.dumps({"error": "sell not visible via orders API — enable "
                              "order-read permission on the credential and retry"}))
            sys.exit(1)
        temp = {"position_qty": 0.0, "cash_usd": 0.0, "trades": 0}
        booked = book_order(temp, order, fallback_price=bid)
        cash = temp["cash_usd"]
        # the seeded position is the intended target minus anything unfilled
        target_qty = float(Decimal(str(bankroll_qty - booked["filled_qty"]))
                           .quantize(increment, rounding=ROUND_DOWN))

    orders_visible = len(client.orders()) > 0
    state.update({
        "initialized": True,
        "orders_read_verified": orders_visible,
        "pending_order": None,
        "last_bar": plan["bar"],
        "position_qty": target_qty,
        "cash_usd": round(cash, 4),
        "peak_equity": round(target_qty * mid + cash, 4),
    })
    state.setdefault("equity_history", []).append(
        [st.now_iso(), round(target_qty * mid + cash, 4)])
    st.save(state)
    print(json.dumps({"seeded": True, "orders_read_verified": orders_visible,
                      "state_file": st.STATE_FILE}, indent=2))
    if not orders_visible:
        print("WARNING: credential cannot list orders; engine will refuse to "
              "trade until order-read permission is enabled and books re-verified.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
