"""LangGraph desk agent for the perps book.

Same shape as the 15-minute desk (quantfirm/kalshi/agent.py): the graph only
sequences observe → reconcile → risk → tick → persist. Every buy/sell is made
by ``paper.PaperEngine`` from the registered strategy; no language model is
in the order path (see docs/KALSHI_PERPS.md §4 for why that is the rule and
not a preference).

Cadence: the strategy is daily, so one tick per hour is plenty — the hourly
ticks exist to accrue funding, keep the server-side stops fresh, and catch a
drawdown kill between rebalances. ``--minutes`` bounds the session so a
supervisor can restart it (scripts/perps_loop.sh).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .paper import PaperEngine
from .risk import kill_switch_tripped


class DeskState(TypedDict, total=False):
    notes: list[str]
    halted: bool
    halt_reason: str
    equity: float


def build_desk(engine: PaperEngine):
    def observe(state: DeskState) -> dict[str, Any]:
        if kill_switch_tripped():
            return {"halted": True, "halt_reason": "KILL_SWITCH_PERPS present"}
        if engine.adapter == "live" and not engine.client.can_trade:
            return {"halted": True, "halt_reason": "live requested but no prod API key"}
        return {"halted": False, "halt_reason": ""}

    def risk(state: DeskState) -> dict[str, Any]:
        if state.get("halted"):
            return {}
        if engine.book.halted and engine.book.halted != "kill_switch":
            return {"halted": True, "halt_reason": engine.book.halted}
        return {}

    def tick(state: DeskState) -> dict[str, Any]:
        if state.get("halted"):
            return {"notes": [f"halted: {state.get('halt_reason')}"]}
        notes = engine.tick()
        return {"notes": notes, "equity": engine.equity()}

    def persist(state: DeskState) -> dict[str, Any]:
        engine.save()
        return {}

    g = StateGraph(DeskState)
    g.add_node("observe", observe)
    g.add_node("risk", risk)
    g.add_node("tick", tick)
    g.add_node("persist", persist)
    g.add_edge(START, "observe")
    g.add_edge("observe", "risk")
    g.add_conditional_edges("risk", lambda s: "halt" if s.get("halted") else "go", {"halt": END, "go": "tick"})
    g.add_edge("tick", "persist")
    g.add_edge("persist", END)
    return g.compile()


def run_agent(engine: PaperEngine, minutes: float, poll_s: float = 3600.0) -> None:
    graph = build_desk(engine)
    t_end = time.time() + minutes * 60
    print(f"perps desk: adapter={engine.adapter} strategy={engine.strategy_name} "
          f"universe={engine.universe} key={'yes' if engine.client.can_trade else 'no'} "
          f"equity={engine.equity():.2f}", flush=True)
    while True:
        t0 = time.time()
        try:
            out = graph.invoke({"notes": [], "halted": False})
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            for note in out.get("notes") or []:
                print(f"[{ts}] {note}", flush=True)
            if out.get("halted") and out.get("halt_reason"):
                print(f"[{ts}] halt: {out['halt_reason']}", flush=True)
                break
        except Exception as e:  # noqa: BLE001 — a tick error must not kill the loop
            print(f"tick error: {e}", flush=True)
        if time.time() + poll_s >= t_end:
            break
        time.sleep(max(0.0, poll_s - (time.time() - t0)))
    engine.save()
    print(f"perps desk done: equity={engine.equity():.2f} positions={list(engine.book.positions)}", flush=True)
