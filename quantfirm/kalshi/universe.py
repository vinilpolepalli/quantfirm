"""15-minute series this desk knows.

Default paper book: five live commodity binaries plus BTC/ETH 15-minute.
Indexes (SPX/NDX) and dark metals stay listed for harvest, not trading.

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

# 15-minute crypto (live, large books). Harvested for research, not in the
# conservative paper book — last-week lag locks lost on BTC/ETH.
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

# Conservative paper book: five commodities. Crypto stays in LIVE_SERIES
# for harvest. Correlation slots are in halt.CORR_GROUPS.
PAPER_ASSETS = ("gold", "silver", "copper", "wti", "natgas")

# Shadow book on the 24/7 supervisor. 4% 88–94¢ FLB (research/kalshi_iterate.md).
# Not a go-live. Risky mixes stay registered as yolo_* / nuke_lock.
PAPER_STRATEGY = "rich_fav"

# Legacy single cluster. Live gating uses halt.CORR_GROUPS (precious /
# energy / copper) so the $250 can sit in metals AND energy at once.
CORR_GROUP = frozenset({"gold", "silver"})

# Starting paper/backtest bankroll for this research pass.
BANKROLL = 250.0

# Train/test split, fixed before this pass's new strategies were scored.
# Same instant as the prior desk (2026-08-27T00:00:00Z).
SPLIT_TS = 1787788800
