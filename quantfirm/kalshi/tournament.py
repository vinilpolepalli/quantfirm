"""Honest $250 strategy tournament on 15-minute commodity binaries.

Protocol (registered before looking at this pass's test numbers):
  * Bankroll $250 everywhere.
  * Fill model: lag (realistic REST-latency floor). Touch is reported only
    as a ceiling and is never used to pick a winner.
  * Train = windows closing before 2026-08-27T00:00Z; test = the rest.
  * Strategy parameters are frozen in strategies.registry() — no train-side
    selection that then gets a second look at test.
  * Controls (always-yes / always-no / ATM coin-flip) must be worse than
    any strategy we keep. If a control wins, the 'edge' is a drift, not us.
  * A strategy is a CANDIDATE only if test n≥30, test net P&L>0, test
    t-stat≥1.5, test max DD≤30%, and it beats both always-yes and coin-flip
    on test P&L. Promotion to live paper still needs the docs/KALSHI.md gate.

The prior desk already showed the registered oracle taker loses at lag
fill. This file exists to test the OTHER hypotheses that research still
leaves open — not to resuscitate stale-quote sniping by retuning theta.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .backtest import Backtest
from .diagnostics import run_diagnostics
from .strategies import Spec, registry
from .universe import BANKROLL, SPLIT_TS


def _view(m: dict) -> dict:
    return {k: v for k, v in m.items() if k != "trades"}


def _candidate(test: dict, ctrl_yes: dict, ctrl_atm: dict) -> tuple[bool, str]:
    if (test.get("n_trades") or 0) < 30:
        return False, "n<30"
    if (test.get("net_pnl") or 0) <= 0:
        return False, "test_pnl<=0"
    if (test.get("t_stat") or 0) < 1.5:
        return False, "t<1.5"
    if (test.get("max_drawdown_pct") or 0) > 30:
        return False, "dd>30"
    if test["net_pnl"] <= (ctrl_yes.get("net_pnl") or -1e9):
        return False, "loses_to_always_yes"
    if test["net_pnl"] <= (ctrl_atm.get("net_pnl") or -1e9):
        return False, "loses_to_coin_flip"
    return True, "candidate"


def run_tournament(data_dir: str, bankroll: float = BANKROLL,
                   out_json: str | None = None) -> dict:
    bt = Backtest(data_dir, bankroll=bankroll)
    specs = registry()
    diag = run_diagnostics(bt, None, SPLIT_TS)
    rows = []
    for spec in specs:
        from dataclasses import replace
        p = replace(spec.params, fill_mode=spec.fill_mode)
        train = bt.run(p, end_ts=SPLIT_TS, decide_fn=spec.fn)
        test = bt.run(p, start_ts=SPLIT_TS, decide_fn=spec.fn)
        # +1c slippage stress on TEST only (does not create a new selection)
        p_slip = replace(p, slippage_extra=0.01)
        stress = bt.run(p_slip, start_ts=SPLIT_TS, decide_fn=spec.fn)
        rows.append({
            "name": spec.name,
            "note": spec.note,
            "fill_mode": spec.fill_mode,
            "train": _view(train),
            "test": _view(test),
            "test_slip1c": _view(stress),
        })
        print(f"{spec.name:20s} train n={train['n_trades']:4} "
              f"pnl={train['net_pnl']:+8.2f} t={train.get('t_stat')}  "
              f"TEST n={test['n_trades']:4} pnl={test['net_pnl']:+8.2f} "
              f"t={test.get('t_stat')} hit={test.get('hit_rate')} "
              f"dd={test.get('max_drawdown_pct')}%", flush=True)

    by_name = {r["name"]: r for r in rows}
    ctrl_yes = by_name.get("ctrl_always_yes", {}).get("test", {})
    ctrl_atm = by_name.get("ctrl_coin_flip", {}).get("test", {})
    for r in rows:
        ok, why = _candidate(r["test"], ctrl_yes, ctrl_atm)
        r["candidate"] = ok
        r["gate"] = why

    survivors = [r["name"] for r in rows if r["candidate"]]
    # paper pick: best test t-stat among survivors, else the theoretically
    # cleanest remaining idea (late_lock) for the live measurement — not a
    # claim of edge.
    if survivors:
        paper = max((r for r in rows if r["candidate"]),
                    key=lambda r: (r["test"].get("t_stat") or 0))
        paper_name = paper["name"]
    else:
        paper_name = "late_lock"

    out = {
        "bankroll": bankroll,
        "split": "2026-08-27T00:00:00Z",
        "fill_primary": "lag",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "diagnostics_train": diag,
        "strategies": rows,
        "survivors": survivors,
        "paper_strategy": paper_name,
        "verdict": (
            f"{len(survivors)} strategy(ies) cleared the $250 / lag-fill / "
            f"t≥1.5 / beat-controls gate: {survivors or 'NONE'}."
        ),
    }
    if out_json:
        os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
        with open(out_json, "w") as f:
            json.dump(out, f, indent=1, default=str)
    return out


def render_markdown(result: dict) -> str:
    lines = [
        "# Kalshi 15M commodity tournament — $250, lag fill",
        "",
        f"Generated {result['generated']}. Bankroll ${result['bankroll']:.0f}. "
        f"Split {result['split']}. Primary fill model: **{result['fill_primary']}**.",
        "",
        result["verdict"],
        "",
        "## Train-split diagnostics (not a backtest)",
        "",
    ]
    for note in (result.get("diagnostics_train") or {}).get("reading") or []:
        lines.append(f"- {note}")
    lines += [
        "",
        "## Results",
        "",
        "| strategy | train n / pnl / t | TEST n / pnl / t / hit / dd | slip+1c | gate |",
        "|---|---|---|---|---|",
    ]
    for r in result["strategies"]:
        tr, te, sl = r["train"], r["test"], r["test_slip1c"]
        lines.append(
            f"| `{r['name']}` | {tr['n_trades']} / {tr['net_pnl']:+.1f} / {tr.get('t_stat')} "
            f"| {te['n_trades']} / {te['net_pnl']:+.1f} / {te.get('t_stat')} / "
            f"{te.get('hit_rate')} / {te.get('max_drawdown_pct')}% "
            f"| {sl['net_pnl']:+.1f} | {r['gate']} |"
        )
    lines += [
        "",
        f"Paper engine default for the live shadow book: `{result['paper_strategy']}`.",
        "",
        "A green train number that dies on test is the prior desk's story and "
        "is not evidence. Maker P&L is not in this table — candle maker fills "
        "are an artifact (see `maker-control`). The live paper maker leg is "
        "the measurement for that hypothesis.",
        "",
    ]
    return "\n".join(lines)
