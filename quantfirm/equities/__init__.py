"""quantfirm.equities — the stock desk.

Same firm, different physics: costs are ~5bps/side instead of 93bps, so the
viable strategy space is far wider; but the account is a $250 CASH account
(PDT-exempt, T+1 settlement) trading fractional shares through the Robinhood
agentic MCP during regular hours only, and any stock universe chosen today is
survivorship-biased in backtests (the ETF track is not — see
data/equities/universe.json for the documented mitigation policy).
"""
