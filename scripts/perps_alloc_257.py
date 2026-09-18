#!/usr/bin/env python3
"""Should the $257 leave the incentive book for Kalshi perps (or 'just perps')?

This is a SCREEN, not a tournament and not an order. It recomputes the
numbers a session is tempted to inherit, then writes
``research/kalshi_perps/alloc_257.json``. It does not append to the trial
registry. Dumping internet strategies into that registry is how this desk
makes itself unable to validate the next real idea.

    python3 scripts/perps_alloc_257.py              # state + saved backtests
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

INCENTIVE_STATE = os.path.join(REPO, "state", "kalshi_incentive_paper.json")
GRANULARITY = os.path.join(REPO, "research", "kalshi_perps", "granularity.json")
OUT = os.path.join(REPO, "research", "kalshi_perps", "alloc_257.json")
CAPITAL = 257.0
# 2026-09-16 board identity (research/kalshi_incentives.md): $106,033/day
# paid against $17,067,304 resting. Not re-scraped here — that scrape is
# how the first four wrong numbers were born. The identity is the bound.
BOARD_PAID_PER_DAY = 106033.0
BOARD_RESTING = 17067304.0
PERPS_BASE_BANKROLL = 250.0

# Internet / "just perps" names mapped onto families this desk already killed.
# The point is not completeness. The point is that a catalog is not a pipeline.
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
     "HL geoblocks US; Jupiter is unregulated 1.1–250x vs JLP; this $257 is already on Kalshi"),
)


def parse_ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def wall_clock_window(history: list, hours: float, now: dt.datetime) -> dict:
    """Dollars the log actually booked in the last ``hours`` of wall clock.

    This is not the paper book's gate. The gate divides by the *capped*
    ``interval_h`` sum and refuses the window when that span is too gappy.
    A human asking 'what did the last day look like?' wants the wall-clock
    sum. Both get reported so nobody mixes them.
    """
    cut = now - dt.timedelta(hours=hours)
    rows = [h for h in history if _safe_ts(h) is not None and _safe_ts(h) >= cut]
    earned = sum(float(h.get("earned") or 0.0) for h in rows)
    span = sum(float(h.get("interval_h") or 0.0) for h in rows)
    return {
        "hours": hours,
        "n_ticks": len(rows),
        "earned_usd": round(earned, 4),
        "capped_interval_h": round(span, 3),
        "wall_usd_per_day": round(earned / hours * 24.0, 4) if hours else None,
        "gate_usd_per_day": (round(earned / span * 24.0, 4)
                             if span >= hours * 0.5 else None),
    }


def _safe_ts(h: dict) -> dt.datetime | None:
    try:
        return parse_ts(h["t"])
    except (KeyError, TypeError, ValueError):
        return None


def incentive_screen(st: dict, now: dt.datetime | None = None) -> dict:
    hist = st.get("history") or []
    if not hist:
        return {"verdict": st.get("verdict", "INSUFFICIENT"), "reason": "no history"}
    last = parse_ts(hist[-1]["t"])
    now = now or last
    started = parse_ts(st["started"])
    run_h = (now - started).total_seconds() / 3600.0
    accrued = float(st.get("accrued") or 0.0)
    capital = float(st.get("capital") or CAPITAL)
    identity = BOARD_PAID_PER_DAY / BOARD_RESTING * capital
    return {
        "verdict": st.get("verdict"),
        "verdict_reason": st.get("verdict_reason"),
        "capital": capital,
        "started": st["started"],
        "last_tick": hist[-1]["t"],
        "run_hours": round(run_h, 2),
        "ticks": st.get("ticks"),
        "accrued_usd": accrued,
        "since_inception_usd_per_day": round(accrued / run_h * 24.0, 4) if run_h else None,
        "board_identity_usd_per_day": round(identity, 4),
        "windows": {f"{int(h)}h": wall_clock_window(hist, h, now) for h in (6, 12, 24, 48)},
        "note": ("since-inception and the 48h window are early-tick over-reads; "
                 "trust the 12–24h wall-clock windows and the board identity"),
    }


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


def allocation_table(inc: dict, perps: dict) -> list[dict]:
    """What $257 does in each place. Dollars only, no annualised fantasy on the LIP."""
    w24 = inc["windows"]["24h"]
    w12 = inc["windows"]["12h"]
    return [
        {
            "place": "kalshi_predictions_idle",
            "usd_per_day": 0.0,
            "usd_per_year": 0.0,
            "typical_dd_usd": 0.0,
            "what_it_is": "cash sitting where it is now, earning no 3.25% (that yield is margin-only)",
        },
        {
            "place": "kalshi_margin_idle",
            "usd_per_day": round(0.0325 * CAPITAL / 365.0, 4),
            "usd_per_year": round(0.0325 * CAPITAL, 2),
            "typical_dd_usd": 0.0,
            "what_it_is": "transfer to perps margin and hold cash; ~3.25% APY if the $250 avg-balance rule is met",
        },
        {
            "place": "incentive_board_identity",
            "usd_per_day": inc["board_identity_usd_per_day"],
            "usd_per_year": None,
            "typical_dd_usd": 125.0,
            "what_it_is": ("accounting identity from 2026-09-16: $106k/day pot / $17.1M resting "
                           f"= {inc['board_identity_usd_per_day']}/day on ${inc['capital']:.0f}. "
                           "Not a promise Kalshi credits. Worst-case fill math is about -$125. "
                           "Do not annualise."),
        },
        {
            "place": "incentive_last_24h_wall",
            "usd_per_day": w24["wall_usd_per_day"],
            "usd_per_year": None,
            "typical_dd_usd": 125.0,
            "what_it_is": (f"paper book logged ${w24['earned_usd']} in the last 24h of wall clock. "
                           "Uncredited estimate. Do not annualise."),
        },
        {
            "place": "incentive_last_12h_wall",
            "usd_per_day": w12["wall_usd_per_day"],
            "usd_per_year": None,
            "typical_dd_usd": 125.0,
            "what_it_is": "more recent, closer to the board identity, still decaying, still uncredited",
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
    classes = {}
    for r in tradable:
        classes.setdefault(r.get("asset_class") or "?", []).append(r["ticker"])
    non_crypto = sorted(t for t, names in classes.items() if t not in ("crypto",) for t in [t])
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


def verdict(inc: dict, markets: dict | None, funding: dict | None) -> dict:
    """The only output that matters. Everything else is supporting arithmetic."""
    w24 = inc["windows"]["24h"]["wall_usd_per_day"]
    identity = inc["board_identity_usd_per_day"]
    perps_day = 0.1016 * CAPITAL / 365.0
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
        "move_the_257_to_perps": "NO",
        "dump_internet_strats_into_the_registry": "NO",
        "restart_the_halted_perps_desk": "NO",
        "register_a_funding_overlay_today": "NO",
        "why": (
            f"The $257 is in the predictions account, reserved for the LIP, still "
            f"INSUFFICIENT ({inc['run_hours']}h of 48h). Last-24h wall-clock paper "
            f"accrual is ${w24}/day against a board identity of ${identity}/day. "
            f"The deployable perps posture at this size is gated beta at about "
            f"${perps_day:.2f}/day with a ~$24 drawdown, and that desk is owner-halted "
            f"after two paper days. A catalog of internet perps strategies is the "
            f"set this desk already killed; more trials raise the deflated-Sharpe "
            f"bar. BTC Kalshi funding is still live on a 90-interval window"
            f"{btc_bit}, which is the one named opening — watch it, do not "
            f"register it on three months of one name. Jupiter/Hyperliquid are "
            f"the wrong venue for this account. Copper/US500/WTI {listings}."
        ),
        "what_would_change_this": [
            "incentive gate prints GO on a trailing 24h that is not still falling, then a $40 canary — still not the full $257",
            "incentive gate prints NO and stays there: then the $257 is free, and perps is still only a beta bet after the §7 paper gate",
            "a non-crypto listing (copper, US500, WTI) — the missing diversifier",
            "Kalshi-native BTC funding history long enough to pre-register a cost overlay against the existing crowding-gauge miss",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="hit Kalshi public perps endpoints for funding and listings")
    ap.add_argument("--state", default=INCENTIVE_STATE)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    with open(args.state) as fh:
        st = json.load(fh)
    with open(GRANULARITY) as fh:
        gran = json.load(fh)
    inc = incentive_screen(st)
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
        "verdict": verdict(inc, markets, funding),
        "incentive": inc,
        "perps_at_257": perps,
        "allocation": allocation_table(inc, perps),
        "already_killed": [
            {"name": a, "family": b, "why": c} for a, b, c in ALREADY_KILLED
        ],
        "plumbing": {
            "predictions_vs_margin": "separate accounts; liquidation on perps cannot touch predictions",
            "to_use_257_on_perps": "owner applies for margin, completes the tutorial, transfers from predictions",
            "kill_switch_perps": True,
            "incentive_armed": False,
            "perps_status": "HALTED, shadow, live=false",
        },
        "funding": funding,
        "markets": markets,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=1)
        f.write("\n")

    v = payload["verdict"]
    print(f"move $257 to perps: {v['move_the_257_to_perps']}")
    print(f"dump internet strats: {v['dump_internet_strats_into_the_registry']}")
    print(f"restart perps desk: {v['restart_the_halted_perps_desk']}")
    print(f"register funding overlay: {v['register_a_funding_overlay_today']}")
    print()
    print(v["why"])
    print()
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
