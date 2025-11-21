import sys
import os
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

if len(sys.argv) < 2:
    print("Usage: python3 analysis/analyze.py run.csv")
    sys.exit(1)

csv = sys.argv[1]
if not os.path.exists(csv):
    print("File not found:", csv)
    sys.exit(2)

df = pd.read_csv(csv)

# Normalize column names lower-case
df.columns = [c.strip() for c in df.columns]

# Ensure latency_s exists
if 'latency_s' not in df.columns:
    if 'latency_ms' in df.columns:
        df['latency_s'] = df['latency_ms'] / 1000.0
    else:
        print("CSV missing 'latency_s' or 'latency_ms'. Columns:", df.columns.tolist())
        sys.exit(3)

total = len(df)
timestamp_present = 'timestamp' in df.columns
if timestamp_present:
    try:
        t0 = pd.to_datetime(df['timestamp']).min()
        t1 = pd.to_datetime(df['timestamp']).max()
        duration_s = (t1 - t0).total_seconds()
    except Exception:
        duration_s = None
else:
    duration_s = None

throughput = (total / duration_s) if duration_s and duration_s > 0 else None

print("=== run.csv summary ===")
print("Total requests:", total)
if duration_s:
    print(f"Duration (s): {duration_s:.2f}")
if throughput:
    print(f"Observed throughput (req/s): {throughput:.2f}")

print("\nLatency (s) stats:")
print(df['latency_s'].describe().to_string())

print("\nPer-backend distribution:")
if 'backend' in df.columns:
    counts = df['backend'].value_counts()
    for b, c in counts.items():
        print(f"{b:12s} {c:6d} {c/total*100:6.2f}%")
else:
    print("No 'backend' column in CSV; skipping distribution.")

# Plot
os.makedirs("analysis", exist_ok=True)
plt.figure(figsize=(11,5))

plt.subplot(1,2,1)
plt.hist(df['latency_s'].dropna(), bins=40)
plt.title("Latency histogram (s)")
plt.xlabel("seconds")
plt.ylabel("count")

plt.subplot(1,2,2)
if 'backend' in df.columns:
    df.boxplot(column='latency_s', by='backend', rot=45)
    plt.title("Latency by backend")
    plt.suptitle("")
else:
    plt.text(0.5, 0.5, "No backend column", ha='center', va='center')
    plt.title("Latency by backend (empty)")

plt.tight_layout()
out = "analysis/summary.png"
plt.savefig(out)
print("\nSaved chart to", out)

