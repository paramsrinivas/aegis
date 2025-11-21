import time
import requests
import statistics
import math
import sys
from typing import Dict

MANAGER = "http://localhost:8001"
POLL = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0   # seconds
SMOOTH_ALPHA = 0.3   # smoothing for manual weight updates
MIN_WEIGHT = 0.05
MAX_WEIGHT = 100.0
SESSION = requests.Session()
SESSION.headers.update({"Content-Type": "application/json"})


class SmoothStore:
    def __init__(self, alpha=SMOOTH_ALPHA):
        self.alpha = alpha
        self.store = {}

    def update(self, new_map: Dict[str, float]):
        for k, v in new_map.items():
            if k not in self.store:
                self.store[k] = v
            else:
                self.store[k] = self.alpha * v + (1 - self.alpha) * self.store[k]
        return dict(self.store)


def fetch_weights():
    url = MANAGER + "/weights"
    r = SESSION.get(url, timeout=3)
    r.raise_for_status()
    return r.json()


def apply_manual_weights(weights: Dict[str, float]):
    # ensure values are sane
    cleaned = {}
    for k, v in weights.items():
        try:
            fv = float(v)
        except Exception:
            fv = 1.0
        fv = max(MIN_WEIGHT, min(MAX_WEIGHT, fv))
        cleaned[k] = fv
    url = MANAGER + "/weights"
    r = SESSION.post(url, json=cleaned, timeout=3)
    r.raise_for_status()
    return r.json()


def compute_target_from_weights(wmap: Dict[str, float]):
    # goal: allocate manual weights that reflect normalized inverse latency
    # manager might already return inverse-latency scores; we re-normalize to percentages
    vals = list(wmap.values())
    if not vals:
        return wmap
    # If values look like latencies (small floats), convert to 1/latency
    if all(0 < abs(v) < 5.0 for v in vals):  # heuristic
        inv = {k: 1.0 / (v + 0.001) for k, v in wmap.items()}
    else:
        inv = dict(wmap)
    s = sum(inv.values()) or 1.0
    normalized = {k: max(MIN_WEIGHT, (v / s) * 100.0) for k, v in inv.items()}
    return normalized


def main():
    print("autoscaler started: polling", MANAGER, "every", POLL, "s")
    smooth = SmoothStore(alpha=SMOOTH_ALPHA)
    while True:
        try:
            observed = fetch_weights()
        except Exception as e:
            print("fetch error", e)
            time.sleep(POLL)
            continue
        target = compute_target_from_weights(observed)
        smoothed = smooth.update(target)
        try:
            resp = apply_manual_weights(smoothed)
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "applied", resp.get("applied", resp))
        except Exception as e:
            print("apply error", e)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
