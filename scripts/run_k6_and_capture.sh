set -eu
RESULT_DIR="$HOME/projects/aegis/results"
mkdir -p "$RESULT_DIR"
K6_LOG="/tmp/k6_run.log"
k6 run -u 10 -d 20s -e URL=http://localhost:8000/predict bench/simple_router_test.js > "$K6_LOG" 2>&1 &
K6PID=$!
echo "k6 PID=$K6PID" | tee "$RESULT_DIR/k6_pid_$(date +%s).txt"
wait "$K6PID" || true
cp "$K6_LOG" "$RESULT_DIR/k6_run_$(date +%s).log"
START=$(date -u -d '10 minutes ago' +%s 2>/dev/null || date -u -v-10M +%s 2>/dev/null || python3 - <<PY
import time
print(int(time.time())-10*60)
PY
)
END=$(date -u +%s)

echo "START=${START} END=${END}" | tee "$RESULT_DIR/time_window_$(date +%s).txt"

PROM="http://localhost:9090"
curl -sS --get "$PROM/api/v1/query_range" \
  --data-urlencode "query=router_backend_chosen_total" \
  --data-urlencode "start=${START}" --data-urlencode "end=${END}" --data-urlencode "step=5s" \
  | jq > "$RESULT_DIR/router_chosen_timeseries_$(date +%s).json"

curl -sS --get "$PROM/api/v1/query_range" \
  --data-urlencode "query=sum(rate(router_backend_chosen_total[1m])) by (backend)" \
  --data-urlencode "start=${START}" --data-urlencode "end=${END}" --data-urlencode "step=5s" \
  | jq > "$RESULT_DIR/router_rate_1m_range_$(date +%s).json"

curl -sS --get "$PROM/api/v1/query" \
  --data-urlencode 'query=sum(increase(router_backend_chosen_total[1m])) by (backend)' \
  | jq > "$RESULT_DIR/prom_increase_$(date +%s).json"
curl -sS http://localhost:8000/metrics > "$RESULT_DIR/router_metrics_$(date +%s).txt" || true
curl -sS http://localhost:8001/metrics > "$RESULT_DIR/manager_metrics_$(date +%s).txt" || true
curl -sS http://localhost:8001/weights | jq > "$RESULT_DIR/manager_weights_$(date +%s).json" || true

echo "captured to $RESULT_DIR"
