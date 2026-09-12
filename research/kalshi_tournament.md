# Kalshi 15M commodity tournament — $250, lag fill

Generated 2026-09-12T00:43:37Z. Bankroll $250. Split 2026-08-27T00:00:00Z. Primary fill model: **lag**.

1 strategy(ies) cleared the $250 / lag-fill / t≥1.5 / beat-controls gate: ['favorite_blind'].

## Train-split diagnostics (not a backtest)

- At τ=5min, contracts mid≥90c won 97% (n=724). Supports favorite harvest.
- At τ=5min, contracts mid<10c won 3% (n=553). Longshots overpriced — do not buy them.
- First-3-minute impulse does not predict the rest of the window.
- At τ=2min, model-certain favorites (z≥0.8) hit 98% (n=954). late_lock is plausible.

## Results

| strategy | train n / pnl / t | TEST n / pnl / t / hit / dd | slip+1c | gate |
|---|---|---|---|---|
| `ctrl_always_yes` | 61 / -157.5 / -2.45 | 100 / -141.2 / -1.75 / 0.33 / 70.64% | -159.7 | test_pnl<=0 |
| `ctrl_always_no` | 61 / +104.1 / 0.31 | 95 / -152.6 / -2.04 / 0.379 / 67.81% | -167.1 | test_pnl<=0 |
| `ctrl_coin_flip` | 20 / -13.8 / -1.28 | 28 / -9.5 / -0.73 / 0.321 / 5.72% | -11.0 | n<30 |
| `oracle_lag` | 34 / +55.2 / 0.71 | 35 / -31.0 / -0.42 / 0.4 / 26.71% | -56.6 | test_pnl<=0 |
| `oracle_flow` | 5 / -30.8 / -4.74 | 14 / +59.8 / 1.08 / 0.429 / 10.03% | +44.6 | n<30 |
| `favorite_blind` | 329 / -1.2 / -0.02 | 531 / +278.0 / 1.8 / 0.763 / 16.83% | +161.3 | candidate |
| `favorite_confirmed` | 108 / +28.6 / 0.43 | 158 / +66.5 / 0.69 / 0.778 / 20.58% | +46.0 | t<1.5 |
| `late_lock` | 10 / -18.6 / -0.53 | 14 / +39.9 / 0.98 / 0.857 / 7.38% | +36.3 | n<30 |
| `open_fade` | 33 / +69.6 / 0.31 | 27 / -97.1 / -1.41 / 0.111 / 63.7% | -110.9 | n<30 |
| `open_follow` | 0 / +0.0 / 0.0 | 0 / +0.0 / 0.0 / None / 0.0% | +0.0 | n<30 |
| `session_favorite` | 21 / -8.7 / -0.28 | 26 / -19.5 / -0.65 / 0.769 / 12.12% | -22.3 | n<30 |
| `iv_rich_favorite` | 18 / +17.7 / 0.49 | 15 / +29.2 / 0.59 / 0.8 / 14.93% | +25.5 | n<30 |

Paper engine default for the live shadow book: `favorite_blind`.

A green train number that dies on test is the prior desk's story and is not evidence. Maker P&L is not in this table — candle maker fills are an artifact (see `maker-control`). The live paper maker leg is the measurement for that hypothesis.
