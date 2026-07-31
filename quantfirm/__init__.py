"""quantfirm — an agent-operated systematic crypto trading firm.

Layout:
    costs.py       venue cost model (Robinhood Crypto spreads)
    data.py        historical + live candle acquisition
    metrics.py     performance metrics incl. deflated Sharpe
    backtest.py    vectorized long-only backtester with walk-forward splits
    strategies/    strategy registry (signal functions)
    risk.py        risk policy enforcement
    live/          signed Robinhood API client + hourly execution engine
    cli.py         entrypoints used by humans, CI, and agents alike
"""

__version__ = "0.1.0"
