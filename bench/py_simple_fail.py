# bench/py_simple_fail.py
# Sends requests to a fail endpoint to simulate backend errors.
import asyncio, httpx, time, csv, argparse

async def run_once(url, n):
    async with httpx.AsyncClient() as client:
        results = []
        for _ in range(n):
            start = time.perf_counter()
            try:
                r = await client.get(url, timeout=5.0)
                status = r.status_code
            except Exception:
                status = 0
            latency = (time.perf_counter() - start) * 1000.0
            results.append((time.time(), latency, status))
        return results

def save_csv(results, out):
    import csv
    results.sort()
    with open(out, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['ts','latency_ms','status'])
        for r in results:
            writer.writerow([int(r[0]*1000), round(r[1],3), r[2]])

if __name__ == '__main__':
    import argparse, statistics
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='http://localhost:8102/fail')
    p.add_argument('--requests', type=int, default=50)
    p.add_argument('--out', default='bench_fail.csv')
    args = p.parse_args()
    res = asyncio.run(run_once(args.url, args.requests))
    save_csv(res, args.out)
    print('done')

