#!/usr/bin/env python3
"""$257 on the Kalshi perps desk — economics and the already-killed catalog.

Owner killed the incentive book 2026-09-18 and will move this capital to
perps margin themselves after paper has a reading. This screen does not
transfer money, does not set live:true, and does not append to the trial
registry.

    python3 scripts/perps_alloc_257.py              # saved backtests
    python3 scripts/perps_alloc_257.py --live       # plus Kalshi public APIs
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
if os.path.join(REPO, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "scripts"))

GRANULARITY = os.path.join(REPO, "research", "kalshi_perps", "granularity.json")
OUT = os.path.join(REPO, "research", "kalshi_perps", "alloc_257.json")
KILL = os.path.join(REPO, "state", "KILL_SWITCH_PERPS")
CAPITAL = 257.0
PERPS_BASE_BANKROLL = 250.0
COLLATERAL_APY = 0.0325

ALREADY_KILLED = (
    ("grid / DCA / martingale bots", "intraday + leverage",
     "20 RT/month at 12 bps and 2x is a 115%/yr fee hurdle; recovery sizing is ruin"),
    ("funding farm / cash-and-carry", "funding carry",
     "Kalshi deadband zeroes most intervals; ETH still does; cross-venue needs an offshore short a US account cannot hold"),
    ("basis / funding-as-crowding", "basis_crowding",
     "OOS Sharpe 1.100 vs control 1.131, 0.996 correlated with the long book"),
    ("scalping / tape / market making", "kalshi_micro + MM",
     "no rebates below 0.5% of maker volume; largest native micro effect 6.8 bps vs 49 bps hurdle"),
    ("EMA / MACD / RSI / Ichimoku", "trend, ma_trend, tsmom, trend_v2",
     "every dress of slow trend lost to vol-targeted long-only"),
    ("weekend / turn-of-month / OpEx", "reversal_seasonality",
     "OOS 1.026 and 0.958; fees ate 24–63% of the gap"),
    ("crash / VIX / vol-spike filter", "crash_filter_beta",
     "OOS 1.011; the configs that 'work' were the ones that rode 2022"),
    ("dual / relative momentum", "dual_momentum",
     "OOS 1.047, real timing content, still trails the passive book"),
    ("raw cross-sectional alt momentum", "xsec_momentum + breadth",
     "sixteen names are 1.98 bets; raw sort is a beta sort; t-stat ≤ 0.52"),
    ("LLM / GPT signals, copy-trading", "Alpha Arena / FIRM rule",
     "4/6 frontier models lost 31–63% in 17 days; code decides, models do not"),
    ("Hyperliquid / Jupiter / offshore perps", "venue + US retail",
     "HL geoblocks US; Jupiter is unregulated 1.1–250x vs JLP; this $257 is a Kalshi transfer"),
)


def perps_row(granularity: dict, name: str, capital: float) -> dict:
    row = granularity["rows"][name][str(int(PERPS_BASE_BANKROLL))]
    return {
        "family": name,
        "measured_at_usd": PERPS_BASE_BANKROLL,
        "scaled_to_usd": capital,
        "net_sharpe": row["net_sharpe"],
        "cagr": row["cagr"],
        "max_drawdown": row["max_drawdown"],
        "expected_usd_per_year": round(row["cagr"] * capital, 2),
        "typical_dd_usd": round(abs(row["max_drawdown"]) * capital, 2),
        "expected_usd_per_day": round(row["cagr"] * capital / 365.0, 4),
        "window": granularity["window"],
    }


def allocation_table(perps: dict) -> list[dict]:
    return [
        {
            "place": "kalshi_margin_idle",
            "usd_per_day": round(COLLATERAL_APY * CAPITAL / 365.0, 4),
            "usd_per_year": round(COLLATERAL_APY * CAPITAL, 2),
            "typical_dd_usd": 0.0,
            "what_it_is": "cash on perps margin; ~3.25% APY if the $250 avg-balance rule is met",
        },
        {
            "place": "perps_trend_gate_12pct",
            "usd_per_day": perps["trend_long_only@0.12"]["expected_usd_per_day"],
            "usd_per_year": perps["trend_long_only@0.12"]["expected_usd_per_year"],
            "typical_dd_usd": perps["trend_long_only@0.12"]["typical_dd_usd"],
            "what_it_is": "paper incumbent, proxy history 2018–2025, whole contracts, tier-0 taker. Beta with a gate, not alpha.",
        },
        {
            "place": "perps_vol_target_hold_12pct",
            "usd_per_day": perps["vol_target_hold@0.12"]["expected_usd_per_day"],
            "usd_per_year": perps["vol_target_hold@0.12"]["expected_usd_per_year"],
            "typical_dd_usd": perps["vol_target_hold@0.12"]["typical_dd_usd"],
            "what_it_is": "the control the campaign could not beat. Larger return, ~2x the drawdown, losing years in 2018 and 2022.",
        },
    ]


def live_funding() -> dict:
    import pandas as pd
    import perps_watch as W
    from quantfirm.perps.client import MarginClient
    from quantfirm.perps.specs import SPECS

    c = MarginClient("prod")
    out = {}
    for asset in ("btc", "eth", "gold", "silver"):
        spec = SPECS[asset]
        rows = c.funding_history(spec.ticker)
        if not rows:
            out[asset] = {"n": 0}
            continue
        df = pd.DataFrame(rows)
        df["funding_time"] = pd.to_datetime(df["funding_time"], utc=True)
        df["funding_rate"] = pd.to_numeric(df["funding_rate"])
        s = df.sort_values("funding_time").set_index("funding_time")["funding_rate"]
        windows = {str(n): W.summarise_funding(s, n, funding_per_day=spec.funding_per_day)
                   for n in (12, 30, 90, len(s))}
        last = [{"ts": t.isoformat(), "rate": float(r)} for t, r in s.tail(8).items()]
        est = c.funding_estimate(spec.ticker)
        out[asset] = {
            "ticker": spec.ticker,
            "n": int(len(s)),
            "first": s.index.min().isoformat(),
            "last": s.index.max().isoformat(),
            "funding_per_day": spec.funding_per_day,
            "windows": windows,
            "last_8": last,
            "estimate_now": est,
        }
    return out


def live_markets() -> dict:
    from quantfirm.perps.client import MarginClient, parse_market
    rows = [parse_market(m) for m in MarginClient("prod").markets()]
    tradable = [r for r in rows if r.get("bid") and r.get("ask")]
    classes: dict[str, list[str]] = {}
    for r in tradable:
        classes.setdefault(r.get("asset_class") or "?", []).append(r["ticker"])
    return {
        "n_listed": len(rows),
        "n_tradable": len(tradable),
        "by_class": {k: sorted(v) for k, v in classes.items()},
        "non_crypto_classes": sorted({r.get("asset_class") for r in tradable
                                      if r.get("asset_class") not in ("crypto", None)}),
        "inactive": [r["ticker"] for r in rows if not (r.get("bid") and r.get("ask"))],
        "copper_us500_wti_listed": any(
            "COPPER" in (r.get("ticker") or "") or "US500" in (r.get("ticker") or "")
            or "WTI" in (r.get("ticker") or "") or "OIL" in (r.get("ticker") or "")
            for r in rows),
    }


def verdict(markets: dict | None, funding: dict | None) -> dict:
    btc90 = None
    if funding and "btc" in funding and "windows" in funding["btc"]:
        btc90 = funding["btc"]["windows"]["90"]
    btc_bit = ""
    if btc90:
        btc_bit = f" ({btc90['annualised']:+.1%} a year paid by longs)"
    listings = ("are still unlisted"
                if not (markets or {}).get("copper_us500_wti_listed")
                else "NEED A REREAD")
    return {
        "incentive_desk": "DEAD",
        "owner_transfers_257_to_perps": "YES_AFTER_PAPER",
        "agent_moves_money": "NO",
        "lift_kill_switch_for_paper": "YES",
        "set_live_true": "NO",
        "dump_internet_strats_into_the_registry": "NO",
        "register_a_funding_overlay_today": "NO",
        "why": (
            "Owner asked to paper the measured books before transferring the "
            "$257. Kill switch is lifted for shadow/paper only; live stays "
            "false. Agents do not transfer. Gated beta at this size is about "
            f"${0.1016 * CAPITAL / 365.0:.2f}/day with a ~$24 drawdown. "
            "A catalog of internet perps strategies is the set this desk already "
            "killed; more trials raise the deflated-Sharpe bar. BTC Kalshi funding "
            f"is still live on a 90-interval window{btc_bit}. Copper/US500/WTI "
            f"{listings}."
        ),
        "what_is_next": [
            "paper the three measured books (incumbent / candidate / growth)",
            "owner transfers $257 after those books have a reading",
            "do not register a funding overlay on three months of one name",
        ],
    }


def _plumbing() -> dict:
    cfg: dict = {}
    cfg_path = os.path.join(REPO, "config", "perps.json")
    try:
        with open(cfg_path) as fh:
            cfg = json.load(fh)
    except (OSError, json.JSONDecodeError):
        pass
    status = cfg.get("status") or "UNKNOWN"
    live = bool(cfg.get("live"))
    return {
        "predictions_vs_margin": "separate accounts; owner transfers, agents do not",
        "kill_switch_perps": os.path.exists(KILL),
        "incentive_desk": "DEAD",
        "perps_status": f"{status}, shadow, live={str(live).lower()}",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="hit Kalshi public perps endpoints for funding and listings")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    with open(GRANULARITY) as fh:
        gran = json.load(fh)
    perps = {
        "trend_long_only@0.12": perps_row(gran, "trend_long_only@0.12", CAPITAL),
        "vol_target_hold@0.12": perps_row(gran, "vol_target_hold@0.12", CAPITAL),
        "vol_target_hold@0.08": perps_row(gran, "vol_target_hold@0.08", CAPITAL),
    }
    funding = live_funding() if args.live else None
    markets = live_markets() if args.live else None
    payload = {
        "ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "live": bool(args.live),
        "capital_usd": CAPITAL,
        "verdict": verdict(markets, funding),
        "perps_at_257": perps,
        "allocation": allocation_table(perps),
        "already_killed": [
            {"name": a, "family": b, "why": c} for a, b, c in ALREADY_KILLED
        ],
        "plumbing": _plumbing(),
        "funding": funding,
        "markets": markets,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=1)
        f.write("\n")

    v = payload["verdict"]
    print(f"incentive desk: {v['incentive_desk']}")
    print(f"owner transfers $257 to perps: {v['owner_transfers_257_to_perps']}")
    print(f"agent moves money: {v['agent_moves_money']}")
    print(f"lift kill switch for paper: {v['lift_kill_switch_for_paper']}")
    print(f"set live true: {v['set_live_true']}")
    print(f"dump internet strats: {v['dump_internet_strats_into_the_registry']}")
    print()
    print(v["why"])
    print()
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
