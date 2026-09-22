"""Run the pre-registered Polymarket → Kalshi copy trials. Paper only.

    python -m quantfirm.kalshi.copybacktest
    python -m quantfirm.kalshi.copybacktest paper-tick

Never places a Kalshi order and never places a Polymarket order.
The decision trial is ``honest_pnl_equal``. A positive print is not a
promotion: live stays behind the Kalshi kill switch.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict

from quantfirm.kalshi.copyfeed import (
    SELECT_DAYS,
    activity,
    candlesticks,
    closed_positions,
    gamma_event,
    leaderboard,
    load_books,
    orderbook_touch,
    _session,
)
from quantfirm.kalshi.copytrade import (
    CUTOFF_TS,
    LAG_S,
    LEAGUE_SERIES,
    TOP_K,
    TRIALS,
    Candle,
    build_market_index,
    coalesce,
    date_token_from_slug,
    is_prior_sport,
    league_of,
    map_trade,
    simulate,
    top_scores,
    weights_from_scores,
)
from quantfirm.kalshi.halt import kill_switch_tripped

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_PATH = os.path.join(ROOT, "research", "kalshi_copytrade.json")
STATE_PATH = os.path.join(ROOT, "state", "kalshi_copy_paper_state.json")

# Candidate pool, fixed before the P&L run. Not a search over wallets.
POOL = (("WEEK", "PNL", 20), ("WEEK", "VOL", 10), ("MONTH", "PNL", 15), ("ALL", "PNL", 10))


def _refuse_live(argv: list[str]) -> None:
    if any(a in ("--live", "--prod", "--arm") for a in argv):
        raise SystemExit("copytrade refuses live orders")
    if os.environ.get("KALSHI_LIVE") == "1":
        print("KALSHI_LIVE=1 is set. This process still does not send orders.", flush=True)


def _score_window(rows: list[dict], start: int, end: int, truncated: bool) -> dict | None:
    """Sports closed-position pnl and stake with timestamp in [start, end).

    A truncated pull that never reached ``start`` is ineligible (None):
    the visible tail is not the prior record.
    """
    if truncated:
        oldest = min((int(r.get("timestamp") or 0) for r in rows), default=end)
        if oldest >= start:
            return None
    pnl = 0.0
    vol = 0.0
    n = 0
    for row in rows:
        ts = int(row.get("timestamp") or 0)
        if ts < start or ts >= end:
            continue
        if not is_prior_sport(row.get("title") or ""):
            continue
        n += 1
        pnl += float(row.get("realizedPnl") or 0)
        vol += float(row.get("totalBought") or 0) * float(row.get("avgPrice") or 0)
    return {"pnl": pnl, "vol": vol, "n": n, "truncated": truncated}


def _names(boards: dict[tuple[str, str], list[dict]]) -> dict[str, str]:
    out = {}
    for rows in boards.values():
        for row in rows:
            w = (row.get("proxyWallet") or "").lower()
            if w:
                out[w] = row.get("userName") or w[:10]
    return out


def _week_order(boards) -> list[str]:
    rows = boards.get(("WEEK", "PNL")) or []
    return [(r.get("proxyWallet") or "").lower() for r in rows if r.get("proxyWallet")]


def _skip_reason(trade: dict, event: dict | None) -> str:
    slug = trade.get("eventSlug") or trade.get("slug") or ""
    if not date_token_from_slug(slug):
        return "no_game_date"
    if league_of(slug) not in LEAGUE_SERIES:
        return "league_not_on_kalshi"
    if event is None:
        return "no_gamma"
    markets = event.get("markets") or []
    gm = next((m for m in markets if m.get("slug") == trade.get("slug")), None)
    if gm is None:
        return "slug_missing"
    if (gm.get("sportsMarketType") or "").lower() != "moneyline":
        return "not_moneyline"
    return "no_kalshi_twin"


def _public(rep: dict) -> dict:
    out = {k: v for k, v in rep.items() if k != "closes"}
    closes = rep.get("closes") or []
    out["closes_head"] = closes[:12]
    out["closes_tail"] = closes[-12:]
    return out


def _run_trials(mapped: dict[str, list], candles, metas, prior, week: list[str]) -> list[dict]:
    reports = []
    for spec in TRIALS:
        if spec["biased"]:
            chosen = {w: float(TOP_K - i) for i, w in enumerate(week[:TOP_K])}
        elif spec["rank"] == "vol":
            chosen = top_scores({w: (prior.get(w) or {}).get("vol") for w in prior}, TOP_K)
        else:
            chosen = top_scores({w: (prior.get(w) or {}).get("pnl") for w in prior}, TOP_K)
        mode = "equal" if spec["weight"] == "equal" else "pnl"
        wts = weights_from_scores(chosen, mode)
        trades = [t for w in wts for t in mapped.get(w, []) if t.ts >= CUTOFF_TS]
        buckets = coalesce(trades)
        rep = simulate(
            buckets, candles, metas, wts,
            bankroll=spec["bankroll"],
            price_gate=spec["price_gate"],
            fade=spec["fade"],
            fill=spec["fill"],
        )
        rep["name"] = spec["name"]
        rep["biased"] = spec["biased"]
        rep["fade"] = spec["fade"]
        rep["fill"] = spec["fill"]
        rep["leaders"] = [
            {"wallet": w, "weight": round(wt, 4), "score": chosen.get(w)}
            for w, wt in sorted(wts.items(), key=lambda kv: -kv[1])
        ]
        rep["n_buckets"] = len(buckets)
        rep["n_trades"] = len(trades)
        reports.append(rep)
        print(
            f"{spec['name']}: pnl_mtm={rep['pnl_mtm']} settled={rep['pnl_settled']} "
            f"closes={rep['n_closes']} fills={rep['n_fills']} "
            f"open={rep['n_open']} t={rep['t_stat']} dd={rep['max_dd']}",
            flush=True,
        )
    return reports


def backtest() -> dict:
    session = _session()
    boards = {}
    wallets = []
    seen = set()
    for period, order, limit in POOL:
        rows = leaderboard(session, period, order, limit)
        boards[(period, order)] = rows
        print(f"leaderboard {period} {order} {len(rows)}", flush=True)
        for row in rows:
            w = (row.get("proxyWallet") or "").lower()
            if w and w not in seen:
                seen.add(w)
                wallets.append(w)
    names = _names(boards)
    start = CUTOFF_TS - SELECT_DAYS * 86400
    prior = {}
    for i, w in enumerate(wallets, 1):
        rows, truncated = closed_positions(session, w)
        scored = _score_window(rows, start, CUTOFF_TS, truncated)
        prior[w] = scored
        label = "ineligible" if scored is None else (
            f"pnl={scored['pnl']:.0f} vol={scored['vol']:.0f} n={scored['n']}")
        print(f"score {i}/{len(wallets)} {names.get(w, w[:8])} {label}", flush=True)

    week = _week_order(boards)
    need = set(week[:TOP_K])
    need.update(top_scores({w: (prior.get(w) or {}).get("pnl") for w in prior if prior.get(w)}, TOP_K))
    need.update(top_scores({w: (prior.get(w) or {}).get("vol") for w in prior if prior.get(w)}, TOP_K))
    need.discard("")
    print(f"fetching tapes for {len(need)} wallets", flush=True)

    tapes = {}
    for w in sorted(need):
        tapes[w] = activity(session, w, CUTOFF_TS)
        print(f"activity {names.get(w, w[:8])} {len(tapes[w])}", flush=True)

    now = int(time.time())
    markets, _fees = load_books(session, CUTOFF_TS - 3 * 86400, now + 5 * 86400)
    index = build_market_index(markets)
    by_ticker = {m.ticker: m for m in markets}
    print(f"kalshi indexed {len(markets)} contracts", flush=True)

    events: dict[str, dict | None] = {}
    mapped: dict[str, list] = defaultdict(list)
    reasons = defaultdict(float)
    examples = []
    n_considered = 0
    mapped_notional = 0.0
    for w, rows in tapes.items():
        for trade in rows:
            ts = int(trade.get("timestamp") or 0)
            if ts < CUTOFF_TS:
                continue
            n_considered += 1
            notional = float(trade.get("size") or 0) * float(trade.get("price") or 0)
            slug = trade.get("eventSlug") or ""
            if slug not in events and date_token_from_slug(slug) and league_of(slug) in LEAGUE_SERIES:
                events[slug] = gamma_event(session, slug)
            hit = map_trade(trade, events.get(slug), [], index=index)
            if hit is None:
                reason = _skip_reason(trade, events.get(slug) if slug in events else None)
                reasons[reason] += notional
                if len(examples) < 25 and reason in ("no_kalshi_twin", "not_moneyline", "league_not_on_kalshi"):
                    examples.append({
                        "reason": reason,
                        "title": trade.get("title"),
                        "slug": trade.get("slug"),
                        "notional": round(notional, 2),
                    })
                continue
            mapped[w].append(hit)
            mapped_notional += notional

    tickers = {t.ticker for rows in mapped.values() for t in rows}
    print(f"mapped tickers {len(tickers)}; fetching candles", flush=True)
    candles = {}
    metas = {}
    for i, ticker in enumerate(sorted(tickers), 1):
        km = by_ticker.get(ticker)
        if km is None:
            continue
        trades = [t for rows in mapped.values() for t in rows if t.ticker == ticker]
        start_ts = min(t.ts for t in trades) - 120
        end_ts = max(km.close_ts or now, max(t.ts for t in trades)) + 180
        try:
            candles[ticker] = candlesticks(session, km.series, ticker, start_ts, end_ts)
        except Exception as e:
            print(f"candles {ticker} failed {e}", flush=True)
            candles[ticker] = []
        metas[ticker] = (km.close_ts, km.result, km.fee_multiplier)
        if i % 10 == 0 or i == len(tickers):
            print(f"candles {i}/{len(tickers)} {ticker} n={len(candles[ticker])}", flush=True)

    reports = _run_trials(mapped, candles, metas, prior, week)
    decision = next(r for r in reports if r["name"] == "honest_pnl_equal")
    payload = {
        "asof": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "cutoff": "2026-09-15T00:00:00Z",
        "select_window_days": SELECT_DAYS,
        "decision_trial": "honest_pnl_equal",
        "live_orders": False,
        "kill_switch": kill_switch_tripped(),
        "pool": [list(p) for p in POOL],
        "n_wallets_scored": len(wallets),
        "n_trades_after_cutoff": n_considered,
        "mapped_notional": round(mapped_notional, 2),
        "unmapped_notional_by_reason": {k: round(v, 2) for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])},
        "unmapped_examples": examples,
        "leaders_scored": [
            {
                "wallet": w,
                "name": names.get(w),
                "prior": None if prior.get(w) is None else {
                    "pnl": round(prior[w]["pnl"], 2),
                    "vol": round(prior[w]["vol"], 2),
                    "n": prior[w]["n"],
                    "truncated": prior[w]["truncated"],
                },
            }
            for w in wallets
        ],
        "trials": [_public(r) for r in reports],
        "decision": _public(decision),
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"wrote {OUT_PATH}", flush=True)
    return payload


def _paper_leaders(prior_now: dict[str, dict | None]) -> dict[str, float]:
    scores = top_scores(
        {w: (row or {}).get("pnl") for w, row in prior_now.items() if row},
        TOP_K,
    )
    return weights_from_scores(scores, "equal")


def paper_tick() -> None:
    """Arm or advance the paper book. Fills at the current Kalshi touch. No orders."""
    _refuse_live(sys.argv)
    session = _session()
    now = int(time.time())
    state = None
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            state = json.load(f)
    if state is None:
        boards = {}
        wallets = []
        seen = set()
        for period, order, limit in POOL:
            rows = leaderboard(session, period, order, limit)
            boards[(period, order)] = rows
            for row in rows:
                w = (row.get("proxyWallet") or "").lower()
                if w and w not in seen:
                    seen.add(w)
                    wallets.append(w)
        names = _names(boards)
        start = now - SELECT_DAYS * 86400
        prior = {}
        for w in wallets:
            rows, truncated = closed_positions(session, w)
            prior[w] = _score_window(rows, start, now, truncated)
        wts = _paper_leaders(prior)
        state = {
            "version": 1,
            "live_orders": False,
            "bankroll": 250.0,
            "created": now,
            "cursor": now,
            "weights": wts,
            "names": {w: names.get(w, w[:10]) for w in wts},
            "scores": {w: None if prior.get(w) is None else round(prior[w]["pnl"], 2) for w in wts},
            "trades": [],
            "note": "Copies trades with timestamp after cursor only. Does not chase positions already open.",
        }
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        print(json.dumps({
            "paper": "armed",
            "leaders": state["names"],
            "weights": state["weights"],
            "cursor": now,
            "kill_switch": kill_switch_tripped(),
            "live_orders": False,
        }, indent=2), flush=True)
        return

    cursor = int(state["cursor"])
    weights = state["weights"]
    new_rows = []
    for w in weights:
        # Fresh tape. The backtest cache is a frozen research snapshot.
        for row in activity(session, w, cursor, use_cache=False):
            ts = int(row.get("timestamp") or 0)
            if ts <= cursor:
                continue
            row = dict(row)
            row["proxyWallet"] = w
            new_rows.append(row)
    new_rows.sort(key=lambda r: int(r.get("timestamp") or 0))
    if not new_rows:
        print(json.dumps({"paper": "idle", "cursor": cursor, "new_trades": 0,
                          "live_orders": False}, indent=2), flush=True)
        return

    markets, _fees = load_books(session, now - 2 * 86400, now + 5 * 86400)
    index = build_market_index(markets)
    by_ticker = {m.ticker: m for m in markets}
    events: dict[str, dict | None] = {}
    fresh = []
    for trade in new_rows:
        slug = trade.get("eventSlug") or ""
        if slug not in events and date_token_from_slug(slug) and league_of(slug) in LEAGUE_SERIES:
            events[slug] = gamma_event(session, slug)
        hit = map_trade(trade, events.get(slug), [], index=index)
        if hit is not None and hit.wallet in weights:
            fresh.append(hit)
    # Remember every copied clip and the touch we could actually lift, then
    # replay the whole paper book. A later tick must not reprice an old fill.
    stored = state.setdefault("mapped", [])
    quotes = state.setdefault("quotes", {})
    touched = {t.ticker for t in fresh}
    for ticker in touched:
        bid, ask = orderbook_touch(session, ticker)
        if bid is None or ask is None:
            continue
        quotes.setdefault(ticker, []).append({
            "end_ts": now, "bid": bid, "ask": ask,
        })
    for t in fresh:
        stored.append({
            "wallet": t.wallet, "ts": t.ts, "ticker": t.ticker,
            "kalshi_side": t.kalshi_side, "action": t.action, "size": t.size,
            "poly_price": t.poly_price, "fee_multiplier": t.fee_multiplier,
            "close_ts": t.close_ts, "result": t.result,
        })
    from quantfirm.kalshi.copytrade import MappedTrade
    rebuilt = [MappedTrade(**row) for row in stored]
    candles: dict[str, list] = {}
    for ticker, pts in quotes.items():
        candles[ticker] = [
            Candle(p["end_ts"], p["bid"], p["bid"], p["ask"], p["ask"], volume=1)
            for p in pts
        ]
    metas = {}
    for row in stored:
        km = by_ticker.get(row["ticker"])
        if km is not None:
            metas[row["ticker"]] = (km.close_ts, km.result, km.fee_multiplier)
        elif row.get("close_ts"):
            metas[row["ticker"]] = (row["close_ts"], row.get("result"), row["fee_multiplier"])
    buckets = coalesce(rebuilt)
    rep = simulate(
        buckets, candles, metas, weights,
        bankroll=float(state["bankroll"]), grace_s=86400,
    )
    state["cursor"] = max(int(r.get("timestamp") or cursor) for r in new_rows)
    state["last_tick"] = now
    state["last_report"] = _public(rep)
    state["live_orders"] = False
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    print(json.dumps({
        "paper": "tick",
        "new_trades": len(new_rows),
        "mapped": len(fresh),
        "pnl_mtm": rep["pnl_mtm"],
        "n_fills": rep["n_fills"],
        "live_orders": False,
        "kill_switch": kill_switch_tripped(),
    }, indent=2), flush=True)


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    _refuse_live(argv)
    if argv[:1] == ["paper-tick"]:
        paper_tick()
        return
    backtest()


if __name__ == "__main__":
    main()
