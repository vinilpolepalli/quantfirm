#!/usr/bin/env python3
"""Paper-trade the Kalshi Liquidity Incentive Program. No credentials, no orders.

Holds a notional book (default $250), re-prices it every run, and accrues the
reward it WOULD have earned since the last run. Writes
state/kalshi_incentive_paper.json and prints a digest.

    python scripts/kalshi_incentive_paper.py --capital 250          # one tick
    python scripts/kalshi_incentive_paper.py --capital 250 --email  # tick + email

Why this exists: the scan in kalshi_incentive_scan.py puts $250 somewhere
between $1.55/day (board average) and ~$70/day (perfect selection). That gap
cannot be closed from snapshots, only by logging what we would have scored and
reconciling it against rewards Kalshi actually credits. Estimates update live
but are not final until a program ends, so ESTIMATED here is a claim, not a
result, and the memo says so.

Accrual is deliberately conservative:
  * a snapshot pays NOBODY unless both sides hold >= Target Size, so a
    position whose book falls under target accrues zero for that interval;
  * competition is the qualifying-depth score (orders that help reach
    Target Size), not the whole book;
  * our size is scored against the CURRENT book, i.e. we assume competitors
    react instantly and we never get a stale-book bonus;
  * we bill ourselves the whole interval at the rate observed at its END,
    which is the pessimistic end of the interval when competition is growing;
  * new slots require --min-age-hours (default 12): a thin book on a
    brand-new program is an empty room, not an edge.
"""
import argparse
import datetime as dt
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
STATE = os.path.join(REPO, "state", "kalshi_incentive_paper.json")

from quantfirm.kalshi.incentive import (  # noqa: E402
    MIN_AGE_HOURS, MIN_HOURS_LEFT, SELECTION, eligible_program,
    fetch_programs, price_book, price_many, rate_per_hour, ts as _ts,
)



# ---------------------------------------------------------------- the gate
# Deterministic go/no-go. The firm's rule is that code decides and agents
# report, so this is arithmetic on the accrual log, not a judgement call.
#
# Thresholds, and why:
#   $1.55/day  the board-wide average return on resting capital ($106k/day of
#              reward against $17.07M resting). Earning this is earning nothing
#              special -- it is what capital makes by showing up.
#   $5.00/day  2%/day on $250. Enough to clear the operational cost of
#              requoting five slots continuously and to be worth real money.
MIN_HOURS = 48.0          # below this the sample is noise, whatever it says
STALE_HOURS = 3.0         # no tick this recently => the collector is down
# A tick accrues rate x interval, i.e. it reads the book ONCE and applies that
# rate backwards over the whole gap since the last tick. GitHub's scheduler
# drops slots, so gaps of hours happen, and uncapped this manufactures accrual
# from a single instant -- on 2026-09-16 one tick booked $9.03, over half the
# running total, off a 2.65h gap. Capping means a missed slot LOSES accrual
# instead of inventing it, which is the direction this book should err in. It
# also restores the trailing-window gap guard: `span` is a sum of intervals, so
# uncapped intervals grew to fill any gap and the guard never fired.
MAX_INTERVAL_H = 1.0
BOARD_AVG_PER_DAY = 1.55
GO_PER_DAY = 5.00


def trailing_rate(history, hours, now):
    """$/day accrued over the last `hours`, or None if not enough log."""
    cut = now - dt.timedelta(hours=hours)
    got = span = 0.0
    for h in history:
        try:
            t = _ts(h["t"])
        except Exception:
            continue
        if t < cut:
            continue
        got += h.get("earned", 0.0)
        span += h.get("interval_h", 0.0)
    if span < hours * 0.5:        # too many gaps to trust the window
        return None
    return got / span * 24 if span > 0 else None


def verdict(st, now):
    """(code, one-line reason). Codes: STALLED, INSUFFICIENT, FALLING, GO,
    MARGINAL, NO."""
    hist = st.get("history", [])
    if not hist:
        return "INSUFFICIENT", "no accrual logged yet"
    try:
        last = _ts(hist[-1]["t"])
    except Exception:
        return "STALLED", "unreadable last tick"
    age = (now - last).total_seconds() / 3600.0
    if age > STALE_HOURS:
        return "STALLED", (f"no tick for {age:.1f}h - the collector is down, so "
                           f"nothing below this line is being measured")
    clock = st.get("selection_since") or st["started"]
    run_h = (now - _ts(clock)).total_seconds() / 3600.0
    if run_h < MIN_HOURS:
        return "INSUFFICIENT", (f"{run_h:.1f}h of {st.get('selection', 'legacy')} "
                                f"data, need {MIN_HOURS:.0f}h "
                                f"- early ticks over-read badly")
    r24 = trailing_rate(hist, 24.0, now)
    r48 = trailing_rate(hist, 48.0, now)
    if r24 is None:
        return "INSUFFICIENT", "trailing 24h window has too many gaps"
    # Still decaying? Then the current number is not the number.
    if r48 is not None and r48 > 0 and r24 < 0.7 * r48:
        return "FALLING", (f"trailing 24h ${r24:.2f}/day is still well under the "
                           f"48h ${r48:.2f}/day - it has not settled, keep waiting")
    if r24 >= GO_PER_DAY:
        return "GO", (f"trailing 24h ${r24:.2f}/day on ${st['capital']:.0f} "
                      f"({r24 / st['capital'] * 100:.2f}%/day), stable, clears "
                      f"${GO_PER_DAY:.2f}/day")
    if r24 >= BOARD_AVG_PER_DAY:
        return "MARGINAL", (f"trailing 24h ${r24:.2f}/day - above the "
                            f"${BOARD_AVG_PER_DAY:.2f}/day board average but under "
                            f"${GO_PER_DAY:.2f}/day; probably not worth the plumbing")
    return "NO", (f"trailing 24h ${r24:.2f}/day - at or below the "
                  f"${BOARD_AVG_PER_DAY:.2f}/day a passive book earns anyway")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=250.0)
    ap.add_argument("--slots", type=int, default=5, help="markets held at once")
    ap.add_argument("--sample", type=int, default=400, help="programs to price per tick")
    ap.add_argument("--min-hours-left", type=float, default=MIN_HOURS_LEFT,
                    help="only open positions in programs ending no sooner than this. "
                         "Must match kalshi_incentive_quote.py or the shadow book is "
                         "measuring a different strategy than the one we would run.")
    ap.add_argument("--min-age-hours", type=float, default=MIN_AGE_HOURS,
                    help="skip programs younger than this when opening a slot. Fresh "
                         "books are empty rooms (measured 119x decay); the first 24h "
                         "of this book picked them and over-read. Must match the quoter.")
    ap.add_argument("--email", action="store_true")
    ap.add_argument("--email-every", type=float, default=0.0,
                    help="with --email, only emit a digest if this many hours have passed "
                         "since the last one. Lets the tick run hourly (good accrual data) "
                         "without sending 24 mails a day.")
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--exit-on-go", action="store_true",
                    help="exit 10 when the gate says GO, so a cron can branch on it")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    st = {"started": now.isoformat(), "accrued": 0.0, "ticks": 0,
          "positions": [], "history": []}
    if os.path.exists(args.state):
        try:
            st = json.load(open(args.state))
        except Exception:
            pass

    if st.get("selection") != SELECTION:
        # Do not rewrite accrued history — that is the audit trail of the
        # old freshness-biased book. Restart the 48h clock so a GO cannot
        # fire on a mix of two strategies.
        st["selection"] = SELECTION
        st["selection_since"] = now.isoformat()

    live = {p["market_ticker"]: p for p in fetch_programs()
            if p["incentive_type"] == "liquidity" and _ts(p["end_date"]) > now}

    # 1. accrue on what we already hold
    last = st.get("last_tick")
    raw_interval_h = 0.0
    if last:
        raw_interval_h = max(0.0, (now - _ts(last)).total_seconds() / 3600.0)
    interval_h = min(raw_interval_h, MAX_INTERVAL_H)
    dropped_h = raw_interval_h - interval_h
    earned, kept, closed = 0.0, [], []
    per = args.capital / max(args.slots, 1)
    for pos in st.get("positions", []):
        prog = live.get(pos["ticker"])
        if not prog:
            closed.append(dict(pos, reason="program ended"))
            continue
        m = price_book(prog, now)
        if not m:
            closed.append(dict(pos, reason="book unreadable"))
            continue
        rate, size, share, excluded = rate_per_hour(m, per)
        got = rate * interval_h
        earned += got
        rec = dict(ticker=pos["ticker"], capital=per, size=round(size, 1),
                   share=round(share, 4), rate_per_hour=round(rate, 4),
                   excluded=excluded, accrued=round(pos.get("accrued", 0.0) + got, 4),
                   ends=m["ends"])
        # Carry fields recorded at open. The accrual loop rebuilds the
        # dict every tick; anything not copied here lives one tick and
        # dies (the #88 / #90 bug).
        if pos.get("age_h_at_open") is not None:
            rec["age_h_at_open"] = pos["age_h_at_open"]
        if pos.get("opened"):
            rec["opened"] = pos["opened"]
        kept.append(rec)

    # 2. refill empty slots with the best available
    if len(kept) < args.slots:
        import random
        random.seed()
        held = {k["ticker"] for k in kept}
        # Only pick what the REAL quoter would quote. kalshi_incentive_quote.py
        # skips anything ending sooner than --min-hours-left, so without the
        # same filter the shadow book measures a strategy we would never run:
        # it sorts on $/hour, short programs have a small pool over a short
        # duration and so score highest, and the book fills with things that
        # expire before we could rest anything in them. On 2026-09-16 it held
        # KXTEMPMIAH-26SEP1617, which ended within the hour having accrued
        # $0.00. `live` stays unfiltered above so positions already held keep
        # accruing as they age out, rather than churning on the boundary.
        pool = [p for t, p in live.items()
                if t not in held
                and eligible_program(p, now, args.min_hours_left, args.min_age_hours)]
        pick = random.sample(pool, min(args.sample, len(pool)))
        cand = price_many(pick, now)
        scored = []
        for m in cand:
            rate, size, share, excluded = rate_per_hour(m, per)
            if not excluded and rate > 0:
                scored.append((rate, size, share, m))
        scored.sort(reverse=True, key=lambda z: z[0])
        for rate, size, share, m in scored[:args.slots - len(kept)]:
            kept.append(dict(ticker=m["ticker"], capital=per, size=round(size, 1),
                             share=round(share, 4), rate_per_hour=round(rate, 4),
                             excluded=False, accrued=0.0, ends=m["ends"],
                             # Age of the PROGRAM when we picked it. New
                             # slots also require --min-age-hours; this
                             # field is how we verify the filter held.
                             age_h_at_open=round(m["age_h"], 1),
                             opened=now.isoformat()))

    st["positions"] = kept
    st["accrued"] = round(st.get("accrued", 0.0) + earned, 4)
    st["ticks"] = st.get("ticks", 0) + 1
    st["last_tick"] = now.isoformat()
    st["capital"] = args.capital
    st["history"] = (st.get("history", []) + [dict(
        t=now.isoformat(), earned=round(earned, 4), total=st["accrued"],
        held=len(kept), interval_h=round(interval_h, 3))])[-500:]

    life_h = max((now - _ts(st["started"])).total_seconds() / 3600.0, 1e-9)
    sel_h = max((now - _ts(st.get("selection_since") or st["started"])).total_seconds() / 3600.0, 1e-9)
    lines = []
    lines.append(f"Kalshi LIP paper book — ${args.capital:,.0f} notional, {len(kept)} slots")
    lines.append(f"tick {st['ticks']}  ·  book {life_h:.1f}h  ·  "
                 f"{st.get('selection', 'legacy')} {sel_h:.1f}h  ·  "
                 f"{now.strftime('%Y-%m-%d %H:%M')}Z")
    lines.append("")
    lines.append(f"  accrued this tick   ${earned:,.4f}  (over {interval_h:.2f}h)")
    if dropped_h > 0.01:
        lines.append(f"  ** MISSED SLOTS: gap was {raw_interval_h:.2f}h, capped at "
                     f"{MAX_INTERVAL_H:.2f}h — {dropped_h:.2f}h of accrual dropped "
                     f"rather than extrapolated. The scheduler is skipping.")
    lines.append(f"  accrued total       ${st['accrued']:,.4f}  (lifetime, mixed strategies)")
    if interval_h > 0:
        tick_rate = earned / interval_h * 24
        lines.append(f"  this-tick run-rate  ${tick_rate:,.2f}/day  "
                     f"({tick_rate / args.capital * 100:.2f}%/day) — a single tick, not a finding")
    lines.append("")
    lines.append(f"  {'ticker':<34}{'size':>8}{'share':>8}{'$/hr':>9}{'accrued':>10}{'age@open':>10}")
    for k in kept:
        age = k.get("age_h_at_open")
        age_s = f"{age:>9.1f}h" if age is not None else f"{'—':>10}"
        lines.append(f"  {k['ticker']:<34}{k['size']:>8,.0f}{k['share']*100:>7.1f}%"
                     f"{k['rate_per_hour']:>9.3f}{k['accrued']:>10.4f}{age_s}")
    ages = [k["age_h_at_open"] for k in kept if k.get("age_h_at_open") is not None]
    if ages:
        lines.append(f"  mean program age at open: {sum(ages)/len(ages):.1f}h "
                     f"(fresh-to-week-old decay is 119x; a verdict off hours-old "
                     f"programs is measuring freshness)")
    if closed:
        lines.append("")
        for c in closed:
            lines.append(f"  closed: {c['ticker']} — {c['reason']} "
                         f"(accrued ${c.get('accrued', 0):.4f})")
    code, why = verdict(st, now)
    st["verdict"] = code
    st["verdict_reason"] = why
    lines.append("")
    lines.append(f"  VERDICT: {code} - {why}")
    lines.append("")
    lines.append("PAPER ONLY — no orders placed, no credentials used. Accrual is an")
    lines.append("ESTIMATE from the public book; Kalshi only credits after a program ends.")
    digest = "\n".join(lines)
    print(digest)

    os.makedirs(os.path.dirname(args.state), exist_ok=True)
    with open(args.state, "w") as fh:
        json.dump(st, fh, indent=1)

    if args.email:
        due = True
        if args.email_every > 0 and st.get("last_email"):
            since = (now - _ts(st["last_email"])).total_seconds() / 3600.0
            due = since >= args.email_every
        out = os.path.join(os.path.dirname(args.state), "kalshi_incentive_digest.txt")
        if due:
            with open(out, "w") as fh:
                fh.write(digest)
            st["last_email"] = now.isoformat()
            with open(args.state, "w") as fh:
                json.dump(st, fh, indent=1)
            print(f"\n[EMAIL DUE - digest at {out}]", file=sys.stderr)
        else:
            if os.path.exists(out):
                os.remove(out)
            print("\n[email not due yet - tick recorded silently]", file=sys.stderr)

    if args.exit_on_go and code == "GO":
        return 10


if __name__ == "__main__":
    sys.exit(main() or 0)
