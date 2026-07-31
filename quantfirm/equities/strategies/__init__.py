"""Equity strategy registry — same pattern as the crypto desk.

A strategy is a function (closes, **params) -> DataFrame of long-only target
weights (dates x symbols, row sums <= 1), causal (row t uses closes <= t).
Register with @register("name"); modules in this directory auto-load.
"""

from __future__ import annotations

import importlib
import pkgutil

REGISTRY: dict = {}


def register(name: str):
    def deco(fn):
        REGISTRY[name] = fn
        fn.strategy_name = name
        return fn
    return deco


def load_all() -> dict:
    for mod in pkgutil.iter_modules(__path__):
        if not mod.name.startswith("_"):
            importlib.import_module(f"{__name__}.{mod.name}")
    return REGISTRY
