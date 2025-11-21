import json, glob, os
from datetime import datetime

RDIR = os.path.expanduser('~/projects/aegis/results')

def read_latest(pattern):
    files = sorted(glob.glob(os.path.join(RDIR, pattern)))
    if not files:
        return None, None
    fn = files[-1]
    with open(fn) as f:
        return fn, json.load(f)

def ts_to_str(ts):
    return datetime.utcfromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S')
fn_ts, data_ts = read_latest('router_chosen_timeseries_*.json')
if fn_ts and isinstance(data_ts, dict) and 'data' in data_ts:
    print(f"Using timeseries file: {fn_ts}")
    for res in data_ts['data']['result']:
        metric = res.get('metric', {})
        backend = metric.get('backend', 'unknown')
        values = res.get('values') or []
        pts = len(values)
        first = values[0] if pts > 0 else None
        last = values[-1] if pts > 0 else None
        delta = None
        if first and last:
            try:
                delta = float(last[1]) - float(first[1])
            except Exception:
                delta = None
        print(f"- backend={backend} points={pts} first={first} last={last} delta={delta}")
else:
    print("No router chosen timeseries file found.")
fn_rate, data_rate = read_latest('router_rate_1m_range_*.json')
if fn_rate and isinstance(data_rate, dict) and 'data' in data_rate:
    print(f"\nUsing rate file: {fn_rate}")
    for res in data_rate['data']['result']:
        backend = res['metric'].get('backend', 'unknown')
        vals = res.get('values', [])
        nonzero = [v for v in vals if float(v[1]) != 0.0]
        print(f"- backend={backend} points={len(vals)} nonzero={len(nonzero)}")
        if nonzero:
            print("  sample (first 3 nonzero):")
            for v in nonzero[:3]:
                print(f"   {ts_to_str(v[0])}\t{v[1]}")
else:
    print("No router rate file found.")
fn_inc, data_inc = read_latest('prom_increase_*.json')
if fn_inc and isinstance(data_inc, dict) and 'data' in data_inc:
    print(f"\nUsing prom increase file: {fn_inc}")
    for r in data_inc['data']['result']:
        b = r['metric'].get('backend', 'unknown')
        print(f" - backend={b} value={r['value'][1]}")
else:
    print("No prom increase file found.")
fn_w, data_w = read_latest('manager_weights_*.json')
if fn_w:
    print(f"\nUsing manager weights file: {fn_w}")
    try:
        print(json.dumps(data_w, indent=2)[:4000])
    except Exception:
        print("(unable to pretty-print manager weights)")
else:
    print("No manager weights file found.")
mx_files = sorted(glob.glob(os.path.join(RDIR, 'router_metrics_*.txt')))
if mx_files:
    print(f"\nInspecting router metrics file: {mx_files[-1]}")
    with open(mx_files[-1]) as f:
        text = f.read()
    for metric in ['router_latency_seconds_count', 'router_latency_seconds_sum', 'router_requests_total', 'router_failed_total']:
        for line in text.splitlines():
            if line.startswith(metric):
                print("  "+line)
else:
    print("No router_metrics_*.txt found.")
score = 0
score += 30 if fn_ts else 0
score += 20 if fn_rate else 0
score += 10 if fn_inc else 0
score += 20 if fn_w else 0
score += 20 if mx_files else 0
print(f"\nAnalysis completeness score (0-100): {score}")
