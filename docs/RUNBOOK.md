# Runbook — operating the firm

## Go-live checklist (in order)

1. **Secrets** (repo → Settings → Secrets and variables → Actions):
   - `RH_API_KEY` — the Robinhood Crypto API key
   - `RH_PRIVATE_KEY_B64` — base64 of the raw 32-byte Ed25519 private seed
   - Strongly recommended: revoke any credential whose private key was ever
     displayed in a chat/log, generate a fresh keypair locally
     (`openssl genpkey -algorithm ed25519`), register the new public key in the
     [Robinhood credentials portal](https://robinhood.com/account/crypto), and
     use that here.
2. **Fund the bot**: the account needs ≥ `bankroll_usd` ($250) in *cash*
   buying power. The engine only spends its recorded `cash_usd`, so seed the
   books: set `state/live_state.json` → `cash_usd` to the funded amount
   (`position_qty` 0). The bot will never touch other holdings.
3. **Enable**: set `"enabled": true` in `config/live.json` (via PR).
4. Workflows `execution-desk` (hourly) and `research-desk-nightly` run on
   GitHub Actions from `main`. First run can be forced from the Actions tab
   (`workflow_dispatch`).

## Kill switch

- `state/KILL_SWITCH` file existing = no trading. The engine trips it itself
  on a −40% drawdown from peak equity. Any agent or human can trip it by
  committing the file; remove it (via PR) to resume.
- Hard stop: disable the `execution-desk` workflow in the Actions tab, or set
  `"enabled": false` in `config/live.json`, or revoke the API credential in
  the Robinhood portal (strongest).

## Monitoring

- `state/live_state.json` — position, cash, equity history, last action.
- `state/trade_log.csv` — every order ever placed.
- `state/research_report.json` — nightly walk-forward revalidation.
- Failed Actions runs = engine error; the run log contains the JSON result.

## Incident playbook

| Symptom | Action |
|---|---|
| Engine run fails repeatedly | Check Actions log; if API errors, verify credential in portal; trip kill switch if unclear |
| Drawdown kill switch tripped | Risk-committee agent reviews `research_report.json` + equity history, decides restart or strategy change via PR |
| Stale data (`stale_data` violations) | Kraken outage; engine refuses to trade — no action needed, resolves itself |
| Duplicate-order suspicion | Order IDs are deterministic per (strategy, symbol, side, bar); check `trade_log.csv` for repeated `client_order_id` — the venue rejects duplicates |

## Parameter / strategy changes

Never edit `config/live.json` directly on `main` outside an emergency. The
research-desk agent proposes changes as PRs with the walk-forward + holdout
evidence in the PR body; the human (or risk-committee agent) merges.
