"""Kalshi 15-minute commodities desk.

Default universe: KXGOLD15M / KXSILVER15M / KXCOPPER15M / KXWTI15M /
KXNATGAS15M — one $1 binary per 15-minute window, "will the Pyth index
close this window at or above its open print?". Strike is the Pyth 1-min
candle close at window open; settlement is the 1-min close at window close;
tie → YES.

Also listed (dark as of 2026-09-12): platinum, palladium, S&P 500, Nasdaq
15-minute series. Crypto 15-minute books exist and are research-only.

Venue (verified 2026-09-12): quadratic taker fee, multiplier 1, maker $0,
no settlement fee. Live S is Kalshi event live_data (1s, settlement-aligned).
Paper bankroll for this pass: $250. See docs/KALSHI.md.
"""
