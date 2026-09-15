"""CLI for the perps desk — humans, CI and agents use the same entrypoints.

    python -m quantfirm.perps.cli markets                # live contract table (no key)
    python -m quantfirm.perps.cli funding --asset btc    # Kalshi funding history summary
    python -m quantfirm.perps.cli update-data            # refresh data/perps/*.csv.gz
    python -m quantfirm.perps.cli backtest --strategy trend_long_only --split dev
    python -m quantfirm.perps.cli walkforward --strategy tsmom --grid '{"lookbacks": [[63,126,252],[126,252]]}'
    python -m quantfirm.perps.cli tournament             # the pre-registered run (dev only)
    python -m quantfirm.perps.cli holdout --strategy X --i-am-the-judge   # ONCE per strategy
    python -m quantfirm.perps.cli paper --minutes 5      # shadow tick(s) on the live book
    python -m quantfirm.perps.cli agent --minutes 110 --adapter shadow
    python -m quantfirm.perps.cli status

Research commands only ever read the DEV split unless you are the judge.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from . import data as D
from . import specs as SPECS_MOD
from .backtest import BacktestConfig, public, run_strategy, stress, walk_forward
from .client import MarginClient, parse_market
from .risk import PROFILES, kill_switch_tripped
from .specs import RESEARCH_UNIVERSE, SPECS, cost_by_name
from .strategies import REGISTRY, load_all

load_all()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESEARCH = os.path.join(ROOT, "research", "kalshi_perps")


def _out(obj) -> None:
    print(json.dumps(obj, indent=1, default=str))


def _resolve_universe(spec):
    """A comma list, or the name of a universe constant in specs (TRADABLE_UNIVERSE)."""
    if not spec:
        return tuple(RESEARCH_UNIVERSE)
    named = getattr(SPECS_MOD, spec.upper(), None)
    return tuple(named) if named else tuple(x for x in spec.split(",") if x)


def _cfg(a) -> BacktestConfig:
    # "auto" scales the band with the universe; a fixed 0.03 freezes any book
    # of seven or more names, whose weight step is smaller than the band
    band = a.band if a.band == "auto" else float(a.band)
    n_assets = len(_resolve_universe(getattr(a, "universe", None)) or ())
    return BacktestConfig(cost=cost_by_name(a.cost), funding=a.funding,
                          rebalance_every=a.every, rebalance_band=band,
                          min_assets=1 if band == "auto" or n_assets > 4 else None)


def _params(a) -> dict:
    p = json.loads(a.params or "{}")
    # JSON lists → tuples for hashable strategy params
    for k, v in list(p.items()):
        if isinstance(v, list):
            p[k] = tuple(tuple(x) if isinstance(x, list) else x for x in v)
    return p


def cmd_markets(a):
    c = MarginClient("prod")
    rows = [parse_market(m) for m in c.markets()]
    rows.sort(key=lambda r: -(r["vol24h_usd"] or 0))
    print(f"{'ticker':<14}{'class':<8}{'status':<9}{'bid':>10}{'ask':>10}{'spr bps':>9}{'lev@1k':>8}{'OI $':>13}{'24h $':>14}")
    for r in rows:
        spr = (r["ask"] - r["bid"]) / ((r["ask"] + r["bid"]) / 2) * 1e4 if r["bid"] and r["ask"] else float("nan")
        print(f"{r['ticker']:<14}{r['asset_class']:<8}{r['status']:<9}{r['bid'] or 0:>10.4f}{r['ask'] or 0:>10.4f}"
              f"{spr:>9.2f}{r['leverage_1k'] or 0:>8.2f}{r['oi_usd'] or 0:>13,.0f}{r['vol24h_usd'] or 0:>14,.0f}")


def cmd_funding(a):
    import pandas as pd
    c = MarginClient("prod")
    tick = SPECS[a.asset].ticker
    rows = c.funding_history(tick)
    if not rows:
        _out({"ticker": tick, "n": 0})
        return
    r = pd.Series([float(x["funding_rate"]) for x in rows])
    per_day = SPECS[a.asset].funding_per_day
    est = c.funding_estimate(tick)
    _out({"ticker": tick, "n": len(rows), "first": min(x["funding_time"] for x in rows),
          "mean_per_interval": round(float(r.mean()), 7),
          "annualized_pct": round(float(r.mean()) * per_day * 365 * 100, 2),
          "pct_zero": round(float((r == 0).mean()), 3), "min": float(r.min()), "max": float(r.max()),
          "estimate_now": est})


def cmd_update_data(a):
    meta = D.update_all(tuple(a.assets.split(",")) if a.assets else None)
    if a.aux:
        meta["aux"] = D.update_aux()
    _out(meta)


def cmd_backtest(a):
    if a.split == "holdout" and not a.i_am_the_judge:
        sys.exit("holdout is sealed: use `holdout --i-am-the-judge`")
    panel = D.load_panel(_resolve_universe(a.universe))
    start, end = None, None
    if a.split == "dev":
        end = D.HOLDOUT_START
    elif a.split == "holdout":
        start = D.HOLDOUT_START
    if a.start:
        start = a.start
    r = run_strategy(panel, REGISTRY[a.strategy], _params(a), _cfg(a), start=start, end=end)
    out = public(r)
    from .registry import record
    out["registry_key"] = record(a.strategy, _params(a), a.split, out, source="cli:backtest", note=a.note or "")
    if a.stress:
        out["stress"] = stress(panel, REGISTRY[a.strategy], _params(a), _cfg(a), start, end)
    if a.yearly:
        ret = r["_series"]["returns"]
        out["by_year"] = {str(y): round(float((1 + g).prod() - 1), 4) for y, g in ret.groupby(ret.index.year)}
    _out(out)


def cmd_walkforward(a):
    panel = D.load_panel(_resolve_universe(a.universe))
    grid = json.loads(a.grid or "{}")
    for k, v in grid.items():
        grid[k] = [tuple(tuple(y) if isinstance(y, list) else y for y in x) if isinstance(x, list) else x for x in v]
    wf = walk_forward(panel, REGISTRY[a.strategy], _params(a), _cfg(a), grid=grid or None,
                      n_folds=a.folds, warmup_days=a.warmup, dev_start=a.start or "2016-06-01")
    from .registry import record
    for f in wf["folds"]:
        record(a.strategy, f["params"], "dev", {"net_sharpe": f["oos_sharpe"], "max_drawdown": f["max_drawdown"],
                                                  "ann_turnover": f["turnover"], "start": f["start"], "end": f["end"]},
               source="cli:walkforward", note=a.note or "")
    _out({k: v for k, v in wf.items() if not k.startswith("_")})


def cmd_tournament(a):
    from .tournament import run_tournament, DEV_START, WARMUP_DAYS, N_FOLDS
    out = run_tournament(universe=_resolve_universe(a.universe), cfg=_cfg(a),
                         dev_start=a.dev_start or DEV_START,
                         warmup_days=a.warmup or WARMUP_DAYS, n_folds=a.folds or N_FOLDS,
                         families=tuple(a.families.split(",")) if a.families else None,
                         tag=a.tag, version=a.version,
                         reference_universe=_resolve_universe(a.reference_universe))
    _out({"ranked": out["ranked"], "pbo": out["pbo"],
          "reference": (out.get("reference") or {}).get("walk_forward", {}).get("oos_sharpe_concat"),
          "verdicts": {k: v["gates"] for k, v in out["verdicts"].items()}})


def cmd_holdout(a):
    """The judge opens the sealed window once per strategy and records it."""
    if not a.i_am_the_judge:
        sys.exit("refusing: pass --i-am-the-judge (this burns the holdout for that strategy)")
    os.makedirs(RESEARCH, exist_ok=True)
    marker = os.path.join(RESEARCH, f"holdout_{a.strategy}.json")
    if os.path.exists(marker) and not a.force:
        sys.exit(f"holdout already opened for {a.strategy}: {marker} (re-running is a new trial; --force to record it as one)")
    panel = D.load_panel(_resolve_universe(a.universe))
    cfg = _cfg(a)
    params = _params(a)
    r = run_strategy(panel, REGISTRY[a.strategy], params, cfg, start=D.HOLDOUT_START, end=None)
    dev = run_strategy(panel, REGISTRY[a.strategy], params, cfg, start="2018-01-01", end=D.HOLDOUT_START)
    bench = run_strategy(panel, REGISTRY["vol_target_hold"], {"target_vol": params.get("target_vol", 0.12)}, cfg,
                         start=D.HOLDOUT_START, end=None)
    ret = r["_series"]["returns"]
    out = {"strategy": a.strategy, "params": params, "opened_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "holdout_start": D.HOLDOUT_START, "n_prior_openings": (json.load(open(marker)).get("n_prior_openings", 0) + 1) if os.path.exists(marker) else 0,
           "holdout": public(r), "dev_2018_on": public(dev), "benchmark_holdout": public(bench),
           "retention_sharpe": (round(r["net_sharpe"] / dev["net_sharpe"], 3) if r["net_sharpe"] is not None and dev["net_sharpe"] else None),
           "by_month": {str(m.date()): round(float(v), 4) for m, v in ((1 + ret).resample("ME").prod() - 1).items()}}
    with open(marker, "w") as f:
        json.dump(out, f, indent=1, default=str)
    _out(out)


def cmd_paper(a):
    from .paper import PaperEngine, write_status
    cfg = json.load(open(os.path.join(ROOT, "config", "perps.json"))) if os.path.exists(os.path.join(ROOT, "config", "perps.json")) else {}
    books = cfg.get("books") or {}
    bk = books.get(a.book, {}) if a.book else {}
    uni = a.universe or bk.get("universe") or cfg.get("universe", RESEARCH_UNIVERSE)
    eng = PaperEngine(a.strategy or bk.get("strategy") or cfg.get("strategy", "trend_long_only"),
                      _params(a) or bk.get("params") or cfg.get("params", {}),
                      PROFILES[a.profile or bk.get("profile") or cfg.get("profile", "balanced")],
                      adapter=a.adapter,
                      bankroll=a.bankroll or bk.get("bankroll_usd") or cfg.get("bankroll_usd", 250.0),
                      universe=tuple(uni if isinstance(uni, (list, tuple)) else uni.split(",")),
                      book=a.book, band=bk.get("rebalance_band", cfg.get("rebalance_band", 0.03)),
                      rebalance_every_days=bk.get("rebalance_every_days",
                                                  cfg.get("rebalance_every_days", 7)),
                      log=print if a.verbose else None)
    if a.adapter == "live":
        _refuse_unless_live_armed(cfg)
    t_end = dt.datetime.now().timestamp() + a.minutes * 60
    while True:
        for n in eng.tick():
            print(n, flush=True)
        if dt.datetime.now().timestamp() + a.poll >= t_end:
            break
        import time
        time.sleep(a.poll)
    _out(write_status(eng))


def cmd_agent(a):
    from .agent import run_agent
    from .paper import PaperEngine
    cfg = json.load(open(os.path.join(ROOT, "config", "perps.json"))) if os.path.exists(os.path.join(ROOT, "config", "perps.json")) else {}
    if a.adapter == "live":
        _refuse_unless_live_armed(cfg)
    books = cfg.get("books") or {}
    bk = books.get(a.book, {}) if a.book else {}
    uni = a.universe or bk.get("universe") or cfg.get("universe", RESEARCH_UNIVERSE)
    eng = PaperEngine(a.strategy or bk.get("strategy") or cfg.get("strategy", "trend_long_only"),
                      _params(a) or bk.get("params") or cfg.get("params", {}),
                      PROFILES[a.profile or bk.get("profile") or cfg.get("profile", "balanced")],
                      adapter=a.adapter,
                      bankroll=a.bankroll or bk.get("bankroll_usd") or cfg.get("bankroll_usd", 250.0),
                      universe=tuple(uni if isinstance(uni, (list, tuple)) else uni.split(",")),
                      book=a.book, band=bk.get("rebalance_band", cfg.get("rebalance_band", 0.03)),
                      rebalance_every_days=bk.get("rebalance_every_days",
                                                  cfg.get("rebalance_every_days", 7)),
                      log=print if a.verbose else None)
    run_agent(eng, a.minutes, poll_s=a.poll)


def _refuse_unless_live_armed(cfg: dict) -> None:
    if not cfg.get("live"):
        sys.exit("refusing live: config/perps.json live=false")
    if os.environ.get("KALSHI_LIVE") not in ("1", "true"):
        sys.exit("refusing live: KALSHI_LIVE is not 1")
    if kill_switch_tripped():
        sys.exit("refusing live: state/KILL_SWITCH_PERPS present")


def cmd_robust(a):
    """Adversarial checks on one configuration (dev only)."""
    from . import robust as RB
    panel = D.load_panel(_resolve_universe(a.universe))
    out = RB.full_report(panel, REGISTRY[a.strategy], _params(a), _cfg(a), start=a.start or "2018-01-01",
                         end=D.HOLDOUT_START, benchmark=a.benchmark, n_boot=a.n_boot, n_null=a.n_null)
    os.makedirs(RESEARCH, exist_ok=True)
    path = os.path.join(RESEARCH, f"robust_{a.strategy}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1, default=str)
    out["_written"] = path
    _out(out)


def cmd_registry(a):
    from .registry import summary
    _out(summary())


def cmd_status(a):
    c = MarginClient("prod")
    st = c.exchange_status()
    out = {"exchange": st, "prod_key": c.can_trade, "kill_switch": kill_switch_tripped(),
           "data_dir": D.DATA_DIR}
    try:
        with open(os.path.join(D.DATA_DIR, "META.json")) as f:
            out["data_meta"] = json.load(f)
    except FileNotFoundError:
        out["data_meta"] = None
    p = os.path.join(ROOT, "state", "perps_desk_status.json")
    if os.path.exists(p):
        with open(p) as f:
            out["desk"] = json.load(f)
    if c.can_trade:
        try:
            out["balance"] = c.balance()
            out["positions"] = c.positions()
            out["risk"] = c.risk()
        except Exception as e:  # noqa: BLE001
            out["account_error"] = str(e)
    _out(out)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="quantfirm.perps.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, research=True):
        # default None, NOT the research four: an explicit flag has to be
        # distinguishable from "not given", or a book config could never
        # supply its own universe. _resolve_universe falls back to the
        # research four, so every existing command behaves as before.
        sp.add_argument("--universe", default=None)
        if research:
            sp.add_argument("--cost", default="taker_t0")
            sp.add_argument("--funding", default="kalshi", choices=["none", "kalshi", "proxy", "proxy_raw"])
            sp.add_argument("--every", type=int, default=7)
            sp.add_argument("--band", default=0.03, help="float, or 'auto' to scale with the universe")
            sp.add_argument("--params", default="{}")
            sp.add_argument("--note", default="")

    sub.add_parser("markets").set_defaults(fn=cmd_markets)
    sp = sub.add_parser("funding"); sp.add_argument("--asset", default="btc"); sp.set_defaults(fn=cmd_funding)
    sp = sub.add_parser("update-data"); sp.add_argument("--assets", default="")
    sp.add_argument("--aux", action="store_true"); sp.set_defaults(fn=cmd_update_data)
    sp = sub.add_parser("backtest"); common(sp)
    sp.add_argument("--strategy", required=True); sp.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    sp.add_argument("--start", default=None); sp.add_argument("--stress", action="store_true")
    sp.add_argument("--yearly", action="store_true"); sp.add_argument("--i-am-the-judge", action="store_true")
    sp.set_defaults(fn=cmd_backtest)
    sp = sub.add_parser("walkforward"); common(sp)
    sp.add_argument("--strategy", required=True); sp.add_argument("--grid", default="{}")
    sp.add_argument("--folds", type=int, default=6); sp.add_argument("--warmup", type=int, default=550)
    sp.add_argument("--start", default=None); sp.set_defaults(fn=cmd_walkforward)
    sp = sub.add_parser("tournament"); common(sp)
    sp.add_argument("--dev-start"); sp.add_argument("--warmup", type=int); sp.add_argument("--folds", type=int)
    sp.add_argument("--families", help="comma-separated subset of declared families")
    sp.add_argument("--tag", help="suffix for the output files, so one run never overwrites another")
    sp.add_argument("--version", help="tournament version string recorded in the output")
    sp.add_argument("--reference-universe",
                    help="a second yardstick: the benchmark on this universe over the same folds")
    sp.set_defaults(fn=cmd_tournament)
    sp = sub.add_parser("holdout"); common(sp)
    sp.add_argument("--strategy", required=True); sp.add_argument("--i-am-the-judge", action="store_true")
    sp.add_argument("--force", action="store_true"); sp.set_defaults(fn=cmd_holdout)
    for name, fn in (("paper", cmd_paper), ("agent", cmd_agent)):
        sp = sub.add_parser(name); common(sp, research=False)
        sp.add_argument("--strategy", default=None); sp.add_argument("--params", default="{}")
        sp.add_argument("--profile", default=None, choices=[None, *PROFILES])
        sp.add_argument("--adapter", default="shadow", choices=["shadow", "demo", "live"])
        sp.add_argument("--bankroll", type=float, default=None)
        sp.add_argument("--minutes", type=float, default=1.0)
        sp.add_argument("--poll", type=float, default=3600.0)
        sp.add_argument("--verbose", action="store_true")
        sp.add_argument("--book", default=None,
                        help="named book from config/perps.json books{}; omit for the incumbent")
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("robust"); common(sp)
    sp.add_argument("--strategy", required=True); sp.add_argument("--start", default=None)
    sp.add_argument("--benchmark", default="vol_target_hold"); sp.add_argument("--n-boot", type=int, default=2000)
    sp.add_argument("--n-null", type=int, default=200); sp.set_defaults(fn=cmd_robust)
    sub.add_parser("registry").set_defaults(fn=cmd_registry)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
