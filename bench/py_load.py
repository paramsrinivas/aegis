#!/usr/bin/env python3
# bench/py_load.py
import time, argparse, requests, threading, statistics, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque

parser = argparse.ArgumentParser(description="Simple Python load generator")
parser.add_argument("--url",    default="http://localhost:8000/predict")
parser.add_argument("--vus",    type=int, default=20, help="concurrent workers")
parser.add_argument("--dur",    type=int, default=60, help="duration seconds")
parser.add_argument("--think",  type=float, default=0.1, help="sleep between requests (s)")
parser.add_argument("--timeout",type=float, default=5.0, help="request timeout (s)")
args = parser.parse_args()

stop_at = time.time() + args.dur
stats_lock = threading.Lock()
latencies = deque(maxlen=1000000)
codes = {}
errors = 0
requests_total = 0

def worker(id):
    global errors, requests_total
    s = requests.Session()
    while time.time() < stop_at:
        t0 = time.time()
        try:
            r = s.get(args.url, timeout=args.timeout)
            dt = (time.time() - t0) * 1000.0
            with stats_lock:
                latencies.append(dt)
                codes[r.status_code] = codes.get(r.status_code, 0) + 1
                requests_total += 1
        except Exception as e:
            dt = (time.time() - t0) * 1000.0
            with stats_lock:
                latencies.append(dt)
                errors += 1
                requests_total += 1
        time.sleep(args.think)

# start workers
print(f"Starting {args.vus} workers -> {args.url} for {args.dur}s")
workers = []
with ThreadPoolExecutor(max_workers=args.vus) as ex:
    for i in range(args.vus):
        ex.submit(worker, i)
    # wait until duration passes
    try:
        while time.time() < stop_at:
            remaining = int(stop_at - time.time())
            print(f"\rTime left: {remaining:3}s  requests: {requests_total}", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
print("\n\nFinished. Summary:")
with stats_lock:
    l = list(latencies)
    total = requests_total
    errs = errors
    code_snapshot = dict(codes)
if l:
    print(f" requests: {total}  errors: {errs}")
    print(f" latency ms: avg={statistics.mean(l):.1f} med={statistics.median(l):.1f} p90={statistics.quantiles(l, n=10)[8]:.1f} max={max(l):.1f}")
else:
    print(" no successful requests recorded (latency list empty)")
print(" status codes:", code_snapshot)

