# bench/py_baseline.py
# Simple asyncio-based load generator to mimic baseline.js k6 behavior.
import asyncio, httpx, time, csv, argparse, statistics

async def worker(client, url, q, results):
    while True:
        try:
            _ = await q.get()
        except asyncio.CancelledError:
            break
        start = time.perf_counter()
        try:
            r = await client.get(url, timeout=10.0)
            status = r.status_code
        except Exception as e:
            status = 0
        latency = (time.perf_counter() - start) * 1000.0
        results.append((time.time(), latency, status))
        q.task_done()

async def run(url, concurrency, total_requests):
    q = asyncio.Queue()
    for _ in range(total_requests):
        q.put_nowait(1)
    results = []
    async with httpx.AsyncClient() as client:
        workers = [asyncio.create_task(worker(client, url, q, results)) for _ in range(concurrency)]
        await q.join()
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    return results

def save_csv(results, out):
    results.sort()
    with open(out, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['ts','latency_ms','status'])
        for r in results:
            writer.writerow([int(r[0]*1000), round(r[1],3), r[2]])

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='http://localhost:8000/predict')
    p.add_argument('--concurrency', type=int, default=10)
    p.add_argument('--requests', type=int, default=100)
    p.add_argument('--out', default='bench_baseline.csv')
    args = p.parse_args()
    res = asyncio.run(run(args.url, args.concurrency, args.requests))
    save_csv(res, args.out)
    lat = [r[1] for r in res if r[2] != 0]
    if lat:
        print('median', statistics.median(lat), 'p95', statistics.quantiles(lat, n=100)[94])
    else:
        print('no successful requests')
