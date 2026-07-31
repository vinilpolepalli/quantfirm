"""Strategy registry. A strategy is a function (df, **params) -> pd.Series of
target positions in [0, 1], causally computed (row t may use data <= t only).

Register with @register("name"). Tournament agents add modules here; importing
the package auto-discovers every module in the directory.
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
    pkg = __name__
    for mod in pkgutil.iter_modules(__path__):
        if not mod.name.startswith("_") and mod.name != "base":
            importlib.import_module(f"{pkg}.{mod.name}")
    return REGISTRY
