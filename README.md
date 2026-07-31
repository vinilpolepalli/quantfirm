# quantfirm — an agent-operated crypto trading firm

A miniature systematic trading operation modeled on how real quant firms run
(research → validation → risk → execution → review), except every seat is an
AI agent and every process is a scheduled loop. Live venue: Robinhood Crypto.
Bankroll: $250. Everything net of the venue's ~0.93%/side spread.

## Map

| Piece | Where | Cadence |
|---|---|---|
| Execution desk | `.github/workflows/trade.yml` → `quantfirm/live/engine.py` | hourly |
| Research desk (data + revalidation) | `.github/workflows/research.yml` | nightly |
| Risk committee / research review | Claude Routines (agent sessions) | daily/weekly |
| Strategy R&D | agent tournament, `docs/TOURNAMENT.md` | on demand |
| The books | `state/live_state.json`, `state/trade_log.csv` | every run |
| Kill switch | `state/KILL_SWITCH` | honored by every run |

## Docs

- `docs/FIRM.md` — org design: desks, loops, and the eval that drives them
- `docs/RESEARCH.md` — research-swarm findings
- `docs/TOURNAMENT.md` — strategy tournament results and the winner
- `docs/RUNBOOK.md` — go-live checklist, kill switch, incidents
- `docs/PROCESS.md` — build log (how agents built this)

## Quick start (backtesting)

```bash
pip install -r requirements.txt
python -m quantfirm.cli list
python -m quantfirm.cli walkforward --strategy trend_vol_composite --symbol BTCUSDT --split dev
python tests/test_backtest.py
```

## Reality disclosure

Backtests — even walk-forward, holdout-verified, deflated-Sharpe-penalized
ones — do not guarantee live profit. Crypto is volatile; the configured risk
policy tolerates a 40% drawdown before the kill switch trips. Never fund this
with money you cannot lose.
