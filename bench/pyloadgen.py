#!/usr/bin/env python3
import argparse
import asyncio
import httpx
import time
import csv
import os

parser = argparse.ArgumentParser()
parser.add_argument('--rps', type=float, default=10)
parser.add_argument('--duration', type=float, default=30)
parser.add_argument('--url', type=str, default='http://localhost:8000/predict')
parser.add_argument('--concurrency', type=int, default=5)
parser.add_argument('--out', type=str, default='run.csv')
args = parser.parse_args()

async def worker(name, q, results):
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            item = await q.get()
            if item is None:
                q.task_done()
                break
            t0 = time.time()
            try:
                r = await client.get(args.url)
                status = r.status_code
                latency = (time.time() - t0)*1000
            except Exception:
                status = 0
                latency = (time.time() - t0)*1000
            results.append((time.time(), status, latency))
            q.task_done()

async def main():
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    q = asyncio.Queue()
    results = []
    workers = [asyncio.create_task(worker(i, q, results)) for i in range(args.concurrency)]
    start = time.time()
    interval = 1.0/args.rps if args.rps>0 else 0
    while time.time() - start < args.duration:
        await q.put(1)
        await asyncio.sleep(interval)
    for _ in workers:
        await q.put(None)
    await q.join()
    for w in workers:
        w.cancel()
    with open(args.out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['ts', 'status', 'latency_ms'])
        for r in results:
            w.writerow(r)
    print('done', len(results))

if __name__ == '__main__':
    asyncio.run(main())

