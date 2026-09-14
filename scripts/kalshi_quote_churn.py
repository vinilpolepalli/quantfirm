import re, datetime as dt, statistics as st, sys
from collections import defaultdict
pat=re.compile(r'\[(\S+?)\] maker (quote|cancel|FILL) \w* ?\d* ?(KX\S+)')
events=defaultdict(list)
for line in open(sys.argv[1] if len(sys.argv)>1 else "state/kalshi_paper_loop.log", errors="ignore"):
    m=pat.search(line)
    if not m: continue
    ts=dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ")
    events[m.group(3)].append((ts, m.group(2)))
lives=[]
for tkr, evs in events.items():
    evs.sort(); open_ts=None
    for ts, kind in evs:
        if kind=="quote": open_ts=ts
        elif open_ts is not None:
            lives.append(((ts-open_ts).total_seconds(), kind)); open_ts=None
if not lives:
    print("no quote episodes found"); sys.exit()
secs=[l for l,_ in lives]
ends={}
for _,k in lives: ends[k]=ends.get(k,0)+1
print(f"quote episodes   : {len(lives)}")
print(f"median lifetime  : {st.median(secs):.0f}s")
print(f"mean lifetime    : {st.mean(secs):.0f}s")
print(f"under 10s        : {sum(1 for s in secs if s<10)/len(secs):.0%}")
print(f"under 30s        : {sum(1 for s in secs if s<30)/len(secs):.0%}")
print(f"ended by         : {ends}")
print()
print("A resting quote that lives ~5s is not a market-making strategy; it")
print("barely participates. Any P&L measured under this regime describes the")
print("cancel logic, not the maker thesis. See docs/KALSHI.md 3c.")
