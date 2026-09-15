"""How many independent bets does the wide universe actually carry?

Reproduces sections 1 and 2 of BREADTH_FINDING.md. DEV window only; nothing
after HOLDOUT_START is read. Run from the repo root:

    python research/kalshi_perps/effective_bets.py
"""
import numpy as np
import pandas as pd

from quantfirm.perps import data as D, specs as S

START, END = "2021-10-01", D.HOLDOUT_START


def effective_bets_eigen(corr: pd.DataFrame) -> float:
    """Participation ratio of the correlation matrix's normalised eigenvalues."""
    ev = np.linalg.eigvalsh(np.nan_to_num(corr.to_numpy()))
    ev = ev[ev > 0]
    w = ev / ev.sum()
    return float(1.0 / np.sum(w ** 2))


def effective_bets_dr2(corr: pd.DataFrame) -> float:
    """Squared diversification ratio of an equal-weight book, 1/(u'Cu).

    The variant that maps to a long-only book's Sharpe, which is why an
    independent analyst reached for it.
    """
    n = corr.shape[0]
    u = np.full(n, 1.0 / n)
    return float(1.0 / (u @ np.nan_to_num(corr.to_numpy()) @ u))


def main() -> None:
    panel = D.load_panel(tuple(S.TRADABLE_UNIVERSE))
    closes = D.align(panel)
    avail = D.availability(panel)
    idx = closes.index[(closes.index >= pd.Timestamp(START, tz="UTC"))
                       & (closes.index < pd.Timestamp(END, tz="UTC"))]
    rets = np.log(closes.loc[idx]).diff().where(avail.reindex(idx).fillna(False))

    # a name needs real history in the window; bnb lists 2025-10 and hype 2026-02,
    # both AFTER the holdout opens, so neither has a single dev-window bar
    have = [a for a in rets.columns if rets[a].notna().sum() >= 250]
    dropped = sorted(set(rets.columns) - set(have))
    print(f"window {START} → {END}, {len(idx)} days")
    print(f"names with >= 250 dev-window returns: {len(have)}")
    print(f"dropped for want of history: {dropped}\n")

    print(f"{'asset':<8}{'n':>6}{'ann_ret':>9}{'ann_vol':>9}{'sharpe':>8}{'total_%':>10}")
    rows = []
    for a in have:
        x = rets[a].dropna()
        ann, vol = x.mean() * 365, x.std() * np.sqrt(365)
        rows.append((a, len(x), ann, vol, ann / vol, (np.exp(x.sum()) - 1) * 100))
    for t in sorted(rows, key=lambda t: -t[4]):
        print(f"{t[0]:<8}{t[1]:>6}{t[2]:>9.3f}{t[3]:>9.3f}{t[4]:>8.2f}{t[5]:>10.1f}")
    losers = sum(1 for t in rows if t[2] < 0)
    print(f"\n{losers} of {len(rows)} names lost money over the window\n")

    crypto = [a for a in have if S.SPECS[a].asset_class == "crypto"]
    cc = rets[crypto].corr()
    iu = np.triu_indices_from(cc.to_numpy(), 1)
    print(f"crypto names: {len(crypto)}")
    print(f"mean pairwise crypto correlation  {np.nanmean(cc.to_numpy()[iu]):.3f} "
          f"(median {np.nanmedian(cc.to_numpy()[iu]):.3f})\n")

    four = list(S.RESEARCH_UNIVERSE)
    c4 = rets[four].corr()
    print(f"{'universe':<34}{'eigen ENB':>11}{'DR-squared':>12}")
    print(f"{'4 researched (btc,eth,gold,silver)':<34}"
          f"{effective_bets_eigen(c4):>11.2f}{effective_bets_dr2(c4):>11.2f}")
    print(f"{f'{len(crypto)} crypto with dev history':<34}"
          f"{effective_bets_eigen(cc):>11.2f}{effective_bets_dr2(cc):>11.2f}")
    allc = rets[have].corr()
    print(f"{f'all {len(have)} with dev history':<34}"
          f"{effective_bets_eigen(allc):>11.2f}{effective_bets_dr2(allc):>11.2f}")


if __name__ == "__main__":
    main()
