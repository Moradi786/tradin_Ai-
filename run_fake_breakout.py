import csv, io, json, hashlib, zipfile
from urllib.request import urlopen
from datetime import datetime, timezone
from fake_breakout_research import candidates, evaluate

def download(symbol):
    rows=[]
    for year,month in [(2025,11),(2025,12)]+[(2026,m) for m in range(1,11)]:
        url=f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/5m/{symbol}-5m-{year}-{month:02}.zip"
        with urlopen(url,timeout=60) as response:
            data=response.read()
        with urlopen(url+".CHECKSUM",timeout=60) as response:
            expected=response.read().decode().split()[0]
        if hashlib.sha256(data).hexdigest()!=expected:
            raise ValueError("Checksum mismatch: "+url)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            with archive.open(archive.namelist()[0]) as file:
                for r in csv.reader(io.TextIOWrapper(file)):
                    if not r or not r[0].isdigit(): continue
                    rows.append(dict(zip(("timestamp","open","high","low","close"),[int(r[0])//1000]+list(map(float,r[1:5])))))
    rows.sort(key=lambda r:r["timestamp"])
    start=int(datetime(2025,11,1,tzinfo=timezone.utc).timestamp())
    end=int(datetime(2026,11,1,tzinfo=timezone.utc).timestamp())
    if len(rows)!=(end-start)//300 or any(r["timestamp"]!=start+i*300 for i,r in enumerate(rows)):
        raise ValueError("Incomplete or duplicated candles: "+symbol)
    return rows

def main():
    results=[]
    for symbol in ("BTCUSDT","ETHUSDT","SOLUSDT"):
        rows=download(symbol)
        signals=list(candidates(rows))
        for mode in "ABC":
            for rr in (2,3,5):
                results.append(dict(symbol=symbol,mode=mode,rr=rr,**evaluate(rows,signals,mode,rr)))
    with open("fake_breakout_results.json","w") as f:
        json.dump(results,f,indent=2)
    print(json.dumps(results,indent=2))

if __name__=="__main__":
    main()
