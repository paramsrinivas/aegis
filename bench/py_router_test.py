# bench/py_router_test.py
# Simple router test: hit /predict repeatedly and record which backend responds (if header present).
import asyncio, httpx, time, csv, argparse, re

async def run(url, n, concurrency):
    q = asyncio.Queue()
    for _ in range(n):
        q.put_nowait(1)
    results = []
    async with httpx.AsyncClient() as client:
        async def worker():
            while True:
                try:
                    _ = await q.get()
                except asyncio.CancelledError:
                    break
                start = time.perf_counter()
                try:
                    r = await client.get(url, timeout=10.0)
                    status = r.status_code
                    # try to extract backend name from header or body
                    backend = r.headers.get('x-backend', '') or (r.text[:100])
                except Exception as e:
                    status = 0
                    backend = ''
                latency = (time.perf_counter() - start) * 1000.0
                results.append((time.time(), latency, status, backend))
                q.task_done()
        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        await q.join()
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
    return results

def save_csv(results, out):
    with open(out, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['ts','latency_ms','status','backend'])
        for r in results:
            writer.writerow([int(r[0]*1000), round(r[1],3), r[2], r[3]])

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='http://localhost:8000/predict')
    p.add_argument('--requests', type=int, default=100)
    p.add_argument('--concurrency', type=int, default=10)
    p.add_argument('--out', default='bench_router.csv')
    args = p.parse_args()
    res = asyncio.run(run(args.url, args.requests, args.concurrency))
    save_csv(res, args.out)
    print('done')

