"""Research prototype: closed 15m candles, confirmed 1h levels, 5m structure.
Input CSV: timestamp (UTC epoch seconds),open,high,low,close; continuous 5m bars.
No live orders. Initial rules are hypotheses, not validated trading advice.
"""
import csv
import sys
from collections import defaultdict

def aggregate(rows, seconds):
    groups = defaultdict(list)
    for r in rows:
        groups[int(r["timestamp"]) // seconds * seconds].append(r)
    return [dict(timestamp=t, open=g[0]["open"], high=max(x["high"] for x in g),
                 low=min(x["low"] for x in g), close=g[-1]["close"])
            for t,g in sorted(groups.items()) if len(g)==seconds//300 and
            all(x["timestamp"]==t+i*300 for i,x in enumerate(g))]

def candidates(rows):
    hours, quarters, trends = (aggregate(rows,s) for s in (3600,900,14400))
    h=q=k=0
    active=None
    for i,b in enumerate(rows):
        end=b["timestamp"]+300
        while h<len(hours) and hours[h]["timestamp"]+3600<=end: h+=1
        while k<len(trends) and trends[k]["timestamp"]+14400<=end: k+=1
        while q<len(quarters) and quarters[q]["timestamp"]+900<=end:
            f=quarters[q]; q+=1
            prior=[x for x in hours[max(0,h-25):h] if x["timestamp"]+3600<=f["timestamp"]][-20:]
            if len(prior)<20 or k<20 or i<8: continue
            up=trends[k-1]["close"]>sum(x["close"] for x in trends[k-20:k])/20
            resistance=max(x["high"] for x in prior)
            support=min(x["low"] for x in prior)
            side=-1 if not up and f["high"]>resistance>f["close"] else 1 if up and f["low"]<support<f["close"] else 0
            if not side: continue
            before=rows[i-8:i-2]
            key=min(x["low"] for x in before) if side==-1 else max(x["high"] for x in before)
            stop=f["high"] if side==-1 else f["low"]
            active=dict(side=side,key=key,stop=stop,start=i,broken=None)
            yield i,side,stop,"A"
        if active:
            a=active; side=a["side"]
            if i-a["start"]>24 or (i>a["start"] and (b["high"]>=a["stop"] if side==-1 else b["low"]<=a["stop"])):
                active=None; continue
            if a["broken"] is None and i>a["start"] and side*(b["close"]-a["key"])>0:
                a["broken"]=i
                yield i,side,a["stop"],"B"
            elif a["broken"] is not None and i>a["broken"]:
                touch=b["low"]<=a["key"] if side==1 else b["high"]>=a["key"]
                if touch and side*(b["close"]-a["key"])>0:
                    yield i,side,a["stop"],"C"
                    active=None

def evaluate(rows, signals, mode, rr, cost=.002):
    returns=[]; next_i=0; equity=peak=1.; drawdown=0.
    for i,side,stop,kind in signals:
        if kind!=mode or i+1<next_i or i+48>=len(rows): continue
        entry=rows[i+1]["open"]; risk=side*(entry-stop)
        if risk<=0 or risk/entry<.001: continue
        target=entry+side*rr*risk
        if target<=0: continue
        for j in range(i+1,i+49):
            b=rows[j]
            if (b["low"]<=stop if side==1 else b["high"]>=stop):
                exit_price=min(stop,b["open"]) if side==1 else max(stop,b["open"]); break
            if (b["high"]>=target if side==1 else b["low"]<=target):
                exit_price=target; break
        else: exit_price=b["close"]
        r=(side*(exit_price-entry)-cost*entry)/risk
        returns.append(r); next_i=j+1
        equity*=max(0,1+.01*r); peak=max(peak,equity)
        drawdown=max(drawdown,1-equity/peak)
    n=len(returns)
    return dict(trades=n,win_rate=sum(r>0 for r in returns)/n if n else None,
                mean_R=sum(returns)/n if n else None,return_pct=100*(equity-1),drawdown_pct=100*drawdown)

if __name__=="__main__":
    with open(sys.argv[1],newline="") as f:
        rows=[{k:float(r[k]) for k in ("timestamp","open","high","low","close")} for r in csv.DictReader(f)]
    rows.sort(key=lambda r:r["timestamp"])
    if any(b["timestamp"]-a["timestamp"]!=300 for a,b in zip(rows,rows[1:])):
        raise ValueError("Missing or duplicate 5m bars")
    signals=list(candidates(rows))
    for mode in "ABC":
        for rr in (2,3,5):
            print(mode,rr,evaluate(rows,signals,mode,rr))
