"""Append-only trial registry.

Every backtest that produces a number an agent might act on is recorded
here: strategy, parameters, split, window, and the headline metrics. The
deflated Sharpe's N is the count of distinct (strategy, params) entries, so
running a hundred variants to find one that works raises the bar for that
one. That is the point (docs/FIRM.md §2, Bailey & López de Prado 2014).

The file is JSONL and only ever appended. Deleting rows is a protocol
violation and shows up in git history.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, "research", "kalshi_perps", "trial_registry.jsonl")


def _key(strategy: str, params: dict) -> str:
    blob = json.dumps({"s": strategy, "p": params}, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def record(strategy: str, params: dict, split: str, metrics: dict, source: str = "cli",
           note: str = "") -> str:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    row = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "key": _key(strategy, params),
        "strategy": strategy,
        "params": params,
        "split": split,
        "source": source,
        "net_sharpe": metrics.get("net_sharpe"),
        "cagr": metrics.get("cagr"),
        "max_drawdown": metrics.get("max_drawdown"),
        "ann_turnover": metrics.get("ann_turnover"),
        "start": metrics.get("start"), "end": metrics.get("end"),
        "note": note,
    }
    with open(PATH, "a") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return row["key"]


def load() -> list[dict]:
    if not os.path.exists(PATH):
        return []
    out = []
    with open(PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def count_unique(split: str | None = "dev") -> int:
    rows = load()
    keys = {r["key"] for r in rows if split is None or r.get("split") == split}
    return len(keys)


def summary() -> dict:
    rows = load()
    by = {}
    for r in rows:
        by.setdefault(r["strategy"], set()).add(r["key"])
    return {"rows": len(rows), "unique_configs": len({r["key"] for r in rows}),
            "by_strategy": {k: len(v) for k, v in sorted(by.items())}}
