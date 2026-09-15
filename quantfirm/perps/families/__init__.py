"""Strategy families contributed by designer agents — one module per family.

Each module registers its strategies with ``quantfirm.perps.strategies.register``
and may declare a ``TRIALS`` dict in the tournament's format::

    TRIALS = {"my_family": {"params": {...fixed...}, "grid": {"param": [v1, v2]}}}

``load_all()`` imports every module here so the registry and the tournament
see them. A module that fails to import is reported, not fatal: one broken
family must not take the desk down.
"""

from __future__ import annotations

import importlib
import pkgutil
import traceback

LOAD_ERRORS: dict[str, str] = {}


def load_all() -> dict:
    trials: dict = {}
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_"):
            continue
        try:
            m = importlib.import_module(f"{__name__}.{mod.name}")
        except Exception:  # noqa: BLE001 — isolate a broken family
            LOAD_ERRORS[mod.name] = traceback.format_exc(limit=3)
            continue
        for k, v in (getattr(m, "TRIALS", None) or {}).items():
            trials[k] = v
    return trials
