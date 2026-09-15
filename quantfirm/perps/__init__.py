"""Kalshi perpetual-futures desk (research, paper, canary).

Layout:
    specs.py       venue facts: contracts, margin rule, funding rule, fee tiers, cost model
    client.py      /margin REST client (public data keyless; RSA-PSS for account/orders)
    data.py        daily bars + funding (proxies for history, Kalshi native for the live period)
    strategies.py  registered signal → target-weight functions and the controls
    backtest.py    daily portfolio simulator (fees, funding, interest, liquidation), WFO, CSCV, DSR
    tournament.py  the pre-registered trial set and gates
    risk.py        policy, pre-trade gate, drawdown ladder, kill switch
    paper.py       shadow / demo / live engine (deterministic order path)
    agent.py       LangGraph loop around the engine
    cli.py         entrypoints

Status: RESEARCH + SHADOW. Nothing here sends a real order unless a human
sets config/perps.json live=true AND KALSHI_LIVE=1 AND no kill switch file.
See docs/KALSHI_PERPS.md.
"""
