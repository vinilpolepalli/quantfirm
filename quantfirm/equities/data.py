"""Panel loading for the equity desk.

Per-symbol CSVs (data/equities/SYMBOL_1d.csv.gz, written by the fetch swarm
from Robinhood MCP historicals, split-adjusted) are assembled into wide
DataFrames indexed by date with one column per symbol.
"""

from __future__ import annotations

import json
import os

import pandas as pd

EQ_DATA_DIR = os.environ.get(
    "QF_EQ_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "equities"))


def universe() -> dict:
    with open(os.path.join(EQ_DATA_DIR, "universe.json")) as f:
        return json.load(f)


def available_symbols() -> list[str]:
    return sorted(
        f[:-len("_1d.csv.gz")] for f in os.listdir(EQ_DATA_DIR)
        if f.endswith("_1d.csv.gz"))


def load_symbol(symbol: str) -> pd.DataFrame:
    path = os.path.join(EQ_DATA_DIR, f"{symbol}_1d.csv.gz")
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).dt.normalize()
    df = df.drop_duplicates(subset="ts").set_index("ts").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


def load_panel(symbols: list[str] | None = None,
               field: str = "close") -> pd.DataFrame:
    """Wide panel of `field` (dates x symbols). Missing symbols are skipped;
    dates are the union of trading days across members (NaN before listing)."""
    syms = symbols if symbols is not None else available_symbols()
    cols = {}
    for s in syms:
        try:
            cols[s] = load_symbol(s)[field]
        except FileNotFoundError:
            continue
    panel = pd.DataFrame(cols).sort_index()
    # drop non-trading rows that are all-NaN
    return panel.dropna(how="all")
