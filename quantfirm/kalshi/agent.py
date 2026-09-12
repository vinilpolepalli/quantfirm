"""LangGraph desk agent for the 15-minute commodity book.

Trading decisions stay deterministic (``strategies.registry``). LangGraph
only orchestrates the loop: observe → risk → tick → persist. An LLM is
NOT in the order path — the firm's rule is that code, not a chat model,
places every buy/sell.

When Kalshi API keys land in the environment the same graph can:

  * paper / shadow (default, no key needed — public books)
  * demo IOC plumbing (``KALSHI_DEMO_KEY_ID`` + PEM)
  * live prod orders (``KALSHI_PROD_KEY_ID`` + PEM **and** ``--live``
    **and** no ``state/KILL_SWITCH_KALSHI``)

Drop the key as:

    export KALSHI_PROD_KEY_ID=...
    export KALSHI_PROD_PRIVATE_KEY="$(cat kalshi.pem)"   # or _PATH=
    python -m quantfirm.kalshi.cli agent --minutes 60 --strategy spot_lock
"""

from __future__ import annotations

import os
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .halt import KILL_SWITCH, kill_switch_tripped
from .paper import PaperEngine
from .universe import BANKROLL, PAPER_ASSETS


class DeskState(TypedDict, total=False):
    notes: list[str]
    halted: bool
    halt_reason: str
    cash: dict
    n_open: int
    strategy: str
    live: bool


def build_desk(engine: PaperEngine, live: bool = False):
    """Compile the observe → risk → tick → persist graph."""

    def observe(state: DeskState) -> dict[str, Any]:
        if kill_switch_tripped():
            return {"halted": True, "halt_reason": "KILL_SWITCH_KALSHI present"}
        if live and not engine.prod.can_trade:
            return {"halted": True, "halt_reason": "live requested but no prod API key"}
        return {
            "halted": False,
            "halt_reason": "",
            "strategy": state.get("strategy", ""),
            "live": live,
        }

    def risk(state: DeskState) -> dict[str, Any]:
        if state.get("halted"):
            return {}
        allowed = engine._entries_allowed()
        if not any(allowed.values()):
            return {"halted": True, "halt_reason": "daily loss stop"}
        return {}

    def tick(state: DeskState) -> dict[str, Any]:
        if state.get("halted"):
            return {"notes": [f"halted: {state.get('halt_reason')}"]}
        notes = engine.tick()
        return {
            "notes": notes,
            "cash": {k: round(float(v), 2) for k, v in engine.state.d["cash"].items()},
            "n_open": len(engine.state.open),
        }

    def persist(state: DeskState) -> dict[str, Any]:
        engine.state.save()
        try:
            from .runtime import write_desk_status
            write_desk_status()
        except Exception:
            pass
        return {}

    g = StateGraph(DeskState)
    g.add_node("observe", observe)
    g.add_node("risk", risk)
    g.add_node("tick", tick)
    g.add_node("persist", persist)
    g.add_edge(START, "observe")
    g.add_edge("observe", "risk")
    g.add_conditional_edges(
        "risk",
        lambda s: "halt" if s.get("halted") else "go",
        {"halt": END, "go": "tick"},
    )
    g.add_edge("tick", "persist")
    g.add_edge("persist", END)
    return g.compile()


def run_agent(engine: PaperEngine, minutes: float, poll_s: float = 2.0,
              live: bool = False, strategy: str = "favorite_blind"):
    import time
    from datetime import datetime, timezone

    graph = build_desk(engine, live=live)
    t_end = time.time() + minutes * 60
    n = 0
    print(f"langgraph desk: strategy={strategy} live={live} "
          f"demo={'ON' if engine.use_demo else 'off'} "
          f"prod_key={'yes' if engine.prod.can_trade else 'no'} "
          f"cash={engine.state.d['cash']}", flush=True)
    while time.time() < t_end:
        if kill_switch_tripped():
            print("KILL_SWITCH_KALSHI — exiting", flush=True)
            break
        t0 = time.time()
        try:
            out = graph.invoke({
                "notes": [], "halted": False, "strategy": strategy, "live": live,
            })
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for note in out.get("notes") or []:
                print(f"[{ts}] {note}", flush=True)
            if out.get("halted") and out.get("halt_reason"):
                print(f"[{ts}] halt: {out['halt_reason']}", flush=True)
        except Exception as e:
            print(f"tick error: {e}", flush=True)
        n += 1
        if n % 30 == 0:
            engine.state.save()
        time.sleep(max(0.0, poll_s - (time.time() - t0)))
    engine.state.save()
    print(f"langgraph desk done: cash={engine.state.d['cash']} "
          f"realized={engine.state.d['realized']} open={len(engine.state.open)}",
          flush=True)


def paper_bankroll() -> float:
    return BANKROLL
