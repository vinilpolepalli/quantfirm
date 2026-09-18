# quantfirm — orientation for a fresh session

An agent-operated systematic trading firm. Deterministic code makes every
buy/sell decision; agents execute, verify and supervise. Real money is live.
Read this before touching anything.

## Hard rules

1. **Never send a live order that the code's own gate would not send.** Every
   desk gates on a kill-switch file plus an explicit env flag. Do not bypass a
   gate to "test" something — run the dry run instead.
2. **Kill switches are files.** `state/KILL_SWITCH_KALSHI`, `KILL_SWITCH_PERPS`,
   `KILL_SWITCH_EQ`. Present = that desk is stopped. Creating one is always safe.
3. **Broker state is truth.** Reconcile against the venue before deciding
   anything; never "correct" a mismatch by trading.
4. **Promotion is gated**: IDEA → RESEARCH → REVIEW → PAPER → CANARY →
   PRODUCTION. No strategy skips paper. `docs/FIRM.md` has the eval and the
   anti-overfitting machinery (sealed vault, trial registry, DSR/PBO).
5. **State lives in git.** `state/*.json` is committed every run; that history
   is the audit trail. Never rewrite it, and never let a stale copy from a
   branch overwrite a live one.
6. **Do not quote a P&L number you have not recomputed.** See the traps below.

## Desks and where they are

| desk | venue | status | doc |
|---|---|---|---|
| Equity | Robinhood equities | **LIVE**, $250, six names | `docs/EQUITY.md` |
| Kalshi 15M | Kalshi commodity/crypto binaries | halted (kill switch) | `docs/KALSHI_15M.md` |
| Kalshi perps | Kalshi perpetual futures | **PAPER/SHADOW**, live=false; $257 owner-transfers after paper | `docs/KALSHI_PERPS.md` |
| Crypto | Robinhood Crypto | disabled, tournament NO-GO | `docs/TOURNAMENT.md` |

The Kalshi Liquidity Incentive Program desk is **dead**. Owner killed it
2026-09-18. Do not rebuild the collector, the quoter, or `state/INCENTIVE_LIVE`.
The $257 that was reserved for it transfers to perps **by the owner**, not by
an agent, and **after** the paper books have a reading — not before. Do not
set `live: true`. Do not recreate `state/KILL_SWITCH_PERPS` unless something
is actually wrong.

Note `docs/FIRM.md` is the original design brief and has drifted: it describes a
Robinhood **crypto** desk that is now disabled, and references paths under
`/home/user/2-3-24VEX/` that no longer exist. Its architecture, risk policy and
eval still govern; its subject does not.

## Traps this repo has already fallen into

- **`quantfirm/kalshi/maker.py`** reports ~+800% and is an artifact. Replacing
  the model's fair value with the market's own mid makes it *better*, which
  proves the P&L is not coming from prediction. The file is kept because the
  failure is instructive. Never quote its number.
- **Annualising short windows.** A $100 pool over 24 minutes is not $6,000/day.
- **Thin books on brand-new programs are empty rooms, not edges.** Measured
  decay is 119x from fresh to a week old.
- **A persistence test that re-measures the same fresh objects proves nothing.**
- The dead incentive book produced four optimistic numbers on 2026-09-16, each
  wrong by about an order of magnitude. That lesson stays: recompute; do not
  inherit.

## Conventions

- Research memos: `research/*.md`, blunt verdict table up top, honest about
  losses. Scripts: `scripts/*.py`, stdlib-first, public endpoints where possible.
- Scheduled work runs in **GitHub Actions** (`.github/workflows/`), which is
  what commits state. Claude Routines are for email/reporting; a Routine that
  silently fails to push produces no data and is worse than a loud failure.
- Credentials never go in chat, never in a commit. `.env*` is gitignored;
  Actions reads from repo secrets.
