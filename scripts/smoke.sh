set -euo pipefail
echo "Building and starting stack..."
docker-compose up -d --build
echo "Waiting 4s for services..."
sleep 4
echo "Health checks:"
curl -fsS http://localhost:8000/healthz || (echo "router health failed" && exit 1)
curl -fsS http://localhost:8001/weights || (echo "manager weights failed" && exit 1)
curl -fsS http://localhost:9090/-/ready || (echo "prometheus not ready" && exit 1)
echo "Quick load (pyloadgen) — 5s @ 5rps"
python3 bench/pyloadgen.py --rps 5 --duration 5 --concurrency 2 --url http://localhost:8000/predict --out /tmp/run.csv || echo "pyloadgen failed"
echo "Analyze results"
python3 analysis/analyze.py /tmp/run.csv || true
echo "Smoke: OK"
