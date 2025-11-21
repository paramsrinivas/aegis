# router_poll_weights.py
import asyncio
import httpx
import random
WEIGHTS = {}
MANAGER_URLS = ("http://manager:8001/weights", "http://localhost:8001/weights")
POLL_INTERVAL = 1.0

async def fetch_weights_once(client):
    for u in MANAGER_URLS:
        try:
            r = await client.get(u, timeout=2.0)
            if r.status_code == 200:
                j = r.json()
                if isinstance(j, dict):
                    return j
        except Exception:
            pass
    return None

async def poll_weights_loop():
    global WEIGHTS
    async with httpx.AsyncClient() as client:
        while True:
            j = await fetch_weights_once(client)
            if isinstance(j, dict):
                new = {}
                for k, v in j.items():
                    try:
                        new[k] = float(v)
                    except Exception:
                        try:
                            new[k] = float(v.get("weight", 1.0))
                        except Exception:
                            new[k] = 1.0
                WEIGHTS = new
            await asyncio.sleep(POLL_INTERVAL)

def weighted_choice(names):
    if not names:
        raise ValueError("no names")
    weights = []
    for n in names:
        w = WEIGHTS.get(n)
        if w is None:
            w = 1.0
        try:
            w = float(w)
        except Exception:
            w = 1.0
        weights.append(max(0.0, w))
    total = sum(weights)
    if total <= 0.0:
        return random.choice(names)
    chosen = random.choices(names, weights=weights, k=1)[0]
    return chosen

