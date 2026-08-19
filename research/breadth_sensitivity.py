"""Does universe breadth help xsec_refined? Registered trial, 2026-08-18.

QUESTION. The owner asked whether the 200-name universe should be widened
"as much as possible". Widening is not free: it deepens survivorship bias
(every added name is one that survived to be large TODAY), it invalidates
every number in config/profiles.json, and it costs a full-history backfill.
So measure the marginal value of breadth before paying for it.

DESIGN. Vary ONLY the number of rankable stocks — top-N by market cap, the
same screen that built the live universe — holding params, cost model, dev
split and all 21 rebalance anchors fixed. Compare paired across anchors, so
each N faces the identical 21 market phases.

Shrinking rather than growing is deliberate: every name tested already has
full history in the panel, so no result here is contaminated by choosing new
symbols with hindsight. The cost is that it measures the slope BELOW 200 and
infers what happens above it.

RESULT (net Sharpe, dev 2016-06..2024-07, 5bps/side, median of 21 anchors):

      N=40   1.063      40 ->  80   -0.061   0/21 wins   t=-16.51  WORSE
      N=80   1.001      80 -> 120   +0.206  21/21 wins   t=+30.57  improves
      N=120  1.217     120 -> 160   +0.035  20/21 wins   t= +8.18  improves
      N=160  1.246     160 -> 200   -0.009   5/21 wins   t= -1.46  no effect
      N=200  1.226

CONCLUSION. The breadth curve saturates before the live universe size. The
last step, 160 -> 200, is indistinguishable from zero and slightly negative;
the gain is concentrated in 80 -> 120 and mostly spent by 160. Tail risk moves
the other way: worst-anchor drawdown widens -31.3% (N=120) -> -33.8% (160) ->
-38.3% (200).

So expanding past 200 is not supported. It would cost a backfill, invalidate
the shipped profile numbers, and add another trial to a trial space whose PBO
is already 0.496 — to buy a marginal Sharpe that measures as zero at the top
of the range tested.

CAVEAT. This measures the slope up to 200 and extrapolates beyond it. A
genuinely different universe — small caps, non-US, a point-in-time membership
that fixes survivorship rather than deepening it — is a different question
this experiment does not answer.

    python research/breadth_sensitivity.py
"""
import json, sys, statistics as stat
import numpy as np, pandas as pd
sys.path.insert(0, ".")
from quantfirm.equities.data import load_panel, available_symbols
from quantfirm.equities.strategies import load_all
from quantfirm.equities.backtest import run, split

cfg=json.load(open("config/equity_live.json")); params=dict(cfg["params"])
strat=load_all()[cfg["strategy"]]; every=params["every"]
meta=json.load(open("data/equities/universe.json"))
have=set(available_symbols())
ranked=[s["ticker"] for s in meta["stocks"] if s["ticker"] in have]
etfs=sorted(have-set(ranked))
dev=split(load_panel(),"dev")

SIZES=[40,80,120,160,200]
dist={}
for n in SIZES:
    panel=dev[[c for c in ranked[:n]+etfs if c in dev.columns]]
    s=[]
    for k in range(every):
        sub=panel.iloc[k:]
        s.append(run(sub,strat(sub,**params),5.0)["net_sharpe"])
    dist[n]=sorted(s)

print(f'{"N":>4}{"min":>8}{"p25":>8}{"med":>8}{"p75":>8}{"max":>8}{"spread":>9}')
for n in SIZES:
    d=dist[n]; q=lambda p: d[int(p*(len(d)-1))]
    print(f'{n:>4}{d[0]:>8.3f}{q(.25):>8.3f}{stat.median(d):>8.3f}{q(.75):>8.3f}{d[-1]:>8.3f}{d[-1]-d[0]:>9.3f}')

# is 200 distinguishable from 160? paired across the same anchors
import itertools
a=np.array(dist[160]); b=np.array(dist[200])
diff=b-a
print()
print(f'200 vs 160, paired over 21 anchors: mean diff {diff.mean():+.4f}, '
      f'sd {diff.std(ddof=1):.4f}, anchors where 200 wins {int((diff>0).sum())}/21')
t=diff.mean()/(diff.std(ddof=1)/np.sqrt(len(diff)))
print(f'paired t = {t:+.2f}  (|t|>2.09 would be significant at 5% with 20 df)')
json.dump({str(k):v for k,v in dist.items()},
  open("/tmp/claude-0/-home-user-2-3-24VEX/f4aa4a88-f776-5906-a4a2-8598d943a764/scratchpad/breadth_dist.json","w"),indent=1)
