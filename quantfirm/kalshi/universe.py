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
# of the book each (~$9–10), ≥75¢. BTC after the 3 min wait; ETH
# after 5 min. Both sit the last 2 minutes. Not a split budget. Names
# may disagree. SOL/DOGE/XRP 15m exist but stay off the live loop until
# a lag-fill pass clears each name independently.
SERIES_COMPARE = {
    "KXBTC15M": "btc",
    "KXETH15M": "eth",
}

# Scored in research/kalshi_div_nowcast.md. Not PAPER_ASSETS, not live.
# SOL is in the map so a CLI `--metals sol` still gets the 4% overlay
# instead of the 8% commodity book. It is not CRYPTO_PAPER.
SERIES_CRYPTO_EXTRA = {
    "KXSOL15M": "sol",
    "KXDOGE15M": "doge",
    "KXXRP15M": "xrp",
    "KXNEAR15M": "near",
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
    "sol": "SOL-USD",
    "doge": "DOGE-USD",
    "xrp": "XRP-USD",
    "near": "NEAR-USD",
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

# Lag-fill cleared 2026-09-13 (research/kalshi_div_nowcast.md). SOL/HYPE/BNB/ZEC
# did not. Overlay is 4% / ≥75¢ / wait-3 like BTC (not ETH's 5 min).
# Not PAPER_ASSETS.
CRYPTO_PAPER = ("doge", "xrp", "near")
CRYPTO_OVERLAY = CRYPTO_LIVE + tuple(SERIES_CRYPTO_EXTRA.values())

# Live book: five commodities + BTC + ETH. Correlation slots are in
# halt.CORR_GROUPS (precious / energy). Crypto names are their own books.
PAPER_ASSETS = ("gold", "silver", "copper", "wti", "natgas") + CRYPTO_LIVE

# Live canary on the 24/7 supervisor. Commodities wait the first 3
# minutes, then 8% FLB ≥75¢ (no Poly 15m book). BTC: 4% / ≥75¢ after
# T+3, sit last 2 min. ETH: same size/bar after T+5, sit last 2 min.
# Both sit if Polymarket's 15m favorite disagrees. Names are independent
# (BTC YES and ETH NO in the same window is allowed). Sit out 60–74¢,
# longshots, and fee-eat (99¢ last ticks). Do not raise 75¢ — live
# 78¢+ is red. Risky mixes stay registered as yolo_* / nuke_lock and
# off this loop.
PAPER_STRATEGY = "desk_book"

# Legacy single cluster. Live gating uses halt.CORR_GROUPS (precious /
# energy / copper) so the $250 can sit in metals AND energy at once.
CORR_GROUP = frozenset({"gold", "silver"})

# Starting paper/backtest bankroll for this research pass.
BANKROLL = 250.0

# Train/test split, fixed before this pass's new strategies were scored.
# Same instant as the prior desk (2026-08-27T00:00:00Z).
SPLIT_TS = 1787788800
