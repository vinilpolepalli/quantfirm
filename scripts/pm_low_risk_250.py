#!/usr/bin/env python3
"""$250 prediction-market arithmetic. No credentials, no orders.

Prints the sizing, fee, and variance tables behind
`research/pm_low_risk_250.md`. Re-run rather than quoting this file.

    python3 scripts/pm_low_risk_250.py
    python3 scripts/pm_low_risk_250.py --live

`--live` hits Kalshi public incentive endpoints and reprints today's LIP
board. It does not place quotes.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import os
import statistics
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from quantfirm.kalshi.fair import kelly_fraction, taker_fee  # noqa: E402

BANKROLL = 250.0
RUIN = 125.0
RISK_FRAC = 0.02          # firm per-trade ceiling: 2% of equity
APY = 0.0325              # Kalshi Help Center, 2026-03-17; variable
WHELAN_MAKER_MU = 0.026   # makers, contracts ≥50¢, through Apr 2025
WHELAN_MAKER_SD = 0.33
WHELAN_TAKER_MU = -0.3146
LIP_TARGET_DEFAULT = 1000
VOLUME_CAP_PER_CT = 0.005


def clip(price: float, bankroll: float = BANKROLL, risk_frac: float = RISK_FRAC) -> dict:
    """Largest integer lot whose worst-case loss (stake + taker fee) ≤ risk budget."""
    budget = bankroll * risk_frac
    if price <= 0 or price >= 1:
        raise ValueError("price must be inside (0, 1)")
    n = 0
    fee = 0.0
    while True:
        nxt = n + 1
        f = taker_fee(nxt, price)
        if nxt * price + f > budget + 1e-12:
            break
        n, fee = nxt, f
    stake = n * price
    max_loss = stake + fee
    win = n * (1.0 - price) - fee
    # p*win + (1-p)*(-max_loss) = 0  => p = max_loss / (win + max_loss)
    be = max_loss / (win + max_loss) if n else None
    return dict(price=price, n=n, stake=round(stake, 4), fee=fee,
                max_loss=round(max_loss, 4), win=round(win, 4),
                breakeven_hit=be, fee_pct_stake=(fee / stake if stake else None))


def n_for_mean_ci(mu: float, sd: float, z: float = 1.65) -> int:
    """Independent trials so P(sample mean > 0) ≈ Φ(z) under N(mu, sd/√n).

    Used to show that Whelan's +2.6% / 33% sd is not 'consistent' at $250:
    you cannot run hundreds of independent binaries at once.
    """
    if mu <= 0 or sd <= 0:
        return math.inf  # type: ignore[return-value]
    n = (z * sd / mu) ** 2
    return math.ceil(n)


def lip_collateral(target: float, yes_ref: float, no_ref: float) -> float:
    """Cash to rest `target` contracts on both sides at the given refs."""
    return target * (yes_ref + no_ref)


def apy_year(bankroll: float = BANKROLL, apy: float = APY) -> float:
    return bankroll * apy


def volume_cap(contracts: float) -> float:
    return contracts * VOLUME_CAP_PER_CT


def _get(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": "quantfirm-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_lip_board(horizon_h: float = 24.0) -> dict:
    """Public incentive-program board. Accounting identity, not a P&L forecast."""
    now = dt.datetime.now(dt.timezone.utc)
    horizon = now + dt.timedelta(hours=horizon_h)
    progs, cursor = [], ""
    while True:
        url = ("https://external-api.kalshi.com/trade-api/v2/incentive_programs"
               f"?status=active&limit=1000" + (f"&cursor={cursor}" if cursor else ""))
        d = _get(url)
        page = d.get("incentive_programs") or []
        progs += page
        cursor = d.get("next_cursor") or ""
        if not cursor or not page:
            break
    lip = [p for p in progs
           if p.get("incentive_type") == "liquidity" and _ts(p["end_date"]) > now]
    vol = [p for p in progs
           if p.get("incentive_type") == "volume" and _ts(p["end_date"]) > now]
    pool = 0.0
    targets, rewards, durs = [], [], []
    for p in lip:
        d = (_ts(p["end_date"]) - _ts(p["start_date"])).total_seconds() / 3600.0
        ov = max(0.0, (min(_ts(p["end_date"]), horizon)
                       - max(_ts(p["start_date"]), now)).total_seconds() / 3600.0)
        reward = p["period_reward"] / 10000.0
        if d > 0:
            pool += reward * (ov / d)
        durs.append(d)
        rewards.append(reward)
        try:
            targets.append(float(p.get("target_size_fp") or 0))
        except (TypeError, ValueError):
            pass
    tc = collections.Counter(int(t) for t in targets if t > 0)
    cheap = sum(1 for t in targets if lip_collateral(t, 0.01, 0.01) <= BANKROLL)
    atm = sum(1 for t in targets if lip_collateral(t, 0.50, 0.50) <= BANKROLL)
    return dict(
        asof=now.isoformat(),
        n_programs=len(progs),
        n_lip=len(lip),
        n_volume=len(vol),
        pool_24h=pool,
        target_p50=statistics.median(targets) if targets else None,
        target_min=min(targets) if targets else None,
        target_max=max(targets) if targets else None,
        target_counts=dict(tc.most_common(8)),
        reward_p50=statistics.median(rewards) if rewards else None,
        duration_h_p50=statistics.median(durs) if durs else None,
        n_qualify_1c=cheap,
        n_qualify_50c=atm,
    )


def print_tables(live: dict | None = None) -> None:
    print(f"bankroll ${BANKROLL:.0f}  ruin ${RUIN:.0f}  per-trade cap {RISK_FRAC:.0%}"
          f" = ${BANKROLL * RISK_FRAC:.2f}")
    print(f"Kalshi idle APY {APY:.2%} → ${apy_year():.2f}/year"
          f" = ${apy_year()/365:.3f}/day  (Help Center 2026-03-17, variable)")
    print()
    print("taker clips at the 2% loss cap (cent-ceil fee)")
    print(f"{'px':>6} {'n':>4} {'stake':>7} {'fee':>6} {'lose':>7} {'win':>7} {'be hit':>8} {'fee/st':>7}")
    for px in (0.10, 0.20, 0.40, 0.50, 0.60, 0.75, 0.88, 0.90, 0.94, 0.97):
        c = clip(px)
        be = f"{c['breakeven_hit']*100:5.1f}%" if c["breakeven_hit"] else "   n/a"
        fps = f"{c['fee_pct_stake']*100:5.1f}%" if c["fee_pct_stake"] else "   n/a"
        print(f"{px:6.2f} {c['n']:4d} {c['stake']:7.2f} {c['fee']:6.2f} "
              f"{c['max_loss']:7.2f} {c['win']:7.2f} {be:>8} {fps:>7}")

    print()
    print("Whelan 2026 (Kalshi, through Apr 2025, 313k contracts):")
    print(f"  makers ≥50¢  mean {WHELAN_MAKER_MU:+.1%}  sd {WHELAN_MAKER_SD:.0%}")
    print(f"  takers all    mean {WHELAN_TAKER_MU:+.1%}")
    print(f"  independent fills so P(mean>0)≈95%: n≥{n_for_mean_ci(WHELAN_MAKER_MU, WHELAN_MAKER_SD)}")
    print("  sample ended when Kalshi started charging maker fees — +2.6% is pre-fee.")
    q, a = 0.60, 0.50
    print(f"  quarter-Kelly on q={q:.2f} bought at {a:.2f}: "
          f"{0.25 * kelly_fraction(q, a):.2%} of bankroll = "
          f"${0.25 * kelly_fraction(q, a) * BANKROLL:.2f}")

    print()
    print("LIP qualification at $250 (resting BOTH sides at Target Size):")
    for target, y, n in ((1000, 0.01, 0.01), (1000, 0.02, 0.02),
                         (300, 0.01, 0.01), (1000, 0.50, 0.50),
                         (1000, 0.25, 0.25)):
        cap = lip_collateral(target, y, n)
        ok = "yes" if cap <= BANKROLL else "NO"
        print(f"  target {target:4.0f} @ {y:.2f}/{n:.2f} locks ${cap:7.2f}  {ok}")
    print("  a snapshot pays nobody unless BOTH sides hold Target Size.")
    print("  rewards under $1.00 per program are not paid.")

    print()
    n_full = int(BANKROLL / 0.50)
    print(f"Volume incentive: cap {VOLUME_CAP_PER_CT:.3f}/contract.")
    print(f"  spend the whole ${BANKROLL:.0f} once at 50¢ → {n_full} contracts"
          f" → max reward ${volume_cap(n_full):.2f}.")
    print(f"  taker fee on that clip: ${taker_fee(n_full, 0.50):.2f}"
          f"  (fee > cap; churning for volume is negative EV).")

    print()
    print("15m 1% compounding pitch: 1.01^96/day is not on this venue.")
    print("  a 95¢ favorite pays 5¢; 1% of $250 is $2.50 → 50 contracts ≈ $47.50"
          " (19% of book, above the 2–8% live cap).")

    if live:
        print()
        print(f"LIVE LIP board  asof {live['asof']}")
        print(f"  active programs {live['n_programs']:,}  "
              f"liquidity {live['n_lip']:,}  volume {live['n_volume']}")
        print(f"  pool accruing next 24h  ${live['pool_24h']:,.0f}")
        print(f"  target p50 {live['target_p50']:.0f}  "
              f"min {live['target_min']:.0f}  max {live['target_max']:.0f}  "
              f"counts {live['target_counts']}")
        print(f"  reward p50 ${live['reward_p50']:.0f}  "
              f"duration p50 {live['duration_h_p50']:.1f}h")
        print(f"  $250 covers Target Size at 1c/1c on {live['n_qualify_1c']:,} programs")
        print(f"  $250 covers Target Size at 50c/50c on {live['n_qualify_50c']:,} programs")
        print("  board-average $/day needs resting capital, which this pass does not")
        print("  re-sum. 2026-09-16 identity: $106,033 / $17,067,304 = 0.62%/day")
        print("  → $1.55 on $250, only if we actually qualify.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="fetch the public LIP board (read-only)")
    ap.add_argument("--json", help="write the live board dict here")
    args = ap.parse_args(argv)
    live = fetch_lip_board() if args.live else None
    print_tables(live)
    if args.json and live:
        with open(args.json, "w") as fh:
            json.dump(live, fh, indent=2)
            fh.write("\n")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
