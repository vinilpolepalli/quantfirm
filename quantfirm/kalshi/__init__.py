"""Kalshi commodities desk (gold/silver/copper 15-minute binaries).

Instruments: KXGOLD15M / KXSILVER15M / KXCOPPER15M — one $1 binary per
15-minute window, "will the Pyth metals index close this window at or above
its open print?". Strike (floor_strike) is the Pyth 1-min candle close at
window open; settlement is the close of the 1-min candle at window close,
both rounded to 2dp; tie goes to YES (strike_type greater_or_equal).

Venue facts this desk is built on (verified 2026-09-10, docs in
docs/KALSHI.md): taker fee ceil(0.07*C*P*(1-P)), maker fee $0, no settlement
fee; books quote ~1c wide with deep size on gold; demo env mirrors prod
tickers but its books are empty, so demo is used for order plumbing only and
all economics are measured against prod public data.
"""
