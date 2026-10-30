#!/usr/bin/env python3
"""Read-only health probe for an explicitly supplied lab URL."""
import argparse, json, time
from urllib.request import urlopen
from urllib.error import URLError
from urllib.parse import urlsplit

def probe(url, timeout=2):
    start=time.monotonic()
    try:
        with urlopen(url, timeout=timeout) as response:
            status=response.status
        ok=200 <= status < 300
    except (URLError, TimeoutError, OSError) as exc:
        status=None;ok=False
    return {"ok":ok,"status":status,"elapsed_ms":round((time.monotonic()-start)*1000,2)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--url',required=True);p.add_argument('--count',type=int,default=5)
    p.add_argument('--interval',type=float,default=1.0);p.add_argument('--timeout',type=float,default=2.0)
    a=p.parse_args()
    parsed=urlsplit(a.url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or not (1<=a.count<=1000) or not (0<=a.interval<=60) or not (0<a.timeout<=30):
        p.error('invalid URL or probe arguments')
    outcomes=[]
    for i in range(a.count):
        outcomes.append(probe(a.url,a.timeout))
        if i<a.count-1:time.sleep(a.interval)
    passed=sum(v['ok'] for v in outcomes)
    print(json.dumps({'target':a.url,'success':passed,'total':len(outcomes),'availability_pct':round(100*passed/len(outcomes),2),'observations':outcomes},indent=2))
    return 0 if passed==len(outcomes) else 1
if __name__=='__main__':raise SystemExit(main())
