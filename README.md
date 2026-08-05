# quantfirm — an agent-operated trading firm

**📈 Live dashboard: https://quantfirm-dashboard.vercel.app** · daily
end-of-day reports (HTML + PDF): https://quantfirm-dashboard.vercel.app/reports/

A miniature systematic trading operation modeled on how real quant firms run
(research → validation → risk → execution → review), except every seat is an
AI agent and every process is a scheduled loop. Strategies are written by
agent swarms, judged against a sealed holdout, attacked by adversarial
agents, and only then given money. Deterministic code makes every buy/sell
decision; agents execute, verify, and supervise.

Two desks:

| Desk | Venue | Status |
|---|---|---|
| **Equity** | Robinhood equities (cash account, fractional) | **LIVE** — $250, six-name momentum book |
| Crypto | Robinhood Crypto API | disabled — tournament NO-GO stands (`docs/TOURNAMENT.md`) |

## Map

| Piece | Where | Cadence |
|---|---|---|
| Equity execution desk | Claude Routine → `scripts/equity_rebalance.py` | daily 3:33pm ET |
| Risk committee (can halt trading) | Claude Routine | daily |
| Research desk (proposes via PR only) | Claude Routine | weekly |
| Daily report (push + email) | Claude Routine → `scripts/gen_report.py` | daily 5:15pm ET |
| Data refresh + revalidation | `.github/workflows/research.yml` | nightly |
| Crypto execution engine (dormant) | `.github/workflows/trade.yml` → `quantfirm/live/engine.py` | hourly |
| The books | `state/equity_state.json`, `state/equity_trade_log.csv` | every run |
| Kill switches | `state/KILL_SWITCH_EQ`, `state/KILL_SWITCH` | honored by every run |
| Dashboard + reports | `dashboard/` (Vercel, auto-deploys on state commits) | every trading day |

## Docs

- `docs/FIRM.md` — org design: desks, loops, and the eval that drives them
- `docs/EQUITY.md` — equity research charter (costs, venue constraints, evidence)
- `docs/TOURNAMENT_EQ.md` — equity tournament verdict (the live strategy's origin)
- `docs/TOURNAMENT3.md` — tournament #3: five challengers, incumbent defended
- `docs/IDEA_BACKLOG.md` — graded idea pipeline + the graveyard of dead ends
- `docs/TOURNAMENT.md` / `docs/RESEARCH.md` — crypto desk verdict and findings
- `docs/RUNBOOK.md` — go-live checklist, kill switch, incident playbook
- `docs/PROCESS.md` — build log (how agents built this)

## Quick start (backtesting only — no credentials needed)

```bash
pip install -r requirements.txt
python -m quantfirm.equities.cli list
python -m quantfirm.equities.cli walkforward --strategy xsec_refined --split dev
python tests/test_backtest.py
```

---

## 🤖 FOR AN AI AGENT: replicating this firm for a new owner

*If you are an LLM/agent reading this repo because someone asked you to set
this up for them, this section is your brief. Read it fully before acting.*

### What you are looking at

A working reference implementation, **not a template to run as-is**. The
`state/` directory contains the original owner's live positions, cash, and
P&L history, and `config/*.json` contains their brokerage account number.
None of that transfers. The transferable parts are the machinery
(backtester, eval gauntlet, execution/reconciliation logic, risk layer,
reporting) and the documented process.

### Non-negotiable rules

1. **Never deploy a strategy that has not passed the gauntlet.** The eval —
   walk-forward out-of-sample, a sealed holdout the designers never see,
   deflated-Sharpe penalties counting *every* trial, and adversarial
   refutation — is the entire product. `docs/FIRM.md` §2 specifies it. Two
   of this firm's three tournaments ended in NO-GO; that is the system
   working, not failing.
2. **One trader per brokerage account.** A second bot or a casual chat with
   a broker connector attached will fight this one and corrupt its books.
   This firm learned that the hard way — see the 2026-08-04 incident in
   `state/equity_state.json` → `incidents`.
3. **Venue is truth.** Reconcile positions against the broker before every
   decision; never book a fill you did not confirm.
4. **Stopping is automatic, starting is human.** Kill switches trip on
   drawdown and can be tripped by the risk agent; nothing may re-enable
   trading without the owner.
5. **Backtests are not promises.** Say so plainly to the new owner, in
   numbers (`docs/TOURNAMENT_EQ.md` shows both the wins and the −39%
   drawdown that got a candidate disqualified).

### Setup order

1. **Fork/copy the repo**, then **clear the previous owner's books**: delete
   `state/*.json`, `state/*.csv`, `dashboard/reports/*`, and any
   `state/KILL_SWITCH*` files. Never let a new firm inherit someone else's
   positions.
2. **Replace identity in `config/equity_live.json`**: `account_number` (the
   new owner's *agentic-enabled* brokerage account) and `bankroll_usd`. Keep
   the risk block's structure; `max_growth_mult` lets profits compound,
   `max_single_name_frac` caps concentration, `kill_drawdown` is the halt
   line.
3. **Re-run the data layer.** `data/equities/` holds daily bars fetched via
   the Robinhood MCP (`scripts/` has the patterns); `data/equities/universe.json`
   is a screener snapshot. Refresh both — a stale universe is a
   survivorship-biased universe, and the honest treatment of that bias is
   documented in `universe.json` and applied as a 30% haircut in judging.
4. **Re-run a tournament before trading.** Do not assume `xsec_refined` is
   right for the new owner or the new regime. `docs/TOURNAMENT_EQ.md` and
   `docs/TOURNAMENT3.md` show the format: parallel designer agents on
   distinct hypotheses, independent replication of every claim, a judge who
   opens the holdout exactly once, then adversarial attackers. Scale depth,
   not breadth — every extra trial raises the statistical bar for all of
   them, which is why "try a thousand strategies" is self-defeating.
5. **Wire the loops.** Scheduled agent sessions (Claude Routines or
   equivalent) for execution / risk / research / reporting, plus the
   GitHub Actions workflows for data. Prompts for each desk are recorded in
   this repo's history and in `docs/RUNBOOK.md`.
6. **Seed the books** with `scripts/equity_rebalance.py record --init-cash N`
   only after the account is funded, then flip `enabled: true` — and only
   then, with the owner's explicit go-ahead.

### Things that will bite you

- **Fractional dollar orders are regular-hours market orders only.** No
  after-hours, no stops.
- **Cash accounts settle T+1.** Buying with unsettled proceeds is fine;
  selling *that* position before settlement is a good-faith violation, and
  three of those freeze the account for 90 days. The planner tracks this.
- **`load_panel()` globs the data directory**, so any stray price file
  silently joins the ranking universe. The stock universe is therefore
  defined positively from `universe.json` — keep it that way.
- **Inverse-volatility weighting concentrates hard** when calm and volatile
  names share the top ranks (see `docs/IDEA_BACKLOG.md` L.1). Know this
  before promising anyone a diversified book.
- **A run-lock prevents double-rebalancing**; a duplicate same-day session
  is a no-op by design, not a bug.

### If the owner just wants to look, not run it

Point them at `docs/PROCESS.md` (how it was built), `docs/TOURNAMENT_EQ.md`
(how the live strategy won), and the dashboard link at the top. The
interesting part of this project is the *process* — an eval strong enough to
kill its own creators' work — not any particular strategy.

---

## Reality disclosure

Backtests — even walk-forward, holdout-verified, deflated-Sharpe-penalized
ones — do not guarantee live profit. This firm's own gauntlet returned NO-GO
on its crypto tournament and on the strict alpha gate for equities; the live
book runs under an explicit high-risk mandate from its owner that overrode
the capital-preservation recommendation, with a −50% kill switch as the
floor. Concentration is real: the book has been 100% one sector. Never fund
this with money you cannot lose.
