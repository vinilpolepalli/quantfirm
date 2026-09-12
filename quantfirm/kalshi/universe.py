"""15-minute series this desk knows.

Default paper book: five live commodity binaries plus BTC/ETH 15-minute
(both can be on at once). Indexes and dark metals stay listed for harvest,
not trading.

Fees are quadratic, multiplier 1, maker $0 on every series here.
"""

from __future__ import annotations

# series_ticker -> short asset name used in state / YF files / paper books
SERIES = {
    "KXGOLD15M": "gold",
    "KXSILVER15M": "silver",
    "KXCOPPER15M": "copper",
    "KXWTI15M": "wti",
    "KXNATGAS15M": "natgas",
}

# Listed but not live as of 2026-09-12 (no settled or open markets).
SERIES_LISTED_DARK = {
    "KXPALLADIUM15M": "palladium",
    "KXPLATINUM15M": "platinum",
    "KXINX15M": "spx",
    "KXNDQ15M": "ndx",
}

# 15-minute crypto (live, large books). BTC and ETH both clip at 4%
# of the book each (~$9–10), ≥60¢ / until close. Not a split budget.
# SOL/DOGE/XRP 15m exist but are not scored.
SERIES_COMPARE = {
    "KXBTC15M": "btc",
    "KXETH15M": "eth",
}

LIVE_SERIES = {**SERIES, **SERIES_COMPARE}

YF_SYMBOLS = {
    "gold": "GC=F",
    "silver": "SI=F",
    "copper": "HG=F",
    "wti": "CL=F",
    "natgas": "NG=F",
    "palladium": "PA=F",
    "platinum": "PL=F",
    "btc": "BTC-USD",
    "eth": "ETH-USD",
}

# Swissquote public BBO (keyless). Gold/silver measured ~1 bp vs Pyth.
# OIL is a Swissquote WTI-ish quote — basis vs Pyth PYTHOIL is not 1 bp,
# so paper entries on WTI prefer Kalshi event live_data.
SWISSQUOTE = {
    "gold": "XAU",
    "silver": "XAG",
    "wti": "OIL",
}

# Harvest both. Live both — independent books, same cautious overlay.
CRYPTO_ASSETS = ("btc", "eth")
CRYPTO_LIVE = ("btc", "eth")

# Live book: five commodities + BTC + ETH. Correlation slots are in
# halt.CORR_GROUPS (precious / energy). Crypto names are their own books.
PAPER_ASSETS = ("gold", "silver", "copper", "wti", "natgas") + CRYPTO_LIVE

# Live canary on the 24/7 supervisor. Commodities: 8% FLB ≥60¢ from
# window open until close. ETH: 4% / ≥60¢ / from open. BTC: wait the
# first 3 minutes, then 4% / ≥60¢, and sit if Polymarket's 15m favorite
# disagrees. Sit out coin-flips, longshots, and fee-eat (that is the
# 99¢ last-tick skip). Risky mixes stay registered as yolo_* / nuke_lock
# and off this loop.
PAPER_STRATEGY = "desk_book"

# Legacy single cluster. Live gating uses halt.CORR_GROUPS (precious /
# energy / copper) so the $250 can sit in metals AND energy at once.
CORR_GROUP = frozenset({"gold", "silver"})

# Starting paper/backtest bankroll for this research pass.
BANKROLL = 250.0

# Train/test split, fixed before this pass's new strategies were scored.
# Same instant as the prior desk (2026-08-27T00:00:00Z).
SPLIT_TS = 1787788800
